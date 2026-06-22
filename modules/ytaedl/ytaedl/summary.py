"""
ytaedl summary subcommand — displays real-time statistics and locks.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import List, Optional, Sequence


# ANSI Color Codes
CYAN = "\x1b[36m"
GREEN = "\x1b[32m"
BLUE = "\x1b[34m"
MAGENTA = "\x1b[35m"
YELLOW = "\x1b[33m"
WHITE = "\x1b[37m"
RESET = "\x1b[0m"
BOLD = "\x1b[1m"


def process_exists(pid: int) -> bool:
    """Check if a process with the given PID is currently active."""
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    else:
        # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False


def format_hms(seconds: float) -> str:
    """Format duration in seconds to HH:MM:SS."""
    s = int(round(seconds))
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    return f"{h:02d}:{m:02d}:{sec:02d}"


def format_speed(bps: float) -> str:
    """Format speed in bytes per second to human-readable string."""
    if bps <= 0:
        return "0B/s"
    units = ["B/s", "KiB/s", "MiB/s", "GiB/s"]
    val = float(bps)
    i = 0
    while val >= 1024.0 and i < len(units) - 1:
        val /= 1024.0
        i += 1
    return f"{val:.2f}{units[i]}"


def archive_stale_file(filepath: Path, data: dict, mtime: float) -> None:
    """Archive a stale active manager file."""
    try:
        pid = data.get("pid", 0)
        start_time_raw = data.get("start_time", "")
        # Parse or default start time
        try:
            # Try to format or fallback
            started_dt = start_time_raw.replace("-", "").replace(":", "")[:15]
        except Exception:
            started_dt = "unknown"
            
        ended_str = time.strftime("%Y%m%d_%H%M%S", time.localtime(mtime))
        archive_name = f"ended_{ended_str}_started_{started_dt}_{pid}.json"
        
        stats_archive_dir = filepath.parent / "stats_archive"
        stats_archive_dir.mkdir(parents=True, exist_ok=True)
        dest_file = stats_archive_dir / archive_name
        
        # Update end time fields
        data["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(mtime))
        if "runtime_seconds" not in data or data["runtime_seconds"] <= 0:
            # Estimate from start time if possible
            data["runtime_seconds"] = max(0.0, mtime - filepath.stat().st_ctime)
            
        dest_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        filepath.unlink(missing_ok=True)
    except Exception:
        pass


def make_parser() -> argparse.ArgumentParser:
    """Build summary subcommand argument parser."""
    parser = argparse.ArgumentParser(
        description="Display real-time statistics and active locks across ytaedl instances."
    )
    parser.add_argument("-a", "--archive", default="./archive",
                        help="Path to archive directory")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = make_parser().parse_args(argv)
    archive_dir = Path(args.archive).expanduser().resolve()
    stats_dir = archive_dir / "instance_stats"
    
    if not stats_dir.exists():
        print("No active ytaedl instances found (stats directory does not exist).")
        return 0
        
    active_files = list(stats_dir.glob("active_manager_*.json"))
    
    active_instances = []
    
    # Process files and archive stale ones
    for filepath in active_files:
        try:
            mtime = filepath.stat().st_mtime
            try:
                data = json.loads(filepath.read_text(encoding="utf-8"))
            except Exception:
                continue
                
            pid = data.get("pid")
            if pid is None:
                continue
                
            # Stale checks
            is_stale = False
            if not process_exists(pid):
                is_stale = True
            elif time.time() - mtime > 10.0:
                is_stale = True
                
            if is_stale:
                archive_stale_file(filepath, data, mtime)
            else:
                active_instances.append(data)
        except Exception:
            pass
            
    if not active_instances:
        print("No active ytaedl instances found.")
        return 0
        
    # Sort active instances by PID
    active_instances.sort(key=lambda x: x.get("pid", 0))
    
    # Header format
    # columns: instances - workers - instance runtimes - finished downloads - average download speed - avg url dl speed - current dl speed
    headers = [
        ("instances", CYAN),
        ("workers", BLUE),
        ("instance runtimes", GREEN),
        ("finished downloads", MAGENTA),
        ("average download speed", YELLOW),
        ("avg url dl speed", WHITE),
        ("current dl speed", CYAN),
    ]
    
    header_str = " - ".join(f"{color}{name}{RESET}" for name, color in headers)
    print(header_str)
    
    # Display each active instance
    for idx, inst in enumerate(active_instances, 1):
        pid = inst.get("pid", 0)
        workers_count = inst.get("workers_count", 0)
        runtime = inst.get("runtime_seconds", 0.0)
        finished = inst.get("finished_count", 0)
        avg_speed = inst.get("average_speed_bps", 0.0)
        avg_url_speed = inst.get("avg_url_speed_bps", 0.0)
        current_speed = inst.get("current_speed_bps", 0.0)
        
        # Values
        val_inst = f"ytaedl_instance_{idx}" # Or ytaedl_instance_<pid>, but user format specifies ytaedl_instance_1, ytaedl_instance_2
        val_workers = str(workers_count)
        val_runtime = format_hms(runtime)
        val_finished = str(finished)
        val_avg_speed = format_speed(avg_speed)
        val_avg_url_speed = format_speed(avg_url_speed)
        val_current_speed = format_speed(current_speed)
        
        row_parts = [
            f"{CYAN}{val_inst}{RESET}",
            f"{BLUE}{val_workers}{RESET}",
            f"{GREEN}{val_runtime}{RESET}",
            f"{MAGENTA}{val_finished}{RESET}",
            f"{YELLOW}{val_avg_speed}{RESET}",
            f"{WHITE}{val_avg_url_speed}{RESET}",
            f"{CYAN}{val_current_speed}{RESET}",
        ]
        print(" - ".join(row_parts))
        
        # Display locks grouped by parent directory
        locks = inst.get("locks_held", [])
        if locks:
            print(f"    {BOLD}locks and times held:{RESET}")
            # Group locks
            groups = defaultdict(list)
            for l in locks:
                fp = Path(l.get("file_path", ""))
                parent = fp.parent.name or "root"
                groups[parent].append((fp.name, l.get("time_held_seconds", 0.0)))
                
            # Print groups sorted by parent name
            for parent in sorted(groups.keys()):
                print(f"        {CYAN}{parent}/{RESET}")
                # Sort files by name
                for fname, held_s in sorted(groups[parent], key=lambda x: x[0]):
                    duration = format_hms(held_s)
                    print(f"            {fname} / {GREEN}{duration}{RESET}")
                    
    return 0
