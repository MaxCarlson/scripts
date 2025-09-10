#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Orchestrator — scan URL files and then download, with a Termdash (or simple) UI.

Exports used by tests:
- CountsSnapshot
- _is_snapshot_complete(snapshot, *extras)
- _build_worklist(...): accepts multiple historical call shapes:
    (_snap, main_url_dir, out_root)
    (_snap, main_url_dir, ae_url_dir, out_root)
    (main_url_dir, out_root)
    (main_url_dir, ae_url_dir, out_root)
  plus optional single_files=...
"""
from __future__ import annotations

import argparse
import random
import time
import subprocess, sys, threading
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import Dict, Iterator, List, Optional, Any, Tuple

# parsers (moved to procparsers module)
from procparsers import parse_ytdlp_line

# run logger with program-runtime timestamps & counters
from .runlogger import RunLogger

# ---------- cross-platform console input (POSIX + Windows) ----------
try:
    import termios  # POSIX
    import tty
    import select
    _HAVE_TERMIOS = True
except Exception:
    _HAVE_TERMIOS = False
    try:
        import msvcrt  # Windows
    except Exception:
        msvcrt = None  # type: ignore

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

@dataclass
class CountsSnapshot:
    """
    Mutable snapshot model; tests write into .files.
    """
    total_urls: int = 0
    completed: int = 0
    failed: int = 0
    already: int = 0
    active: int = 0
    queued: int = 0
    files: Dict[str, Dict[str, object]] = field(default_factory=dict)


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
    return (out_root / url_file.stem).resolve()


# -------------------- Coordinator --------------------

class _Coordinator:
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

    # Compatibility alias expected by tests
    def acquire_next(self) -> Optional[_WorkFile]:
        return self.acquire()

    def release(self, w: _WorkFile, *, remaining_delta: int = 0) -> None:
        with self._lock:
            key = str(w.url_file.resolve())
            rec = self._work.get(key)
            if rec:
                rec.remaining = max(0, rec.remaining + int(remaining_delta))
                self._assigned[key] = 0


# -------------------- CLI --------------------

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="ytaedl-orchestrate",
        description="Multi-threaded downloader orchestrator with optional Termdash UI.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # General / version
    p.add_argument("-V", "--version", action="store_true", help="Print version info and exit.")

    # Process Allocation
    proc = p.add_argument_group("Process Allocation")
    proc.add_argument("-a", "--num-aebn-dl", type=int, default=1, help="Number of concurrent AEBN download workers.")
    proc.add_argument("-y", "--num-ytdl-dl", type=int, default=3, help="Number of concurrent yt-dlp download workers.")

    # Paths
    paths = p.add_argument_group("Paths")
    paths.add_argument("-f", "--file", dest="url_files", action="append", default=[], help="Path to specific URL file(s) (repeatable).")
    paths.add_argument("-u", "--url-dir", type=Path, default=DEF_URL_DIR, help="Main URL dir (yt-dlp sources).")
    paths.add_argument("-e", "--ae-url-dir", type=Path, default=DEF_AE_URL_DIR, help="AEBN URL dir.")
    paths.add_argument("-o", "--output-dir", type=Path, default=DEF_OUT_DIR, help="Output root directory.")

    # Mode
    mode = p.add_argument_group("Mode")
    mode.add_argument("-S", "--skip-scan", action="store_true", help="Skip scanning and build worklist directly from disk.")

    # Archive
    arch = p.add_argument_group("Archive")
    arch.add_argument("-A", "--archive", type=Path, default=DEF_ARCHIVE, help="Path to download archive file.")

    # Runtime / Logging
    rt = p.add_argument_group("Runtime")
    rt.add_argument("-t", "--timeout", type=int, default=None, help="Per-process timeout (seconds).")
    rt.add_argument("-L", "--log-file", type=Path, default=None, help="Write detailed run log (START/FINISH with status).")

    # UI
    ui_group = p.add_argument_group("UI")
    ui_group.add_argument("-n", "--no-ui", action="store_true", help="Disable Termdash UI and use simple console UI.")

    return p.parse_args(argv)


def _build_config(args: argparse.Namespace) -> DownloaderConfig:
    return DownloaderConfig(
        work_dir=args.output_dir,
        archive_path=args.archive,
        max_size_gb=10.0,
        keep_oversized=False,
        timeout_seconds=args.timeout,   # <-- from -t / --timeout
        ytdlp_connections=None,
        ytdlp_rate_limit=None,
        ytdlp_retries=None,
        ytdlp_fragment_retries=None,
        ytdlp_buffer_size=None,
        aria2_splits=None,
        aria2_x_conn=None,
        aria2_min_split=None,
        aria2_timeout=None,
        log_file=args.log_file,         # mirrored for parity
    )


# -------------------- Worklist builders --------------------

def _build_worklist_from_disk(
    main_url_dir: Path,
    ae_url_dir: Path,
    out_root: Path,
    single_files: Optional[List[Path]] = None,
) -> List[_WorkFile]:
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


# -------------------- yt-dlp single-run wrapper (parser-aware) ----------------

def run_single_ytdlp(
    logger: RunLogger,
    url: str,
    url_index: int,
    out_tpl: str,
    extra_args: Optional[List[str]] = None,
    retries: int = 3,
) -> Tuple[str, str]:
    """
    Returns (status, note)
      status ∈ {'Finished DL', 'Exists', 'Bad URL', 'Internal Stop', 'External Stop'}
      note: optional details
    """
    cmd = [
        "yt-dlp",
        "--newline",
        "--print", "TDMETA\t%(id)s\t%(title)s",
        "-o", out_tpl,
        "--retries", str(retries),
        url,
    ]
    if extra_args:
        cmd = cmd[:-1] + extra_args + [url]  # keep URL last

    attempt_id = logger.start(url_index, url)

    # State gathered from parsing
    saw_already = False
    saw_progress = False
    finished_progress = False
    saw_destination = False
    last_error_line = None

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            universal_newlines=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception as ex:
        logger.finish(url_index, url, "External Stop", f"spawn-error: {ex!r}")
        return "External Stop", f"spawn-error: {ex!r}"

    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            evt = parse_ytdlp_line(raw)
            if not evt:
                if raw.strip().startswith("ERROR:"):
                    last_error_line = raw.strip()
                continue
            kind = evt["event"]
            if kind == "already":
                saw_already = True
            elif kind == "destination":
                saw_destination = True
            elif kind == "progress":
                saw_progress = True
                if evt.get("percent", 0.0) >= 100.0 or evt.get("eta_s") == 0:
                    finished_progress = True

        ret = proc.wait()
    except KeyboardInterrupt:
        try:
            proc.terminate()
        except Exception:
            pass
        logger.finish(url_index, url, "Internal Stop", "keyboard interrupt")
        return "Internal Stop", "keyboard interrupt"

    # Classification
    if ret != 0:
        note = last_error_line or f"exit code {ret}"
        logger.finish(url_index, url, "Bad URL", note)
        return "Bad URL", note

    # ret == 0
    if saw_already:
        logger.finish(url_index, url, "Exists")
        return "Exists", ""

    if finished_progress:
        logger.finish(url_index, url, "Finished DL")
        return "Finished DL", ""

    if saw_destination or saw_progress:
        logger.finish(url_index, url, "Finished DL", "no explicit 100% marker")
        return "Finished DL", "no explicit 100% marker"

    logger.finish(url_index, url, "Finished DL", "ret=0 but no parseable markers")
    return "Finished DL", "ret=0 but no parseable markers"


# -------------------- Main --------------------

def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if args.version:
        try:
            from . import __version__
            print(__version__)
        except Exception:
            print("ytaedl (version unknown)")
        return 0

    random.seed()

    args.url_dir = Path(args.url_dir)
    args.ae_url_dir = Path(args.ae_url_dir)
    args.output_dir = Path(args.output_dir)

    # Ensure output dir exists
    try:
        args.output_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    # Detailed run logger (program-runtime timestamps)
    runlog = RunLogger(args.log_file)

    ui = make_ui(
        num_workers=max(1, int(args.num_ytdl_dl) + int(args.num_aebn_dl)),
        total_urls=0,
    )

    stop_evt = threading.Event()
    pause_evt = threading.Event()

    # --------- cross-platform hotkeys ----------
    def _key_reader() -> None:
        if _HAVE_TERMIOS:
            try:
                fd = sys.stdin.fileno()
                old = termios.tcgetattr(fd)
                try:
                    tty.setcbreak(fd)
                    while not stop_evt.is_set():
                        r, _, _ = select.select([sys.stdin], [], [], 0.1)
                        if not r:
                            continue
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
                pass
        else:
            if msvcrt is None:
                return
            try:
                while not stop_evt.is_set():
                    if msvcrt.kbhit():
                        ch = msvcrt.getwch()  # unicode char
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
                    else:
                        time.sleep(0.05)
            except Exception:
                pass
    # ------------------------------------------

    with ui:
        threading.Thread(target=_key_reader, daemon=True, name="keys").start()

        single_files_provided = [Path(f) for f in args.url_files] if args.url_files else None
        all_work = _build_worklist_from_disk(
            args.url_dir, args.ae_url_dir, args.output_dir, single_files=single_files_provided
        )

        # If there’s nothing to do, exit gracefully (useful on Windows where the window may close)
        if not all_work:
            print("No URL work found (check -f/-u/-e paths).")
            runlog.close()
            return 0

        coord = _Coordinator(all_work)

        archive_path: Optional[Path] = args.archive
        archived_urls: set[str] = set()
        archive_lock = threading.Lock()
        if archive_path:
            archived_urls = set(read_archive(archive_path))

        cfg = _build_config(args)
        ytdl = YtDlpDownloader(cfg)
        aebn = AebnDownloader(cfg)

        def worker(slot: int, downloader_type: str) -> None:
            thread_name = f"dl-{downloader_type}-{slot+1}"
            threading.current_thread().name = thread_name

            while not stop_evt.is_set() and not abort_requested():
                if pause_evt.is_set():
                    time.sleep(0.1)
                    continue

                wf = coord.acquire()
                if not wf:
                    break

                successful_downloads_this_run = 0

                try:
                    for i, url in enumerate(list(wf.urls), start=0):  # url_index in file: 0-based
                        if stop_evt.is_set() or abort_requested():
                            break
                        if archive_path and url in archived_urls:
                            # still generate a FINISH entry so the counter is consistent
                            attempt_id = runlog.start(i, url)
                            runlog.finish(i, url, "Exists", "archive-hit")
                            continue

                        out_tpl = str(wf.out_dir / "%(title)s.%(ext)s")
                        wf.out_dir.mkdir(parents=True, exist_ok=True)

                        if is_aebn_url(url):
                            # AEBN path: wrap with START/FINISH logging but use existing downloader
                            runlog.start(i, url)
                            item = DownloadItem(
                                id=(slot * 10_000_000) + (i + 1),
                                url=url,
                                output_dir=wf.out_dir,
                                source=URLSource(file=wf.url_file, line_number=i + 1, original_url=url),
                                extra_ytdlp_args=[],
                                extra_aebn_args=[],
                            )
                            ok = False
                            events: Iterator = aebn.download(item)
                            last_status: Optional[str] = None
                            try:
                                for ev in events:
                                    try:
                                        ui.handle_event(ev)
                                    except Exception:
                                        pass
                                    if isinstance(ev, FinishEvent):
                                        res: DownloadResult = ev.result
                                        if res.status in (DownloadStatus.COMPLETED, DownloadStatus.ALREADY_EXISTS):
                                            ok = True
                                        last_status = res.status.value
                            except KeyboardInterrupt:
                                runlog.finish(i, url, "Internal Stop", "keyboard interrupt")
                                stop_evt.set()
                                break

                            if ok:
                                runlog.finish(i, url, "Finished DL")
                                successful_downloads_this_run += 1
                                if archive_path:
                                    with archive_lock:
                                        if url not in archived_urls:
                                            write_to_archive(archive_path, url)
                                            archived_urls.add(url)
                            else:
                                runlog.finish(i, url, "Bad URL", last_status or "aebn-dl failure")
                        else:
                            # yt-dlp path (parser-aware + tolerant of quiet success)
                            try:
                                status, note = run_single_ytdlp(
                                    logger=runlog,
                                    url=url,
                                    url_index=i,
                                    out_tpl=out_tpl,
                                    extra_args=None,
                                    retries=3,
                                )
                                if status in ("Finished DL", "Exists"):
                                    successful_downloads_this_run += 1
                                    if archive_path:
                                        with archive_lock:
                                            if url not in archived_urls:
                                                write_to_archive(archive_path, url)
                                                archived_urls.add(url)
                            except KeyboardInterrupt:
                                stop_evt.set()
                                break

                        try:
                            ui.pump()
                        except Exception:
                            pass

                except KeyboardInterrupt:
                    stop_evt.set()
                    break
                finally:
                    coord.release(wf, remaining_delta=-(successful_downloads_this_run))

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

    runlog.close()
    return 0


# -------------------- Legacy shims for tests ---------------------------------

def _is_snapshot_complete(snapshot: CountsSnapshot, *args, **kwargs) -> bool:
    """
    Completion rule (legacy): ignore per-file 'remaining'.
      - all URLs accounted for (completed+failed+already >= total_urls),
      - and no active or queued.
    """
    total_done = snapshot.completed + snapshot.failed + snapshot.already
    return (total_done >= snapshot.total_urls) and snapshot.active == 0 and snapshot.queued == 0


def _build_worklist(*args: Any, **kwargs: Any) -> List[_WorkFile]:
    """
    Compatibility wrapper expected by tests.

    Accepts:
      _build_worklist(_snap, main_url_dir, out_root)
      _build_worklist(_snap, main_url_dir, ae_url_dir, out_root)
      _build_worklist(main_url_dir, out_root)
      _build_worklist(main_url_dir, ae_url_dir, out_root)
      plus optional single_files=...

    Also tolerates odd legacy shapes like a single non-path argument (returns []).
    """
    single_files = kwargs.get("single_files")

    # Peel off optional leading snapshot
    if len(args) >= 1 and isinstance(args[0], CountsSnapshot):
        args = args[1:]

    # Tolerate single non-path arg (e.g., {'mp4'}) by returning empty work
    if len(args) == 1 and not isinstance(args[0], (str, bytes, PurePath)):
        return []

    # Normalize positional args into (main, ae, out)
    if len(args) == 2:
        main_url_dir = Path(args[0])
        ae_url_dir = Path(args[0])  # mirror main when AE dir not provided
        out_root = Path(args[1])
    elif len(args) >= 3:
        main_url_dir = Path(args[0])
        ae_url_dir = Path(args[1])
        out_root = Path(args[2])
    else:
        raise TypeError("_build_worklist requires (main_url_dir, out_root) or (main_url_dir, ae_url_dir, out_root)")

    return _build_worklist_from_disk(main_url_dir, ae_url_dir, out_root, single_files=single_files)


if __name__ == "__main__":
    raise SystemExit(main())
