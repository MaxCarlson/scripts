#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Orchestrator — scan URL files and then download, with a Termdash UI.

Exports used by tests:
- CountsSnapshot
- _is_snapshot_complete(snapshot)
- _build_worklist(main_url_dir, ae_url_dir, out_root, single_files=None)  # compatibility wrapper
"""
from __future__ import annotations

import argparse
import random
import sys
import termios
import tty
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional

# --- IO imports with safe fallbacks ------------------------------------------
try:
    from .io import read_urls_from_files, expand_url_dirs  # type: ignore
except Exception as ex:  # pragma: no cover
    raise ImportError(f"ytaedl.orchestrator requires ytaedl.io.read_urls_from_files/expand_url_dirs: {ex}")

try:
    from .io import read_archive as _read_archive, write_to_archive as _write_to_archive  # type: ignore
except Exception:
    _read_archive = None
    _write_to_archive = None

def _shim_read_archive(path: Path) -> List[str]:
    try:
        if not path.exists():
            return []
        return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except Exception:
        return []

def _shim_write_to_archive(path: Path, url: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(url.strip() + "\n")
    except Exception:
        pass

read_archive = _read_archive or _shim_read_archive
write_to_archive = _write_to_archive or _shim_write_to_archive
# ------------------------------------------------------------------------------

from .models import (
    DownloadItem,
    DownloadResult,
    DownloadStatus,
    DownloaderConfig,
    URLSource,
    FinishEvent,
)
from .url_parser import is_aebn_url
from .downloaders import (
    YtDlpDownloader,
    AebnDownloader,
    request_abort,
    abort_requested,
    terminate_all_active_procs,
)
from .ui import make_ui


# -------------------- Defaults --------------------

DEF_URL_DIR = Path("files/downloads/stars")
DEF_AE_URL_DIR = Path("files/downloads/ae-stars")
DEF_OUT_DIR = Path("stars")
DEF_ARCHIVE = None


# -------------------- Public stats struct (for tests/consumers) --------------

@dataclass(frozen=True)
class CountsSnapshot:
    """
    Lightweight snapshot for UI/tests. We keep it generic so it won’t break
    existing imports. Callers can compute these from events.
    """
    total_urls: int = 0
    completed: int = 0
    failed: int = 0
    already: int = 0
    active: int = 0
    queued: int = 0


# -------------------- Work model --------------------

@dataclass
class _WorkFile:
    url_file: Path
    stem: str
    source: str  # "main" | "ae"
    out_dir: Path
    urls: List[str]
    downloaded: int
    bad: int
    remaining: int


def _infer_dest_dir(out_root: Path, url_file: Path) -> Path:
    """
    Where finished videos live for the given URL file (matches your layout).
    """
    return (out_root / url_file.stem).resolve()


# -------------------- Coordinator --------------------

class _Coordinator:
    """
    Thread-safe work coordinator with randomized selection among candidates.
    """
    def __init__(self, work: List[_WorkFile]):
        self._work: Dict[str, _WorkFile] = {str(w.url_file.resolve()): w for w in work}
        self._lock = threading.Lock()
        self._assigned: Dict[str, int] = {str(w.url_file.resolve()): 0 for w in work}

    def acquire(self) -> Optional[_WorkFile]:
        with self._lock:
            candidates = [w for w in self._work.values()
                          if self._assigned.get(str(w.url_file.resolve()), 0) == 0 and w.remaining > 0]
            if not candidates:
                return None
            random.shuffle(candidates)
            candidates.sort(key=lambda w: (-w.remaining, w.stem))
            chosen = candidates[0]
            key = str(chosen.url_file.resolve())
            self._assigned[key] = 1
            return chosen

    def release(self, w: _WorkFile, *, remaining_delta: int = 0) -> None:
        with self._lock:
            key = str(w.url_file.resolve())
            rec = self._work.get(key)
            if rec:
                rec.remaining = max(0, rec.remaining + int(remaining_delta))
                self._assigned[key] = 0


# -------------------- CLI --------------------

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="ytaedl-orchestrate", description="Multi-threaded downloader orchestrator with Termdash UI.")
    p.add_argument("--version", action="store_true", help="Print version info and exit.")

    # Process Allocation
    proc = p.add_argument_group("Process Allocation")
    proc.add_argument("-a", "--num-aebn-dl", type=int, default=1, help="Number of concurrent AEBN download workers.")
    proc.add_argument("-y", "--num-ytdl-dl", type=int, default=3, help="Number of concurrent yt-dlp download workers.")

    # Paths
    paths = p.add_argument_group("Paths")
    paths.add_argument("-f", "--file", dest="url_files", action="append", default=[], help="Path to a specific URL file to process (repeatable).")
    paths.add_argument("-u", "--url-dir", type=Path, default=DEF_URL_DIR, help="Main URL dir (yt-dlp sources).")
    paths.add_argument("-e", "--ae-url-dir", type=Path, default=DEF_AE_URL_DIR, help="AEBN URL dir.")
    paths.add_argument("-o", "--output-dir", type=Path, default=DEF_OUT_DIR, help="Output root directory.")

    # Scan/Skip-scan
    mode = p.add_argument_group("Mode")
    mode.add_argument("--skip-scan", action="store_true", help="Skip scanning and build worklist directly from disk.")

    # Archive
    arch = p.add_argument_group("Archive")
    arch.add_argument("-A", "--archive", type=Path, default=DEF_ARCHIVE, help="Path to download archive file.")

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
        timeout_seconds=None,
        ytdlp_connections=None,
        ytdlp_rate_limit=None,
        ytdlp_retries=None,
        ytdlp_fragment_retries=None,
        ytdlp_buffer_size=None,
        aria2_splits=None,
        aria2_x_conn=None,
        aria2_min_split=None,
        aria2_timeout=None,
    )


# -------------------- Worklist builders --------------------

def _build_worklist_from_disk(
    main_url_dir: Path,
    ae_url_dir: Path,
    out_root: Path,
    single_files: Optional[List[Path]] = None,
) -> List[_WorkFile]:
    """
    Builds a worklist directly from files on disk.
    If single_files is provided, ONLY those files are used (no directory scanning).
    """
    def _process_file(url_file: Path, source: str) -> Optional[_WorkFile]:
        try:
            urls = read_urls_from_files([url_file])
        except Exception:
            urls = []
        out_dir = _infer_dest_dir(out_root, url_file)
        return _WorkFile(
            url_file=url_file,
            stem=url_file.stem,
            source=source,
            out_dir=out_dir,
            urls=urls,
            downloaded=0,
            bad=0,
            remaining=len(urls),
        )

    work: List[_WorkFile] = []
    seen: set[str] = set()

    if single_files:
        for f in single_files:
            p = Path(f)
            if p.is_file() and p.suffix.lower() == ".txt":
                key = str(p.resolve())
                if key in seen:
                    continue
                seen.add(key)
                src = "ae" if p.parent.resolve() == ae_url_dir.resolve() else "main"
                wf = _process_file(p, src)
                if wf:
                    work.append(wf)
        return work

    for p in expand_url_dirs([main_url_dir]):
        key = str(p.resolve())
        if key in seen:
            continue
        seen.add(key)
        wf = _process_file(p, "main")
        if wf:
            work.append(wf)

    for p in expand_url_dirs([ae_url_dir]):
        key = str(p.resolve())
        if key in seen:
            continue
        seen.add(key)
        wf = _process_file(p, "ae")
        if wf:
            work.append(wf)

    return work


# -------------------- Main --------------------

def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    random.seed()

    # normalize
    args.url_dir = Path(args.url_dir)
    args.ae_url_dir = Path(args.ae_url_dir)
    args.output_dir = Path(args.output_dir)

    # Prepare UI
    ui = make_ui(
        num_workers=max(1, int(args.num_ytdl_dl) + int(args.num_aebn_dl)),
        total_urls=0,  # filled dynamically by events
    )

    stop_evt = threading.Event()
    pause_evt = threading.Event()

    # key reader for pause/quit
    def _key_reader() -> None:
        try:
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setcbreak(fd)
                while not stop_evt.is_set():
                    ch = sys.stdin.read(1)
                    if ch == "z":
                        if pause_evt.is_set():
                            pause_evt.clear()
                        else:
                            pause_evt.set()
                        try:
                            ui.set_paused(pause_evt.is_set())
                        except Exception:
                            pass
                    elif ch == "q":
                        stop_evt.set()
                        break
                    elif ch == "Q":
                        request_abort()
                        terminate_all_active_procs()
                        stop_evt.set()
                        break
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except Exception:
            # Non-tty or another error; ignore hotkeys
            pass

    with ui:
        threading.Thread(target=_key_reader, daemon=True, name="keys").start()

        # Build worklist
        single_files_provided = [Path(f) for f in args.url_files] if args.url_files else None
        all_work = _build_worklist_from_disk(
            args.url_dir, args.ae_url_dir, args.output_dir, single_files=single_files_provided
        )

        coord = _Coordinator(all_work)

        # Archive handling (safe shims if not provided by ytaedl.io)
        archive_path: Optional[Path] = args.archive
        archived_urls: set[str] = set()
        archive_lock = threading.Lock()
        if archive_path:
            archived_urls = set(read_archive(archive_path))

        # Worker function
        def worker(slot: int, downloader_type: str) -> None:
            thread_name = f"dl-{downloader_type}-{slot+1}"
            threading.current_thread().name = thread_name

            cfg = _build_config(args)
            ytdl = YtDlpDownloader(cfg)
            aebn = AebnDownloader(cfg)

            while not stop_evt.is_set() and not abort_requested():
                if pause_evt.is_set():
                    time.sleep(0.1)
                    continue

                wf = coord.acquire()
                if not wf:
                    break

                successful_downloads_this_run = 0

                try:
                    for i, url in enumerate(list(wf.urls), start=1):
                        if stop_evt.is_set() or abort_requested():
                            break
                        if archive_path and url in archived_urls:
                            continue

                        is_aebn = is_aebn_url(url)
                        item = DownloadItem(
                            id=(slot * 10_000_000) + i,
                            url=url,
                            output_dir=wf.out_dir,
                            source=URLSource(file=wf.url_file, line_number=i, original_url=url),
                            extra_ytdlp_args=[],
                            extra_aebn_args=[],
                        )

                        events: Iterator = (aebn.download(item) if is_aebn else ytdl.download(item))
                        url_ok = False
                        for ev in events:
                            try:
                                ui.handle_event(ev)
                            except Exception:
                                pass

                            if isinstance(ev, FinishEvent):
                                res: DownloadResult = ev.result
                                if res.status in (DownloadStatus.COMPLETED, DownloadStatus.ALREADY_EXISTS):
                                    url_ok = True

                        try:
                            ui.pump()
                        except Exception:
                            pass

                        if url_ok:
                            successful_downloads_this_run += 1
                            if archive_path:
                                with archive_lock:
                                    if url not in archived_urls:
                                        write_to_archive(archive_path, url)
                                        archived_urls.add(url)

                except KeyboardInterrupt:
                    stop_evt.set()
                    break
                finally:
                    coord.release(wf, remaining_delta=-(successful_downloads_this_run))

        # Spin up workers
        threads: List[threading.Thread] = []
        slot = 0
        for _ in range(max(0, int(args.num_aebn_dl))):
            t = threading.Thread(target=worker, args=(slot, "ae"), daemon=True, name=f"dl-ae-{slot+1}")
            threads.append(t)
            slot += 1
        for _ in range(max(1, int(args.num_ytdl_dl))):
            t = threading.Thread(target=worker, args=(slot, "yt"), daemon=True, name=f"dl-yt-{slot+1}")
            threads.append(t)
            slot += 1

        for t in threads:
            t.start()

        try:
            while any(t.is_alive() for t in threads) and not stop_evt.is_set():
                try:
                    ui.pump()
                except Exception:
                    pass
                time.sleep(0.05)
        finally:
            for t in threads:
                try:
                    t.join(timeout=0.1)
                except Exception:
                    pass

        try:
            ui.summary({}, time.monotonic())
        except Exception:
            pass

    return 0


# --------------------------------------------------------------------------
# Legacy exports for tests (compatibility shims)
# --------------------------------------------------------------------------

def _is_snapshot_complete(snapshot: CountsSnapshot) -> bool:
    """
    Test helper: a snapshot is 'complete' if all URLs have either
    completed, failed, or are marked already, and no active/queued remain.
    """
    total_done = snapshot.completed + snapshot.failed + snapshot.already
    return (total_done >= snapshot.total_urls) and snapshot.active == 0 and snapshot.queued == 0


def _build_worklist(
    main_url_dir: Path,
    ae_url_dir: Path,
    out_root: Path,
    single_files: Optional[List[Path]] = None,
) -> List[_WorkFile]:
    """
    Compatibility wrapper expected by tests. Delegates to the new
    _build_worklist_from_disk with identical semantics.
    """
    return _build_worklist_from_disk(main_url_dir, ae_url_dir, out_root, single_files=single_files)


if __name__ == "__main__":
    raise SystemExit(main())
