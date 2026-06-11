#!/usr/bin/env python3
"""Validate ytaedl archive and domain-index state against current URL reality."""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as _dt
import json
import os
import random
import sys
import threading
import time
import logging
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Deque, Dict, List, Optional, Sequence, Tuple

from . import __version__ as YTAEDL_VERSION
from . import _partial_utils
from .domain_index import DomainIndex, _extract_domain
import subprocess
import tempfile

from .downloader import (
    ARCHIVE_PROCESSED_STATUSES,
    _build_aebndl_cmd,
    _build_ytdlp_cmd,
    _coerce_progress_number,
    _is_aebn,
    _simulate_check,
)
from termdash import utils as td_utils

PLAN_VERSION = 1
GOOD_STATUS = "viable"
PRESENT_STATUS = "preexisting"
PARTIAL_STATUS = "partial"
BAD_STATUS = "bad-url"
UNKNOWN_STATUS = "unknown"
ARCHIVE_PLAN_STATUS = "ARCHIVE_VALIDATE"


@dataclass(frozen=True)
class ArchiveUrl:
    url: str
    archive_status: str
    archive_file: Path
    archive_line: int
    archive_text: str
    source_group: str
    archive_size_mib: float = 0.0


@dataclass
class UrlReality:
    status: str
    downloader: str
    reason: str = ""
    present_path: Optional[str] = None
    partial_path: Optional[str] = None
    predicted_name: Optional[str] = None


@dataclass
class Mismatch:
    url: str
    archive_status: str
    actual_status: str
    archive_file: str
    archive_line: int
    source_group: str
    downloader: str
    reason: str
    present_path: Optional[str] = None
    partial_path: Optional[str] = None

    @property
    def transition(self) -> str:
        return f"{self.archive_status} -> {self.actual_status}"


@dataclass
class WorkerView:
    slot: int
    processed: int = 0
    mismatches: int = 0
    matched: int = 0
    unknown: int = 0
    partial: int = 0
    current: str = "-"
    current_file: str = "-"
    current_line: int = 0
    current_tag: str = "   "
    phase: str = "idle"
    last_result: str = "-"
    last_status: str = "-"
    last_elapsed_s: float = 0.0
    last_transition: str = "-"
    last_tool: str = "-"
    last_url: str = "-"
    started_at: float = field(default_factory=time.time)
    log: Deque[str] = field(default_factory=lambda: deque(maxlen=200))


@dataclass
class ValidationSummary:
    total_archive_urls: int
    processed: int
    matched: int
    mismatches: List[Mismatch]
    partial_count: int
    unknown_count: int
    elapsed_s: float
    stopped_by: str
    status_counts: Counter[str]
    evidence_counts: Counter[str]
    domain_breakdown: Dict[str, Counter] = field(default_factory=dict)
    transition_counts: Counter = field(default_factory=Counter)
    sample_pct: Optional[float] = None  # None = full run; float = % of pool that was sampled


def _color(text: str, color: str) -> str:
    return td_utils.color_text(text, color) if color else text


def _status_color(status: str) -> str:
    status = status.lower()
    if status in {PRESENT_STATUS, "downloaded", "already", "preexisting"}:
        return "green"
    if status in {GOOD_STATUS, PARTIAL_STATUS}:
        return "cyan"
    if status == UNKNOWN_STATUS:
        return "yellow"
    if status in {BAD_STATUS, "bad", "failed", "error"}:
        return "red"
    return "bright"


def _tool_tag(url: str) -> str:
    return "[A]" if _is_aebn(url) else "[Y]"


def _tag_color(tag: str) -> str:
    return "magenta" if tag == "[A]" else "cyan"


def _metric(value: int, color: str) -> str:
    return _color(str(value), color)


def _metric_group(processed: int, matched: int, mismatches: int, unknown: int, partial: int) -> str:
    return "/".join(
        (
            _metric(processed, "yellow"),
            _metric(matched, "green"),
            _metric(mismatches, "red"),
            _metric(unknown, "magenta"),
            _metric(partial, "cyan"),
        )
    )


def _metric_legend() -> str:
    return "/".join(
        (
            _color("processed", "yellow"),
            _color("matched", "green"),
            _color("mismatch", "red"),
            _color("unknown", "magenta"),
            _color("partial", "cyan"),
        )
    )


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_archive_file(path: Path) -> List[ArchiveUrl]:
    entries: List[ArchiveUrl] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return entries
    source_group = path.stem
    for line_num, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 6:
            continue
        status = parts[0].strip().lower()
        url = parts[-1].strip()
        if not status or not url.startswith(("http://", "https://")):
            continue
        try:
            size_mib = float(parts[3].strip().replace("MiB", "").replace("GiB", "").strip())
            if "GiB" in parts[3]:
                size_mib *= 1024.0
        except (ValueError, IndexError):
            size_mib = 0.0
        entries.append(
            ArchiveUrl(
                url=url,
                archive_status=status,
                archive_file=path,
                archive_line=line_num,
                archive_text=line,
                source_group=source_group,
                archive_size_mib=size_mib,
            )
        )
    return entries


def load_archive_urls(archive_dir: Path) -> List[ArchiveUrl]:
    entries: List[ArchiveUrl] = []
    for path in sorted(archive_dir.glob("*.txt")):
        if path.name.endswith(".rebuild.txt"):
            continue
        entries.extend(_parse_archive_file(path))
    return entries


def _archive_status_class(status: str) -> str:
    status = status.lower()
    if status == UNKNOWN_STATUS:
        return UNKNOWN_STATUS
    if status in ARCHIVE_PROCESSED_STATUSES or status == ARCHIVE_PLAN_STATUS.lower():
        return PRESENT_STATUS
    if status in {"bad", "bad-url", "failed", "error"}:
        return BAD_STATUS
    if status in {"partial"}:
        return PARTIAL_STATUS
    return status


def _status_matches(archive_status: str, actual_status: str) -> bool:
    old = _archive_status_class(archive_status)
    new = _archive_status_class(actual_status)
    if old == new:
        return True
    if old == PRESENT_STATUS and new == PRESENT_STATUS:
        return True
    return False


def _source_stem(entry: ArchiveUrl) -> str:
    stem = entry.archive_file.stem
    for prefix in ("yt-", "ae-"):
        if stem.startswith(prefix):
            return stem[len(prefix):]
    return stem


def _canonical_dirs(entry: ArchiveUrl, download_roots: Sequence[Path]) -> List[Path]:
    stem = _source_stem(entry)
    return [(root / stem).resolve() for root in download_roots]


def _find_partial(entry: ArchiveUrl, download_roots: Sequence[Path]) -> Optional[Path]:
    for directory in _canonical_dirs(entry, download_roots):
        partial_root = directory / _partial_utils.PARTIAL_DIR_NAME
        if not partial_root.exists():
            continue
        for partial_url, partial_dir in _partial_utils.scan_partial_dirs(partial_root):
            if partial_url == entry.url:
                return partial_dir.resolve()
    return None


def _aebn_url_tokens(url: str) -> List[str]:
    tokens: List[str] = []
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        path_parts = [part for part in parsed.path.split("/") if part]
        if len(path_parts) >= 3 and path_parts[-2].isdigit():
            tokens.append(path_parts[-2])
        if path_parts:
            slug = path_parts[-1].lower().replace("-", " ")
            if slug:
                tokens.extend(part for part in slug.split() if len(part) >= 4)
        fragment = parsed.fragment.lower()
        if "scene-" in fragment:
            scene = fragment.split("scene-", 1)[1].split("&", 1)[0].split("#", 1)[0]
            if scene:
                tokens.append(scene)
    except Exception:
        return tokens
    return list(dict.fromkeys(tokens))


def _find_aebn_specific_mp4(entry: ArchiveUrl, download_roots: Sequence[Path]) -> Optional[Path]:
    tokens = _aebn_url_tokens(entry.url)
    if not tokens:
        return None
    required = tokens[:1]
    optional = set(tokens[1:])
    for directory in _canonical_dirs(entry, download_roots):
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.mp4")):
            if path.name.lower().endswith((".part", ".temp")):
                continue
            haystack = path.stem.lower().replace("-", " ").replace("_", " ")
            if all(token in haystack for token in required) and (not optional or any(t in haystack for t in optional)):
                return path.resolve()
    return None


def _verify_aebn_metadata_existing(
    entry: ArchiveUrl,
    download_roots: Sequence[Path],
    validation_log_dir: Path,
) -> UrlReality:
    try:
        from aebn_dl import Downloader  # type: ignore
    except Exception as exc:
        return UrlReality(
            status=UNKNOWN_STATUS,
            downloader="aebndl",
            reason=f"aebndl metadata verification unavailable: {exc}",
        )

    work_dir = validation_log_dir / "aebn-metadata-work"
    work_dir.mkdir(parents=True, exist_ok=True)
    dirs = _canonical_dirs(entry, download_roots)
    if not dirs:
        return UrlReality(
            status=UNKNOWN_STATUS,
            downloader="aebndl-metadata",
            reason="no download roots were available for AEBN metadata verification",
        )
    try:
        dl = Downloader(
            url=entry.url,
            output_dir=str(dirs[0]),
            work_dir=str(work_dir),
            keep_logs=False,
            json_output=True,
        )
        dl._initialize_download()
        movie = dl._scrape_movie_info()
        for out_dir in dirs:
            dl.output_dir = str(out_dir)
            existing = dl._find_existing_output(movie)
            if existing:
                _close_aebn_logger(dl)
                return UrlReality(
                    status=PRESENT_STATUS,
                    downloader="aebndl-metadata",
                    reason="aebndl metadata naming matched an existing output file",
                    present_path=str(existing),
                )
        _close_aebn_logger(dl)
    except Exception as exc:
        try:
            _close_aebn_logger(dl)  # type: ignore[name-defined]
        except Exception:
            pass
        return UrlReality(
            status=BAD_STATUS,
            downloader="aebndl-metadata",
            reason=f"aebndl metadata verification failed: {type(exc).__name__}: {exc}",
        )
    return UrlReality(
        status=GOOD_STATUS,
        downloader="aebndl-metadata",
        reason="aebndl metadata resolved naming and no checked root contained the output file",
    )


def _close_aebn_logger(dl: object) -> None:
    logger = getattr(dl, "logger", None)
    if not isinstance(logger, logging.Logger):
        return
    for handler in list(logger.handlers):
        try:
            handler.close()
        except Exception:
            pass
        try:
            logger.removeHandler(handler)
        except Exception:
            pass


_URL_TEST_STATUSES: frozenset[str] = frozenset({"stalled", "bad-url", "bad", "error", "failed"})
_VIDEO_EXTENSIONS: frozenset[str] = frozenset({".mp4", ".mkv", ".webm", ".ts", ".avi", ".mov"})
_FAST_CHECK_MIN_BYTES: int = 5_000_000  # 5 MB minimum to count as a real video file


def _check_dir_has_video(entry: ArchiveUrl, download_roots: Sequence[Path]) -> bool:
    """Return True if any canonical dir for *entry* contains at least one video file >= 5 MB."""
    for directory in _canonical_dirs(entry, download_roots):
        if not directory.exists():
            continue
        try:
            for path in directory.iterdir():
                if path.suffix.lower() in _VIDEO_EXTENSIONS:
                    try:
                        if path.stat().st_size >= _FAST_CHECK_MIN_BYTES:
                            return True
                    except OSError:
                        pass
        except OSError:
            pass
    return False


def _test_aebn_url_download(
    entry: ArchiveUrl,
    *,
    validation_log_dir: Path,
    timeout_s: int = 120,
) -> UrlReality:
    """Start a real aebndl download into a temp folder to verify the URL is still accessible.

    Uses the same _build_aebndl_cmd() as normal downloads so auth and behaviour are identical.
    Requests the lowest available resolution (-r 0) to minimise bandwidth.
    Kills the process as soon as any bytes are confirmed and cleans up the temp dir.
    """
    test_root = validation_log_dir / "_aebn_url_tests"
    try:
        test_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    with tempfile.TemporaryDirectory(dir=test_root, prefix="aebn_test_") as td:
        td_path = Path(td)
        out_dir = td_path / "out"
        work_dir = td_path / "work"
        out_dir.mkdir()
        work_dir.mkdir()

        cmd = _build_aebndl_cmd(entry.url, out_dir, work_dir, max_height=0)
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                cwd=str(td_path),
            )
        except (FileNotFoundError, PermissionError, OSError) as exc:
            return UrlReality(
                status=UNKNOWN_STATUS,
                downloader="aebndl",
                reason=f"aebndl command failed to launch: {exc}",
            )

        bytes_seen = 0
        error_msg: Optional[str] = None
        deadline = time.time() + timeout_s
        try:
            while time.time() < deadline:
                line = proc.stdout.readline()  # type: ignore[union-attr]
                if not line:
                    if proc.poll() is not None:
                        break
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ev = evt.get("event", "")
                if ev == "progress":
                    dl = _coerce_progress_number(evt.get("downloaded"))
                    if isinstance(dl, (int, float)) and dl > 0:
                        bytes_seen = int(dl)
                        break
                elif ev == "complete":
                    raw_sz = _coerce_progress_number(evt.get("file_size"))
                    bytes_seen = int(raw_sz) if isinstance(raw_sz, (int, float)) and raw_sz > 0 else 1
                    break
                elif ev in ("error", "failed"):
                    error_msg = str(evt.get("message") or evt.get("reason") or "unknown error")
                    break
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    if bytes_seen > 0:
        return UrlReality(
            status=GOOD_STATUS,
            downloader="aebndl",
            reason=f"AEBN URL confirmed viable — {bytes_seen:,} bytes received before test kill",
        )
    if error_msg:
        return UrlReality(
            status=BAD_STATUS,
            downloader="aebndl",
            reason=f"AEBN URL reported error during test download: {error_msg}",
        )
    if proc.poll() is not None and proc.returncode not in (0, -9, -15):
        return UrlReality(
            status=BAD_STATUS,
            downloader="aebndl",
            reason=f"aebndl exited rc={proc.returncode} before any bytes received",
        )
    return UrlReality(
        status=UNKNOWN_STATUS,
        downloader="aebndl",
        reason=f"AEBN test timed out after {timeout_s}s without bytes, error, or clean exit",
    )


def _test_ytdlp_url_download(
    entry: ArchiveUrl,
    *,
    validation_log_dir: Path,
    timeout_s: int = 60,
) -> UrlReality:
    """Start a real yt-dlp download into a temp folder to verify the URL is still accessible.

    Uses the same _build_ytdlp_cmd() as normal downloads so auth and behaviour are identical.
    Limits rate to 0.5 MiB/s. Kills the process as soon as download start is confirmed.
    """
    test_root = validation_log_dir / "_ytdlp_url_tests"
    try:
        test_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    with tempfile.TemporaryDirectory(dir=test_root, prefix="ytdlp_test_") as td:
        td_path = Path(td)
        cmd = _build_ytdlp_cmd([entry.url], td_path, max_mibs=0.5)
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except (FileNotFoundError, PermissionError, OSError) as exc:
            return UrlReality(
                status=UNKNOWN_STATUS,
                downloader="yt-dlp",
                reason=f"yt-dlp command failed to launch: {exc}",
            )

        download_confirmed = False
        error_msg: Optional[str] = None
        deadline = time.time() + timeout_s
        try:
            while time.time() < deadline:
                line = proc.stdout.readline()  # type: ignore[union-attr]
                if not line:
                    if proc.poll() is not None:
                        break
                    continue
                line = line.rstrip()
                if not line:
                    continue
                if line.startswith("[download]"):
                    if "%" in line or "Destination:" in line:
                        download_confirmed = True
                        break
                elif line.startswith("ERROR:"):
                    error_msg = line[len("ERROR:"):].strip()
                    break
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    if download_confirmed:
        return UrlReality(
            status=GOOD_STATUS,
            downloader="yt-dlp",
            reason="yt-dlp URL confirmed viable — download started before test kill",
        )
    if error_msg:
        return UrlReality(
            status=BAD_STATUS,
            downloader="yt-dlp",
            reason=f"yt-dlp URL reported error during test download: {error_msg}",
        )
    if proc.poll() is not None and proc.returncode not in (0, -9, -15, 130):
        return UrlReality(
            status=BAD_STATUS,
            downloader="yt-dlp",
            reason=f"yt-dlp exited rc={proc.returncode} before download started",
        )
    return UrlReality(
        status=UNKNOWN_STATUS,
        downloader="yt-dlp",
        reason=f"yt-dlp test timed out after {timeout_s}s without confirming download start",
    )


def inspect_url(
    entry: ArchiveUrl,
    *,
    download_roots: Sequence[Path],
    count_partials: bool,
    simulate_timeout: int,
    cookies_from_browser: Optional[str],
    impersonate: Optional[str],
    verify_aebn_metadata: bool,
    validation_log_dir: Path,
    fast_filesystem_check: bool = False,
) -> UrlReality:
    partial_path = _find_partial(entry, download_roots) if count_partials else None
    if partial_path is not None:
        return UrlReality(
            status=PARTIAL_STATUS,
            downloader="local",
            reason="matching _partial directory exists",
            partial_path=str(partial_path),
        )

    if _is_aebn(entry.url):
        present = _find_aebn_specific_mp4(entry, download_roots)
        if present is not None:
            return UrlReality(
                status=PRESENT_STATUS,
                downloader="aebndl",
                reason="URL-specific AEBN filename evidence exists in a checked root",
                present_path=str(present),
            )
        # For stalled/bad entries: run a real download test using the same aebndl command
        # as normal downloads so auth behaviour is identical. This confirms whether the
        # URL is still accessible before deciding to re-queue or mark as bad.
        if entry.archive_status.lower() in _URL_TEST_STATUSES:
            return _test_aebn_url_download(entry, validation_log_dir=validation_log_dir)
        if verify_aebn_metadata:
            return _verify_aebn_metadata_existing(entry, download_roots, validation_log_dir)
        # File not found; if archive says this URL was already downloaded, flag it for
        # re-download so it enters the mismatch → change plan → re-queue pipeline.
        if _archive_status_class(entry.archive_status) == PRESENT_STATUS:
            return UrlReality(
                status=GOOD_STATUS,
                downloader="aebndl",
                reason="Archive marks URL as finished but no output file found in any checked root",
            )
        return UrlReality(
            status=UNKNOWN_STATUS,
            downloader="aebndl",
            reason="AEBN URL requires metadata/download-tool verification; no URL-specific local evidence found",
        )

    # For stalled/bad yt-dlp entries: run a real download test using the same yt-dlp command
    # as normal downloads so auth and behaviour are identical.
    if entry.archive_status.lower() in _URL_TEST_STATUSES:
        return _test_ytdlp_url_download(entry, validation_log_dir=validation_log_dir)

    # Fast filesystem-only check: skip the expensive yt-dlp simulate and instead check
    # whether the canonical output directory contains video files.
    # This is always used for "already" entries (yt-dlp archive-skips with 0 bytes downloaded
    # — file presence is unverified) and for any entry when --fast is requested.
    # Limitation: checks the directory, not the specific file, so it can miss individual
    # missing videos when the directory has other files. Use full simulate for precise checks.
    if fast_filesystem_check or entry.archive_status.lower() == "already":
        if _check_dir_has_video(entry, download_roots):
            return UrlReality(
                status=PRESENT_STATUS,
                downloader="local",
                reason="fast check: canonical dir contains video file(s) >= 5 MB",
            )
        return UrlReality(
            status=GOOD_STATUS,
            downloader="local",
            reason=(
                "fast check: canonical dir is missing or contains no video files >= 5 MB"
                + (f" (archive recorded {entry.archive_size_mib:.2f} MiB)" if entry.archive_size_mib > 0 else "")
            ),
        )

    result = _simulate_check(
        entry.url,
        _canonical_dirs(entry, download_roots),
        timeout_seconds=simulate_timeout,
        cookies_from_browser=cookies_from_browser,
        impersonate=impersonate,
    )
    if result.is_duplicate:
        return UrlReality(
            status=PRESENT_STATUS,
            downloader="yt-dlp",
            reason="yt-dlp simulate predicted an existing file",
            present_path=result.existing_path,
            predicted_name=result.predicted_name,
        )
    if result.predicted_name:
        return UrlReality(
            status=GOOD_STATUS,
            downloader="yt-dlp",
            reason="yt-dlp simulate succeeded and did not match a checked root",
            predicted_name=result.predicted_name,
        )
    if result.timed_out:
        return UrlReality(
            status=UNKNOWN_STATUS,
            downloader="yt-dlp",
            reason="yt-dlp simulate timed out — cannot confirm URL state",
        )
    return UrlReality(
        status=BAD_STATUS,
        downloader="yt-dlp",
        reason="yt-dlp simulate failed (non-zero exit, unsupported site, or network error)",
    )


def _ordered_entries(entries: List[ArchiveUrl], order: str) -> List[ArchiveUrl]:
    if order == "oldest":
        return sorted(entries, key=lambda e: (e.archive_file.stat().st_mtime, e.archive_file.name, e.archive_line))
    if order == "newest":
        return sorted(entries, key=lambda e: (-e.archive_file.stat().st_mtime, e.archive_file.name, e.archive_line))
    if order == "url-file":
        return sorted(entries, key=lambda e: (e.archive_file.name, e.archive_line))
    if order == "random":
        shuffled = list(entries)
        random.shuffle(shuffled)
        return shuffled
    return list(entries)


def _limit_count(total: int, count: Optional[int], ratio: Optional[float]) -> Optional[int]:
    limits = [value for value in (count,) if value is not None and value > 0]
    if ratio is not None and ratio > 0:
        limits.append(max(1, int(total * min(ratio, 1.0))))
    return min(limits) if limits else None


def _pop_next_entry_exclusive_by_file(pending: Deque[ArchiveUrl], active_files: set[Path]) -> Optional[ArchiveUrl]:
    if not pending:
        return None
    if not active_files:
        return pending.popleft()
    for idx, entry in enumerate(pending):
        if entry.archive_file not in active_files:
            del pending[idx]
            return entry
    return None


def _build_interleaved_file_pool(entries: List[ArchiveUrl]) -> List[deque]:
    """Group entries by source file then interleave AEBN (ae-*) and yt-dlp (yt-*) file batches.

    Each returned deque holds all entries from one archive file. AEBN and yt-dlp
    files alternate so workers always process a mix of both types concurrently.
    """
    file_groups: Dict[Path, List[ArchiveUrl]] = defaultdict(list)
    for entry in entries:
        file_groups[entry.archive_file].append(entry)

    aebn_batches: List[deque] = []
    ytdlp_batches: List[deque] = []
    for file_path in sorted(file_groups.keys(), key=lambda p: p.name):
        batch: deque = deque(file_groups[file_path])
        if file_path.name.startswith("ae-"):
            aebn_batches.append(batch)
        else:
            ytdlp_batches.append(batch)

    result: List[deque] = []
    ae_i = yt_i = 0
    while ae_i < len(aebn_batches) or yt_i < len(ytdlp_batches):
        if ae_i < len(aebn_batches):
            result.append(aebn_batches[ae_i])
            ae_i += 1
        if yt_i < len(ytdlp_batches):
            result.append(ytdlp_batches[yt_i])
            yt_i += 1
    return result


def _render_worker_ui(
    workers: Dict[int, WorkerView],
    *,
    total: int,
    processed: int,
    matched: int,
    mismatch_count: int,
    unknown_count: int,
    partial_count: int,
    status_counts: Counter[str],
    evidence_counts: Counter[str],
    selected_slot: int,
    show_log: bool,
    stopped_by: str,
    elapsed_s: float,
) -> None:
    sys.stdout.write("\x1b[0m\x1b[2J\x1b[H")
    rate = processed / elapsed_s if elapsed_s > 0 else 0.0
    remaining = max(0, total - processed)
    eta = td_utils.format_duration_hms(remaining / rate) if rate > 0 and remaining > 0 else ("0s" if remaining == 0 else "?")
    header = (
        f"ytaedl archive validate  "
        f"proc {_metric(processed, 'yellow')}/{total}  "
        f"ok {_metric(matched, 'green')}  mism {_metric(mismatch_count, 'red')}  "
        f"unk {_metric(unknown_count, 'magenta')}  part {_metric(partial_count, 'cyan')}  "
        f"{rate:.1f}/s  ETA {eta}  stop={stopped_by}"
    )
    sys.stdout.write(_color(header, "bright") + "\n")
    sys.stdout.write(f"counts: {_metric_legend()}\n")
    status_part = "  ".join(
        f"{_color(s, _status_color(s))}={c}" for s, c in sorted(status_counts.items())
    )
    evidence_part = "  ".join(f"{k}={c}" for k, c in sorted(evidence_counts.items()))
    combined = f"status: {status_part}   ev: {evidence_part}"
    sys.stdout.write(combined[:170] + "\n")
    sys.stdout.write(_color("Up/Down=select worker  v=log  q=stop", "gray") + "\n")
    for slot in sorted(workers):
        view = workers[slot]
        marker = _color(">", "yellow") if slot == selected_slot else " "
        tag = _color(view.current_tag, _tag_color(view.current_tag))
        worker_elapsed = max(0.001, time.time() - view.started_at)
        worker_rate = view.processed / worker_elapsed
        counts = _metric_group(view.processed, view.matched, view.mismatches, view.unknown, view.partial)
        source = f"{view.current_file}:{view.current_line}" if view.current_line else (view.current_file or "-")
        phase_str = _color(view.phase, "cyan" if view.phase == "checking" else "gray")
        sys.stdout.write(
            f"{marker} W{slot:02d}{tag} {phase_str:<15}  {counts}  {worker_rate:.1f}/s  {source}\n"
        )
        if view.last_transition != "-":
            transition_colored = _color(view.last_transition, _status_color(view.last_status))
            url_short = view.last_url[:75] if view.last_url not in ("-", "") else "-"
            sys.stdout.write(
                f"  {transition_colored}  {view.last_elapsed_s:.2f}s  {view.last_tool:<8}  {url_short}\n"
            )
        else:
            sys.stdout.write(f"  {_color('idle', 'gray')}\n")
    sys.stdout.write(_color("-" * 100, "gray") + "\n")
    if show_log and selected_slot in workers:
        sys.stdout.write(_color(f"\nworker-{selected_slot:02d} log\n", "bright"))
        sys.stdout.write(_color("-" * 100, "gray") + "\n")
        for line in list(workers[selected_slot].log)[-18:]:
            sys.stdout.write(line[:140] + "\n")
    sys.stdout.flush()


def _append_log(path: Path, message: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")
    except OSError:
        return


def _worker_log_path(validation_log_dir: Path, slot: int) -> Path:
    return validation_log_dir / f"archive-validate-worker-{slot:02d}.log"


def _read_key() -> Optional[str]:
    try:
        import msvcrt  # type: ignore
    except Exception:
        return None
    if not msvcrt.kbhit():
        return None
    ch = msvcrt.getwch()
    if ch in ("\x00", "\xe0"):
        special = msvcrt.getwch()
        if special == "H":
            return "up"
        if special == "P":
            return "down"
        return None
    return ch.lower()


def validate_archive(
    *,
    archive_dir: Path,
    log_dir: Path,
    validation_log_dir: Path,
    download_roots: Sequence[Path],
    workers: int,
    order: str,
    max_seconds: Optional[float],
    max_count: Optional[int],
    ratio: Optional[float],
    count_partials: bool,
    simulate_timeout: int,
    cookies_from_browser: Optional[str],
    impersonate: Optional[str],
    verify_aebn_metadata: bool,
    realtime: bool,
    fast_filesystem_check: bool = False,
    sample_pct: Optional[float] = None,
) -> ValidationSummary:
    all_entries = _ordered_entries(load_archive_urls(archive_dir), order)
    total = len(all_entries)

    # Random sampling: shuffle the full pool and take the requested percentage.
    # Overrides -R/--ratio and -c/--count limits when active.
    actual_sample_pct: Optional[float] = None
    if sample_pct is not None and sample_pct > 0:
        clamped = min(sample_pct, 100.0)
        n = max(1, int(round(total * clamped / 100.0)))
        shuffled = list(all_entries)
        random.shuffle(shuffled)
        all_entries = shuffled[:n]
        actual_sample_pct = 100.0 * n / total if total > 0 else 0.0
    else:
        limit = _limit_count(total, max_count, ratio)
        if limit is not None:
            all_entries = all_entries[:limit]

    target = len(all_entries)
    start = time.time()
    stop = threading.Event()
    lock = threading.Lock()
    worker_views = {slot: WorkerView(slot) for slot in range(1, max(1, workers) + 1)}
    selected_slot = 1
    show_log = False
    stopped_by = "complete"
    mismatches: List[Mismatch] = []
    matched = 0
    partial_count = 0
    unknown_count = 0
    processed = 0
    status_counts: Counter[str] = Counter()
    evidence_counts: Counter[str] = Counter()
    domain_breakdown: Dict[str, Counter] = {}
    transition_counts: Counter[str] = Counter()

    log_dir.mkdir(parents=True, exist_ok=True)
    validation_log_dir.mkdir(parents=True, exist_ok=True)
    master_log_path = validation_log_dir / "archive-validate-master.log"

    run_header = (
        f"{'#'*80}\n"
        f"# ytaedl archive validate  —  {_utc_now()}\n"
        f"# archive dir:      {archive_dir}\n"
        f"# log dir:          {log_dir}\n"
        f"# download roots:   {', '.join(str(r) for r in download_roots)}\n"
        f"# workers:          {workers}\n"
        f"# order:            {order}\n"
        f"# total entries:    {target}\n"
        f"# fast filesystem:  {fast_filesystem_check}\n"
        f"{'#'*80}\n"
    )
    _append_log(master_log_path, run_header)
    _append_log(
        master_log_path,
        (
            f"{_utc_now()} START archive_dir={archive_dir} log_dir={log_dir} "
            f"validation_log_dir={validation_log_dir} workers={workers} order={order} total={target}"
        ),
    )

    # Per-worker: track the last URL file seen so we can log file transitions.
    worker_last_file: Dict[int, str] = {}

    def _worker_readable_log_path(slot: int) -> Path:
        return validation_log_dir / f"worker-{slot:02d}.log"

    for slot in range(1, max(1, workers) + 1):
        _append_log(
            _worker_readable_log_path(slot),
            (
                f"{'#'*80}\n"
                f"# ytaedl archive validate — worker-{slot:02d}  —  {_utc_now()}\n"
                f"# archive dir:    {archive_dir}\n"
                f"# download roots: {', '.join(str(r) for r in download_roots)}\n"
                f"# fast mode:      {fast_filesystem_check}\n"
                f"{'#'*80}\n"
                f"# Columns: [verdict] archive_status -> actual_status  elapsed  tool  line#  url\n"
                f"# verdict: OK=match, MISMATCH=needs fix, UNKNOWN=inconclusive\n"
                f"{'#'*80}\n"
            ),
        )

    def _run_one(slot: int, entry: ArchiveUrl) -> Tuple[ArchiveUrl, UrlReality]:
        view = worker_views[slot]
        t_url = time.time()
        with lock:
            tag = _tool_tag(entry.url)
            tool_name = "aebndl" if tag == "[A]" else "yt-dlp"
            prev_file = worker_last_file.get(slot, "")
            if entry.archive_file.name != prev_file:
                worker_last_file[slot] = entry.archive_file.name
                file_header = (
                    f"\n{'='*80}\n"
                    f"  URL FILE: {entry.archive_file.name}  ({_utc_now()})\n"
                    f"  Full path: {entry.archive_file}\n"
                    f"{'='*80}\n"
                )
                _append_log(_worker_readable_log_path(slot), file_header)
                _append_log(master_log_path,
                    f"{_utc_now()} FILE worker={slot:02d} {entry.archive_file.name}")

            start_line = (
                f"{_utc_now()} START worker={slot:02d} {tag} {entry.archive_status} "
                f"{entry.archive_file.name}:{entry.archive_line} {entry.url}"
            )
            view.current_tag = tag
            view.current = entry.url
            view.current_file = entry.archive_file.name
            view.current_line = entry.archive_line
            view.phase = "checking"
            view.log.append(start_line)
            _append_log(_worker_log_path(validation_log_dir, slot), start_line)
            _append_log(master_log_path, start_line)

        reality = inspect_url(
            entry,
            download_roots=download_roots,
            count_partials=count_partials,
            simulate_timeout=simulate_timeout,
            cookies_from_browser=cookies_from_browser,
            impersonate=impersonate,
            verify_aebn_metadata=verify_aebn_metadata,
            validation_log_dir=validation_log_dir,
            fast_filesystem_check=fast_filesystem_check,
        )
        elapsed = time.time() - t_url

        with lock:
            result = f"{entry.archive_status} -> {reality.status} ({reality.downloader}) {reality.reason}"
            view.processed += 1
            view.last_result = result
            view.last_status = reality.status
            view.last_elapsed_s = elapsed
            view.last_transition = f"{entry.archive_status}→{reality.status}"
            view.last_tool = reality.downloader or "-"
            view.last_url = entry.url
            if reality.status == UNKNOWN_STATUS:
                view.unknown += 1
            elif reality.status == PARTIAL_STATUS:
                view.partial += 1
            elif _status_matches(entry.archive_status, reality.status):
                view.matched += 1
            is_mismatch = reality.status != UNKNOWN_STATUS and not _status_matches(entry.archive_status, reality.status)
            if is_mismatch:
                view.mismatches += 1
            view.phase = "idle"

            # Dense machine-readable line (existing format, goes to per-worker debug log + master)
            result_line = (
                f"{_utc_now()} RESULT worker={slot:02d} {view.current_tag} "
                f"source={entry.archive_file.name}:{entry.archive_line} elapsed={elapsed:.3f}s "
                f"{result} url={entry.url}"
                + (f" present={reality.present_path}" if reality.present_path else "")
                + (f" partial={reality.partial_path}" if reality.partial_path else "")
            )
            view.log.append(result_line)
            _append_log(_worker_log_path(validation_log_dir, slot), result_line)
            _append_log(master_log_path, result_line)

            # Human-readable line (goes to worker-NN.log)
            verdict = "MISMATCH" if is_mismatch else ("UNKNOWN" if reality.status == UNKNOWN_STATUS else "OK     ")
            readable = (
                f"[{verdict}] {entry.archive_status:>12} -> {reality.status:<12}  "
                f"{elapsed:6.2f}s  {tool_name:<7}  "
                f"line {entry.archive_line:>4}  {entry.url}"
            )
            if reality.reason:
                readable += f"\n          reason: {reality.reason}"
            if reality.present_path:
                readable += f"\n          file:   {reality.present_path}"
            _append_log(_worker_readable_log_path(slot), readable)

        return entry, reality

    # Build interleaved file pool: AEBN and yt-dlp files alternate so workers always
    # process a mix of both types. Each worker owns its file entirely before moving on.
    file_pool: List[deque] = _build_interleaved_file_pool(all_entries)
    file_pool_idx = 0  # main-thread-only counter — no lock needed
    worker_batches: Dict[int, deque] = {}

    def _claim_next_file() -> Optional[deque]:
        nonlocal file_pool_idx
        while file_pool_idx < len(file_pool):
            batch = file_pool[file_pool_idx]
            file_pool_idx += 1
            if batch:
                return batch
        return None

    # Prime each worker slot with its first file from the pool
    for slot in range(1, max(1, workers) + 1):
        batch = _claim_next_file()
        if batch is not None:
            worker_batches[slot] = batch

    active: Dict[concurrent.futures.Future[Tuple[ArchiveUrl, UrlReality]], Tuple[int, Path]] = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        while True:
            if max_seconds is not None and max_seconds > 0 and time.time() - start >= max_seconds:
                stopped_by = "timer"
                stop.set()

            # Submit one entry per idle worker from its currently assigned file batch.
            # When a worker's batch is exhausted it claims the next file from the pool.
            if not stop.is_set():
                active_slots = {slot for slot, _ in active.values()}
                for slot in sorted(worker_views):
                    if slot in active_slots:
                        continue
                    batch = worker_batches.get(slot)
                    if not batch:
                        new_batch = _claim_next_file()
                        if new_batch is None:
                            continue
                        worker_batches[slot] = new_batch
                        batch = worker_batches[slot]
                    entry = batch.popleft()
                    active[pool.submit(_run_one, slot, entry)] = (slot, entry.archive_file)

            done = [future for future in active if future.done()]
            for future in done:
                slot, _file_path = active.pop(future)
                try:
                    entry, reality = future.result()
                except Exception as exc:
                    entry = ArchiveUrl("", "unknown", Path("-"), 0, "", "-")
                    reality = UrlReality(BAD_STATUS, "validator", str(exc))
                with lock:
                    processed += 1
                    status_counts[reality.status] += 1
                    evidence_counts[reality.downloader] += 1
                    domain = _extract_domain(entry.url)
                    domain_breakdown.setdefault(domain, Counter())[reality.status] += 1
                    transition_counts[f"{entry.archive_status} -> {reality.status}"] += 1
                    if reality.status == PARTIAL_STATUS:
                        partial_count += 1
                    if reality.status == UNKNOWN_STATUS:
                        unknown_count += 1
                    elif _status_matches(entry.archive_status, reality.status):
                        matched += 1
                    else:
                        mismatches.append(
                            Mismatch(
                                url=entry.url,
                                archive_status=entry.archive_status,
                                actual_status=reality.status,
                                archive_file=str(entry.archive_file),
                                archive_line=entry.archive_line,
                                source_group=entry.source_group,
                                downloader=reality.downloader,
                                reason=reality.reason,
                                present_path=reality.present_path,
                                partial_path=reality.partial_path,
                            )
                        )
                    worker_views[slot].current = "-"
                    worker_views[slot].current_file = "-"
                    worker_views[slot].current_line = 0
                    worker_views[slot].phase = "idle"

            has_more_work = (
                file_pool_idx < len(file_pool)
                or any(bool(worker_batches.get(s)) for s in worker_views)
            )
            if not active and (stop.is_set() or not has_more_work):
                break

            key = _read_key() if realtime else None
            if key == "q":
                stopped_by = "user"
                stop.set()
            elif key == "v":
                show_log = not show_log
            elif key == "up":
                selected_slot = max(1, selected_slot - 1)
            elif key == "down":
                selected_slot = min(len(worker_views), selected_slot + 1)

            if max_count is not None and processed >= max_count:
                stopped_by = "count"
                stop.set()
            if realtime:
                _render_worker_ui(
                    worker_views,
                    total=target,
                    processed=processed,
                    matched=matched,
                    mismatch_count=len(mismatches),
                    unknown_count=unknown_count,
                    partial_count=partial_count,
                    status_counts=status_counts,
                    evidence_counts=evidence_counts,
                    selected_slot=selected_slot,
                    show_log=show_log,
                    stopped_by=stopped_by,
                    elapsed_s=time.time() - start,
                )
            if not done:
                time.sleep(0.1)

    elapsed_total = time.time() - start
    _append_log(
        master_log_path,
        (
            f"{_utc_now()} FINISH processed={processed} matched={matched} mismatches={len(mismatches)} "
            f"unknown={unknown_count} partial={partial_count} stopped_by={stopped_by} "
            f"elapsed={elapsed_total:.3f}s"
        ),
    )
    finish_footer = (
        f"\n{'#'*80}\n"
        f"# FINISHED  {_utc_now()}\n"
        f"# processed={processed}/{target}  matched={matched}  mismatches={len(mismatches)}\n"
        f"# unknown={unknown_count}  partial={partial_count}  stopped_by={stopped_by}\n"
        f"# elapsed={elapsed_total:.1f}s\n"
        f"{'#'*80}\n"
    )
    _append_log(master_log_path, finish_footer)
    for slot in range(1, max(1, workers) + 1):
        _append_log(_worker_readable_log_path(slot), finish_footer)
    return ValidationSummary(
        total_archive_urls=total,
        processed=processed,
        matched=matched,
        mismatches=mismatches,
        partial_count=partial_count,
        unknown_count=unknown_count,
        elapsed_s=time.time() - start,
        stopped_by=stopped_by,
        status_counts=status_counts,
        evidence_counts=evidence_counts,
        domain_breakdown=domain_breakdown,
        transition_counts=transition_counts,
        sample_pct=actual_sample_pct,
    )


def build_change_plan(
    summary: ValidationSummary,
    *,
    archive_dir: Path,
    log_dir: Path,
) -> dict:
    changes = []
    for item in summary.mismatches:
        if item.actual_status == GOOD_STATUS:
            action = "remove_archive_entry"
            domain_action = "requeue_url"
        elif item.actual_status == PARTIAL_STATUS:
            action = "remove_archive_entry"
            domain_action = "requeue_url"
        elif item.actual_status == PRESENT_STATUS:
            action = "set_archive_status"
            domain_action = "set_finished"
        else:
            if item.archive_status == "stalled" and item.actual_status == UNKNOWN_STATUS:
                # Can't confirm viability; leave unchanged so the URL gets retried naturally.
                continue
            action = "set_archive_status"
            domain_action = "set_finished"
        changes.append(
            {
                "url": item.url,
                "archive_file": item.archive_file,
                "archive_line": item.archive_line,
                "old_status": item.archive_status,
                "new_status": item.actual_status,
                "transition": item.transition,
                "action": action,
                "domain_index_action": domain_action,
                "reason": item.reason,
            }
        )
    return {
        "version": PLAN_VERSION,
        "generated_at": _utc_now(),
        "archive_dir": str(archive_dir),
        "log_dir": str(log_dir),
        "summary": {
            "total_archive_urls": summary.total_archive_urls,
            "processed": summary.processed,
            "matched": summary.matched,
            "mismatches": len(summary.mismatches),
            "partial_count": summary.partial_count,
            "unknown_count": summary.unknown_count,
            "stopped_by": summary.stopped_by,
            "status_counts": dict(summary.status_counts),
            "evidence_counts": dict(summary.evidence_counts),
        },
        "changes": changes,
    }


def apply_change_plan(plan_path: Path, *, archive_dir: Optional[Path], log_dir: Optional[Path], dry_run: bool) -> int:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    base_archive = archive_dir or Path(plan["archive_dir"])
    base_log = log_dir or Path(plan["log_dir"])
    changes = plan.get("changes", [])
    by_file: Dict[Path, List[dict]] = defaultdict(list)
    for change in changes:
        path = Path(change["archive_file"])
        if not path.is_absolute():
            path = base_archive / path
        by_file[path].append(change)

    archive_updates = 0
    requeued_count = 0
    marked_bad_count = 0
    confirmed_present_count = 0
    for path, file_changes in by_file.items():
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        remove_urls = {c["url"] for c in file_changes if c.get("action") == "remove_archive_entry"}
        set_by_url = {c["url"]: c for c in file_changes if c.get("action") == "set_archive_status"}
        new_lines: List[str] = []
        for line in lines:
            parts = line.split("\t")
            url = parts[-1].strip() if len(parts) >= 6 else ""
            if url in remove_urls:
                archive_updates += 1
                requeued_count += 1
                continue
            if url in set_by_url:
                change = set_by_url[url]
                new_status = change["new_status"]
                parts[0] = new_status
                line = "\t".join(parts)
                archive_updates += 1
                if new_status == PRESENT_STATUS:
                    confirmed_present_count += 1
                else:
                    marked_bad_count += 1
            new_lines.append(line)
        if not dry_run:
            path.write_text("\n".join(new_lines) + ("\n" if new_lines else ""), encoding="utf-8")

    # domain_index.json lives in the archive folder; fall back to log dir for compat
    index_path = base_archive / "domain_index.json"
    if not index_path.exists():
        index_path = base_log / "domain_index.json"
    domain_updates = 0
    domain_requeue_breakdown: Dict[str, int] = {}
    if index_path.exists():
        index = DomainIndex.load(index_path)
        index_modified = False
        for change in changes:
            url = change["url"]
            action = change.get("domain_index_action")
            if action == "set_finished":
                status = PRESENT_STATUS if change.get("new_status") == PRESENT_STATUS else change.get("new_status", PRESENT_STATUS)
                index.mark_finished(url, status)
                domain_updates += 1
                index_modified = True
            elif action in ("requeue_url", "remove_finished"):
                # "remove_finished" is the legacy name; both actions should unfinish + re-queue
                if index.unfinish_and_requeue_url(url):
                    domain_updates += 1
                    d = _extract_domain(url)
                    domain_requeue_breakdown[d] = domain_requeue_breakdown.get(d, 0) + 1
                    index_modified = True
        if index_modified and not dry_run:
            index.save(index_path)

    print("\n=== Archive Apply Summary ===")
    print(f"Plan:          {plan_path}")
    print(f"Archive dir:   {base_archive}")
    print(f"Log dir:       {base_log}")
    print(f"Dry run:       {dry_run}")
    print()
    print("--- Changes applied ---")
    print(f"Re-queued (removed from archive):       {requeued_count:>6}")
    print(f"Marked bad-url:                         {marked_bad_count:>6}")
    print(f"Confirmed present (status updated):     {confirmed_present_count:>6}")
    print(f"Total archive file edits:               {archive_updates:>6}")
    print(f"Domain index updates:                   {domain_updates:>6}")
    if domain_requeue_breakdown:
        print()
        print("--- Domain breakdown of re-queued URLs ---")
        for d, cnt in sorted(domain_requeue_breakdown.items(), key=lambda x: -x[1]):
            print(f"  {d:<40} {cnt:>6}")
    return 0


def _print_summary(summary: ValidationSummary) -> None:
    n_processed = summary.processed or 1  # avoid division by zero
    pool_total = summary.total_archive_urls
    is_sampled = summary.sample_pct is not None
    sample_fraction = (summary.sample_pct / 100.0) if is_sampled else 1.0

    needs_redl = summary.status_counts.get(GOOD_STATUS, 0) + summary.status_counts.get(PARTIAL_STATUS, 0)
    confirmed_done = summary.status_counts.get(PRESENT_STATUS, 0)
    confirmed_bad = summary.status_counts.get(BAD_STATUS, 0)
    unknown = summary.status_counts.get(UNKNOWN_STATUS, 0)

    def pct(n: int) -> str:
        return f"{100.0 * n / n_processed:5.1f}%"

    def extrap(n: int) -> str:
        """Extrapolated count across the full pool, shown only in sample mode."""
        if not is_sampled or sample_fraction <= 0:
            return ""
        est = int(round(n / sample_fraction))
        return f"  →  est. {est:>7,} of {pool_total:,} total"

    mode_tag = f" — SAMPLED {summary.sample_pct:.1f}% of pool" if is_sampled else ""
    print(f"\n=== Archive Validation Summary{mode_tag} ===")
    if is_sampled:
        print(f"Sample:           {summary.processed:>8,} URLs checked  ({summary.sample_pct:.1f}% of {pool_total:,} total)")
        print(f"                  Results below are sample rates; extrapolated totals shown after →")
    else:
        print(f"Processed:        {summary.processed:>8,} / {pool_total:,} entries"
              f"  ({summary.elapsed_s:.1f}s, {summary.processed / max(summary.elapsed_s, 0.001):.1f}/s)")
    print(f"Stopped by:       {summary.stopped_by}")
    print(f"Elapsed:          {summary.elapsed_s:.1f}s  ({summary.processed / max(summary.elapsed_s, 0.001):.1f} URLs/s)")

    print()
    print("--- Actual State ---")
    print(f"Confirmed on disk:      {confirmed_done:>8,}  ({pct(confirmed_done)}){extrap(confirmed_done)}")
    print(f"Needs re-download:      {needs_redl:>8,}  ({pct(needs_redl)}){extrap(needs_redl)}  [file missing or URL re-viable]")
    print(f"Confirmed bad/dead:     {confirmed_bad:>8,}  ({pct(confirmed_bad)}){extrap(confirmed_bad)}")
    print(f"Partial downloads:      {summary.partial_count:>8,}  ({pct(summary.partial_count)}){extrap(summary.partial_count)}")
    print(f"Unknown / unverified:   {unknown:>8,}  ({pct(unknown)}){extrap(unknown)}")

    requeue_plan = sum(1 for m in summary.mismatches if m.actual_status in (GOOD_STATUS, PARTIAL_STATUS))
    mark_bad_plan = sum(1 for m in summary.mismatches if m.actual_status == BAD_STATUS)
    confirm_plan = sum(1 for m in summary.mismatches if m.actual_status == PRESENT_STATUS)
    if summary.mismatches:
        print()
        if is_sampled:
            print(f"--- Changes plan would apply  (sample only — {summary.processed:,} of {pool_total:,} URLs checked) ---")
        else:
            print("--- Changes the plan will apply ---")
        print(f"Re-queue (remove from archive):      {requeue_plan:>6}  ({pct(requeue_plan)}){extrap(requeue_plan)}")
        print(f"Mark bad:                            {mark_bad_plan:>6}  ({pct(mark_bad_plan)}){extrap(mark_bad_plan)}")
        print(f"Confirm present (update archive):    {confirm_plan:>6}  ({pct(confirm_plan)}){extrap(confirm_plan)}")
        if is_sampled:
            print(f"  Note: apply-plan only fixes the sampled URLs; re-run full validate to fix all.")

    if summary.evidence_counts:
        print()
        print("--- Evidence sources ---")
        for source, count in sorted(summary.evidence_counts.items(), key=lambda x: -x[1]):
            print(f"  {source:<24} {count:>8,}  ({pct(count)})")

    if summary.domain_breakdown:
        print()
        print("--- Domain Breakdown ---")
        col_w = max(len(d) for d in summary.domain_breakdown) + 2
        col_w = max(col_w, 26)
        if is_sampled:
            hdr = (f"{'Domain':<{col_w}} {'Done%':>7}  {'Re-DL%':>7}  {'Bad%':>6}  "
                   f"{'Unk%':>6}  {'Sampled':>8}  {'Est.Total':>10}")
        else:
            hdr = (f"{'Domain':<{col_w}} {'Done':>8}  {'Done%':>6}  {'Re-DL':>6}  "
                   f"{'Bad':>6}  {'Unknown':>8}  {'Total':>8}")
        print(hdr)
        print("-" * len(hdr))
        rows = []
        for domain, counts in summary.domain_breakdown.items():
            done = counts.get(PRESENT_STATUS, 0)
            redl = counts.get(GOOD_STATUS, 0) + counts.get(PARTIAL_STATUS, 0)
            bad = counts.get(BAD_STATUS, 0)
            unk = counts.get(UNKNOWN_STATUS, 0)
            tot = sum(counts.values())
            rows.append((domain, done, redl, bad, unk, tot))
        rows.sort(key=lambda r: -r[5])
        for domain, done, redl, bad, unk, tot in rows:
            d_total = tot or 1
            if is_sampled:
                est_tot = int(round(tot / sample_fraction)) if sample_fraction > 0 else 0
                print(
                    f"{domain:<{col_w}} {100*done/d_total:>6.1f}%  {100*redl/d_total:>6.1f}%  "
                    f"{100*bad/d_total:>5.1f}%  {100*unk/d_total:>5.1f}%  {tot:>8,}  {est_tot:>10,}"
                )
            else:
                print(
                    f"{domain:<{col_w}} {done:>8,}  {100*done/d_total:>5.1f}%  {redl:>6,}  "
                    f"{bad:>6,}  {unk:>8,}  {tot:>8,}"
                )

    if summary.transition_counts:
        print()
        print("--- Mismatch transitions ---")
        for transition, count in sorted(summary.transition_counts.items(), key=lambda x: -x[1]):
            if " -> " in transition:
                old_s, new_s = transition.split(" -> ", 1)
                if old_s != new_s:
                    ext = extrap(count)
                    print(f"  {transition:<40} {count:>6,}  ({pct(count)}){ext}")

    if summary.mismatches:
        files = sorted({item.archive_file for item in summary.mismatches})
        print()
        print("URL files with mismatches:")
        for path in files:
            print(f"  {path}")
        print()
        print("Mismatched URLs:")
        for item in summary.mismatches:
            print(
                f"  {item.transition} | {item.archive_file}:{item.archive_line} | "
                f"{item.downloader} | {item.reason} | {item.url}"
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ytaedl archive validate",
        description=f"ytaedl {YTAEDL_VERSION} - validate archive/domain_index state against current URL reality.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    _stars_default = os.environ.get("STARS_DIR", "./files/downloads/stars")
    _ae_default = os.environ.get("AESTARS_DIR", "./files/downloads/ae-stars")
    parser.add_argument("-a", "--archive", default="./archive", help="Archive folder containing per-urlfile status files.")
    parser.add_argument("-g", "--log-dir", default="./logs", help="Log folder containing domain_index.json.")
    parser.add_argument("-G", "--validation-log-dir", default=None, help="Folder for archive validation logs (default: validator_logs/ next to archive/).")
    parser.add_argument("-s", "--stars-dir", default=_stars_default, help="yt-dlp URL file directory ($STARS_DIR).")
    parser.add_argument("-d", "--aebn-dir", default=_ae_default, help="AEBN URL file directory ($AESTARS_DIR).")
    parser.add_argument("-L", "--download-root", action="append", default=None, help="Download root to check for existing files. Repeatable.")
    parser.add_argument("-t", "--threads", dest="workers", type=int, default=2, help="Number of concurrent validation workers.")
    parser.add_argument("-w", "--workers", dest="workers", type=int, help=argparse.SUPPRESS)
    parser.add_argument("-O", "--order", choices=("oldest", "newest", "url-file", "random"), default="url-file", help="Archive URL processing order.")
    parser.add_argument("-T", "--timer-seconds", type=float, default=None, help="Stop after this many seconds and print a summary.")
    parser.add_argument("-c", "--count", type=int, default=None, help="Stop after this many archive URLs have completed validation.")
    parser.add_argument("-R", "--ratio", type=float, default=None, help="Stop after this ratio of archive URLs has completed validation.")
    parser.add_argument("-p", "--count-partials", action="store_true", help="Count and report URLs with matching _partial state.")
    parser.add_argument("-j", "--json-plan", default="validator_logs/archive_repair_plan.json", help="Path for the JSON repair plan.")
    parser.add_argument("-n", "--no-ui", action="store_true", help="Disable the realtime in-place worker UI.")
    parser.add_argument("-S", "--simulate-timeout", type=int, default=15, help="yt-dlp simulate timeout per URL.")
    parser.add_argument("-M", "--aebn-metadata-check", action="store_true", help="Use aebndl metadata naming checks for AEBN URLs without downloading segments.")
    parser.add_argument("-b", "--ytdlp-cookies-from-browser", default="firefox", help="Browser cookie source for yt-dlp simulate; use 'none' to disable.")
    parser.add_argument("-i", "--ytdlp-impersonate", default="chrome", help="yt-dlp impersonation browser; use 'none' to disable.")
    parser.add_argument(
        "-F", "--fast",
        action="store_true",
        help=(
            "Fast filesystem-only check: skip yt-dlp simulate and instead verify whether "
            "the canonical output directory contains video files. Always active for 'already' "
            "entries (0-byte archive skips). Much faster than simulate but cannot verify which "
            "specific video is present — use for bulk re-queue of undownloaded URL files."
        ),
    )
    parser.add_argument(
        "-r", "--sample",
        dest="sample_pct",
        type=float,
        default=None,
        metavar="PCT",
        help=(
            "Random sampling mode: randomly select PCT%% of archive URLs to validate instead "
            "of processing all of them (e.g. --sample 10 checks a random 10%%). "
            "Summary shows sample rates and extrapolated estimates for the full pool. "
            "Overrides -R/--ratio and -c/--count when set."
        ),
    )
    return parser


def _prompt_clear_validator_logs(vlog_dir: Path) -> bool:
    """Check for existing logs and prompt the user before overwriting.

    Returns True to proceed, False to abort.
    Choices: y=delete old logs, c=copy to timestamped backup then delete, n=abort.
    """
    existing = sorted(vlog_dir.glob("archive-validate*.log"))
    if not existing:
        return True
    oldest_ts = min(f.stat().st_mtime for f in existing)
    oldest_dt = _dt.datetime.fromtimestamp(oldest_ts).strftime("%Y-%m-%d %H:%M:%S")
    print(f"\nExisting validator logs found in: {vlog_dir}")
    print(f"  {len(existing)} log file(s), from run started {oldest_dt}")
    print("  [y] delete old logs and start fresh")
    print("  [c] copy old logs to a timestamped backup folder, then start fresh")
    print("  [n] abort")
    while True:
        sys.stdout.write("Choice [y/c/n]: ")
        sys.stdout.flush()
        try:
            choice = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return False
        if choice == "y":
            for f in existing:
                try:
                    f.unlink()
                except OSError:
                    pass
            return True
        if choice == "c":
            import shutil
            ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = vlog_dir.parent / f"{vlog_dir.name}_{ts}"
            try:
                shutil.copytree(vlog_dir, backup)
                print(f"  Backed up to: {backup}")
            except Exception as exc:
                print(f"  Backup failed: {exc} — aborting to avoid data loss.")
                return False
            for f in existing:
                try:
                    f.unlink()
                except OSError:
                    pass
            return True
        if choice == "n":
            print("Aborted.")
            return False
        print("  Please enter y, c, or n.")


def cli_main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    archive_dir = Path(args.archive).expanduser().resolve()
    log_dir = Path(args.log_dir).expanduser().resolve()
    # Default: ./validator_logs relative to CWD — sits at the run root alongside archive/ and logs/.
    validation_log_dir = (
        Path(args.validation_log_dir).expanduser().resolve()
        if args.validation_log_dir
        else Path("validator_logs").resolve()
    )
    if not _prompt_clear_validator_logs(validation_log_dir):
        return 1
    download_roots = [Path(p).expanduser().resolve() for p in (args.download_root or ["./stars"])]
    cookies = None if str(args.ytdlp_cookies_from_browser).lower() == "none" else args.ytdlp_cookies_from_browser
    impersonate = None if str(args.ytdlp_impersonate).lower() == "none" else args.ytdlp_impersonate
    summary = validate_archive(
        archive_dir=archive_dir,
        log_dir=log_dir,
        validation_log_dir=validation_log_dir,
        download_roots=download_roots,
        workers=max(1, args.workers),
        order=args.order,
        max_seconds=args.timer_seconds,
        max_count=args.count,
        ratio=args.ratio,
        count_partials=args.count_partials,
        simulate_timeout=args.simulate_timeout,
        cookies_from_browser=cookies,
        impersonate=impersonate,
        verify_aebn_metadata=args.aebn_metadata_check,
        realtime=not args.no_ui,
        fast_filesystem_check=args.fast,
        sample_pct=args.sample_pct,
    )
    _print_summary(summary)
    plan_path = Path(args.json_plan).expanduser().resolve()
    plan = build_change_plan(summary, archive_dir=archive_dir, log_dir=log_dir)
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nRepair plan written: {plan_path}")
    return 1 if summary.mismatches else 0


def apply_main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ytaedl archive apply-plan",
        description=f"ytaedl {YTAEDL_VERSION} - apply a JSON archive validation change plan.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("-p", "--plan-file", default="./validator_logs/archive_repair_plan.json", help="JSON change plan produced by archive validate (default: ./validator_logs/archive_repair_plan.json).")
    parser.add_argument("-a", "--archive", default=None, help="Override archive folder to apply changes to.")
    parser.add_argument("-g", "--log-dir", default=None, help="Override log folder containing domain_index.json.")
    parser.add_argument("-n", "--dry-run", action="store_true", help="Print the apply summary without writing changes.")
    args = parser.parse_args(argv)
    return apply_change_plan(
        Path(args.plan_file).expanduser().resolve(),
        archive_dir=Path(args.archive).expanduser().resolve() if args.archive else None,
        log_dir=Path(args.log_dir).expanduser().resolve() if args.log_dir else None,
        dry_run=args.dry_run,
    )


def status_main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ytaedl archive status",
        description=f"ytaedl {YTAEDL_VERSION} - fast archive status overview (no network required).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    _stars_default = os.environ.get("STARS_DIR")
    _ae_default = os.environ.get("AESTARS_DIR")
    parser.add_argument("-a", "--archive", default="./archive", help="Archive folder containing per-urlfile status files.")
    parser.add_argument("-s", "--stars-dir", default=_stars_default, metavar="DIR",
                        help="yt-dlp URL file directory (*.txt); shows URL file coverage stats ($STARS_DIR).")
    parser.add_argument("-d", "--aebn-dir", default=_ae_default, metavar="DIR",
                        help="AEBN URL file directory (*.txt); shows URL file coverage stats ($AESTARS_DIR).")
    args = parser.parse_args(argv)

    archive_dir = Path(args.archive).expanduser().resolve()
    if not archive_dir.exists():
        print(f"Archive directory not found: {archive_dir}", file=sys.stderr)
        return 1

    entries = load_archive_urls(archive_dir)
    if not entries:
        print(f"No archive entries found in {archive_dir}", file=sys.stderr)
        return 1

    # Status priority: keep the best status seen per URL across all archive lines.
    # A URL retried many times has many lines; we show it once at its best status.
    _STATUS_RANK: Dict[str, int] = {
        "downloaded": 6, "preexisting": 5, "already": 4, "partial": 3,
        "stalled": 2, "bad-url": 1, "bad": 1, "error": 1, "failed": 1,
    }
    best_by_url: Dict[str, ArchiveUrl] = {}
    for entry in entries:
        prev = best_by_url.get(entry.url)
        if prev is None or _STATUS_RANK.get(entry.archive_status, 0) > _STATUS_RANK.get(prev.archive_status, 0):
            best_by_url[entry.url] = entry

    raw_line_total = len(entries)
    deduped_entries = list(best_by_url.values())

    aebn_counts: Counter[str] = Counter()
    ytdlp_counts: Counter[str] = Counter()
    for entry in deduped_entries:
        if entry.archive_file.stem.startswith("ae-"):
            aebn_counts[entry.archive_status] += 1
        else:
            ytdlp_counts[entry.archive_status] += 1

    all_statuses = sorted(set(list(aebn_counts.keys()) + list(ytdlp_counts.keys())))
    aebn_total = sum(aebn_counts.values())
    ytdlp_total = sum(ytdlp_counts.values())
    total_entries = aebn_total + ytdlp_total
    duplicate_lines = raw_line_total - total_entries

    print(f"\n=== ytaedl Archive Status ===")
    print(f"Archive: {archive_dir}")
    if duplicate_lines > 0:
        print(f"Archive lines: {raw_line_total:,}  ({duplicate_lines:,} duplicate retry lines collapsed — counts below are unique URLs)")
    print()

    col_w = max((len(s) for s in all_statuses), default=10) + 2
    col_w = max(col_w, 14)
    hdr = f"{'Status':<{col_w}} {'AEBN':>10}  {'yt-dlp':>10}  {'Total':>10}  {'%':>6}"
    sep = "-" * len(hdr)
    print(hdr)
    print(sep)
    for status in all_statuses:
        ae = aebn_counts.get(status, 0)
        yt = ytdlp_counts.get(status, 0)
        tot = ae + yt
        pct = 100.0 * tot / total_entries if total_entries > 0 else 0.0
        print(f"{status:<{col_w}} {ae:>10,}  {yt:>10,}  {tot:>10,}  {pct:>5.1f}%")
    print(sep)
    print(f"{'TOTAL':<{col_w}} {aebn_total:>10,}  {ytdlp_total:>10,}  {total_entries:>10,}  100.0%")

    already_yt = ytdlp_counts.get("already", 0)
    if already_yt > 0:
        print()
        print(f"Note: {already_yt:,} yt-dlp 'already' entries were archive-skipped by yt-dlp (URL was in")
        print(f"      its download archive). This does NOT guarantee the file is on disk.")
        print(f"      Run 'archive validate' without --fast to verify actual file presence.")

    # Load domain index for queue/in-progress/finished breakdown
    index_path = archive_dir / "domain_index.json"
    if index_path.exists():
        try:
            index = DomainIndex.load(index_path)
            di_queued = index.total_queued
            di_inprog = len(index._in_progress)
            di_finished = index.total_finished
            # total = queued + in-progress + finished; total_urls only counts
            # queued entries after a load(), so we derive the true total ourselves.
            di_total = di_queued + di_inprog + di_finished
            di_domain_queues: Dict[str, int] = {
                d: index.domain_queue_size(d)
                for d in index.all_domains()
                if index.domain_queue_size(d) > 0
            }
            di_finished_by_status: Counter[str] = Counter()
            for us in index._finished.values():
                di_finished_by_status[us.status] += 1

            # AEBN vs yt-dlp across queued + in-progress + finished
            all_known_urls = (
                set(index._url_entry_map)
                | set(index._in_progress)
                | set(index._finished)
            )
            di_aebn_total = sum(1 for url in all_known_urls if _is_aebn(url))
            di_ytdlp_total = di_total - di_aebn_total

            pct_done = 100.0 * di_finished / di_total if di_total > 0 else 0.0
            pct_queued = 100.0 * di_queued / di_total if di_total > 0 else 0.0

            print()
            print("--- Domain index (URLs in current URL files) ---")
            print(f"Total URLs:           {di_total:>8,}  (AEBN: {di_aebn_total:,}  yt-dlp: {di_ytdlp_total:,})")
            print(f"Done:                 {di_finished:>8,}  ({pct_done:.1f}%)")
            for status, cnt in sorted(di_finished_by_status.items(), key=lambda x: -x[1]):
                pct = 100.0 * cnt / di_finished if di_finished > 0 else 0.0
                lbl = "file-on-disk" if status == "downloaded" else ("archive-skip (verify!)" if status == "already" else status)
                print(f"  {lbl:<26} {cnt:>8,}  ({pct:.1f}%)")
            print(f"Remaining to download:{di_queued:>8,}  ({pct_queued:.1f}%)  ← URLs pending in queue")
            if di_domain_queues:
                top = sorted(di_domain_queues.items(), key=lambda x: -x[1])[:8]
                for domain, cnt in top:
                    print(f"  {domain:<38} {cnt:>8,}")
            if di_inprog:
                print(f"Interrupted:          {di_inprog:>8,}  (in-progress from last session)")
        except Exception as exc:
            print(f"\nWarning: could not load domain_index.json: {exc}", file=sys.stderr)
    else:
        print(f"\nDomain index not found at: {index_path}")

    # URL file coverage — only when -s/--stars-dir or -d/--aebn-dir is given
    url_scan_dirs: List[Tuple[Path, str]] = []  # (dir, label)
    if args.stars_dir:
        url_scan_dirs.append((Path(args.stars_dir).expanduser().resolve(), "yt-dlp"))
    if args.aebn_dir:
        url_scan_dirs.append((Path(args.aebn_dir).expanduser().resolve(), "AEBN"))

    if url_scan_dirs:
        url_file_urls: Dict[Path, List[str]] = {}
        for url_dir, _label in url_scan_dirs:
            if not url_dir.exists():
                print(f"Warning: URL dir not found: {url_dir}", file=sys.stderr)
                continue
            for txt in sorted(url_dir.glob("*.txt")):
                lines = txt.read_text(encoding="utf-8", errors="replace").splitlines()
                urls = [
                    ln.strip() for ln in lines
                    if ln.strip() and not ln.strip().startswith("#")
                    and ln.strip().startswith(("http://", "https://"))
                ]
                if urls:
                    url_file_urls[txt] = urls

        archive_url_set = {e.url for e in deduped_entries}
        total_file_urls = sum(len(v) for v in url_file_urls.values())
        in_archive = sum(1 for urls in url_file_urls.values() for u in urls if u in archive_url_set)
        never_attempted = total_file_urls - in_archive
        historical_only = len(archive_url_set) - in_archive

        aebn_file_total = sum(len(v) for p, v in url_file_urls.items() if _is_aebn(next(iter(v), "")))
        ytdlp_file_total = total_file_urls - aebn_file_total

        print()
        print("--- URL file coverage ---")
        for url_dir, label in url_scan_dirs:
            print(f"  {label}: {url_dir}")
        print(f"Total URLs in files:  {total_file_urls:>8,}  (AEBN: {aebn_file_total:,}  yt-dlp: {ytdlp_file_total:,})")
        print(f"  In archive:         {in_archive:>8,}  ({100*in_archive/max(total_file_urls,1):.1f}%)  — attempted at least once")
        print(f"  Never attempted:    {never_attempted:>8,}  ({100*never_attempted/max(total_file_urls,1):.1f}%)  — not yet in archive")
        if historical_only > 0:
            print(f"  Historical only:    {historical_only:>8,}  — in archive but not in any current URL file")

        # Per-file breakdown: only files with unprocessed URLs
        pending_files = []
        for txt, urls in sorted(url_file_urls.items(), key=lambda x: x[0].name):
            file_in_archive = sum(1 for u in urls if u in archive_url_set)
            file_pending = len(urls) - file_in_archive
            if file_pending > 0:
                pending_files.append((txt, len(urls), file_in_archive, file_pending))
        if pending_files:
            print()
            print(f"  Files with unarchived URLs ({len(pending_files)} of {len(url_file_urls)}):")
            print(f"  {'File':<40} {'Total':>7}  {'Archived':>8}  {'Remaining':>9}")
            print(f"  {'-'*40} {'-'*7}  {'-'*8}  {'-'*9}")
            for txt, total_f, archived_f, pending_f in pending_files[:30]:
                print(f"  {txt.name:<40} {total_f:>7,}  {archived_f:>8,}  {pending_f:>9,}")
            if len(pending_files) > 30:
                print(f"  ... and {len(pending_files)-30} more files")

    return 0


if __name__ == "__main__":
    raise SystemExit(cli_main())
