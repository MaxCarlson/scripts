#!/usr/bin/env python3
# folder_stats.py

import argparse
import sys
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

from rich.console import Console
from rich.table import Table
from rich import box

console = Console()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Scan a directory and report file-type statistics."
    )
    parser.add_argument(
        "directory", metavar="DIR",
        help="Target directory to scan"
    )
    parser.add_argument(
        "-d", "--depth", metavar="N", type=int, default=-1,
        help="Max recursion depth (default infinite with -1)"
    )
    parser.add_argument(
        "-t", "--tree", action="store_true",
        help="Print stats per-subdirectory (indented) instead of aggregate"
    )
    parser.add_argument(
        "-a", "--auto-units", action="store_true",
        help="Auto-select best size unit (KB/MB/GB). Default is MB"
    )
    parser.add_argument(
        "--dates", choices=["atime", "mtime", "ctime"], default=None,
        help="Include oldest/newest access/modify/create dates per category"
    )
    return parser.parse_args()


def humanize_size(bytes_size: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if bytes_size < 1024 or unit == "TB":
            return f"{bytes_size:.2f}{unit}"
        bytes_size /= 1024
    return f"{bytes_size:.2f}TB"


def to_mb(bytes_size: int) -> float:
    return bytes_size / (1024 * 1024)


def gather_stats(
    path: Path,
    maxdepth: int,
    current_depth: int = 0,
) -> Dict[str, Dict[str, Any]]:
    stats: Dict[str, Dict[str, Any]] = {}
    for entry in path.iterdir():
        if entry.is_symlink():
            cat = "[symlink]"
            info = entry.lstat()
            size = 0
        elif entry.is_file():
            cat = entry.suffix.lower() or "[no extension]"
            info = entry.stat()
            size = info.st_size
        elif entry.is_dir() and (maxdepth < 0 or current_depth < maxdepth):
            child = gather_stats(entry, maxdepth, current_depth + 1)
            for ext, data in child.items():
                d = stats.setdefault(ext, {
                    "count": 0, "total": 0,
                    "atime_min": None, "atime_max": None,
                    "mtime_min": None, "mtime_max": None,
                    "ctime_min": None, "ctime_max": None,
                })
                d["count"] += data["count"]
                d["total"] += data["total"]
                for key in ("atime", "mtime", "ctime"):
                    if data[f"{key}_min"] is not None:
                        d[f"{key}_min"] = min(
                            d[f"{key}_min"] or data[f"{key}_min"],
                            data[f"{key}_min"]
                        )
                        d[f"{key}_max"] = max(
                            d[f"{key}_max"] or data[f"{key}_max"],
                            data[f"{key}_max"]
                        )
            continue
        else:
            continue

        d = stats.setdefault(cat, {
            "count": 0, "total": 0,
            "atime_min": None, "atime_max": None,
            "mtime_min": None, "mtime_max": None,
            "ctime_min": None, "ctime_max": None,
        })
        d["count"] += 1
        d["total"] += size
        for key, stamp in (("atime", info.st_atime),
                           ("mtime", info.st_mtime),
                           ("ctime", info.st_ctime)):
            mn = f"{key}_min"; mx = f"{key}_max"
            d[mn] = min(d[mn] or stamp, stamp)
            d[mx] = max(d[mx] or stamp, stamp)

    # Hardlink category
    hard = 0
    for entry in path.rglob("*"):
        try:
            if entry.is_file() and entry.stat().st_nlink > 1:
                hard += 1
        except Exception:
            pass
    if hard:
        stats["[hardlink]"] = {"count": hard, "total": 0,
            "atime_min": None, "atime_max": None,
            "mtime_min": None, "mtime_max": None,
            "ctime_min": None, "ctime_max": None}

    return stats


def find_max_depth(root: Path) -> int:
    maxd = 0
    for p in root.rglob("*"):
        if p.is_dir():
            depth = len(p.relative_to(root).parts)
            maxd = max(maxd, depth)
    return maxd


def print_stats(
    stats: Dict[str, Dict[str, Any]],
    indent: int = 0,
    dir_name: Optional[str] = None,
    args: argparse.Namespace = None,
    header_note: Optional[str] = None,
):
    pad = "    " * indent
    if header_note:
        console.print(f"{pad}[bold yellow]{header_note}[/]")
    if dir_name:
        console.print(f"{pad}[bold underline]{dir_name}[/]")

    table = Table(
        box=box.SIMPLE, expand=True,
        show_header=True, header_style="bold cyan"
    )
    table.add_column("Extension", style="white", no_wrap=True)
    table.add_column("Count", justify="right")
    table.add_column("Size", justify="right")
    if args.dates:
        table.add_column("Oldest", justify="right")
        table.add_column("Newest", justify="right")

    for ext in sorted(stats):
        d = stats[ext]
        count = d["count"]
        size_bytes = d["total"]
        if args.auto_units:
            size = humanize_size(size_bytes)
        else:
            size = f"{to_mb(size_bytes):.2f}MB"
        row = [ext, str(count), size]
        if args.dates:
            mn = datetime.fromtimestamp(d[f"{args.dates}_min"]).isoformat()
            mx = datetime.fromtimestamp(d[f"{args.dates}_max"]).isoformat()
            row += [mn, mx]
        table.add_row(*row)

    console.print(table)
    console.print()


def traverse(
    path: Path,
    args: argparse.Namespace,
    current_depth: int = 0,
):
    stats = gather_stats(path, args.depth, current_depth)
    note = None
    if not args.auto_units:
        # detect if any MB value is > 9999, switch to auto
        for d in stats.values():
            if to_mb(d["total"]) > 9999:
                note = "Large sizes detected: switching to auto-units"
                args.auto_units = True
                break

    print_stats(
        stats,
        indent=current_depth,
        dir_name=str(path.resolve()),
        args=args,
        header_note=note
    )

    if args.tree and (args.depth < 0 or current_depth < args.depth):
        for sub in sorted(p for p in path.iterdir() if p.is_dir()):
            traverse(sub, args, current_depth + 1)


def main():
    args = parse_args()
    root = Path(args.directory)
    if not root.is_dir():
        console.print(f"[red]Error[/] '{root}' is not a directory.")
        sys.exit(1)

    maxd = find_max_depth(root)
    console.print(f"[green]Max depth:[/] {maxd}\n")

    if args.tree:
        traverse(root, args, 0)
    else:
        stats = gather_stats(root, args.depth, 0)
        print_stats(stats, args=args)

if __name__ == "__main__":
    main()
