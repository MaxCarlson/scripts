#!/usr/bin/env python3
"""
Generic Process Stats Viewer using Rich (with interactive sort-switch and quit)

Press:
  - **s** to cycle sort mode (cpu → memory → disk → alphabetical → random → …)
  - **q** to quit immediately

Default behavior: if -g/--glob is _not_ specified, matches **all** processes.
"""

import time
import fnmatch
import random
import argparse
import psutil
import os
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

# Windows-only for key polling
if os.name == 'nt':
    import msvcrt

SORT_MODES = ['cpu', 'memory', 'disk', 'alphabetical', 'random']

def get_initial_matches(glob_pattern):
    """Return list of psutil.Process objects matching the glob."""
    matches = []
    for p in psutil.process_iter(['pid', 'name']):
        name = (p.info['name'] or '').lower()
        if fnmatch.fnmatch(name, glob_pattern.lower()):
            matches.append(p)
    return matches

def sample_stats(processes, analysis_ms):
    """
    Sample CPU percent and I/O deltas over analysis_ms for each process.
    """
    entries = []
    for p in processes:
        try:
            p.cpu_percent(None)  # prime
            io0 = p.io_counters()
            entries.append((p, io0))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    time.sleep(analysis_ms / 1000.0)
    stats = []
    for p, io0 in entries:
        try:
            cpu = p.cpu_percent(None)
            mem = p.memory_info().rss / 1024**2
            io1 = p.io_counters()
            read_mb  = (io1.read_bytes  - io0.read_bytes)  / 1024**2
            write_mb = (io1.write_bytes - io0.write_bytes) / 1024**2
            stats.append({
                'pid': p.pid,
                'name': p.name(),
                'cpu_pct': cpu,
                'mem_mb' : mem,
                'read_mb': read_mb,
                'write_mb': write_mb,
                'disk_mb': read_mb + write_mb
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return stats

def build_table(stats, total, limit):
    table = Table(expand=True)
    table.add_column("PID", justify="right")
    table.add_column("Name", justify="left")
    table.add_column("CPU %", justify="right")
    table.add_column("Memory (MB)", justify="right")
    table.add_column("Read Δ(MB)", justify="right")
    table.add_column("Write Δ(MB)", justify="right")
    table.add_column("Disk Δ(MB)", justify="right")
    if total > limit:
        table.caption = f"Showing {limit} out of {total} matching processes"
    for s in stats[:limit]:
        table.add_row(
            str(s['pid']),
            s['name'],
            f"{s['cpu_pct']:.2f}",
            f"{s['mem_mb']:.1f}",
            f"{s['read_mb']:.2f}",
            f"{s['write_mb']:.2f}",
            f"{s['disk_mb']:.2f}",
        )
    return table

def main():
    parser = argparse.ArgumentParser(
        description="Live process stats with interactive sort-switch (s) & quit (q)."
    )
    parser.add_argument(
        "-n","--number-of-procs",
        type=int, default=3,
        help="Number of processes to display"
    )
    parser.add_argument(
        "-g","--glob",
        type=str, default=None,
        help="Glob pattern to match process names (default: all)"
    )
    parser.add_argument(
        "-s","--sort-ordering",
        choices=SORT_MODES, default="alphabetical",
        help="Sort by: cpu, memory, disk, alphabetical, or random"
    )
    parser.add_argument(
        "-a","--analysis-time",
        type=int, default=1000,
        help="Milliseconds to sample CPU & I/O"
    )
    parser.add_argument(
        "-u","--update-frequency",
        type=int, default=1000,
        help="Milliseconds between screen refreshes"
    )
    args = parser.parse_args()

    # Determine the glob pattern
    if args.glob is None:
        glob_pattern = "*"
    elif not any(c in args.glob for c in "*?[]"):
        glob_pattern = f"*{args.glob}*"
    else:
        glob_pattern = args.glob

    sort_index = SORT_MODES.index(args.sort_ordering)

    with Live(redirect_stdout=False, refresh_per_second=10) as live:
        while True:
            start = time.time()

            # Key polling on Windows
            if os.name == 'nt' and msvcrt.kbhit():
                key = msvcrt.getwch().lower()
                if key == "q":
                    break
                if key == "s":
                    sort_index = (sort_index + 1) % len(SORT_MODES)
                    args.sort_ordering = SORT_MODES[sort_index]

            procs = get_initial_matches(glob_pattern)
            total = len(procs)
            if total == 0:
                notice = Text.assemble(
                    ("No processes found", "yellow"),
                    ("\n[s] switch sort, [q] quit", "dim")
                )
                live.update(Panel(notice, title="Process Stats"))
                time.sleep(args.update_frequency / 1000.0)
                continue

            stats = sample_stats(procs, args.analysis_time)

            mode = args.sort_ordering
            if mode == "cpu":
                stats.sort(key=lambda x: x["cpu_pct"], reverse=True)
            elif mode == "memory":
                stats.sort(key=lambda x: x["mem_mb"], reverse=True)
            elif mode == "disk":
                stats.sort(key=lambda x: x["disk_mb"], reverse=True)
            elif mode == "alphabetical":
                stats.sort(key=lambda x: x["name"])
            else:
                random.shuffle(stats)

            table = build_table(stats, total, args.number_of_procs)
            footer = Text(f"Mode: {mode}   [s] switch | [q] quit", style="dim")
            panel = Panel(table, title=f"Stats — sorted by {mode}", subtitle=footer)
            live.update(panel)

            elapsed = (time.time() - start) * 1000
            to_sleep = (args.update_frequency - elapsed) / 1000.0
            if to_sleep > 0:
                time.sleep(to_sleep)

if __name__ == "__main__":
    main()
