#!/usr/bin/env python3
"""Validate ytaedl archive and domain-index state against current URL reality."""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as _dt
import json
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
from .domain_index import DomainIndex
from .downloader import (
    ARCHIVE_PROCESSED_STATUSES,
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
        entries.append(
            ArchiveUrl(
                url=url,
                archive_status=status,
                archive_file=path,
                archive_line=line_num,
                archive_text=line,
                source_group=source_group,
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
        if verify_aebn_metadata:
            return _verify_aebn_metadata_existing(entry, download_roots, validation_log_dir)
        return UrlReality(
            status=UNKNOWN_STATUS,
            downloader="aebndl",
            reason="AEBN URL requires metadata/download-tool verification; no URL-specific local evidence found",
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
    return UrlReality(
        status=BAD_STATUS,
        downloader="yt-dlp",
        reason="yt-dlp simulate failed or timed out",
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
        f"ytaedl archive validate | processed {_metric(processed, 'yellow')}/{total} | "
        f"matched {_metric(matched, 'green')} | mismatches {_metric(mismatch_count, 'red')} | "
        f"unknown {_metric(unknown_count, 'magenta')} | partial {_metric(partial_count, 'cyan')} | "
        f"rate {rate:.1f}/s | ETA {eta} | stop={stopped_by}"
    )
    sys.stdout.write(_color(header, "bright") + "\n")
    sys.stdout.write(f"worker counts: {_metric_legend()}\n")
    status_line = "statuses: " + "  ".join(
        f"{_color(status, _status_color(status))}={count}" for status, count in sorted(status_counts.items())
    )
    evidence_line = "evidence: " + "  ".join(f"{kind}={count}" for kind, count in sorted(evidence_counts.items()))
    sys.stdout.write(status_line[:160] + "\n")
    sys.stdout.write(evidence_line[:160] + "\n")
    sys.stdout.write(_color("Keys: Up/Down select worker, v show selected worker log, q stop after current work", "gray") + "\n\n")
    for slot in sorted(workers):
        view = workers[slot]
        marker = _color(">", "yellow") if slot == selected_slot else " "
        tag = _color(view.current_tag, _tag_color(view.current_tag))
        worker_elapsed = max(0.001, time.time() - view.started_at)
        worker_rate = view.processed / worker_elapsed
        counts = _metric_group(view.processed, view.matched, view.mismatches, view.unknown, view.partial)
        divider = _color("-" * 112, "gray")
        sys.stdout.write(divider + "\n")
        sys.stdout.write(
            f"{marker} worker-{slot:02d} {tag} phase={_color(view.phase, 'cyan')} "
            f"counts={counts}  rate={worker_rate:.1f}/s\n"
        )
        source = f"{view.current_file}:{view.current_line}" if view.current_line else view.current_file
        last_status = _color(view.last_status, _status_color(view.last_status))
        if view.phase == "idle" and view.current == "-":
            sys.stdout.write(f"  source={_color('-', 'gray')}  state={_color('waiting for eligible URL file', 'gray')}\n")
            sys.stdout.write(f"  last={last_status} elapsed={view.last_elapsed_s:.2f}s {view.last_result[:110]}\n")
        else:
            sys.stdout.write(
                f"  source={_color(source, 'bright')}  "
                f"last={last_status} elapsed={view.last_elapsed_s:.2f}s\n"
            )
            sys.stdout.write(f"  current={view.current[:130]}\n")
            sys.stdout.write(f"  result={view.last_result[:130]}\n")
    sys.stdout.write(_color("-" * 112, "gray") + "\n")
    if show_log and selected_slot in workers:
        sys.stdout.write(_color(f"\nworker-{selected_slot:02d} log\n", "bright"))
        sys.stdout.write(_color("-" * 112, "gray") + "\n")
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
) -> ValidationSummary:
    all_entries = _ordered_entries(load_archive_urls(archive_dir), order)
    total = len(all_entries)
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

    log_dir.mkdir(parents=True, exist_ok=True)
    validation_log_dir.mkdir(parents=True, exist_ok=True)
    master_log_path = validation_log_dir / "archive-validate-master.log"
    _append_log(
        master_log_path,
        (
            f"{_utc_now()} START archive_dir={archive_dir} log_dir={log_dir} "
            f"validation_log_dir={validation_log_dir} workers={workers} order={order} total={target}"
        ),
    )

    def _run_one(slot: int, entry: ArchiveUrl) -> Tuple[ArchiveUrl, UrlReality]:
        view = worker_views[slot]
        t_url = time.time()
        with lock:
            tag = _tool_tag(entry.url)
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
        )
        elapsed = time.time() - t_url
        with lock:
            result = f"{entry.archive_status} -> {reality.status} ({reality.downloader}) {reality.reason}"
            view.processed += 1
            view.last_result = result
            view.last_status = reality.status
            view.last_elapsed_s = elapsed
            if reality.status == UNKNOWN_STATUS:
                view.unknown += 1
            elif reality.status == PARTIAL_STATUS:
                view.partial += 1
            elif _status_matches(entry.archive_status, reality.status):
                view.matched += 1
            if reality.status != UNKNOWN_STATUS and not _status_matches(entry.archive_status, reality.status):
                view.mismatches += 1
            view.phase = "idle"
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
        return entry, reality

    pending = deque(all_entries)
    active: Dict[concurrent.futures.Future[Tuple[ArchiveUrl, UrlReality]], Tuple[int, Path]] = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        while pending or active:
            if max_seconds is not None and max_seconds > 0 and time.time() - start >= max_seconds:
                stopped_by = "timer"
                stop.set()
            while pending and not stop.is_set() and len(active) < max(1, workers):
                active_slots = {slot for slot, _file_path in active.values()}
                slot = next(slot for slot in worker_views if slot not in active_slots)
                active_files = {file_path for _slot, file_path in active.values()}
                entry = _pop_next_entry_exclusive_by_file(pending, active_files)
                if entry is None:
                    break
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

    _append_log(
        master_log_path,
        (
            f"{_utc_now()} FINISH processed={processed} matched={matched} mismatches={len(mismatches)} "
            f"unknown={unknown_count} partial={partial_count} stopped_by={stopped_by} "
            f"elapsed={time.time() - start:.3f}s"
        ),
    )
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
            domain_action = "remove_finished"
        elif item.actual_status == PARTIAL_STATUS:
            action = "remove_archive_entry"
            domain_action = "remove_finished"
        elif item.actual_status == PRESENT_STATUS:
            action = "set_archive_status"
            domain_action = "set_finished"
        else:
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
                continue
            if url in set_by_url:
                change = set_by_url[url]
                parts[0] = change["new_status"]
                line = "\t".join(parts)
                archive_updates += 1
            new_lines.append(line)
        if not dry_run:
            path.write_text("\n".join(new_lines) + ("\n" if new_lines else ""), encoding="utf-8")

    index_path = base_log / "domain_index.json"
    domain_updates = 0
    if index_path.exists():
        index = DomainIndex.load(index_path)
        for change in changes:
            url = change["url"]
            action = change.get("domain_index_action")
            if action == "set_finished":
                status = PRESENT_STATUS if change.get("new_status") == PRESENT_STATUS else change.get("new_status", PRESENT_STATUS)
                index.mark_finished(url, status)
                domain_updates += 1
            elif action == "remove_finished":
                data = index._to_dict()
                if url in data.get("finished", {}):
                    data["finished"].pop(url, None)
                    if not dry_run:
                        index_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                    domain_updates += 1
        if domain_updates and not dry_run and any(c.get("domain_index_action") == "set_finished" for c in changes):
            index.save(index_path)

    print("Archive apply summary")
    print("---------------------")
    print(f"Plan: {plan_path}")
    print(f"Archive directory: {base_archive}")
    print(f"Log directory: {base_log}")
    print(f"Archive updates: {archive_updates}")
    print(f"Domain index updates: {domain_updates}")
    print(f"Dry run: {dry_run}")
    return 0


def _print_summary(summary: ValidationSummary) -> None:
    print("\nArchive validation summary")
    print("--------------------------")
    print(f"Total archive URLs: {summary.total_archive_urls}")
    print(f"Processed: {summary.processed}")
    print(f"Matched: {summary.matched}")
    print(f"Mismatches: {len(summary.mismatches)}")
    print(f"Unknown/unconfirmed URLs: {summary.unknown_count}")
    print(f"Partial URLs: {summary.partial_count}")
    print(f"Stopped by: {summary.stopped_by}")
    print(f"Elapsed: {summary.elapsed_s:.1f}s")
    if summary.status_counts:
        print("\nActual status breakdown:")
        for status, count in sorted(summary.status_counts.items()):
            print(f"  {status}: {count}")
    if summary.evidence_counts:
        print("\nEvidence breakdown:")
        for source, count in sorted(summary.evidence_counts.items()):
            print(f"  {source}: {count}")
    counts = Counter(item.transition for item in summary.mismatches)
    if counts:
        print("\nMismatch breakdown:")
        for transition, count in sorted(counts.items()):
            print(f"  {transition}: {count}")
        files = sorted({item.archive_file for item in summary.mismatches})
        print("\nURL files with mismatches:")
        for path in files:
            print(f"  {path}")
        print("\nMismatched URLs:")
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
    parser.add_argument("-a", "--archive", default="./archive", help="Archive folder containing per-urlfile status files.")
    parser.add_argument("-g", "--log-dir", default="./logs", help="Log folder containing domain_index.json.")
    parser.add_argument("-G", "--validation-log-dir", default=None, help="Folder for archive validation master and per-worker logs.")
    parser.add_argument("-s", "--stars-dir", default="./files/downloads/stars", help="yt-dlp URL file directory.")
    parser.add_argument("-d", "--aebn-dir", default="./files/downloads/ae-stars", help="AEBN URL file directory.")
    parser.add_argument("-L", "--download-root", action="append", default=None, help="Download root to check for existing files. Repeatable.")
    parser.add_argument("-t", "--threads", dest="workers", type=int, default=2, help="Number of concurrent validation workers.")
    parser.add_argument("-w", "--workers", dest="workers", type=int, help=argparse.SUPPRESS)
    parser.add_argument("-O", "--order", choices=("oldest", "newest", "url-file", "random"), default="url-file", help="Archive URL processing order.")
    parser.add_argument("-T", "--timer-seconds", type=float, default=None, help="Stop after this many seconds and print a summary.")
    parser.add_argument("-c", "--count", type=int, default=None, help="Stop after this many archive URLs have completed validation.")
    parser.add_argument("-R", "--ratio", type=float, default=None, help="Stop after this ratio of archive URLs has completed validation.")
    parser.add_argument("-p", "--count-partials", action="store_true", help="Count and report URLs with matching _partial state.")
    parser.add_argument("-j", "--json-plan", default=None, help="Write a JSON change plan for archive/domain_index repair.")
    parser.add_argument("-n", "--no-ui", action="store_true", help="Disable the realtime in-place worker UI.")
    parser.add_argument("-S", "--simulate-timeout", type=int, default=15, help="yt-dlp simulate timeout per URL.")
    parser.add_argument("-M", "--aebn-metadata-check", action="store_true", help="Use aebndl metadata naming checks for AEBN URLs without downloading segments.")
    parser.add_argument("-b", "--ytdlp-cookies-from-browser", default="firefox", help="Browser cookie source for yt-dlp simulate; use 'none' to disable.")
    parser.add_argument("-i", "--ytdlp-impersonate", default="chrome", help="yt-dlp impersonation browser; use 'none' to disable.")
    return parser


def cli_main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    archive_dir = Path(args.archive).expanduser().resolve()
    log_dir = Path(args.log_dir).expanduser().resolve()
    validation_log_dir = (
        Path(args.validation_log_dir).expanduser().resolve()
        if args.validation_log_dir
        else (log_dir / "archive-validate").resolve()
    )
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
    )
    _print_summary(summary)
    if args.json_plan:
        plan = build_change_plan(summary, archive_dir=archive_dir, log_dir=log_dir)
        plan_path = Path(args.json_plan).expanduser().resolve()
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON change plan written: {plan_path}")
    return 1 if summary.mismatches else 0


def apply_main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ytaedl archive apply-plan",
        description=f"ytaedl {YTAEDL_VERSION} - apply a JSON archive validation change plan.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("-p", "--plan-file", required=True, help="JSON change plan produced by archive validate.")
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


if __name__ == "__main__":
    raise SystemExit(cli_main())
