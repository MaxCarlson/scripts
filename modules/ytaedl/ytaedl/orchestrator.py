#!/usr/bin/env python3
"""
ytaedl.orchestrator — file-first coordinator that:
  1) Scans two URL roots (main + ae) and estimates remaining viable downloads per URL file.
  2) Picks the top N URL files (by remaining) and assigns each to a dedicated worker slot.
  3) Each worker downloads up to --max-dl successful items from its current file, then picks the next best file.
  4) Live TermDash UI shows one slot per worker (two lines each) via the existing TermdashUI.
  5) Persists and incrementally updates a counts JSON (default: ./urlfile_dl_counts.txt).

This module builds on the existing ytaedl package (downloaders, url_parser, ui, io, models).
It can be used as a standalone CLI (`python -m ytaedl.orchestrator`) or imported.

Design notes:
- We deliberately use the existing downloader implementations and emit their events into TermdashUI.
- We treat a URL as "counts toward --max-dl" ONLY if its DownloadResult is COMPLETED.
  ALREADY_EXISTS and FAILED do not count toward the worker's per-file quota.
- We guarantee *exclusive* assignment of a URL file to only one worker at any time.
- The counts file stores per-URL-file stats and is updated atomically after every successful download.
- If the counts file covers all discovered URL files and their mtimes match (no source changes),
  we skip a re-scan and use the stored snapshot to prioritize work.

Limitations:
- Viability estimates for yt-dlp depend on --simulate --get-filename; if yt-dlp is missing,
  we fall back to a coarse estimate (remaining = total_urls - completed_files_found).
- For AEBN, viability is approximated via slug-based existence checks; "bad" counts are refined at runtime.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import queue
import signal
import sys
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

from .downloaders import get_downloader, terminate_all_active_procs, request_abort, abort_requested
from .io import expand_url_dirs, read_urls_from_files
from .models import DownloaderConfig, DownloadItem, DownloadResult, DownloadStatus, URLSource
from .ui import SimpleUI, TermdashUI
from .url_parser import is_aebn_url, get_url_slug

# ---------- defaults ----------
DEF_URL_DIR = Path("./files/downloads/stars")
DEF_AE_URL_DIR = Path("./files/downloads/ae-stars")
DEF_OUT_DIR = Path("./stars")
DEF_COUNTS_FILE = Path("./urlfile_dl_counts.txt")  # JSON content by default
DEF_EXTS = {"mp4", "mkv", "webm", "mov", "avi", "m4v", "flv", "wmv", "ts"}

# ---------- helpers ----------
def _now_ts() -> str:
    import datetime as dt
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return path.read_text(errors="ignore")

def _atomic_write_json(path: Path, obj: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)

def _ytdlp_expected_filename(url: str, template: str = "%(title)s.%(ext)s") -> Tuple[int, str]:
    """
    Return (rc, output_or_error). rc==0 => output is the first expected filename.
    """
    import subprocess
    cmd = ["yt-dlp", "--simulate", "--get-filename", "-o", template, url]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        out = (p.stdout or "").strip()
        err = (p.stderr or "").strip()
        if p.returncode == 0 and out:
            return 0, out.splitlines()[0].strip()
        return p.returncode or 1, (err or out or "yt-dlp failed without output")
    except FileNotFoundError:
        return 127, "yt-dlp not found"
    except Exception as ex:
        return 1, f"exception: {ex}"

def _exists_with_dup(dest: Path, expected_filename: str) -> bool:
    """
    Check for exact path or Windows-style duplicate suffix ' (n)' before extension.
    """
    p = dest / expected_filename
    if p.exists():
        return True
    if not dest.exists():
        return False
    stem = Path(expected_filename).stem
    ext = Path(expected_filename).suffix
    # manual check to avoid glob escaping headaches
    for f in dest.iterdir():
        if not f.is_file() or f.suffix.lower() != ext.lower():
            continue
        name = f.name
        if name == expected_filename:
            return True
        if name.startswith(stem + " (") and name.endswith(")" + ext):
            return True
    return False

def _aebn_file_exists_like(dest: Path, slug: str, exts: Iterable[str]) -> bool:
    if not dest.exists():
        return False
    for e in exts:
        if (dest / f"{slug}.{e}").exists():
            return True
        # loose match: anything that contains the slug segment
        for f in dest.glob(f"*{slug}*.{e}"):
            if f.is_file():
                return True
    return False

# ---------- scanning ----------
@dataclass
class URLFileInfo:
    url_file: Path
    stem: str
    source: str            # 'main' or 'ae'
    out_dir: Path
    url_count: int
    downloaded: int
    bad: int               # only known after viability checks (0 if unknown)
    remaining: int         # url_count - downloaded - bad
    viable_checked: bool   # True if we did per-URL viability probe

@dataclass
class CountsSnapshot:
    version: int = 1
    computed_at: str = field(default_factory=_now_ts)
    sources: Dict[str, Dict[str, str]] = field(default_factory=dict)
    files: Dict[str, dict] = field(default_factory=dict)  # key = str(url_file.resolve())

    def to_json(self) -> dict:
        return dataclasses.asdict(self)

    @staticmethod
    def from_json(obj: dict) -> "CountsSnapshot":
        cs = CountsSnapshot()
        cs.version = int(obj.get("version", 1))
        cs.computed_at = obj.get("computed_at", _now_ts())
        cs.sources = obj.get("sources", {})
        cs.files = obj.get("files", {})
        return cs

def _scan_one_file_main(url_file: Path, out_base: Path, exts: Iterable[str]) -> URLFileInfo:
    urls = read_urls_from_files([url_file])
    dest = out_base / url_file.stem
    downloaded = 0
    bad = 0
    # Try viability probe via yt-dlp get-filename
    for u in urls:
        rc, got = _ytdlp_expected_filename(u)
        if rc == 0:
            if _exists_with_dup(dest, got):
                downloaded += 1
        else:
            bad += 1
    remaining = max(0, len(urls) - downloaded - bad)
    return URLFileInfo(url_file, url_file.stem, "main", dest, len(urls), downloaded, bad, remaining, True)

def _scan_one_file_ae(url_file: Path, out_base: Path, exts: Iterable[str]) -> URLFileInfo:
    urls = read_urls_from_files([url_file])
    dest = out_base / url_file.stem
    downloaded = 0
    for u in urls:
        slug = get_url_slug(u)
        if _aebn_file_exists_like(dest, slug, exts):
            downloaded += 1
    # We don't probe viability for AE (cheap heuristic)
    bad = 0
    remaining = max(0, len(urls) - downloaded)
    return URLFileInfo(url_file, url_file.stem, "ae", dest, len(urls), downloaded, bad, remaining, False)

def scan_all(main_url_dir: Path, ae_url_dir: Path, out_base: Path, exts: Iterable[str]) -> CountsSnapshot:
    """
    Scan both roots and return a fresh CountsSnapshot.
    """
    exts = {e.lower().lstrip(".") for e in exts}
    snap = CountsSnapshot()
    snap.sources = {
        "main": {"url_dir": str(main_url_dir.resolve()), "out_dir": str(out_base.resolve())},
        "ae": {"url_dir": str(ae_url_dir.resolve()), "out_dir": str(out_base.resolve())},  # AE merges into same out
    }

    # Gather url files (non-recursive)
    def _iter_txt(d: Path) -> List[Path]:
        return [p for p in sorted(Path(d).glob("*.txt")) if p.is_file()]

    files: List[URLFileInfo] = []
    for f in _iter_txt(main_url_dir):
        files.append(_scan_one_file_main(f, out_base, exts))
    for f in _iter_txt(ae_url_dir):
        files.append(_scan_one_file_ae(f, out_base, exts))

    # Build snap
    for info in files:
        snap.files[str(info.url_file.resolve())] = {
            "stem": info.stem,
            "source": info.source,
            "out_dir": str(info.out_dir.resolve()),
            "url_count": info.url_count,
            "downloaded": info.downloaded,
            "bad": info.bad,
            "remaining": info.remaining,
            "viable_checked": info.viable_checked,
            "url_mtime": int(info.url_file.stat().st_mtime),
            "url_size": int(info.url_file.stat().st_size),
        }
    return snap

def _is_snapshot_complete(snap: CountsSnapshot, main_url_dir: Path, ae_url_dir: Path) -> bool:
    """
    A snapshot is considered "complete" if it lists every current *.txt under both roots,
    and each entry has matching mtime/size. This is a pragmatic staleness check.
    """
    def _iter_txt(d: Path) -> List[Path]:
        return [p for p in sorted(Path(d).glob("*.txt")) if p.is_file()]
    all_files = [*_iter_txt(main_url_dir), *_iter_txt(ae_url_dir)]
    for f in all_files:
        k = str(f.resolve())
        rec = snap.files.get(k)
        if not rec:
            return False
        try:
            if int(rec.get("url_mtime", -1)) != int(f.stat().st_mtime):
                return False
            if int(rec.get("url_size", -1)) != int(f.stat().st_size):
                return False
        except Exception:
            return False
    return True

# ---------- selection ----------
@dataclass
class _WorkFile:
    url_file: Path
    stem: str
    source: str
    out_dir: Path
    urls: List[str]
    remaining: int

def _build_worklist(snap: CountsSnapshot, exts: Iterable[str]) -> List[_WorkFile]:
    work: List[_WorkFile] = []
    for k, rec in snap.files.items():
        url_file = Path(k)
        urls = read_urls_from_files([url_file])
        work.append(
            _WorkFile(
                url_file=url_file,
                stem=str(rec.get("stem") or url_file.stem),
                source=str(rec.get("source") or "main"),
                out_dir=Path(rec.get("out_dir") or DEF_OUT_DIR / url_file.stem),
                urls=urls,
                remaining=int(rec.get("remaining") or max(0, len(urls) - int(rec.get("downloaded", 0)))),
            )
        )
    return work

# ---------- workers ----------
@dataclass
class _WorkerState:
    slot: int
    completed_this_file: int = 0
    assigned: Optional[_WorkFile] = None
    next_local_id: int = 1

class _Coordinator:
    """
    Thread-safe coordinator for assigning URL files to workers by highest remaining first.
    """
    def __init__(self, work: List[_WorkFile]):
        self._lock = threading.Lock()
        self._assigned: set[str] = set()
        # start with highest remaining
        self._work = sorted(work, key=lambda w: (w.remaining, w.stem), reverse=True)

    def acquire_next(self) -> Optional[_WorkFile]:
        with self._lock:
            for wf in self._work:
                key = str(wf.url_file.resolve())
                if key in self._assigned:
                    continue
                if wf.remaining <= 0:
                    continue
                self._assigned.add(key)
                return wf
            return None

    def release(self, wf: _WorkFile, remaining_delta: int) -> None:
        """
        Put the file back (updated remaining) so someone else may take it later.
        remaining_delta: negative if we downloaded some.
        """
        with self._lock:
            wf.remaining = max(0, wf.remaining + remaining_delta)
            key = str(wf.url_file.resolve())
            self._assigned.discard(key)
            # stable sort by new remaining
            self._work.sort(key=lambda w: (w.remaining, w.stem), reverse=True)

# ---------- main orchestrator ----------
def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="yt-ae-orchestrate",
        description="File-first orchestrator for yt-dlp/aebndl across two URL roots.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("-t", "--threads", type=int, default=2, help="Worker slots (one URL file per worker at a time).")
    p.add_argument("-m", "--max-dl", type=int, default=3, help="Max SUCCESSFUL downloads per file per assignment.")
    p.add_argument("--url-dir", type=Path, default=DEF_URL_DIR, help="Main url dir (stars).")
    p.add_argument("--ae-url-dir", type=Path, default=DEF_AE_URL_DIR, help="AE url dir (ae-stars).")
    p.add_argument("-o", "--output-dir", type=Path, default=DEF_OUT_DIR, help="Base output dir (stars/<stem>).")
    p.add_argument("-c", "--counts-file", type=Path, default=DEF_COUNTS_FILE, help="JSON counts file path.")
    p.add_argument("-e", "--exts", default=",".join(sorted(DEF_EXTS)), help="Extensions considered 'downloaded'.")
    p.add_argument("--no-ui", action="store_true", help="Disable TermDash UI (use simple console prints).")
    p.add_argument("--ytdlp-template", default="%(title)s.%(ext)s", help="Template used for yt-dlp expected names.")
    # pass-through downloader config (subset)
    p.add_argument("-j", "--jobs", type=int, default=1, help="(per-process) internal jobs for yt-dlp/aebndl, if used.")
    p.add_argument("-w", "--work-dir", type=Path, default=Path("./tmp_dl"), help="Working directory for caches.")
    p.add_argument("-tO", "--timeout", type=int, default=3600, help="Per-download timeout (seconds).")
    p.add_argument("-L", "--log-file", type=Path, help="Append a text log of events to this file.")
    p.add_argument("-A", "--aebn-arg", action="append", help="Append raw arg to aebndl (repeatable).")
    p.add_argument("-Y", "--ytdlp-arg", action="append", help="Append raw arg to yt-dlp (repeatable).")
    return p.parse_args(argv)

def _load_counts(path: Path) -> Optional[CountsSnapshot]:
    try:
        if path.exists():
            obj = json.loads(_read_text(path))
            return CountsSnapshot.from_json(obj)
    except Exception:
        return None
    return None

def _save_counts(path: Path, snap: CountsSnapshot) -> None:
    try:
        _atomic_write_json(path, snap.to_json())
    except Exception:
        pass

def _save_counts_update(path: Path, k: str, field: str, delta: int) -> None:
    """
    Convenience: update one field by delta and write. Tolerates races by re-reading on each call.
    """
    try:
        snap = _load_counts(path)
        if not snap:
            return
        rec = snap.files.get(k)
        if not rec:
            return
        rec[field] = int(rec.get(field, 0)) + int(delta)
        if field == "remaining":
            if rec["remaining"] < 0:
                rec["remaining"] = 0
        _atomic_write_json(path, snap.to_json())
    except Exception:
        pass

def _build_config(args: argparse.Namespace) -> DownloaderConfig:
    return DownloaderConfig(
        output_dir=args.output_dir,
        jobs=max(1, args.jobs),
        work_dir=args.work_dir,
        timeout_seconds=args.timeout,
        keep_covers=False,
        log_file=args.log_file,
        extra_aebn_args=args.aebn_arg or [],
        extra_ytdlp_args=args.ytdlp_arg or [],
    )

def _precheck_exists(url: str, dest_dir: Path, exts: Iterable[str], ytdlp_template: str) -> bool:
    try:
        if is_aebn_url(url):
            slug = get_url_slug(url)
            return _aebn_file_exists_like(dest_dir, slug, exts)
        rc, got = _ytdlp_expected_filename(url, ytdlp_template)
        if rc == 0:
            return _exists_with_dup(dest_dir, got)
        # If we can't probe, fall back to "assume not present" so runner will decide (and may ALREADY).
        return False
    except Exception:
        return False

def _worker_thread(
    slot: int,
    coordinator: _Coordinator,
    cfg: DownloaderConfig,
    ui,
    counts_file: Path,
    exts: set[str],
    ytdlp_template: str,
    stop_evt: threading.Event,
) -> None:
    """
    Each worker repeatedly acquires the next-best URL file and downloads up to max_dl successes,
    updating the counts JSON after each COMPLETED item.
    """
    args_max_dl = getattr(cfg, "_orchestrator_max_dl", 3)
    while not stop_evt.is_set():
        wf = coordinator.acquire_next()
        if not wf:
            break  # nothing left
        completed_for_this_assignment = 0
        # sequentially iterate over URLs of this file
        for idx, url in enumerate(wf.urls, start=1):
            if stop_evt.is_set():
                break
            dest_dir = wf.out_dir
            # quick skip if already present
            try:
                if _precheck_exists(url, dest_dir, exts, ytdlp_template):
                    continue
            except Exception:
                pass

            # Build item id so that slot is stable in UI
            local_id = slot * 1_000_000 + idx
            item = DownloadItem(
                id=local_id,
                url=url,
                output_dir=dest_dir,
                source=URLSource(file=wf.url_file, line_number=idx, original_url=url),
                retries=3,
            )
            dl = get_downloader(url, cfg)
            # stream events to UI and decide on counting
            try:
                for ev in dl.download(item):
                    if stop_evt.is_set() or abort_requested():
                        raise KeyboardInterrupt
                    ui.handle_event(ev)
            except KeyboardInterrupt:
                break
            except Exception:
                # treat as failure
                pass

            # Post-check: if file now exists, count as COMPLETED
            if _precheck_exists(url, dest_dir, exts, ytdlp_template):
                completed_for_this_assignment += 1
                k = str(wf.url_file.resolve())
                _save_counts_update(counts_file, k, "downloaded", +1)
                _save_counts_update(counts_file, k, "remaining", -1)

            if completed_for_this_assignment >= args_max_dl:
                break

        # Release file back (with new remaining); coordinator will re-sort.
        coordinator.release(wf, remaining_delta=-(completed_for_this_assignment))

def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    exts = {e.strip().lower().lstrip(".") for e in args.exts.split(",") if e.strip()}
    if not exts:
        exts = set(DEF_EXTS)

    counts = _load_counts(args.counts_file)
    if counts and _is_snapshot_complete(counts, args.url_dir, args.ae_url_dir):
        snap = counts
    else:
        snap = scan_all(args.url_dir, args.ae_url_dir, args.output_dir, exts)
        _save_counts(args.counts_file, snap)

    work = _build_worklist(snap, exts)
    if not work:
        print("No URL files found under the specified roots.", file=sys.stderr)
        return 0

    # UI
    use_ui = not args.no_ui
    if use_ui:
        try:
            ui = TermdashUI(num_workers=max(1, args.threads), total_urls=sum(w.remaining for w in work))
        except Exception:
            ui = SimpleUI()
            use_ui = False
    else:
        ui = SimpleUI()

    # Build downloader config
    cfg = _build_config(args)
    # Carry max-dl via a private attribute (keeps config dataclass surface intact).
    setattr(cfg, "_orchestrator_max_dl", int(args.max_dl))

    # Coordinator + workers
    coord = _Coordinator(work)
    stop_evt = threading.Event()

    # SIGINT handling: graceful abort request; ensure child processes are torn down.
    def _handle_sigint(signum, frame):
        stop_evt.set()
        request_abort()
        terminate_all_active_procs()
    try:
        signal.signal(signal.SIGINT, _handle_sigint)
    except Exception:
        pass

    start = time.monotonic()
    threads: List[threading.Thread] = []
    for slot in range(max(1, int(args.threads))):
        t = threading.Thread(
            target=_worker_thread,
            args=(slot, coord, cfg, ui, args.counts_file, exts, args.ytdlp_template, stop_evt),
            daemon=True,
        )
        threads.append(t)
        t.start()

    try:
        if use_ui and hasattr(ui, "dash"):
            with ui.dash:
                while any(t.is_alive() for t in threads):
                    time.sleep(0.1)
        else:
            while any(t.is_alive() for t in threads):
                time.sleep(0.1)
    finally:
        stop_evt.set()
        terminate_all_active_procs()
        for t in threads:
            t.join(timeout=1.0)

    elapsed = time.monotonic() - start
    ui.summary({}, elapsed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
