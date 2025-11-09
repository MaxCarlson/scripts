#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Master downloader that coordinates multiple dlscript.py workers.

- Scans URL files under ./files/downloads/ae-stars and ./files/downloads/stars
- Runs up to -t workers (each runs dlscript.py on one URL file at a time)
- Assigns URL files at random; ensures exclusive assignment
- Enforces a per-assignment time limit (-T seconds; -1 disables)
- Tracks per-worker progress by reading dlscript NDJSON and renders a live dashboard
- Records finished URL files in a log so they are not reassigned
"""

from __future__ import annotations

import argparse
import json
import os
import random
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
import traceback
from pathlib import Path
from typing import List, Optional

# Import EnforcedArgumentParser with fallback
try:
    from argparse_enforcer import EnforcedArgumentParser
    ENFORCER_AVAILABLE = True
except ImportError:
    EnforcedArgumentParser = argparse.ArgumentParser
    ENFORCER_AVAILABLE = False

from .downloader import MAX_RESOLUTION_CHOICES
from .mp4_watcher import MP4Watcher, WatcherConfig, WatcherSnapshot

MP4_VALID_OPERATIONS = ("copy", "move")

# Use TermDash for robust in-place dashboard rendering
# We avoid TermDash here for maximal compatibility across shells; do manual frames


class ManagerLogger:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _write(self, msg: str) -> None:
        # Best-effort cross-process lock
        try:
            import msvcrt  # type: ignore
        except Exception:
            msvcrt = None  # type: ignore
        try:
            import fcntl  # type: ignore
        except Exception:
            fcntl = None  # type: ignore
        with self.path.open("a", encoding="utf-8") as f:
            try:
                if msvcrt and os.name == "nt":
                    msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1_000_000)
                elif fcntl and os.name != "nt":
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            except Exception:
                pass
            try:
                f.write(msg + "\n")
                f.flush()
            finally:
                try:
                    if msvcrt and os.name == "nt":
                        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1_000_000)
                    elif fcntl and os.name != "nt":
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass

    def info(self, msg: str) -> None:
        t = time.strftime("%H:%M:%S")
        self._write(f"{t}|INFO|{msg}")

    def error(self, msg: str) -> None:
        t = time.strftime("%H:%M:%S")
        self._write(f"{t}|ERROR|{msg}")


def _read_urls(path: Path) -> List[str]:
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    out: List[str] = []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if s.startswith("#") or s.startswith(";") or s.startswith("]"):
            continue
        out.append(s.split("  #", 1)[0].split("  ;", 1)[0].strip())
    # stable de-dup
    return list(dict.fromkeys(out))


def _human_bytes(b: Optional[float | int]) -> str:
    if b is None:
        return "?"
    v = float(b)
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    i = 0
    while v >= 1024.0 and i < len(units) - 1:
        v /= 1024.0
        i += 1
    return f"{v:.2f}{units[i]}"

def _human_short_bytes(b: Optional[int]) -> str:
    if b is None:
        return "?"
    v = float(b)
    g = v / (1024*1024*1024)
    if g >= 1.0:
        return f"{g:.1f}G"
    m = v / (1024*1024)
    return f"{m:.1f}M"


def _hms(elapsed_s: float) -> str:
    s = int(elapsed_s) % 60
    m = (int(elapsed_s) // 60) % 60
    h = int(elapsed_s) // 3600
    return f"{h:02d}:{m:02d}:{s:02d}"


def _watcher_bytes(value: Optional[int | float]) -> str:
    if not isinstance(value, (int, float)) or value < 0:
        return "0 B"
    if value < 1024:
        return f"{int(value)} B"
    units = ["KB", "MB", "GB", "TB", "PB"]
    size = float(value)
    for unit in units:
        size /= 1024.0
        if size < 1024.0:
            return f"{size:.2f} {unit}"
    return f"{size:.2f} EB"


def _watcher_rate(bps: Optional[float]) -> str:
    if not isinstance(bps, (int, float)) or bps <= 0:
        return "0 B/s"
    units = ["B/s", "KB/s", "MB/s", "GB/s", "TB/s"]
    value = float(bps)
    idx = 0
    while value >= 1024.0 and idx < len(units) - 1:
        value /= 1024.0
        idx += 1
    return f"{value:.2f} {units[idx]}"


def _watcher_duration(seconds: Optional[float]) -> str:
    if not isinstance(seconds, (int, float)) or seconds < 0:
        return "0:00:00.000"
    frac = float(seconds) - int(seconds)
    millis = int(frac * 1000)
    total = int(seconds)
    mins, secs = divmod(total, 60)
    hours, mins = divmod(mins, 60)
    return f"{hours:d}:{mins:02d}:{secs:02d}.{millis:03d}"


def _watcher_trigger_label(value: Optional[int]) -> str:
    if not isinstance(value, (int, float)) or value <= 0:
        return "disabled"
    gib = float(value) / (1024 ** 3)
    return f"{gib:.1f} GiB"


def _watcher_keep_source_label(config: WatcherConfig) -> str:
    label = "on" if config.keep_source else "off"
    if config.keep_source_locked:
        label += " (locked -K)"
    return label


def _render_screen(lines: List[str]) -> None:
    sys.stdout.write("\x1b[0m\x1b[2J\x1b[H")
    sys.stdout.write("\n".join(lines) + "\n")
    sys.stdout.flush()


def _render_watcher_panel(
    *,
    cols: int,
    watcher_enabled: bool,
    snapshot: Optional[WatcherSnapshot],
    quit_confirm: bool,
    manager_elapsed: float,
    total_downloaded_bytes: int,
) -> List[str]:
    lines: List[str] = []
    header = "MP4 Folder Synchroniser"
    if snapshot:
        header_state = "running" if snapshot.running else "idle"
        if snapshot.dry_run:
            header_state += " · dry-run"
        lines.append(f"{header} ({header_state})"[:cols])
    else:
        lines.append(header[:cols])

    lines.append(f"Manager elapsed: {_hms(manager_elapsed)}"[:cols])
    lines.append(f"Total downloaded: {_watcher_bytes(total_downloaded_bytes)}"[:cols])
    if snapshot:
        cfg = snapshot.config
        lines.append(f"Default op: {cfg.default_operation} | Keep source: {_watcher_keep_source_label(cfg)}"[:cols])
        max_label = cfg.max_files if cfg.max_files is not None else "unlimited"
        lines.append(f"Max files/run: {max_label} | Free trigger: {_watcher_trigger_label(cfg.free_space_trigger_bytes)}"[:cols])
        lines.append(f"Staged size trigger: {_watcher_trigger_label(cfg.total_size_trigger_bytes)}"[:cols])

    if not watcher_enabled:
        lines.append("Watcher disabled. Launch with --watcher to enable the cleaner."[:cols])
        lines.append("-" * min(cols, 100))
    elif snapshot:
        if snapshot.progress:
            lines.append(f"Elapsed: {_watcher_duration(snapshot.progress.get('elapsed'))}"[:cols])
            lines.append(f"Current folder: {snapshot.progress.get('current_folder') or '-'}"[:cols])
            lines.append(f"Current file: {snapshot.progress.get('current_file') or '-'}"[:cols])
            lines.append(f"Files processed: {snapshot.progress.get('processed_files', 0)} / {snapshot.progress.get('total_files', 0)}"[:cols])
            lines.append(f"Copied (no collision): {snapshot.progress.get('copied_without_collision', 0)} | Collisions: {snapshot.progress.get('collisions', 0)} (replaced: {snapshot.progress.get('replaced_dest', 0)}, kept: {snapshot.progress.get('kept_dest', 0)})"[:cols])
            total_prog_pct = snapshot.progress.get('total_percent', 0.0)
            lines.append(f"Total progress: {_watcher_bytes(snapshot.progress.get('processed_bytes', 0))} / {_watcher_bytes(snapshot.progress.get('total_bytes', 0))} ({total_prog_pct:.1f}%)"[:cols])
            lines.append("")
            lines.append("Transfer Progress")
            if snapshot.progress.get('current_file_size'):
                file_prog_pct = snapshot.progress.get('file_percent', 0.0)
                rate = _watcher_rate(snapshot.progress.get('current_speed', 0.0))
                lines.append(f"File progress: {_watcher_bytes(snapshot.progress.get('current_file_done', 0))} / {_watcher_bytes(snapshot.progress.get('current_file_size', 0))} ({file_prog_pct:.1f}%) @ {rate}"[:cols])

        pending_actions = snapshot.plan_actions or (snapshot.last_result.planned_actions if snapshot.last_result else None)
        pending_bytes = snapshot.plan_bytes or (snapshot.last_result.plan_bytes if snapshot.last_result else None)
        if pending_actions is not None or pending_bytes is not None:
            lines.append(
                f"Potential transfers: {pending_actions or 0} files | {_watcher_bytes(pending_bytes or 0)}"
            )

        lines.append(f"Bytes since last run: {_watcher_bytes(snapshot.bytes_since_last or 0)}"[:cols])
        lines.append("")
        lines.append("Recent Activity")
        if snapshot.progress and snapshot.progress.get('recent_logs'):
            for log in snapshot.progress.get('recent_logs'):
                lines.append(log[:cols])
        else:
            lines.append("(no events yet)")
    else:
        lines.append("(no snapshot yet)")


    lines.append("-" * min(cols, 100))
    if quit_confirm:
        lines.append("Press Y to quit, N to cancel"[:cols])
    else:
        lines.append("Keys: w=back, c=start cleaner, s=scan (dry-run), o=toggle copy/move, k=set max-files, f=set free GiB, q=quit"[:cols])

    return lines


def _prompt_text(prompt: str) -> Optional[str]:
    try:
        return input(f"\n{prompt.strip()} ").strip()
    except EOFError:
        return None


def _pause_process(proc: subprocess.Popen) -> bool:
    """Pause a process. Returns True if successful."""
    if not proc or proc.poll() is not None:
        return False

    try:
        if os.name == 'nt':
            # Windows: use psutil if available, otherwise try native API
            try:
                import psutil
                p = psutil.Process(proc.pid)
                p.suspend()
                return True
            except ImportError:
                # Fallback: use Windows API via ctypes
                try:
                    import ctypes
                    from ctypes import wintypes
                    kernel32 = ctypes.windll.kernel32
                    handle = kernel32.OpenProcess(0x0200, False, proc.pid)  # PROCESS_SUSPEND_RESUME
                    if handle:
                        # Get thread IDs and suspend them
                        import ctypes.wintypes
                        class THREADENTRY32(ctypes.Structure):
                            _fields_ = [
                                ("dwSize", wintypes.DWORD),
                                ("cntUsage", wintypes.DWORD),
                                ("th32ThreadID", wintypes.DWORD),
                                ("th32OwnerProcessID", wintypes.DWORD),
                                ("tpBasePri", wintypes.LONG),
                                ("tpDeltaPri", wintypes.LONG),
                                ("dwFlags", wintypes.DWORD)
                            ]

                        # This is complex, so let's use a simpler approach
                        kernel32.CloseHandle(handle)
                        return False
                except Exception:
                    return False
        else:
            # Unix: use SIGSTOP
            os.kill(proc.pid, signal.SIGSTOP)
            return True
    except Exception:
        return False
    return False


def _resume_process(proc: subprocess.Popen) -> bool:
    """Resume a paused process. Returns True if successful."""
    if not proc or proc.poll() is not None:
        return False

    try:
        if os.name == 'nt':
            # Windows: use psutil if available
            try:
                import psutil
                p = psutil.Process(proc.pid)
                p.resume()
                return True
            except ImportError:
                return False
        else:
            # Unix: use SIGCONT
            os.kill(proc.pid, signal.SIGCONT)
            return True
    except Exception:
        return False
    return False


@dataclass
class WorkerState:
    slot: int
    proc: Optional[subprocess.Popen] = None
    reader: Optional[threading.Thread] = None
    reader_stop: threading.Event = field(default_factory=threading.Event)
    urlfile: Optional[Path] = None
    url_count: int = 0
    url_index: Optional[int] = None
    url_current: Optional[str] = None
    downloader: Optional[str] = None
    percent: Optional[float] = None
    speed_bps: Optional[float] = None
    eta_s: Optional[float] = None
    downloaded_bytes: Optional[int] = None
    total_bytes: Optional[int] = None
    assign_t0: float = 0.0
    url_t0: float = 0.0
    last_event_time: float = 0.0
    destination: Optional[str] = None
    rc: Optional[int] = None
    cap_mibs: Optional[float] = None
    last_throttle_t: float = 0.0
    last_already: bool = False
    overlay_msg: Optional[str] = None
    overlay_since: float = 0.0
    ndjson_buf: list[str] = field(default_factory=list)
    prog_log_path: Optional[Path] = None
    is_paused: bool = False
    paused_speed_bps: Optional[float] = None


def _gather_from_roots(roots: List[Path], finished_log: Path, priority_files: Optional[List[str]] = None) -> tuple[List[Path], List[Path]]:
    pool: List[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*.txt"):
            if p.is_file():
                pool.append(p)
    finished: set[str] = set()
    if finished_log.exists():
        try:
            finished = set(x.strip() for x in finished_log.read_text(encoding="utf-8").splitlines() if x.strip())
        except Exception:
            finished = set()

    available_pool = [p for p in pool if str(p.resolve()) not in finished]

    if not priority_files:
        return available_pool, []

    priority_paths = []
    for pf in priority_files:
        p = Path(pf).expanduser().resolve()
        if p.exists() and p.is_file() and str(p) not in finished:
            priority_paths.append(p)

    regular_pool = [p for p in available_pool if p.resolve() not in [pp.resolve() for pp in priority_paths]]

    return regular_pool, priority_paths


def _start_worker(
    slot: int,
    urlfile: Path,
    max_rate: float,
    quiet: bool,
    archive_dir: Optional[Path],
    log_dir: Path,
    cap_mibs: Optional[float],
    proxy_dl_location: Optional[str] = None,
    max_resolution: Optional[str] = None,
) -> subprocess.Popen:
    cmd = [
        sys.executable,
        str(Path(__file__).parent / "downloader.py"),
        "-f",
        str(urlfile),
        "-U",
        str(max_rate),
    ]
    # Dedicated program log per worker to avoid cross-process contention
    log_name = Path(log_dir) / f"ytaedler-worker-{slot:02d}.log"
    cmd += ["-g", str(log_name)]
    if isinstance(cap_mibs, (int, float)) and cap_mibs and cap_mibs > 0:
        cmd += ["-X", str(cap_mibs)]
    if archive_dir:
        cmd += ["-a", str(archive_dir)]
    if proxy_dl_location:
        cmd += ["--proxy-dl-location", str(proxy_dl_location)]
    if max_resolution:
        cmd += ["--max-resolution", max_resolution]
    if quiet:
        cmd.append("-q")
    # line buffered
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=0,
    )


def make_parser() -> argparse.ArgumentParser:
    p = EnforcedArgumentParser(
        prog="dlmanager.py",
        description="Master downloader that coordinates multiple dlscript.py workers",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("-t", "--threads", type=int, default=2, help="Number of concurrent dlscript workers")
    p.add_argument("-l", "--time-limit", type=int, default=-1, help="Max seconds a worker holds a urlfile (-1 for unlimited)")
    p.add_argument("-u", "--max-ndjson-rate", type=float, default=5.0, help="Max progress events/sec printed by workers (-1 unlimited)")
    p.add_argument("-q", "--quiet", action="store_true", help="Pass -q to workers")
    p.add_argument("-p", "--priority-files", action="append", help="URL files to prioritize (can be specified multiple times)")
    p.add_argument("-P", "--proxy-dl-location", default=None, help="Download into this root (per url file subfolder) while checking duplicates in the canonical location")
    p.add_argument("-s", "--stars-dir", default="./files/downloads/stars", help="Folder of yt-dlp url files")
    p.add_argument("-d", "--aebn-dir", default="./files/downloads/ae-stars", help="Folder of AEBN url files")
    p.add_argument("-f", "--finished-log", default="./logs/finished_urlfiles.txt", help="Path to record completed url files")
    p.add_argument("-r", "--refresh-hz", type=float, default=5.0, help="UI refresh rate")
    p.add_argument("-e", "--exit-at-time", type=int, default=-1, help="Exit the manager after N seconds (<=0 disables)")
    p.add_argument("-a", "--archive", type=str, default=None, help="Archive folder to store per-urlfile status files")
    p.add_argument("-g", "--log-dir", type=str, default="./logs", help="Directory for all logs (manager, workers, watcher)")
    p.add_argument("-x", "--max-process-dl-speed", type=float, default=None, help="Per-worker max download speed (MiB/s)")
    p.add_argument("-v", "--max-resolution", choices=MAX_RESOLUTION_CHOICES, default=None, help="Highest video resolution workers should request")
    p.add_argument("-z", "--max-total-dl-speed", type=float, default=None, help="Global max download speed across all workers (MiB/s)")
    p.add_argument("-b", "--show-bars", action="store_true", help="Show an ASCII progress bar per worker")
    p.add_argument("-w", "--enable-mp4-watcher", action="store_true", help="Enable MP4 watcher integration")
    p.add_argument(
        "-o",
        "--mp4-operation",
        choices=sorted(MP4_VALID_OPERATIONS),
        default="move",
        help="Default MP4 watcher operation to apply when syncing staged MP4 files",
    )
    p.add_argument(
        "-k",
        "--mp4-max-files",
        type=int,
        default=None,
        help="Cap how many MP4 files the watcher processes per run (omit for unlimited)",
    )
    p.add_argument(
        "-G",
        "--mp4-trigger-total-gb",
        type=float,
        default=None,
        help="Automatically trigger the watcher when total size of complete MP4 files in proxy location exceeds this GiB threshold (off by default)",
    )
    p.add_argument(
        "-F",
        "--mp4-trigger-free-gb",
        type=float,
        default=75.0,
        help="Automatically trigger the watcher when staging free space drops below this GiB threshold",
    )
    p.add_argument(
        "-K",
        "--mp4-keep-source",
        action="store_true",
        help="Force keep source files after syncing (overrides operation mode to never delete source)",
    )
    return p


def main() -> int:
    args = make_parser().parse_args()
    t0 = time.time()
    deadline = (t0 + args.exit_at_time) if (args.exit_at_time and args.exit_at_time>0) else None
    stars_dir = Path(args.stars_dir).expanduser().resolve()
    aebn_dir = Path(args.aebn_dir).expanduser().resolve()
    # Logs - all logs go in log_dir with timestamps
    log_dir = Path(args.log_dir).expanduser().resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    manager_log_path = log_dir / f"dlmanager-{ts}-{os.getpid()}.log"
    mlog = ManagerLogger(manager_log_path)

    archive_dir: Optional[Path] = Path(args.archive).expanduser().resolve() if args.archive else None
    if archive_dir:
        archive_dir.mkdir(parents=True, exist_ok=True)
    finished_log = Path(args.finished_log).expanduser().resolve()
    finished_log.parent.mkdir(parents=True, exist_ok=True)

    watcher: Optional[MP4Watcher] = None
    if args.enable_mp4_watcher:
        staging_root = Path(args.proxy_dl_location).expanduser().resolve() if args.proxy_dl_location else None
        destination_root = stars_dir
        watcher_log_path = log_dir / f"mp4_watcher-{ts}.log"
        total_size_trigger_bytes = (
            int(args.mp4_trigger_total_gb * (1024 ** 3))
            if isinstance(args.mp4_trigger_total_gb, (int, float)) and args.mp4_trigger_total_gb > 0
            else None
        )
        free_space_trigger_bytes = (
            int(args.mp4_trigger_free_gb * (1024 ** 3))
            if isinstance(args.mp4_trigger_free_gb, (int, float)) and args.mp4_trigger_free_gb > 0
            else None
        )
        max_files = args.mp4_max_files if isinstance(args.mp4_max_files, int) and args.mp4_max_files > 0 else None

        # Determine keep_source based on operation mode
        # move = delete source (keep_source=False), copy = keep source (keep_source=True)
        # But -K flag can override to always keep source
        keep_source_locked = bool(args.mp4_keep_source)
        if keep_source_locked:
            keep_source = True  # -K flag overrides
        else:
            keep_source = (args.mp4_operation == "copy")  # copy mode keeps source, move mode deletes

        if staging_root is None:
            mlog.error("MP4 watcher requested but --proxy-dl-location was not provided; watcher disabled")
        else:
            config = WatcherConfig(
                staging_root=staging_root,
                destination_root=destination_root,
                log_path=watcher_log_path,
                default_operation=args.mp4_operation,
                max_files=max_files,
                keep_source=keep_source,
                keep_source_locked=keep_source_locked,
                total_size_trigger_bytes=total_size_trigger_bytes,
                free_space_trigger_bytes=free_space_trigger_bytes,
            )
            watcher = MP4Watcher(config=config, enabled=True)
            if watcher.is_enabled():
                mlog.info(
                    f"MP4 watcher enabled: staging={staging_root} destination={destination_root} operation={args.mp4_operation}"
                )
            else:
                mlog.error(
                    f"MP4 watcher initialisation failed; staging={staging_root} destination={destination_root} "
                    f"exists={staging_root.exists()}/{destination_root.exists()}"
                )
                watcher = MP4Watcher(config=config, enabled=False)
    elif args.mp4_operation or args.mp4_max_files or args.mp4_trigger_total_gb or args.mp4_trigger_free_gb:
        mlog.info("MP4 watcher configuration ignored because --enable-mp4-watcher was not set")

    roots: List[Path] = [stars_dir, aebn_dir]
    pool, priority_pool = _gather_from_roots(roots, finished_log, args.priority_files)
    if not pool and not priority_pool:
        # Fallback to test dirs if primary roots are empty
        repo_root = Path(__file__).resolve().parent.parent
        test_stars = (repo_root / "test" / "files" / "downloads" / "stars").resolve()
        test_aebn = (repo_root / "test" / "files" / "downloads" / "ae-stars").resolve()
        roots = [test_stars, test_aebn]
        pool, priority_pool = _gather_from_roots(roots, finished_log, args.priority_files)
    random.shuffle(pool)
    random.shuffle(priority_pool)
    active: set[str] = set()

    workers: List[WorkerState] = [WorkerState(slot=i) for i in range(1, args.threads + 1)]
    stop = threading.Event()
    mlog.info(f"Start manager threads={args.threads} time_limit={args.time_limit} refresh_hz={args.refresh_hz} exit_at_time={args.exit_at_time} archive_dir={archive_dir}")
    mlog.info(f"Log dir: {log_dir} | Manager log: {manager_log_path}")
    if args.priority_files:
        mlog.info(f"Priority files: {len(priority_pool)} files specified: {[str(p) for p in priority_pool]}")
    mlog.info(f"Regular pool: {len(pool)} files | Priority pool: {len(priority_pool)} files")

    # Totals tracking
    total_completed_bytes = 0
    total_processed_urls = 0
    total_completed_urls = 0
    total_started_urls = 0

    def _reader(ws: WorkerState):
        f = ws.proc.stdout  # type: ignore
        try:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                # Buffer NDJSON for verbose view
                try:
                    ws.ndjson_buf.append(line)
                    if len(ws.ndjson_buf) > 400:
                        ws.ndjson_buf = ws.ndjson_buf[-200:]
                except Exception:
                    pass
                try:
                    evt = json.loads(line)
                except Exception:
                    continue
                ws.last_event_time = time.time()
                ev = evt.get("event")
                if ev == "start":
                    ws.url_index = evt.get("url_index")
                    ws.url_current = evt.get("url")
                    ws.downloader = evt.get("downloader")
                    # Reset progress state on new URL
                    ws.percent = None
                    ws.speed_bps = None
                    ws.eta_s = None
                    ws.downloaded_bytes = None
                    ws.total_bytes = None
                    ws.url_t0 = time.time()
                    # Clear overlay upon new activity
                    ws.overlay_msg = None
                    ws.overlay_since = 0.0
                    nonlocal total_started_urls
                    total_started_urls += 1
                    mlog.info(f"[{ws.slot:02d}] START idx={ws.url_index} url={ws.url_current}")
                elif ev == "destination":
                    ws.destination = evt.get("path")
                    mlog.info(f"[{ws.slot:02d}] DEST path={ws.destination}")
                elif ev == "already":
                    # Mark that this URL was already downloaded
                    ws.last_already = True
                elif ev == "progress":
                    # Clamp and normalize to avoid >100% and >total displays
                    try:
                        dl = evt.get("downloaded")
                        tot = evt.get("total")
                        sp = evt.get("speed_bps")
                        eta = evt.get("eta_s")
                        pct = evt.get("percent")
                        if isinstance(dl, int) and isinstance(tot, int) and tot and tot > 0:
                            show_dl = min(dl, tot)
                            ws.downloaded_bytes = show_dl
                            ws.total_bytes = tot
                            pct_calc = 100.0 * (float(show_dl) / float(tot))
                            ws.percent = min(99.9, pct_calc)
                        else:
                            # Clamp percentage even when bytes unavailable
                            if isinstance(pct, (int, float)):
                                ws.percent = min(99.9, max(0.0, float(pct)))
                            # Clamp downloaded bytes to total if both provided
                            if isinstance(dl, int) and isinstance(tot, int) and tot > 0:
                                ws.downloaded_bytes = min(dl, tot)
                                ws.total_bytes = tot
                            else:
                                # Keep values as-is only if no total to compare against
                                ws.downloaded_bytes = dl if isinstance(dl, int) else ws.downloaded_bytes
                                ws.total_bytes = tot if isinstance(tot, int) else ws.total_bytes
                        ws.speed_bps = float(sp) if isinstance(sp, (int, float)) else ws.speed_bps
                        # eta may be 0 or negative near completion
                        ws.eta_s = float(eta) if isinstance(eta, (int, float)) else ws.eta_s
                        # Any progress clears overlay
                        ws.overlay_msg = None
                        ws.overlay_since = 0.0
                    except Exception:
                        pass
                elif ev == "finish":
                    mlog.info(f"[{ws.slot:02d}] FINISH rc={evt.get('rc')} idx={ws.url_index}")
                    # Update per-URL counters here (process continues running)
                    try:
                        rc_v = int(evt.get('rc')) if evt.get('rc') is not None else None
                    except Exception:
                        rc_v = None
                    # Count this URL as processed
                    nonlocal total_processed_urls, total_completed_urls, total_completed_bytes
                    total_processed_urls += 1
                    if rc_v == 0:
                        total_completed_urls += 1
                        if isinstance(ws.downloaded_bytes, int):
                            total_completed_bytes += ws.downloaded_bytes
                    # Build overlay message until next start/progress
                    status = "FINISHED_DL" if rc_v == 0 and not ws.last_already else ("DUPLICATE" if rc_v == 0 and ws.last_already else "BAD_URL")
                    ws.last_already = False
                    # Colorize status
                    color = "\x1b[32m" if status == "FINISHED_DL" else ("\x1b[33m" if status == "DUPLICATE" else "\x1b[31m")
                    reset = "\x1b[0m"
                    elapsed_url = _hms(time.time() - (ws.url_t0 or ws.assign_t0))
                    name = ws.url_current or ""
                    ws.overlay_msg = f"URL {ws.url_index or 0} Finished Status {color}{status}{reset} {elapsed_url} {name}"
                    ws.overlay_since = time.time()
                    # Reset progress so stale >100% values don’t linger
                    ws.percent = None
                    ws.speed_bps = None
                    ws.eta_s = None
                    ws.downloaded_bytes = None
                    ws.total_bytes = None
                elif ev == "aborted":
                    mlog.info(f"[{ws.slot:02d}] ABORT reason={evt.get('reason')}")
                    ws.overlay_msg = f"URL {ws.url_index or 0} Finished Status \x1b[35mABORTED\x1b[0m 00:00:00 {ws.url_current or ''}"
                    ws.overlay_since = time.time()
                elif ev == "stalled":
                    mlog.info(f"[{ws.slot:02d}] STALLED stall_seconds={evt.get('stall_seconds')}")
                    ws.overlay_msg = f"URL {ws.url_index or 0} Finished Status \x1b[31mSTALLED\x1b[0m 00:00:00 {ws.url_current or ''}"
                    ws.overlay_since = time.time()
                elif ev == "deadline":
                    mlog.info(f"[{ws.slot:02d}] DEADLINE idx={ws.url_index}")
                    ws.overlay_msg = f"URL {ws.url_index or 0} Finished Status \x1b[35mDEADLINE\x1b[0m 00:00:00 {ws.url_current or ''}"
                    ws.overlay_since = time.time()
                if ws.reader_stop.is_set():
                    break
        except Exception as e:
            mlog.error(f"reader exception slot={ws.slot}: {e}\n{traceback.format_exc()}")

    def _assign(ws: WorkerState) -> bool:
        nonlocal pool, priority_pool
        # Filter out finished from current pools on each assignment
        finished: set[str] = set()
        if finished_log.exists():
            try:
                finished = set(x.strip() for x in finished_log.read_text(encoding="utf-8").splitlines() if x.strip())
            except Exception:
                finished = set()

        # Try priority files first
        priority_avail = [p for p in priority_pool if str(p.resolve()) not in active and str(p.resolve()) not in finished]
        if priority_avail:
            urlfile = random.choice(priority_avail)
            priority_pool.remove(urlfile)
            mlog.info(f"[{ws.slot:02d}] ASSIGN PRIORITY {urlfile}")
        else:
            # Fall back to regular pool
            avail = [p for p in pool if str(p.resolve()) not in active and str(p.resolve()) not in finished]
            if not avail:
                return False
            urlfile = random.choice(avail)
            mlog.info(f"[{ws.slot:02d}] ASSIGN {urlfile}")

        active.add(str(urlfile.resolve()))
        ws.urlfile = urlfile
        ws.url_count = len(_read_urls(urlfile))
        # If archive indicates completion, skip assignment
        if archive_dir and ws.url_count > 0:
            prefix = "ae" if ("ae-stars" in str(urlfile.parent)) else "yt"
            arch = archive_dir / f"{prefix}-{urlfile.stem}.txt"
            if arch.exists():
                try:
                    statuses = arch.read_text(encoding="utf-8").splitlines()
                except Exception:
                    statuses = []
                done = sum(1 for s in statuses if s.strip())
                if done >= ws.url_count:
                    # mark finished and choose another
                    try:
                        with finished_log.open("a", encoding="utf-8") as f:
                            f.write(str(urlfile.resolve()) + "\n")
                    except Exception:
                        pass
                    active.discard(str(urlfile.resolve()))
                    mlog.info(f"[{ws.slot:02d}] SKIP finished {urlfile}")
                    return _assign(ws)
        ws.percent = ws.speed_bps = ws.eta_s = None
        ws.url_index = None
        ws.url_current = None
        ws.destination = None
        ws.assign_t0 = time.time()
        ws.rc = None
        ws.cap_mibs = float(args.max_process_dl_speed) if isinstance(args.max_process_dl_speed, (int, float)) and args.max_process_dl_speed and args.max_process_dl_speed > 0 else None
        # Remember program log path for this worker
        try:
            ws.prog_log_path = (Path(log_dir) / f"ytaedler-worker-{ws.slot:02d}.log").resolve()
        except Exception:
            ws.prog_log_path = None
        ws.proc = _start_worker(ws.slot, urlfile, args.max_ndjson_rate, args.quiet, archive_dir, log_dir, ws.cap_mibs, args.proxy_dl_location, args.max_resolution)
        ws.reader_stop.clear()
        ws.reader = threading.Thread(target=_reader, args=(ws,), daemon=True)
        ws.reader.start()
        return True

    def _requeue(ws: WorkerState, finished: bool, reason: str):
        # Cleanup process
        if ws.proc and ws.proc.poll() is None:
            # Resume if paused before terminating
            if ws.is_paused:
                _resume_process(ws.proc)
                ws.is_paused = False
            try:
                ws.proc.terminate()
            except Exception:
                pass
            try:
                ws.proc.wait(timeout=2)
            except Exception:
                pass
        ws.reader_stop.set()
        if ws.reader:
            try:
                ws.reader.join(timeout=1)
            except Exception:
                pass
        if ws.urlfile is not None:
            key = str(ws.urlfile.resolve())
            active.discard(key)
            if finished:
                try:
                    with finished_log.open("a", encoding="utf-8") as f:
                        f.write(key + "\n")
                except Exception:
                    pass
        mlog.info(f"[{ws.slot:02d}] REQUEUE finished={finished} reason={reason}")
        ws.proc = None
        ws.urlfile = None

    # Helpers for total throttle
    def _current_speed_mib() -> float:
        return sum(float(w.speed_bps) for w in workers if isinstance(w.speed_bps, (int, float)) and not w.is_paused) / (1024*1024)

    def _can_assign_more() -> bool:
        if not isinstance(args.max_total_dl_speed, (int, float)) or not args.max_total_dl_speed or args.max_total_dl_speed <= 0:
            return True
        cur = _current_speed_mib()
        est_add = float(args.max_process_dl_speed) if isinstance(args.max_process_dl_speed, (int, float)) and args.max_process_dl_speed and args.max_process_dl_speed > 0 else 0.0
        return (cur + est_add) <= float(args.max_total_dl_speed)

    # Initial fill
    for ws in workers:
        if not _can_assign_more():
            mlog.info("Admission control: delaying assignment due to max-total-dl-speed")
            break
        if not _assign(ws):
            break

    # UI loop
    refresh_dt = 1.0 / max(1.0, float(args.refresh_hz))
    last_lines = 0
    # Interactive verbose pane state: 0=off, 1=NDJSON, 2=Program log
    verbose_mode = 0
    verbose_slot = 1
    selected_worker_slot = workers[0].slot if workers else 1
    active_panel = "downloads"
    # Pause/quit state
    paused = False
    quit_confirm = False
    try:
        while not stop.is_set():
            if deadline and time.time() >= deadline:
                stop.set()
                break
            watcher_enabled = bool(watcher and watcher.is_enabled())
            if watcher:
                auto_reason = watcher.update_download_progress(total_completed_bytes)
                if auto_reason:
                    mlog.info(f"MP4 watcher auto-triggered: {auto_reason}")
                watcher_status = watcher.snapshot()
            else:
                watcher_status = None
            # Dynamic total throttle: proportional caps across yt-dlp workers
            now_check = time.time()
            if isinstance(args.max_total_dl_speed, (int, float)) and args.max_total_dl_speed and args.max_total_dl_speed > 0:
                cap = float(args.max_total_dl_speed)
                total_mib = sum(float(w.speed_bps) for w in workers if isinstance(w.speed_bps, (int, float)) and not w.is_paused) / (1024*1024)
                elig = [w for w in workers if w.proc and w.downloader == 'yt-dlp' and isinstance(w.speed_bps, (int, float)) and w.speed_bps and w.speed_bps > 0 and not w.is_paused]
                elig_sum = sum((float(w.speed_bps)/(1024*1024)) for w in elig)
                non_elig_mib = max(0.0, total_mib - elig_sum)
                budget = max(0.0, cap - non_elig_mib)
                if total_mib > cap * 1.05 and elig:
                    # Proportional scaling to stay under budget
                    if elig_sum <= 0.0:
                        target_each = budget / len(elig) if budget > 0 else 0.5
                        targets = {w: target_each for w in elig}
                    else:
                        scale = budget / elig_sum if elig_sum > 0 else 0.0
                        targets = {w: max(0.25, (float(w.speed_bps)/(1024*1024)) * scale) for w in elig}
                    for w, tgt in targets.items():
                        # Respect per-process cap if set
                        if isinstance(args.max_process_dl_speed, (int, float)) and args.max_process_dl_speed and args.max_process_dl_speed > 0:
                            tgt = min(tgt, float(args.max_process_dl_speed))
                        # Change only if significant and cooldown passed
                        if (w.cap_mibs is None or abs(tgt - w.cap_mibs) > 0.25) and (now_check - w.last_throttle_t) > 3.0:
                            w.last_throttle_t = now_check
                            mlog.info(f"[{w.slot:02d}] THROTTLE total={total_mib:.2f}MiB/s -> cap {tgt:.2f}MiB/s (budget {budget:.2f})")
                            try:
                                if w.proc and w.proc.poll() is None:
                                    w.proc.terminate()
                                    w.proc.wait(timeout=2)
                            except Exception:
                                pass
                            if w.urlfile:
                                w.cap_mibs = max(0.25, tgt)
                                w.reader_stop.set()
                                if w.reader:
                                    try:
                                        w.reader.join(timeout=1)
                                    except Exception:
                                        pass
                                w.reader_stop.clear()
                                try:
                                    w.prog_log_path = (Path(log_dir) / f"ytaedler-worker-{w.slot:02d}.log").resolve()
                                except Exception:
                                    w.prog_log_path = None
                                w.proc = _start_worker(w.slot, w.urlfile, args.max_ndjson_rate, args.quiet, archive_dir, log_dir, w.cap_mibs, args.proxy_dl_location, args.max_resolution)
                                w.reader = threading.Thread(target=_reader, args=(w,), daemon=True)
                                w.reader.start()
                elif total_mib < cap * 0.60:
                    # Gently increase caps back toward per-process cap (if any)
                    for w in elig:
                        if w.cap_mibs and (now_check - w.last_throttle_t) > 5.0:
                            target = float(args.max_process_dl_speed) if isinstance(args.max_process_dl_speed, (int, float)) and args.max_process_dl_speed and args.max_process_dl_speed > 0 else None
                            new_cap = w.cap_mibs * 1.2
                            if target:
                                new_cap = min(new_cap, target)
                            if new_cap > w.cap_mibs + 0.25:
                                w.last_throttle_t = now_check
                                mlog.info(f"[{w.slot:02d}] UNTHROTTLE total={total_mib:.2f}MiB/s -> cap {new_cap:.2f}MiB/s")
                                try:
                                    if w.proc and w.proc.poll() is None:
                                        w.proc.terminate()
                                        w.proc.wait(timeout=2)
                                except Exception:
                                    pass
                                if w.urlfile:
                                    w.cap_mibs = new_cap
                                    w.reader_stop.set()
                                    if w.reader:
                                        try:
                                            w.reader.join(timeout=1)
                                        except Exception:
                                            pass
                                    w.reader_stop.clear()
                                    try:
                                        w.prog_log_path = (Path(log_dir) / f"ytaedler-worker-{w.slot:02d}.log").resolve()
                                    except Exception:
                                        w.prog_log_path = None
                                    w.proc = _start_worker(w.slot, w.urlfile, args.max_ndjson_rate, args.quiet, archive_dir, log_dir, w.cap_mibs, args.proxy_dl_location, args.max_resolution)
                                    w.reader = threading.Thread(target=_reader, args=(w,), daemon=True)
                                    w.reader.start()
            # Check time limit and exits
            for ws in workers:
                if not ws.proc:
                    continue
                # time limit
                if args.time_limit is not None and args.time_limit > 0:
                    if (time.time() - ws.assign_t0) > args.time_limit:
                        _requeue(ws, finished=False, reason="time_limit")
                        if not paused:
                            _assign(ws)
                        continue
                # exit
                rc = ws.proc.poll()
                if rc is not None:
                    ws.rc = rc
                    finished = (rc == 0)
                    _requeue(ws, finished=finished, reason=f"exit rc={rc}")
                    # Assign a new one if available (only if not paused)
                    if not paused:
                        _assign(ws)

            # Build frame lines and redraw whole screen
            try:
                cols = os.get_terminal_size().columns
            except OSError:
                cols = 80

            lines: List[str] = []

            if active_panel == "watcher":
                manager_elapsed = time.time() - t0
                total_completed_bytes = sum(ws.downloaded_bytes or 0 for ws in workers if ws.rc == 0)
                lines = _render_watcher_panel(
                    cols=cols,
                    watcher_enabled=watcher_enabled,
                    snapshot=watcher_status,
                    quit_confirm=quit_confirm,
                    manager_elapsed=manager_elapsed,
                    total_downloaded_bytes=total_completed_bytes,
                )
                _render_screen(lines)
            else:
                # Downloads panel
                active_workers = sum(1 for w in workers if w.proc)
                current_regular, current_priority = _gather_from_roots(roots, finished_log, args.priority_files)
                total_available = len([p for p in current_regular if str(p.resolve()) not in active]) + len([p for p in current_priority if str(p.resolve()) not in active])
                pause_status = " [PAUSED]" if paused else ""
                quit_status = " [Press Y to confirm quit]" if quit_confirm else ""
                header = f"DL Manager{pause_status}{quit_status}  |  threads={args.threads}  active={active_workers}  pool={total_available}  time_limit={args.time_limit}"
                lines.append(header[:cols])
                total_speed_bps = sum(float(w.speed_bps) for w in workers if isinstance(w.speed_bps, (int, float)) and not w.is_paused)
                total_speed_mib = total_speed_bps / (1024 * 1024) if total_speed_bps else 0.0
                inprog_bytes = sum(int(w.downloaded_bytes) for w in workers if isinstance(w.downloaded_bytes, int))
                agg_bytes = total_completed_bytes + inprog_bytes
                avg_mib_s = (agg_bytes / max(1.0, (time.time() - t0))) / (1024*1024)
                lines.append(f"Totals: speed={total_speed_mib:.2f}MiB/s  avg={avg_mib_s:.2f}MiB/s  downloaded={(agg_bytes/1048576):.1f}MiB  urls: started={total_started_urls} processed={total_processed_urls} completed={total_completed_urls}"[:cols])
                lines.append("-" * min(cols, 100))
                now = time.time()

                def col(text: str, width: int) -> str:
                    return (text[:width]).ljust(width)

                # Build quartiles for color-coding speeds
                speeds = [float(w.speed_bps) for w in workers if isinstance(w.speed_bps, (int, float)) and w.speed_bps and w.speed_bps > 0]
                speeds.sort()
                def _quantile(xs, q):
                    if not xs:
                        return None
                    idx = int(round((len(xs)-1) * q))
                    return xs[max(0, min(len(xs)-1, idx))]
                q1 = _quantile(speeds, 0.25)
                q2 = _quantile(speeds, 0.50)
                q3 = _quantile(speeds, 0.75)
                def speed_color_prefix(sp_bps: Optional[float]) -> str:
                    try:
                        v = float(sp_bps)
                    except Exception:
                        return "\x1b[37m"
                    if not speeds or q1 is None or q2 is None or q3 is None:
                        return "\x1b[37m"
                    if v <= q1:
                        return "\x1b[31m"  # red
                    if v <= q2:
                        return "\x1b[33m"  # yellow
                    if v <= q3:
                        return "\x1b[32m"  # green
                    return "\x1b[36m"      # cyan

                def make_bar(pct: Optional[float], width: int, color_prefix: str = "") -> str:
                    try:
                        p = float(pct)
                    except Exception:
                        p = -1
                    inner = max(0, width-2)
                    if p < 0:
                        return "[" + ("." * inner) + "]"
                    p = max(0.0, min(100.0, p))
                    filled = int(inner * (p/100.0))
                    reset = "\x1b[0m"
                    if color_prefix:
                        return "[" + (f"{color_prefix}" + ("=" * filled) + f"{reset}") + ("." * (inner - filled)) + "]"
                    else:
                        return "[" + ("=" * filled) + ("." * (inner - filled)) + "]"

                for ws in workers:
                    name = ws.urlfile.name if (ws.urlfile) else "idle"
                    url_idx = f"URL {ws.url_index or 0}/{ws.url_count or 0}"
                    elapsed = _hms(now - ws.assign_t0) if ws.urlfile else "00:00:00"
                    pct = f"{ws.percent:.2f}%" if isinstance(ws.percent, (int, float)) else "?%"
                    if ws.is_paused:
                        sp = "PAUSED"
                    else:
                        sp = f"{(float(ws.speed_bps)/(1024*1024)):.2f}MiB/s" if isinstance(ws.speed_bps, (int, float)) and ws.speed_bps is not None else "?/s"
                    # Render ETA; if near completion and eta ≤ 0, show '?' to avoid stuck 00:00:00
                    if isinstance(ws.eta_s, (int, float)) and ws.eta_s is not None:
                        if isinstance(ws.percent, (int, float)) and ws.percent is not None and ws.percent >= 99.5 and float(ws.eta_s) <= 0:
                            eta_txt = "?"
                        else:
                            eta_txt = _hms(float(ws.eta_s))
                    else:
                        eta_txt = "?"
                    sizes = f"{_human_short_bytes(ws.downloaded_bytes)}/{_human_short_bytes(ws.total_bytes)}" if (isinstance(ws.downloaded_bytes, int) and isinstance(ws.total_bytes, int) and ws.total_bytes) else ""
                    sel_marker = ">" if ws.slot == selected_worker_slot else " "

                    if cols >= 110:
                        # Single row packed
                        tag = "[Y]" if ws.downloader == 'yt-dlp' else ("[A]" if ws.downloader == 'aebndl' else "   ")
                        c0 = col(f"{sel_marker}[{ws.slot:02d}]", 5)
                        c1 = col(name, 40)
                        c2 = col(url_idx, 12)
                        c3 = col(f"Elapsed {elapsed}", 16)
                        c4 = col(pct, 8)
                        c5 = col(sp, 12)
                        c6 = col(f"ETA {eta_txt}", 12)
                        c7 = col(sizes, 12)
                        mainline = " | ".join([c0, c1, c2, c3, c4, c5, c6, c7])[:cols]
                        lines.append(ws.overlay_msg[:cols] if ws.overlay_msg else mainline)
                        barw = max(20, cols - 8)
                        lines.append(f"  {sel_marker}{tag}  " + make_bar(ws.percent, barw, speed_color_prefix(ws.speed_bps))[:max(0, cols-7)])
                    elif cols >= 90:
                        # Two rows
                        tag = "[Y]" if ws.downloader == 'yt-dlp' else ("[A]" if ws.downloader == 'aebndl' else "   ")
                        c0 = col(f"{sel_marker}[{ws.slot:02d}]", 5)
                        c1 = col(name, 36)
                        c2 = col(url_idx, 12)
                        c3 = col(sizes, 14)
                        main1 = " | ".join([c0, c1, c2, c3])[:cols]
                        lines.append(ws.overlay_msg[:cols] if ws.overlay_msg else main1)
                        c0b = col(f"{sel_marker}{tag}", 4)
                        c1b = col(f"Elapsed {elapsed}", 20)
                        c2b = col(pct, 10)
                        c3b = col(sp, 12)
                        c4b = col(f"ETA {eta_txt}", 14)
                        lines.append(" | ".join([c0b, c1b, c2b, c3b, c4b])[:cols])
                        barw = max(20, cols - 8)
                        lines.append("     " + make_bar(ws.percent, barw, speed_color_prefix(ws.speed_bps))[:cols])
                    else:
                        # Three rows compact
                        tag = "[Y]" if ws.downloader == 'yt-dlp' else ("[A]" if ws.downloader == 'aebndl' else "   ")
                        c0 = col(f"{sel_marker}[{ws.slot:02d}]", 5)
                        c1 = col(name, max(20, cols - 7))
                        lines.append(ws.overlay_msg[:cols] if ws.overlay_msg else " | ".join([c0, c1])[:cols])
                        c0b = col(f"{sel_marker}{tag}", 4)
                        c1b = col(f"{url_idx}  Elapsed {elapsed}", max(20, cols - 7))
                        lines.append(" | ".join([c0b, c1b])[:cols])
                        c1c = col(f"{pct}  {sp}  ETA {eta_txt}  {sizes}", max(20, cols - 7))
                        lines.append(" | ".join([c0, c1c])[:cols])
                        barw = max(20, cols - 8)
                        lines.append("     " + make_bar(ws.percent, barw, speed_color_prefix(ws.speed_bps))[:cols])

                # Controls and optional verbose pane
                if quit_confirm:
                    lines.append("Press Y to quit, N to cancel"[:cols])
                else:
                    lines.append("Keys: w=watcher, p=pause/unpause, q=quit, v=cycle verbose (NDJSON->LOG->off), 1-9=select worker"[:cols])
                _render_screen(lines)

            # Keyboard handling (for both panels)
            if os.name == 'nt':
                try:
                    import msvcrt  # type: ignore
                    while msvcrt.kbhit():
                        ch = msvcrt.getwch()
                        key = ch.lower() if ch else ""
                        if quit_confirm:
                            # Handle quit confirmation
                            if key == 'y':
                                stop.set()
                                break
                            elif key == 'n':
                                quit_confirm = False
                        else:
                            # Normal key handling
                            if not key:
                                continue
                            if key == 'w':
                                active_panel = "watcher" if active_panel == "downloads" else "downloads"
                                continue
                            if active_panel == "watcher":
                                if key == 'c' and watcher and watcher_enabled:
                                    if watcher.manual_run(dry_run=False, trigger="manual-ui"):
                                        mlog.info("MP4 watcher run started (manual).")
                                    else:
                                        mlog.info("MP4 watcher run request ignored (already running or disabled).")
                                elif key in ('d', 's') and watcher and watcher_enabled:
                                    if watcher.manual_run(dry_run=True, trigger="manual-ui-dry-run"):
                                        mlog.info("MP4 watcher scan (dry-run) started.")
                                    else:
                                        mlog.info("MP4 watcher scan request ignored (already running or disabled).")
                                elif key == 'o' and watcher and watcher_enabled:
                                    new_op = watcher.toggle_operation()
                                    cfg_snapshot = watcher.config_snapshot()
                                    keep_desc = "keep source" if cfg_snapshot.keep_source else "delete source"
                                    if cfg_snapshot.keep_source_locked:
                                        keep_desc += " (locked -K)"
                                    mlog.info(f"MP4 watcher default operation set to {new_op} ({keep_desc}).")
                                elif key == 'k' and watcher and watcher_enabled:
                                    response = _prompt_text("Max MP4 files per watcher run (blank=unlimited)")
                                    if response is None:
                                        continue
                                    if not response:
                                        watcher.set_max_files(None)
                                        mlog.info("MP4 watcher max-files set to unlimited.")
                                        continue
                                    try:
                                        new_limit = int(response)
                                    except ValueError:
                                        mlog.error("Invalid max-files value; expected a positive integer.")
                                        continue
                                    limit = watcher.set_max_files(new_limit)
                                    if limit is None:
                                        mlog.info("MP4 watcher max-files set to unlimited.")
                                    else:
                                        mlog.info(f"MP4 watcher max-files set to {limit}.")
                                elif key == 'f' and watcher and watcher_enabled:
                                    response = _prompt_text("Trigger watcher when staging free space (GiB) drops below (blank=disable)")
                                    if response is None:
                                        continue
                                    if not response:
                                        watcher.set_free_space_trigger_gib(None)
                                        mlog.info("MP4 watcher free-space trigger disabled.")
                                        continue
                                    try:
                                        new_threshold = float(response)
                                    except ValueError:
                                        mlog.error("Invalid free-space threshold; expected a number.")
                                        continue
                                    threshold_bytes = watcher.set_free_space_trigger_gib(new_threshold)
                                    if threshold_bytes:
                                        mlog.info(f"MP4 watcher free-space trigger set to {new_threshold:.1f} GiB.")
                                    else:
                                        mlog.info("MP4 watcher free-space trigger disabled.")
                                elif key == 'q':
                                    quit_confirm = True
                                continue
                            if key == 'v':
                                try:
                                    verbose_mode = int(verbose_mode)
                                except Exception:
                                    verbose_mode = 0
                                verbose_mode = (verbose_mode + 1) % 3
                            elif ch.isdigit() and ch != '0':
                                verbose_slot = int(ch)
                                selected_worker_slot = verbose_slot
                            elif key == 'p':
                                # Toggle pause
                                paused = not paused
                                if paused:
                                    mlog.info("PAUSE requested - pausing all worker processes")
                                    # Pause existing processes
                                    for ws in workers:
                                        if ws.proc and ws.proc.poll() is None and not ws.is_paused:
                                            # Store current speed before pausing
                                            ws.paused_speed_bps = ws.speed_bps
                                            if _pause_process(ws.proc):
                                                ws.is_paused = True
                                                ws.speed_bps = 0.0  # Set speed to 0 while paused
                                                ws.overlay_msg = f"PAUSED - process suspended, no downloads active"
                                                ws.overlay_since = time.time()
                                                mlog.info(f"[{ws.slot:02d}] PAUSED process PID {ws.proc.pid}")
                                            else:
                                                ws.overlay_msg = f"PAUSE FAILED - could not suspend process"
                                                ws.overlay_since = time.time()
                                                mlog.error(f"[{ws.slot:02d}] Failed to pause process PID {ws.proc.pid}")
                                else:
                                    mlog.info("UNPAUSE requested - resuming all worker processes")
                                    # Resume paused processes and allow new assignments
                                    for ws in workers:
                                        if ws.proc and ws.proc.poll() is None and ws.is_paused:
                                            if _resume_process(ws.proc):
                                                ws.is_paused = False
                                                # Restore previous speed (it will update from actual progress soon)
                                                ws.speed_bps = ws.paused_speed_bps
                                                ws.paused_speed_bps = None
                                                ws.overlay_msg = None
                                                mlog.info(f"[{ws.slot:02d}] RESUMED process PID {ws.proc.pid}")
                                            else:
                                                mlog.error(f"[{ws.slot:02d}] Failed to resume process PID {ws.proc.pid}")
                                        elif not ws.proc:
                                            # Assign work to idle workers
                                            _assign(ws)
                            elif key == 'q':
                                # Request quit confirmation
                                quit_confirm = True
                except Exception:
                    pass
            if verbose_mode:
                lines.append("-" * min(cols, 100))
                sel = next((w for w in workers if w.slot == verbose_slot), None)
                # Mode 1: NDJSON buffer
                if verbose_mode == 1:
                    header_v = f"Verbose NDJSON [{verbose_slot:02d}]"
                    lines.append(header_v[:cols])
                    if sel and sel.ndjson_buf:
                        try:
                            max_lines = os.get_terminal_size().lines // 3
                        except Exception:
                            max_lines = 20
                        max_lines = max(10, min(60, max_lines))
                        for ln in sel.ndjson_buf[-max_lines:]:
                            lines.append(ln[:cols])
                # Mode 2: Program log tail (colorized statuses)
                elif verbose_mode == 2:
                    header_v = f"Program Log [{verbose_slot:02d}]"
                    lines.append(header_v[:cols])
                    def _tail_lines(p: Optional[Path], n: int) -> list[str]:
                        if not p:
                            return ["<no log path>"]
                        try:
                            txt = Path(p).read_text(encoding='utf-8', errors='ignore')
                            arr = txt.splitlines()
                            return arr[-n:]
                        except Exception as _e:
                            return [f"<error reading {p}: {_e}>"]
                    def _colorize_log(s: str) -> str:
                        # Color key statuses per line; ensure reset at end
                        pairs = [
                            ("FINISH_BAD", "\x1b[31m"),
                            ("BAD", "\x1b[31m"),
                            ("STALLED", "\x1b[31m"),
                            ("DEADLINE", "\x1b[35m"),
                            ("FORCE_EXIT", "\x1b[35m"),
                            ("DUPLICATE", "\x1b[33m"),
                            ("FINISH_SUCCESS", "\x1b[32m"),
                            ("SUCCESS", "\x1b[32m"),
                        ]
                        out = s
                        for token, colr in pairs:
                            if token in out:
                                out = out.replace(token, f"{colr}{token}\x1b[0m")
                        # Ensure reset at end to prevent bleed
                        if "\x1b[" in out and not out.endswith("\x1b[0m"):
                            out = out + "\x1b[0m"
                        return out
                    try:
                        max_lines = os.get_terminal_size().lines // 3
                    except Exception:
                        max_lines = 20
                    max_lines = max(10, min(60, max_lines))
                    tail = _tail_lines(sel.prog_log_path if sel else None, max_lines)
                    for ln in tail:
                        c = _colorize_log(ln)
                        lines.append(c[:cols])

            # Redraw whole frame (reset attributes first to avoid color bleed)
            sys.stdout.write("\x1b[0m\x1b[2J\x1b[H")
            sys.stdout.write("\n".join(lines) + "\n")
            sys.stdout.flush()

            # If all workers idle and both pools empty, stop
            if all(w.proc is None for w in workers):
                current_regular, current_priority = _gather_from_roots(roots, finished_log, args.priority_files)
                if not current_regular and not current_priority:
                    break

            time.sleep(refresh_dt)
    except KeyboardInterrupt:
        stop.set()
    finally:
        # Cleanup
        for ws in workers:
            if ws.proc and ws.proc.poll() is None:
                # Resume if paused before terminating
                if ws.is_paused:
                    _resume_process(ws.proc)
                    ws.is_paused = False
                try:
                    ws.proc.terminate()
                except Exception:
                    pass
                try:
                    ws.proc.wait(timeout=2)
                except Exception:
                    pass
            if ws.reader:
                ws.reader_stop.set()
                try:
                    ws.reader.join(timeout=1)
                except Exception:
                    pass
        # Leave cursor below
    return 0


if __name__ == "__main__":
    # Make Ctrl-C stop child process trees on POSIX; on Windows terminate() handles direct child
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
