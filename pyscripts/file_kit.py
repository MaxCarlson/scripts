#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
file_kit.py
A command-line utility for finding and listing files by size/date and related tasks.

Key points:
- Fixes Windows cp1252 UnicodeEncodeError by forcing UTF-8 stdout/stderr.
- Memory-efficient top-N selection (heap) for largest files.
- Fast duplicate detection: optional prehash + threaded full hashing; selectable hash algo.
- New global output options: --absolute, --output, --encoding.
- New 'du' command (directory usage) with --max-depth and sort controls.
- Console output shows filenames by default; full paths when --absolute or --output.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import heapq
import io
import os
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Generator, List, Optional, Tuple

# ----------------------------
# Utility & Formatting Helpers
# ----------------------------

def parse_size(size_str: str) -> int:
    """Parse a human size like '50kb', '200mb', '1g' into bytes (int)."""
    s = str(size_str).lower().strip()
    m = re.match(r'^(\d+\.?\d*)\s*([kmgtp]?)(b)?$', s)
    if not m:
        raise argparse.ArgumentTypeError(f"Invalid size format: '{size_str}'")
    num, unit, _ = m.groups()
    numf = float(num)
    powers = {'': 0, 'k': 1, 'm': 2, 'g': 3, 't': 4, 'p': 5}
    if unit not in powers:
        raise argparse.ArgumentTypeError(f"Unknown size unit in '{size_str}'")
    return int(numf * (1024 ** powers[unit]))

def format_bytes(n: int) -> str:
    """Format bytes as human-readable string."""
    units = ['B', 'K', 'M', 'G', 'T', 'P']
    i = 0
    v = float(n)
    while v >= 1024 and i < len(units) - 1:
        v /= 1024.0
        i += 1
    return f"{v:.2f}{units[i]}B"

def configure_stdout(encoding: str = "utf-8") -> None:
    """Force stdout/stderr encoding to avoid Windows codepage issues."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name)
        try:
            stream.reconfigure(encoding=encoding, errors="backslashreplace")  # type: ignore[attr-defined]
        except Exception:
            # Fallback: wrap via TextIOWrapper if .reconfigure is not available and buffer exists
            try:
                wrapped = io.TextIOWrapper(stream.buffer, encoding=encoding, errors="backslashreplace")  # type: ignore[attr-defined]
                setattr(sys, stream_name, wrapped)
            except Exception:
                # As a last resort, keep whatever encoding exists.
                pass

def safe_path_display(p: Path, absolute: bool) -> str:
    """Return a printable path (absolute when requested)."""
    try:
        return str(p.resolve() if absolute else p)
    except Exception:
        return str(p)

class TeeWriter:
    """Print to stdout and optional file (with consistent encoding)."""
    def __init__(self, file_path: Optional[Path] = None, encoding: str = "utf-8"):
        self.file_path = file_path
        self.encoding = encoding
        self._fp = None
        if self.file_path:
            self._fp = open(self.file_path, "w", encoding=self.encoding, newline="")

    def write(self, line: str = "") -> None:
        print(line)
        if self._fp:
            self._fp.write(line + "\n")

    def close(self) -> None:
        if self._fp:
            self._fp.flush()
            self._fp.close()

    def __enter__(self) -> "TeeWriter":
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

# ----------------------------
# File Discovery
# ----------------------------

def get_files_from_path(search_path: str, file_filter: str, recursive: bool) -> Generator[Tuple[Path, os.stat_result], None, None]:
    """Yield (Path, stat) for files matching pattern under search_path."""
    base = Path(search_path)
    if not base.is_dir():
        print(f"Error: Path '{search_path}' is not a valid directory.", file=sys.stderr)
        sys.exit(1)
    iterator = base.rglob(file_filter) if recursive else base.glob(file_filter)
    for file_path in iterator:
        try:
            if file_path.is_file():
                try:
                    yield file_path, file_path.stat()
                except FileNotFoundError:
                    continue
        except PermissionError:
            continue

# ----------------------------
# Subcommand Handlers
# ----------------------------

def _name_for_console(p: Path, args) -> str:
    """Use filename for interactive console; full path if --absolute or writing to file."""
    if args.absolute or args.output:
        return safe_path_display(p, args.absolute)
    return p.name  # keeps tests stable and readable in terminals

def handle_top_size(args: argparse.Namespace) -> None:
    """Find top N largest files (heap-based)."""
    search_type = "recursively" if args.recursive else "in the top-level directory"
    with TeeWriter(Path(args.output) if args.output else None, args.encoding) as w:
        w.write(f"Searching for the {args.top} largest '{args.filter}' files {search_type} of '{args.path}'...")

        heap: List[Tuple[int, str, Path]] = []  # (size, name, path)
        for p, st in get_files_from_path(args.path, args.filter, args.recursive):
            item = (st.st_size, p.name, p)
            if len(heap) < args.top:
                heapq.heappush(heap, item)
            else:
                if item > heap[0]:
                    heapq.heapreplace(heap, item)

        items = sorted(heap, key=lambda x: (x[0], x[1]), reverse=True)

        try:
            console_width = shutil.get_terminal_size().columns
        except OSError:
            console_width = 120

        w.write("-" * console_width)
        for size, _, path_obj in items:
            size_str = f"{format_bytes(size):>10} "
            name_str = _name_for_console(path_obj, args)
            if not args.output and not args.absolute:
                remaining = max(10, console_width - len(size_str) - 1)
                if len(name_str) > remaining:
                    name_str = name_str[: remaining - 3] + "..."
            w.write(f"{size_str}{name_str}")
        w.write("-" * console_width)

def handle_find_recent(args: argparse.Namespace) -> None:
    """Find files larger than size accessed within N days."""
    search_type = "recursively" if args.recursive else "in the top-level directory"
    with TeeWriter(Path(args.output) if args.output else None, args.encoding) as w:
        w.write(
            f"Searching {search_type} of '{args.path}' for '{args.filter}' files > {format_bytes(args.size)} "
            f"accessed in the last {args.days} days..."
        )

        cutoff_ts = (datetime.now() - timedelta(days=args.days)).timestamp()
        matches: List[Tuple[int, float, Path]] = []
        for p, st in get_files_from_path(args.path, args.filter, args.recursive):
            if st.st_size > args.size and st.st_atime > cutoff_ts:
                matches.append((st.st_size, st.st_atime, p))

        if not matches:
            w.write("No matching files found.")
            return

        matches.sort(key=lambda x: (x[0], x[2].name), reverse=True)

        try:
            console_width = shutil.get_terminal_size().columns
        except OSError:
            console_width = 120

        SIZE_W, DATE_W, SP = 10, 25, 2
        name_w = max(20, console_width - SIZE_W - DATE_W - SP)
        w.write(f"\n{'Name':<{name_w}} {'Size':>{SIZE_W}} {'Last Accessed':>{DATE_W}}")
        w.write(f"{'-'*name_w:<{name_w}} {'-'*SIZE_W:>{SIZE_W}} {'-'*DATE_W:>{DATE_W}}")

        for size, atime, p in matches:
            size_str = format_bytes(size)
            date_str = datetime.fromtimestamp(atime).strftime('%Y-%m-%d %H:%M:%S')
            name_str = _name_for_console(p, args)
            if not args.output and not args.absolute and len(name_str) > name_w:
                name_str = name_str[: name_w - 3] + "..."
            w.write(f"{name_str:<{name_w}} {size_str:>{SIZE_W}} {date_str:>{DATE_W}}")

def handle_find_old(args: argparse.Namespace) -> None:
    """Find largest files not accessed/modified/created since cutoff-days ago."""
    mapper = {'a': 'accessed', 'm': 'modified', 'c': 'created'}
    date_type_full = mapper.get(args.date_type, args.date_type)
    date_map = {'accessed': 'st_atime', 'modified': 'st_mtime', 'created': 'st_ctime'}
    if date_type_full not in date_map:
        print(f"Invalid date type: {args.date_type}", file=sys.stderr)
        sys.exit(2)

    search_type = "recursively" if args.recursive else "in the top-level directory"
    with TeeWriter(Path(args.output) if args.output else None, args.encoding) as w:
        w.write(
            f"Searching {search_type} of '{args.path}' for top {args.top} '{args.filter}' files not "
            f"{date_type_full} since {args.cutoff_days} days ago..."
        )

        cutoff_ts = (datetime.now() - timedelta(days=args.cutoff_days)).timestamp()
        attr = date_map[date_type_full]

        matches: List[Tuple[int, float, Path]] = []
        for p, st in get_files_from_path(args.path, args.filter, args.recursive):
            if getattr(st, attr) < cutoff_ts:
                matches.append((st.st_size, getattr(st, attr), p))

        if not matches:
            w.write("No matching files found.")
            return

        matches.sort(key=lambda x: (x[0], x[2].name), reverse=True)
        top = matches[: args.top]

        try:
            console_width = shutil.get_terminal_size().columns
        except OSError:
            console_width = 120

        SIZE_W, DATE_W, SP = 10, 25, 2
        name_w = max(20, console_width - SIZE_W - DATE_W - SP)
        header_date = f"{date_type_full.capitalize()} Date"
        w.write(f"\n{'Name':<{name_w}} {'Size':>{SIZE_W}} {header_date:>{DATE_W}}")
        w.write(f"{'-'*name_w:<{name_w}} {'-'*SIZE_W:>{SIZE_W}} {'-'*DATE_W:>{DATE_W}}")

        for size, ts, p in top:
            size_str = format_bytes(size)
            date_str = datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
            name_str = _name_for_console(p, args)
            if not args.output and not args.absolute and len(name_str) > name_w:
                name_str = name_str[: name_w - 3] + "..."
            w.write(f"{name_str:<{name_w}} {size_str:>{SIZE_W}} {date_str:>{DATE_W}}")

# -------- Duplicate Detection --------

HASH_ALGOS = {
    "blake2b": hashlib.blake2b,
    "sha256": hashlib.sha256,
    "md5": hashlib.md5,
}

def _hash_file(path: Path, algo_name: str, full: bool, chunk_size: int = 1024 * 1024) -> Optional[bytes]:
    """Hash a file. If full=False, hash only the first chunk."""
    try:
        hasher = HASH_ALGOS[algo_name]()  # type: ignore[call-arg]
        with open(path, "rb") as f:
            if not full:
                hasher.update(f.read(chunk_size))
            else:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    hasher.update(chunk)
        return hasher.digest()
    except Exception:
        return None

def handle_find_dupes(args: argparse.Namespace) -> None:
    """Find files with identical content, efficiently."""
    search_type = "recursively" if args.recursive else "in the top-level directory"
    with TeeWriter(Path(args.output) if args.output else None, args.encoding) as w:
        w.write(
            f"Scanning for duplicate files {search_type} in '{args.path}' "
            f"(min size: {format_bytes(args.min_size)}; algo={args.hash}, workers={args.workers}, quick={'on' if args.quick else 'off'})..."
        )

        # Step 1: group by size
        by_size: Dict[int, List[Path]] = defaultdict(list)
        for p, st in get_files_from_path(args.path, "*.*", args.recursive):
            if st.st_size >= args.min_size:
                by_size[st.st_size].append(p)

        candidate_groups = [paths for paths in by_size.values() if len(paths) > 1]
        if not candidate_groups:
            w.write("No potential duplicates found.")
            return

        # Step 2: prehash (first 1MiB) to prune
        prehash_groups: Dict[bytes, List[Path]] = defaultdict(list)
        if args.quick:
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
                fut_to_path = {ex.submit(_hash_file, p, args.hash, False): p for paths in candidate_groups for p in paths}
                for fut in concurrent.futures.as_completed(fut_to_path):
                    p = fut_to_path[fut]
                    digest = fut.result()
                    if digest is not None:
                        prehash_groups[digest].append(p)
        else:
            # Without prehash, just treat each size-bucket as a group keyed by size bytes marker
            for paths in candidate_groups:
                prehash_groups[bytes(os.urandom(8))] = list(paths)

        # Step 3: full hash within each prehash bucket
        fullhash_groups: Dict[bytes, List[Path]] = defaultdict(list)
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
            future_map = {}
            for paths in prehash_groups.values():
                if len(paths) < 2:
                    continue
                for p in paths:
                    future_map[ex.submit(_hash_file, p, args.hash, True)] = p

            for fut in concurrent.futures.as_completed(future_map):
                p = future_map[fut]
                digest = fut.result()
                if digest is not None:
                    fullhash_groups[digest].append(p)

        dupes = {h: sorted(ps, key=lambda x: x.name) for h, ps in fullhash_groups.items() if len(ps) > 1}
        if not dupes:
            w.write("No duplicate files found.")
            return

        w.write("\n--- Found Duplicate Sets ---")
        for h, paths in sorted(dupes.items(), key=lambda kv: (len(kv[1]), kv[1][0].name), reverse=True):
            try:
                size_str = format_bytes(paths[0].stat().st_size)
            except Exception:
                size_str = "?"
            w.write(f"\nHash: {h.hex()[:16]}... ({len(paths)} files, size: {size_str})")
            for p in paths:
                w.write(f"  - {safe_path_display(p, args.absolute)}")

# -------- Directory Usage (du) --------

def handle_du(args: argparse.Namespace) -> None:
    """Summarize directory sizes like 'du', limited by depth and sorted order."""
    base = Path(args.path)
    if not base.is_dir():
        print(f"Error: Path '{args.path}' is not a valid directory.", file=sys.stderr)
        sys.exit(1)

    with TeeWriter(Path(args.output) if args.output else None, args.encoding) as w:
        w.write(f"Summarizing sizes under '{args.path}' (max-depth={args.max_depth}, recursive={args.recursive})...")

        sizes: Dict[Path, int] = defaultdict(int)
        base_depth = len(base.parts)

        stack: List[Path] = [base]
        while stack:
            cur = stack.pop()
            try:
                with os.scandir(cur) as it:
                    for entry in it:
                        try:
                            if entry.is_file(follow_symlinks=False):
                                st = entry.stat(follow_symlinks=False)
                                p = Path(entry.path)
                                # Attribute file size to ancestors within depth
                                for d in range(base_depth, min(len(p.parts), base_depth + args.max_depth + 1)):
                                    sizes[Path(*p.parts[:d])] += st.st_size
                            elif entry.is_dir(follow_symlinks=False) and args.recursive:
                                stack.append(Path(entry.path))
                        except (PermissionError, FileNotFoundError):
                            continue
            except (PermissionError, FileNotFoundError):
                continue

        rows: List[Tuple[int, Path]] = []
        for d, sz in sizes.items():
            depth = len(d.parts) - base_depth
            if 0 <= depth <= args.max_depth:
                rows.append((sz, d))

        if not rows:
            w.write("No data to summarize.")
            return

        key = {"size": lambda x: (x[0], x[1].name), "name": lambda x: (x[1].name,)}[args.sort]
        rows.sort(key=key, reverse=(args.sort == "size"))

        try:
            console_width = shutil.get_terminal_size().columns
        except OSError:
            console_width = 120

        SIZE_W = 12
        name_w = max(20, console_width - SIZE_W - 2)
        w.write(f"\n{'Directory':<{name_w}} {'Total Size':>{SIZE_W}}")
        w.write(f"{'-'*name_w:<{name_w}} {'-'*SIZE_W:>{SIZE_W}}")
        for sz, d in rows[: args.top]:
            name = safe_path_display(d, args.absolute) if (args.absolute or args.output) else d.name
            if not args.output and not args.absolute and len(name) > name_w:
                name = name[: name_w - 3] + "..."
            w.write(f"{name:<{name_w}} {format_bytes(sz):>{SIZE_W}}")

# -------- Summarize by extension --------

def handle_summarize(args: argparse.Namespace) -> None:
    """Breakdown of disk usage by file extension."""
    search_type = "recursively" if args.recursive else "in the top-level directory"
    with TeeWriter(Path(args.output) if args.output else None, args.encoding) as w:
        w.write(f"Summarizing directory '{args.path}' {search_type}...")

        summary: Dict[str, Dict[str, int]] = defaultdict(lambda: {'count': 0, 'size': 0})
        for p, st in get_files_from_path(args.path, "*.*", args.recursive):
            ext = p.suffix.lower() or "[no extension]"
            summary[ext]['count'] += 1
            summary[ext]['size'] += st.st_size

        if not summary:
            w.write("No files found to summarize.")
            return

        sorted_summary = sorted(summary.items(), key=lambda item: (item[1]['size'], item[0]), reverse=True)

        try:
            console_width = shutil.get_terminal_size().columns
        except OSError:
            console_width = 120

        EXT_W, CNT_W, SZ_W = 20, 10, 15
        w.write(f"\n{'Extension':<{EXT_W}} {'Count':>{CNT_W}} {'Total Size':>{SZ_W}}")
        w.write(f"{'-'*EXT_W:<{EXT_W}} {'-'*CNT_W:>{CNT_W}} {'-'*SZ_W:>{SZ_W}}")

        for ext, data in sorted_summary[: args.top]:
            w.write(f"{ext:<{EXT_W}} {data['count']:>{CNT_W}} {format_bytes(data['size']):>{SZ_W}}")

# ----------------------------
# CLI Setup
# ----------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="A command-line utility for finding and managing files.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available utilities", required=True)

    # Common args
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-p", "--path", default=".", help="Directory to search (default: current directory).")
    common.add_argument("-r", "--recursive", action="store_true", help="Enable recursive search.")
    common.add_argument("-A", "--absolute", action="store_true", help="Print absolute paths (no truncation).")
    common.add_argument("-o", "--output", default=None, help="Write output to a file (UTF-8 by default).")
    common.add_argument("-e", "--encoding", default="utf-8", help="Output encoding (default: utf-8).")

    # top-size
    p_top = subparsers.add_parser("top-size", help="Find the largest files.", parents=[common])
    p_top.add_argument("-t", "--top", type=int, default=10, help="Number of files to list (default: 10).")
    p_top.add_argument("-f", "--filter", default="*.*", help='Glob pattern (default: "*.*").')

    # find-recent
    p_recent = subparsers.add_parser("find-recent", help="Find large files accessed recently.", parents=[common])
    p_recent.add_argument("-s", "--size", type=parse_size, default="1gb", help="Minimum file size (default: 1gb).")
    p_recent.add_argument("-d", "--days", type=int, default=30, help="How many days back is 'recent' (default: 30).")
    p_recent.add_argument("-f", "--filter", default="*.*", help='Glob pattern (default: "*.*").')

    # find-old
    p_old = subparsers.add_parser("find-old", help="Find large files untouched since a cutoff date.", parents=[common])
    p_old.add_argument("-c", "--cutoff-days", type=int, default=30, help="Days ago for cutoff (default: 30).")
    p_old.add_argument("-t", "--top", type=int, default=10, help="Number of files to list (default: 10).")
    p_old.add_argument(
        "-d",
        "--date-type",
        choices=["accessed", "a", "modified", "m", "created", "c"],
        default="a",
        help="Date to check (a|m|c); default: accessed.",
    )
    p_old.add_argument("-f", "--filter", default="*.*", help='Glob pattern (default: "*.*").')

    # find-dupes
    p_dupes = subparsers.add_parser("find-dupes", help="Find files with identical content.", parents=[common])
    p_dupes.add_argument("-m", "--min-size", type=parse_size, default="1kb", help="Min file size (default: 1kb).")
    p_dupes.add_argument("--hash", "-H", choices=sorted(HASH_ALGOS.keys()), default="blake2b", help="Hash algorithm.")
    p_dupes.add_argument("--workers", "-w", type=int, default=max(4, (os.cpu_count() or 2)), help="Thread workers.")
    p_dupes.add_argument("--quick", "-q", action="store_true", default=True, help="Enable 1MiB prehash (default on).")
    p_dupes.add_argument("--no-quick", dest="quick", action="store_false", help="Disable prehash.")

    # summarize
    p_sum = subparsers.add_parser("summarize", help="Show disk usage by file type.", parents=[common])
    p_sum.add_argument("-t", "--top", type=int, default=20, help="Top N extensions by size (default: 20).")

    # du (directory usage)
    p_du = subparsers.add_parser("du", help="Summarize directory sizes (like 'du').", parents=[common])
    p_du.add_argument("-t", "--top", type=int, default=50, help="Top N directories to list (default: 50).")
    p_du.add_argument("--max-depth", "-D", type=int, default=2, help="Maximum depth relative to base (default: 2).")
    p_du.add_argument("--sort", choices=["size", "name"], default="size", help="Sort criterion (default: size).")

    return parser

def main(argv: Optional[List[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_stdout(args.encoding)
    handler_map = {
        "top-size": handle_top_size,
        "find-recent": handle_find_recent,
        "find-old": handle_find_old,
        "find-dupes": handle_find_dupes,
        "summarize": handle_summarize,
        "du": handle_du,
    }
    handler = handler_map[args.command]
    handler(args)

if __name__ == "__main__":
    main()
