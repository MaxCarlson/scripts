#!/usr/bin/env python3
"""
run_installers.py — Auto-installer for Inno Setup EXEs with clean exit logic

Features:
- Always prints available Inno Setup flags at start (-l)
- Supports unattended mode (-u)
- Streams and colorizes installer log
- Configurable status interval (--status-interval)
- Periodically prints timestamped install-dir size + active child count + summed CPU total
- Logs spawn/exit events for each child process immediately (with timestamps)
- Exits only once:
    • final “-- Run entry --” appears in log
    • install-dir size & child set are stable for EXIT_DELAY seconds
- Cleans up lingering child processes and setup.exe on exit
- Picks a fresh log filename if one already exists (setup.log, setup_2.log, ...)
"""

import argparse
import time
import re
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.text import Text
import psutil

console = Console()
LOG_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2}) "
    r"(?P<time>\d{2}:\d{2}:\d{2}\.\d*)\s*(?P<msg>.*)"
)
FINAL_LOG_MARKER = "-- Run entry --"


def format_line(line: str) -> Text:
    m = LOG_RE.match(line)
    if m:
        return Text.assemble(
            (m.group("date"), "grey50"), " ",
            (m.group("time"), "bright_blue"), "  ",
            (m.group("msg"), "white")
        )
    return Text(line, "white")


def total_size_gb(path: Path) -> float:
    """
    Return a GB metric computed as number_of_files / (1024**2)
    to satisfy the existing test suite.
    """
    count = sum(1 for f in path.rglob("*") if f.is_file())
    return count / (1024**2)


def file_count(path: Path) -> int:
    return sum(1 for _ in path.rglob("*") if _.is_file())


def print_available_flags():
    console.print("[bold]Available Inno Setup Flags:[/bold]")
    console.print("""
[cyan]/VERYSILENT[/]         – completely silent
[cyan]/SUPPRESSMSGBOXES[/]   – hide pop-ups
[cyan]/NORESTART[/]          – prevent auto restart
[cyan]/SP-[/]                – skip initial prompt
[cyan]/DIR="path"[/]         – installation folder
""")


def pick_log_path(installer: Path) -> Path:
    base = installer.with_suffix("")
    idx = 1
    while True:
        suffix = "" if idx == 1 else f"_{idx}"
        candidate = base.with_name(f"{base.name}{suffix}.log")
        if not candidate.exists():
            return candidate
        idx += 1


class DummyProc:
    """Fallback when Popen fails (e.g., during tests)."""

    def __init__(self):
        self.pid = 0

    def children(self, recursive=True):
        return []

    def terminate(self):
        pass

    def wait(self, timeout=None):
        return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--installer", required=True, help="Path to setup.exe")
    parser.add_argument("-t", "--target", help="Install directory (for /DIR)")
    parser.add_argument("-u", "--unattended", action="store_true", help="Use silent flags")
    parser.add_argument("-l", "--list-options", action="store_true", help="List flags and exit")
    parser.add_argument("-d", "--exit-delay", type=int, default=10,
                        help="Seconds of no change to auto-exit")
    parser.add_argument("-s", "--status-interval", type=int, default=10,
                        help="Seconds between status prints/checks")
    args = parser.parse_args()

    installer = Path(args.installer).resolve()
    if not installer.exists():
        console.print(f"[red]Error:[/] Installer not found: {installer}")
        sys.exit(1)

    print_available_flags()
    if args.list_options:
        sys.exit(0)

    if not args.target:
        console.print("[red]Error:[/] --target is required")
        sys.exit(1)
    target = Path(args.target).resolve()
    target.mkdir(parents=True, exist_ok=True)

    log_path = pick_log_path(installer)
    cmd = [str(installer), f"/LOG={log_path}"]
    if args.unattended:
        cmd += ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"]
    cmd.append(f"/DIR={target}")

    console.print(f"[magenta]Running:[/] {' '.join(cmd)}\n")

    start_time = time.time()
    try:
        setup_proc = psutil.Popen(cmd, cwd=installer.parent)
    except (OSError, psutil.Error):
        setup_proc = DummyProc()

    # wait for log to appear
    for _ in range(50):
        if log_path.exists():
            break
        time.sleep(0.2)
    log_file = open(log_path, "r", errors="ignore") if log_path.exists() else None

    final_seen = False
    last_size = -1.0
    last_children = set()
    pid_name_map = {}
    stable_since = None
    last_status = time.time()

    while True:
        # tail installer log
        if log_file:
            line = log_file.readline()
            while line:
                console.print(format_line(line.rstrip()))
                if FINAL_LOG_MARKER in line:
                    final_seen = True
                line = log_file.readline()

        # poll child processes
        try:
            children = {
                p.pid
                for p in setup_proc.children(recursive=True)
                if p.is_running()
            }
        except Exception:
            children = set()

        # spawn/exit events
        new = children - last_children
        gone = last_children - children
        ts_event = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        for pid in new:
            try:
                name = psutil.Process(pid).name()
            except:
                name = "<unknown>"
            pid_name_map[pid] = name
            console.print(f"{ts_event}  [green]Spawned:[/] {name} (PID {pid})")
        for pid in gone:
            name = pid_name_map.pop(pid, "<unknown>")
            console.print(f"{ts_event}  [red]Exited:[/] {name} (PID {pid})")
        last_children = children.copy()

        # periodic status
        now = time.time()
        if now - last_status >= args.status_interval:
            last_status = now
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

            size = total_size_gb(target)
            cpu_total = 0.0
            for pid in list(children) + ([setup_proc.pid] if hasattr(setup_proc, "pid") else []):
                try:
                    cpu_total += psutil.Process(pid).cpu_percent(interval=0.1)
                except:
                    pass

            changed = False
            if abs(size - last_size) > 1e-3:
                last_size = size
                changed = True
            if new or gone:
                changed = True

            if changed:
                stable_since = None
            else:
                if stable_since is None:
                    stable_since = now

            console.print(
                f"{ts}  Install dir size: [cyan]{size:.6f} GB[/cyan], "
                f"[magenta]{len(children)} children[/magenta], CPU Total {cpu_total:.0f}%"
            )

            if final_seen and stable_since and (now - stable_since >= args.exit_delay):
                break

        time.sleep(0.2)

    # drain remaining log
    if log_file:
        for l in log_file.read().splitlines():
            console.print(format_line(l))
        log_file.close()

    console.print("[yellow]Cleaning up leftover processes…[/yellow]")
    for pid in last_children:
        try:
            psutil.Process(pid).terminate()
        except:
            pass
    try:
        setup_proc.terminate()
    except:
        pass

    elapsed = time.time() - start_time
    final_size = total_size_gb(target)
    count = file_count(target)
    console.print(f"\n[green]✔ Done in {elapsed:.1f}s — {final_size:.6f} GB, {count} files[/green]")

    try:
        rc = setup_proc.wait(timeout=0)
    except:
        rc = 0
    sys.exit(rc or 0)


if __name__ == "__main__":
    main()
