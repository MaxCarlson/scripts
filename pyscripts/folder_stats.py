#!/usr/bin/env python3
# filetypestats.py

import argparse
import sys
from pathlib import Path
from typing import Dict, Tuple


def parse_args():
    parser = argparse.ArgumentParser(
        description="Scan a directory and report file-type statistics."
    )
    parser.add_argument(
        "directory",
        help="Target directory to scan",
        metavar="DIR",
    )
    parser.add_argument(
        "-d", "--depth",
        type=int,
        default=-1,
        help="Max recursion depth (default: infinite with -1)",
        metavar="N",
    )
    parser.add_argument(
        "-s", "--subdirs",
        action="store_true",
        help="Also print stats for each subdirectory (indented)",
    )
    return parser.parse_args()


def gather_stats(
    path: Path,
    maxdepth: int,
    current_depth: int = 0
) -> Dict[str, Dict[str, int]]:
    """
    Return a map: extension -> { "count": int, "total": int }
    counting files under `path` up to maxdepth.
    """
    stats: Dict[str, Dict[str, int]] = {}
    for entry in path.iterdir():
        if entry.is_file():
            ext = entry.suffix.lower() or "[no extension]"
            size = entry.stat().st_size
            stats.setdefault(ext, {"count": 0, "total": 0})
            stats[ext]["count"] += 1
            stats[ext]["total"] += size
        elif entry.is_dir() and (maxdepth < 0 or current_depth < maxdepth):
            nested = gather_stats(entry, maxdepth, current_depth + 1)
            for e, data in nested.items():
                stats.setdefault(e, {"count": 0, "total": 0})
                stats[e]["count"] += data["count"]
                stats[e]["total"] += data["total"]
    return stats


def print_stats(
    stats: Dict[str, Dict[str, int]],
    indent: int = 0,
    dir_name: str = None
):
    pad = "    " * indent
    if dir_name is not None:
        print(f"{pad}{dir_name}:")
    header = f"{'Extension':<15} {'Count':<10} {'Total Size (bytes)':<20} {'Avg Size (bytes)':<20}"
    print(pad + header)
    total_files = total_bytes = 0
    for ext in sorted(stats):
        count = stats[ext]["count"]
        total = stats[ext]["total"]
        avg = total // count if count else 0
        print(pad + f"{ext:<15} {count:<10} {total:<20} {avg:<20}")
        total_files += count
        total_bytes += total
    if stats:
        avg_all = total_bytes // total_files if total_files else 0
        print(pad + f"{'TOTAL':<15} {total_files:<10} {total_bytes:<20} {avg_all:<20}")
    else:
        print(pad + "(no files found)")
    print()


def traverse_and_report(
    path: Path,
    maxdepth: int,
    current_depth: int = 0
):
    stats = gather_stats(path, maxdepth, current_depth)
    print_stats(stats, indent=current_depth, dir_name=str(path))
    if maxdepth < 0 or current_depth < maxdepth:
        for sub in sorted(p for p in path.iterdir() if p.is_dir()):
            traverse_and_report(sub, maxdepth, current_depth + 1)


def main():
    args = parse_args()
    root = Path(args.directory)
    if not root.is_dir():
        sys.exit(f"Error: '{root}' is not a directory.")
    if args.subdirs:
        traverse_and_report(root, args.depth, 0)
    else:
        stats = gather_stats(root, args.depth, 0)
        print_stats(stats)


if __name__ == "__main__":
    main()
