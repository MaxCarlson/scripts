#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Orchestrator — scan URL files and then download, with a Termdash UI.

This build focuses the SCAN phase on yt-dlp correctness and clear per-worker UI:
- Each worker shows: Set <stem> • URLs i/total • ETA hh:mm:ss
- Top banner (Termdash) shows cumulative scanned/already/bad/URLs/s
- Destination for main URLs defaults to ./stars/<stem>  (matches your layout)
- AE is discovered but currently skipped (requested focus on yt-dlp/main)

All UI calls are guarded, so SimpleUI/older TermdashUI won't crash.
Author: you (+ ChatGPT)
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import queue
import random
import re
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

from .downloaders import get_downloader, request_abort, terminate_all_active_procs, DownloadStatus, DownloadResult
from .io import read_urls_from_files, load_archive, write_to_archive
from .models import (
    DownloaderConfig,
    DownloadItem,
    URLSource,
    StartEvent,
    FinishEvent,
    LogEvent,
)
from .ui import SimpleUI, TermdashUI
from .url_parser import get_url_slug

# ---------------------------------------------------------------------------

DEF_URL_DIR = Path("files/downloads/stars")
DEF_AE_URL_DIR = Path("files/downloads/ae-stars")
# NEW default: where finished videos live (your layout)
DEF_OUT_DIR = Path("stars")
DEF_COUNTS_FILE = Path("files/downloads/ytaedl-counts.json")
DEF_EXTS = {"mp4", "mkv", "webm", "mp3", "m4a", "wav"}

_YTDLP_NOT_FOUND = 127
_DUP_SUFFIX_RE = re.compile(r"\s+\(\d+\)$")
_item_id_counter = 0
_item_id_lock = threading.Lock()

# ---------------------------------------------------------------------------

def get_next_item_id():
    global _item_id_counter
    with _item_id_lock:
        _item_id_counter += 1
        return _item_id_counter

def _now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

def _fmt_hms(seconds: Optional[float]) -> str:
    if seconds is None:
        return "--:--:--"
    s = max(0, int(seconds))
    return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"

def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)

def _append_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")

# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class URLFileInfo:
    url_file: Path
    stem: str
    source: str  # "main" or "ae"
    out_dir: Path
    url_count: int
    downloaded: int
    bad: int
    remaining: int
    viable_checked: bool

@dataclass
class CountsSnapshot:
    version: int = 1
    computed_at: str = field(default_factory=_now_str)
    sources: Dict[str, Dict[str, str]] = field(default_factory=dict)
    files: Dict[str, dict] = field(default_factory=dict)

    def to_json(self) -> str:
        import json
        return json.dumps(
            {
                "version": self.version,
                "computed_at": self.computed_at,
                "sources": self.sources,
                "files": self.files,
            },
            indent=2,
            sort_keys=True,
        )

# ---------------------------------------------------------------------------
# PUBLIC helper for tests: is a snapshot complete for the given directories?
def _is_snapshot_complete(
    snap: Union[CountsSnapshot, Dict],
    main_url_dir: Path,
    ae_url_dir: Optional[Path] = None,
) -> bool:
    """
    Return True if 'snap.files' contains an entry for every *.txt file found
    under main_url_dir (and ae_url_dir, when provided).

    - Accepts either a CountsSnapshot instance or a dict with a 'files' key.
    - Paths are normalized via resolve() before comparison.
    - If no *.txt files exist in the provided dirs, returns True.
    """
    def _collect(dir_path: Optional[Path]) -> List[str]:
        if not dir_path:
            return []
        d = Path(dir_path)
        if not d.exists():
            return []
        return [str(p.resolve()) for p in d.glob("*.txt") if p.is_file()]

    expected = set(_collect(main_url_dir) + _collect(ae_url_dir))
    if not expected:
        return True

    files_map = getattr(snap, "files", None)
    if files_map is None and isinstance(snap, dict):
        files_map = snap.get("files", {})

    present = set()
    for k in (files_map or {}).keys():
        try:
            present.add(str(Path(k).resolve()))
        except Exception:
            # keep raw key if it can't be resolved on this platform
            present.add(str(k))

    return expected.issubset(present)

# ---------------------------------------------------------------------------
# yt-dlp helpers used during the scan phase (main source)

def _ytdlp_get_expected_filename(yt_dlp: str, url: str, template: str) -> Tuple[int, str]:
    """
    (rc, value).
    When rc==0, value is the expected output filename.
    """
    cmd = [yt_dlp, "--simulate", "--get-filename", "-o", template, url]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore"
        )
    except FileNotFoundError:
        return (_YTDLP_NOT_FOUND, "yt-dlp not found")
    except Exception as ex:
        return (1, f"yt-dlp error: {ex}")

    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode == 0 and out:
        return (0, out.splitlines()[0].strip())
    msg = err if err else (out if out else "yt-dlp failed")
    return (proc.returncode, msg)

def _exists_with_dup(dest_dir: Path, expected_filename: str) -> bool:
    """
    True if expected exists OR a duplicate variant exists: "<stem> (N)<ext>"
    """
    target = dest_dir / expected_filename
    if target.exists():
        return True
    if not dest_dir.exists():
        return False
    exp = Path(expected_filename)
    for f in dest_dir.glob(f"*{exp.suffix.lower()}"):
        if not f.is_file() or f.suffix.lower() != exp.suffix.lower():
            continue
        stem = f.stem
        base = exp.stem
        if stem == base:
            return True
        if stem.startswith(base) and _DUP_SUFFIX_RE.search(stem[len(base):] or ""):
            return True
    return False

# ---------------------------------------------------------------------------

def _infer_dest_dir(out_root: Path, url_file: Path) -> Path:
    """
    For '.../files/downloads/stars/<stem>.txt' -> './stars/<stem>'
    (Matches your layout. Users can still override --output-dir)
    """
    return (out_root / url_file.stem).resolve()

# ----- guarded UI adapters (so we don't care which UI you run) --------------

def _ui_set_worker_scan_progress(
    ui,
    slot: int,
    set_name: str,
    i: int,
    total: int,
    eta_s: Optional[float],
) -> None:
    """
    Try modern scan progress API on worker lines; fall back to older ones.
    """
    try:
        # Preferred single-call API if your TermdashUI provides it
        if hasattr(ui, "set_worker_scan_progress"):
            ui.set_worker_scan_progress(slot, set_name, i, total, _fmt_hms(eta_s))
            return
        # Older split API
        if hasattr(ui, "set_worker_set"):
            ui.set_worker_set(slot, set_name)
        if hasattr(ui, "set_worker_urls"):
            ui.set_worker_urls(slot, i, total)
        if hasattr(ui, "set_worker_eta"):
            ui.set_worker_eta(slot, _fmt_hms(eta_s))
        # As a last resort, stuff something compact into the scan slots list
        elif hasattr(ui, "set_scan_slot"):
            ui.set_scan_slot(slot, f"{set_name} {i}/{total} {_fmt_hms(eta_s)}")
    except Exception:
        # Never break the scan if UI chokes
        pass

def _ui_scan_banner_delta(ui, seen: int, already: int, bad: int) -> None:
    try:
        if hasattr(ui, "scan_progress_delta"):
            ui.scan_progress_delta(seen, already, bad)
    except Exception:
        pass

def _ui_scan_file_done(ui, file_path: Path, total: int, downloaded: int, bad: int) -> None:
    try:
        if hasattr(ui, "scan_file_done"):
            ui.scan_file_done(file_path, total=total, downloaded=downloaded, bad=bad)
    except Exception:
        pass

# ---------------------------------------------------------------------------

def _scan_one_file_main_with_ytdlp(
    url_file: Path,
    out_root: Path,
    *,
    yt_dlp: str,
    template: str,
    pause_evt: threading.Event,
    stop_evt: threading.Event,
    ui: object,
    slot: int,
    log_fn,
) -> URLFileInfo:
    """Slow & correct scan: query yt-dlp per URL and check presence."""
    urls = read_urls_from_files([url_file])
    total = len(urls)
    stem = url_file.stem
    dest = _infer_dest_dir(out_root, url_file)

    seen = 0
    already = 0
    bad = 0
    start = time.time()
    # Initial paint for the worker block
    _ui_set_worker_scan_progress(ui, slot, stem, 0, total, None)

    for url in urls:
        if stop_evt.is_set():
            break
        while pause_evt.is_set() and not stop_evt.is_set():
            ui.pump()
            time.sleep(0.05)

        rc, value = _ytdlp_get_expected_filename(yt_dlp, url, template)
        exists_flag: Optional[bool]
        if rc == 0:
            expected = value
            exists_flag = _exists_with_dup(dest, expected)
            if exists_flag:
                already += 1
        else:
            exists_flag = None
            bad += 1
            log_fn(
                f"SCAN main {url_file} yt-dlp rc={rc} msg={value}"
            )

        seen += 1

        # UI deltas for the global banner
        _ui_scan_banner_delta(ui, seen=1, already=(1 if exists_flag else 0), bad=(1 if exists_flag is None else 0))

        # Update worker lines with i/total + ETA
        elapsed = max(0.001, time.time() - start)
        rate = seen / elapsed
        eta = (max(0, total - seen) / rate) if rate > 0 else None
        _ui_set_worker_scan_progress(ui, slot, stem, seen, total, eta)
        ui.pump()

    remaining = max(0, total - already - bad)
    _ui_scan_file_done(ui, url_file, total=total, downloaded=already, bad=bad)

    return URLFileInfo(
        url_file=url_file,
        stem=stem,
        source="main",
        out_dir=dest,
        url_count=total,
        downloaded=already,
        bad=bad,
        remaining=remaining,
        viable_checked=True,
    )

# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _WorkFile:
    url_file: Path
    stem: str
    source: str
    out_dir: Path
    urls: List[str]
    remaining: int

def _build_worklist(snap: CountsSnapshot) -> List[_WorkFile]:
    work: List[_WorkFile] = []
    for key, rec in snap.files.items():
        url_file = Path(key)
        try:
            urls = read_urls_from_files([url_file])
        except Exception:
            urls = []
        out_dir = Path(rec.get("out_dir") or DEF_OUT_DIR / url_file.stem)
        remaining = int(rec.get("remaining") or max(0, len(urls) - int(rec.get("downloaded", 0))))
        work.append(
            _WorkFile(
                url_file=url_file,
                stem=str(rec.get("stem") or url_file.stem),
                source=str(rec.get("source") or "main"),
                out_dir=out_dir,
                urls=urls,
                remaining=remaining,
            )
        )
    return work

def _build_worklist_from_disk(
    main_url_dir: Path,
    ae_url_dir: Path,
    out_root: Path,
    single_files: Optional[List[Path]] = None,
) -> List[_WorkFile]:
    """
    Builds a worklist directly from files on disk.
    If single_files is provided, ONLY those files are used.
    Otherwise, scans the provided directories.
    """
    work: List[_WorkFile] = []
    seen_files = set()

    def _process_file(url_file: Path, source: str):
        try:
            resolved_path = str(url_file.resolve())
            if resolved_path in seen_files:
                return
            
            urls = read_urls_from_files([url_file])
            out_dir = _infer_dest_dir(out_root, url_file)
            work.append(
                _WorkFile(
                    url_file=url_file,
                    stem=url_file.stem,
                    source=source,
                    out_dir=out_dir,
                    urls=urls,
                    remaining=len(urls),
                )
            )
            seen_files.add(resolved_path)
        except Exception:
            pass

    # If single_files is provided, ONLY process them.
    if single_files:
        resolved_ae_dir = str(ae_url_dir.resolve())
        for f in single_files:
            if f.is_file():
                # Determine source based on whether it's in the ae dir path
                source = "ae" if str(f.resolve()).startswith(resolved_ae_dir) else "main"
                _process_file(f, source)
    else:
        # Otherwise, process the directories
        def _process_dir(d: Path, source: str):
            if not d.is_dir():
                return
            for url_file in sorted(d.glob("*.txt")):
                if url_file.is_file():
                    _process_file(url_file, source)

        _process_dir(main_url_dir, "main")
        _process_dir(ae_url_dir, "ae")
            
    return work

# ---------------------------------------------------------------------------

def _scan_all_parallel(
    main_url_dir: Path,
    ae_url_dir: Path,
    out_root: Path,
    single_files: Optional[List[Path]],
    *,
    yt_dlp: str,
    ytdlp_template: str,
    n_workers: int,
    counts_path: Path,
    ui,
    log_fn,
    stop_evt: threading.Event,
    pause_evt: threading.Event,
) -> CountsSnapshot:
    """Scan MAIN using yt-dlp; AE is discovered but skipped for now."""
    def _iter_txt(d: Path) -> List[Path]:
        return [p for p in sorted(Path(d).glob("*.txt")) if p.is_file()]

    # Deduplicate all files to be scanned from directories and single-file args
    all_files_map: Dict[str, Tuple[Path, str]] = {}

    if not single_files: # Only scan dirs if no specific files were given
        for p in _iter_txt(main_url_dir):
            all_files_map[str(p.resolve())] = (p, "main")
        for p in _iter_txt(ae_url_dir):
            all_files_map[str(p.resolve())] = (p, "ae")

    if single_files:
        resolved_ae_dir = str(ae_url_dir.resolve())
        for f in single_files:
            if f.is_file():
                resolved_f = str(f.resolve())
                if resolved_f not in all_files_map:
                    source = "ae" if resolved_f.startswith(resolved_ae_dir) else "main"
                    all_files_map[resolved_f] = (f, source)

    all_files: List[Tuple[Path, str]] = list(all_files_map.values())


    snap = CountsSnapshot()
    snap.sources = {
        "main": {"url_dir": str(main_url_dir.resolve()), "out_dir": str(out_root.resolve())},
        "ae": {"url_dir": str(ae_url_dir.resolve()), "out_dir": str(out_root.resolve())},
    }
    _atomic_write_text(counts_path, snap.to_json())

    # UI setup
    ui.begin_scan(n_workers, len(all_files))
    ui.set_footer("Keys: z pause/resume • q confirm quit • Q force quit")
    try:
        ui.set_scan_log_path(counts_path.with_name("ytaedl-scan-results.tsv"))
    except Exception:
        pass

    # Queue files
    q: "queue.Queue[tuple[int, Path, str]]" = queue.Queue()
    for idx, (f, src) in enumerate(all_files):
        q.put((idx, f, src))

    files_lock = threading.Lock()

    def worker(slot: int):
        while not stop_evt.is_set():
            try:
                _idx, f, src = q.get_nowait()
            except queue.Empty:
                break

            # Always paint the worker with a set name on start
            if src == "ae":
                # Skipped for now
                ui.set_scan_slot(slot, f"ae:{f.stem} (skipped)")
                ui.advance_scan(1)
                continue

            log_fn(f"SCAN start main {f}")
            try:
                info = _scan_one_file_main_with_ytdlp(
                    f,
                    out_root,
                    yt_dlp=yt_dlp,
                    template=ytdlp_template,
                    pause_evt=pause_evt,
                    stop_evt=stop_evt,
                    ui=ui,
                    slot=slot,
                    log_fn=log_fn,
                )
            except Exception as ex:
                log_fn(f"SCAN error main {f}: {ex}")
                info = URLFileInfo(f, f.stem, "main", _infer_dest_dir(out_root, f), 0, 0, 0, 0, False)

            # Record into JSON, append TSV line
            with files_lock:
                try:
                    st = f.stat()
                    snap.files[str(f.resolve())] = {
                        "stem": info.stem,
                        "source": info.source,
                        "out_dir": str(info.out_dir),
                        "url_count": info.url_count,
                        "downloaded": info.downloaded,
                        "bad": info.bad,
                        "remaining": info.remaining,
                        "viable_checked": info.viable_checked,
                        "url_mtime": int(st.st_mtime),
                        "url_size": int(st.st_size),
                    }
                    _atomic_write_text(counts_path, snap.to_json())
                except Exception:
                    pass

                # TSV: urlfile \t total \t downloaded \t bad \t remaining
                try:
                    tsv = counts_path.with_name("ytaedl-scan-results.tsv")
                    _append_line(tsv, f"{f}\t{info.url_count}\t{info.downloaded}\t{info.bad}\t{info.remaining}")
                except Exception:
                    pass

            ui.advance_scan(1)
            log_fn(
                f"SCAN done  main {f} urls={info.url_count} dl={info.downloaded} bad={info.bad} rem={info.remaining}"
            )

            q.task_done()

            if stop_evt.is_set():
                break

    threads: List[threading.Thread] = []
    for i in range(max(1, n_workers)):
        t = threading.Thread(target=worker, args=(i,), daemon=True, name=f"scan-{i+1}")
        t.start()
        threads.append(t)

    # Keep pumping UI so pause/resume doesn't jank columns
    while any(t.is_alive() for t in threads):
        if stop_evt.is_set():
            break
        ui.pump()
        time.sleep(0.05)

    for t in threads:
        t.join(timeout=1.0)

    ui.end_scan()
    ui.pump()
    return snap

# ---------------------------------------------------------------------------

class _Coordinator:
    """Simple work balancer; prefers items with more remaining."""
    def __init__(self, work: List["_WorkFile"]):
        self._lock = threading.Lock()
        self._work: Dict[str, _WorkFile] = {str(w.url_file.resolve()): w for w in work}
        self._assigned: Dict[str, int] = {}

    def acquire_next(self) -> Optional["_WorkFile"]:
        with self._lock:
            # Get available candidates
            candidates = [w for w in self._work.values() if self._assigned.get(str(w.url_file.resolve()), 0) == 0]
            if not candidates:
                return None
            
            # Shuffle them to randomize selection among files with the same 'remaining' count
            random.shuffle(candidates)
            
            # Now sort by remaining (primary) and then stem (secondary, for stability after shuffle)
            candidates.sort(key=lambda w: (-w.remaining, w.stem))
            
            # Pick the best one
            best_choice = candidates[0]
            key = str(best_choice.url_file.resolve())
            self._assigned[key] = 1
            return best_choice

    def release(self, wf: "_WorkFile", *, remaining_delta: int = 0) -> None:
        with self._lock:
            key = str(wf.url_file.resolve())
            if key not in self._work:
                return
            cur = self._work[key]
            new_remaining = max(0, int(cur.remaining) + int(remaining_delta))
            self._work[key] = dataclasses.replace(cur, remaining=new_remaining)
            if key in self._assigned:
                self._assigned[key] = max(0, self._assigned[key] - 1)

# ---------------------------------------------------------------------------

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="ytaedl-orchestrate",
        description="Orchestrate scanning and downloads with a Termdash UI.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    # Core Controls
    core = p.add_argument_group("Core Controls")
    core.add_argument("-t", "--threads", type=int, default=4, help="Total concurrent worker slots.")
    core.add_argument("-m", "--max-dl-per-file", dest="max_dl", type=int, default=3, help="Max successful downloads per URL file assignment.")
    core.add_argument("-S", "--skip-scan", action="store_true", help="Skip scanning and download directly from URL files.")

    # Process Allocation
    proc = p.add_argument_group("Process Allocation")
    proc.add_argument("-a", "--num-aebn-dl", type=int, default=1, help="Number of concurrent AEBN download workers.")
    proc.add_argument("-y", "--num-ytdl-dl", type=int, default=3, help="Number of concurrent yt-dlp download workers.")
    
    # Paths
    paths = p.add_argument_group("Paths")
    paths.add_argument("-f", "--file", dest="url_files", action="append", help="Path to a specific URL file to process (repeatable).")
    paths.add_argument("-u", "--url-dir", type=Path, default=DEF_URL_DIR, help="Main URL dir (yt-dlp sources).")
    paths.add_argument("-e", "--ae-url-dir", type=Path, default=DEF_AE_URL_DIR, help="AEBN URL dir.")
    paths.add_argument("-o", "--output-dir", type=Path, default=DEF_OUT_DIR, help="Destination root for downloads.")
    paths.add_argument("-c", "--counts-file", type=Path, default=DEF_COUNTS_FILE, help="JSON counts file path (for scanning).")
    paths.add_argument("-A", "--archive-file", dest="archive", type=Path, default=None, help="Archive file to skip already downloaded URLs.")
    paths.add_argument("-L", "--log-file", type=Path, help="Append detailed logs to this file.")
    
    # Scanning
    scan = p.add_argument_group("Scanning")
    scan.add_argument("-p", "--ytdlp-path", dest="ytdlp", default="yt-dlp", help="Path to yt-dlp executable (for scanning).")
    scan.add_argument("-T", "--ytdlp-template", default="%(title)s.%(ext)s", help="Filename template for yt-dlp.")

    # Downloader Tuning
    tune = p.add_argument_group("Downloader Tuning")
    tune.add_argument("-j", "--jobs", type=int, default=1, help="Per-process jobs for the downloader itself.")
    tune.add_argument("-O", "--timeout", type=int, default=None, help="Per-process timeout in seconds.")
    tune.add_argument("-R", "--rate-limit", default=None, help="Download rate limit (e.g., 500K, 2M).")
    tune.add_argument("-B", "--buffer-size", default=None, help="Download buffer size (e.g., 16M).")
    tune.add_argument("-r", "--retries", type=int, default=None, help="Number of retries for downloads.")
    tune.add_argument("-F", "--fragment-retries", type=int, default=None, help="Number of retries for fragments.")
    tune.add_argument("-C", "--ytdlp-connections", type=int, default=None, help="Number of parallel connections for yt-dlp.")
    tune.add_argument("-s", "--aria2-splits", type=int, default=None, help="Number of splits for aria2.")
    tune.add_argument("-x", "--aria2-x-conn", type=int, default=None, help="Connections per server for aria2.")
    tune.add_argument("-M", "--aria2-min-split", default=None, help="Min split size for aria2 (e.g., 1M).")
    tune.add_argument("-Z", "--aria2-timeout", type=int, default=None, help="Timeout for aria2 in seconds.")
    
    # UI
    ui_group = p.add_argument_group("UI")
    ui_group.add_argument("-n", "--no-ui", action="store_true", help="Disable Termdash UI and use simple print statements.")
    
    return p.parse_args(argv)

def _build_config(args: argparse.Namespace) -> DownloaderConfig:
    return DownloaderConfig(
        work_dir=args.output_dir,
        archive_path=args.archive,
        max_size_gb=10.0,
        keep_oversized=False,
        timeout_seconds=args.timeout,
        parallel_jobs=max(1, args.jobs),
        aebn_only=False,
        scene_from_url=True,
        save_covers=False,
        keep_covers_flag=False,
        extra_aebn_args=[],
        extra_ytdlp_args=[],
        ytdlp_connections=args.ytdlp_connections,
        ytdlp_rate_limit=args.rate_limit,
        ytdlp_retries=args.retries,
        ytdlp_fragment_retries=args.fragment_retries,
        ytdlp_buffer_size=args.buffer_size,
        aria2_splits=args.aria2_splits,
        aria2_x_conn=args.aria2_x_conn,
        aria2_min_split=args.aria2_min_split,
        aria2_timeout=args.aria2_timeout,
        log_file=args.log_file,
    )

# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    random.seed() # Seed with current time for randomness

    # normalize
    args.url_dir = Path(args.url_dir)
    args.ae_url_dir = Path(args.ae_url_dir)
    args.output_dir = Path(args.output_dir)
    args.counts_file = Path(args.counts_file)

    # simple log
    log_fp = None
    if args.log_file:
        try:
            args.log_file.parent.mkdir(parents=True, exist_ok=True)
            log_fp = args.log_file.open("a", encoding="utf-8")
        except Exception:
            log_fp = None

    def olog(msg: str) -> None:
        if log_fp:
            try:
                log_fp.write(f"[{_now_str()}] {msg}\n")
                log_fp.flush()
            except Exception:
                pass

    # UI
    use_ui = not args.no_ui
    if use_ui:
        try:
            ui = TermdashUI(num_workers=max(1, args.threads), total_urls=0)
        except Exception as ex:
            olog(f"UI fallback: {ex}")
            try:
                ui = SimpleUI(num_workers=max(1, args.threads), total_urls=0)
            except TypeError:
                ui = SimpleUI()
            use_ui = False
    else:
        try:
            ui = SimpleUI(num_workers=max(1, args.threads), total_urls=0)
        except TypeError:
            ui = SimpleUI()

    stop_evt = threading.Event()
    pause_evt = threading.Event()

    # hotkeys (best effort)
    def _key_reader():
        if not sys.stdin.isatty():
            return
        if os.name == "nt":
            import msvcrt
            while not stop_evt.is_set():
                if msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    if ch in ("z", "Z"):
                        if pause_evt.is_set():
                            pause_evt.clear()
                            try: ui.set_paused(False)
                            except Exception: pass
                        else:
                            pause_evt.set()
                            try: ui.set_paused(True)
                            except Exception: pass
                    elif ch == "q":
                        stop_evt.set()
                        break
                    elif ch == "Q":
                        stop_evt.set()
                        request_abort()
                        terminate_all_active_procs()
                        break
                else:
                    time.sleep(0.1)
        else:
            import termios, tty, select
            fd = sys.stdin.fileno()
            try:
                old = termios.tcgetattr(fd)
            except Exception:
                return
            try:
                tty.setcbreak(fd)
                while not stop_evt.is_set():
                    r, _, _ = select.select([fd], [], [], 0.1)
                    if not r:
                        continue
                    ch = os.read(fd, 1).decode(errors="ignore")
                    if ch in ("z", "Z"):
                        if pause_evt.is_set():
                            pause_evt.clear()
                            try: ui.set_paused(False)
                            except Exception: pass
                        else:
                            pause_evt.set()
                            try: ui.set_paused(True)
                            except Exception: pass
                    elif ch == "q":
                        stop_evt.set()
                        break
                    elif ch == "Q":
                        stop_evt.set()
                        request_abort()
                        terminate_all_active_procs()
                        break
            finally:
                try:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
                except Exception:
                    pass

    with ui:
        olog("orchestrator start")
        threading.Thread(target=_key_reader, daemon=True, name="keys").start()

        all_work: List[_WorkFile]
        single_files_provided = [Path(f) for f in args.url_files] if args.url_files else None

        if args.skip_scan:
            olog("skip-scan enabled, building worklist from disk")
            all_work = _build_worklist_from_disk(
                args.url_dir,
                args.ae_url_dir,
                args.output_dir,
                single_files=single_files_provided
            )
            random.shuffle(all_work)
        else:
            olog("starting scan phase")
            snap = _scan_all_parallel(
                args.url_dir,
                args.ae_url_dir,
                args.output_dir,
                single_files=single_files_provided,
                yt_dlp=args.ytdlp,
                ytdlp_template=args.ytdlp_template,
                n_workers=max(1, args.threads),
                counts_path=args.counts_file,
                ui=ui,
                log_fn=olog,
                stop_evt=stop_evt,
                pause_evt=pause_evt,
            )
            if stop_evt.is_set():
                if log_fp:
                    try: log_fp.close()
                    except Exception: pass
                return 130
            all_work = sorted(_build_worklist(snap), key=lambda w: (-w.remaining, w.stem))

        # ---- Archive Handling ----
        archive_path = args.archive
        archived_urls = set()
        if archive_path:
            archived_urls = load_archive(archive_path)
        archive_lock = threading.Lock()

        # ---- Thread and Work Allocation ----
        aebn_work = [w for w in all_work if w.source == 'ae']
        ytdlp_work = [w for w in all_work if w.source == 'main']

        num_a = args.num_aebn_dl
        num_y = args.num_ytdl_dl
        total_req = num_a + num_y
        total_allowed = args.threads

        if total_req > total_allowed:
            aebn_threads = round(total_allowed * (num_a / total_req)) if total_req > 0 else 0
            ytdlp_threads = total_allowed - aebn_threads
        else:
            aebn_threads = num_a
            ytdlp_threads = num_y
        
        olog(f"Thread allocation: AEBN={aebn_threads}, yt-dlp={ytdlp_threads} (Total={total_allowed})")

        aebn_coord = _Coordinator(aebn_work)
        ytdlp_coord = _Coordinator(ytdlp_work)

        cfg = _build_config(args)
        object.__setattr__(cfg, "_orchestrator_max_dl", int(args.max_dl))

        def worker(slot: int, coordinator: _Coordinator):
            while not stop_evt.is_set():
                wf = coordinator.acquire_next()
                if wf is None:
                    break
                
                if hasattr(ui, 'reset_worker_stats'):
                    ui.reset_worker_stats(slot)
                
                downloader_type = "AEBN" if wf.source == "ae" else "YT-DLP"
                olog(f"Worker {slot} ({downloader_type}): Acquired work file '{wf.url_file.name}'. Remaining URLs: {wf.remaining}")

                try:
                    if hasattr(ui, 'set_scan_slot'):
                        ui.set_scan_slot(slot, f"{downloader_type}: {wf.stem} (rem {wf.remaining})")
                except Exception:
                    pass

                successful_downloads_this_run = 0
                cap = getattr(cfg, "_orchestrator_max_dl", 3)

                for idx, url in enumerate(wf.urls, start=1):
                    if successful_downloads_this_run >= cap:
                        olog(f"Worker {slot}: Reached cap of {cap} successful downloads for file '{wf.url_file.name}'. Releasing.")
                        break

                    if stop_evt.is_set():
                        break
                    while pause_evt.is_set() and not stop_evt.is_set():
                        ui.pump()
                        time.sleep(0.1)
                    if stop_evt.is_set():
                        break

                    if archive_path and url in archived_urls:
                        olog(f"Worker {slot}: Skipping archived URL: {url}")
                        continue
                    
                    olog(f"Worker {slot}: Attempting download for URL ({idx}/{len(wf.urls)}): {url} from file '{wf.url_file.name}'")

                    item = DownloadItem(
                        id=get_next_item_id(),
                        url=url,
                        output_dir=wf.out_dir,
                        source=URLSource(file=wf.url_file, line_number=idx, original_url=url),
                    )
                    
                    # Add total_in_set for UI to prevent 4/0 display error
                    setattr(item, 'total_in_set', len(wf.urls))
                    
                    downloader = get_downloader(url, cfg)
                    url_was_successful = False
                    
                    try:
                        ui.handle_event(StartEvent(item=item))
                        ui.pump()
                        
                        for ev in downloader.download(item):
                            if stop_evt.is_set():
                                break
                            
                            if isinstance(ev, LogEvent):
                                olog(f"Worker {slot} [URL: {url}]: {ev.message}")

                            ui.handle_event(ev)

                            if isinstance(ev, FinishEvent):
                                result = ev.result
                                olog(f"Worker {slot}: Finished URL '{url}' with status: {result.status.value}")
                                if result.error_message:
                                    olog(f"Worker {slot}: Error for '{url}': {result.error_message}")
                                
                                if result.status in (DownloadStatus.COMPLETED, DownloadStatus.ALREADY_EXISTS):
                                    url_was_successful = True
                                    if archive_path:
                                        with archive_lock:
                                            if url not in archived_urls:
                                                write_to_archive(archive_path, url)
                                                archived_urls.add(url)
                            ui.pump()

                    except KeyboardInterrupt:
                        stop_evt.set()
                        break
                    except Exception as ex:
                        olog(f"DOWNLOAD error url='{url}' exc='{ex}'")
                        try:
                            ui.handle_event(LogEvent(item=item, message=f"Error: {ex}"))
                            ui.handle_event(FinishEvent(item=item, result=DownloadResult(item=item, status=DownloadStatus.FAILED, error_message=str(ex))))
                        except:
                            pass
                    finally:
                        ui.pump()

                    if url_was_successful:
                        successful_downloads_this_run += 1
                    
                coordinator.release(wf, remaining_delta=-(successful_downloads_this_run))
                olog(f"Worker {slot}: Released work file '{wf.url_file.name}'. Completed {successful_downloads_this_run} successful downloads in this run.")
            
            olog(f"Worker {slot}: No more work. Shutting down.")


        threads: List[threading.Thread] = []
        slot_counter = 0
        for i in range(aebn_threads):
            t = threading.Thread(target=worker, args=(slot_counter, aebn_coord), daemon=True, name=f"dl-ae-{i+1}")
            threads.append(t)
            slot_counter += 1
        
        for i in range(ytdlp_threads):
            t = threading.Thread(target=worker, args=(slot_counter, ytdlp_coord), daemon=True, name=f"dl-yt-{i+1}")
            threads.append(t)
            slot_counter += 1
            
        for t in threads:
            t.start()

        try:
            while any(t.is_alive() for t in threads) and not stop_evt.is_set():
                ui.pump()
                time.sleep(0.1)
        finally:
            for t in threads:
                try:
                    t.join(timeout=1.0)
                except Exception:
                    pass

        ui.summary({}, time.monotonic())

    if log_fp:
        try:
            log_fp.close()
        except Exception:
            pass
    return 0

# ---------------------------------------------------------------------------

if __name__ == "__main__":
    raise SystemExit(main())
