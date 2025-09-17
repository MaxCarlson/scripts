#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
file_kit.py
A command-line utility for finding and listing files by size/date and related tasks.

Key points:
- Fixes Windows cp1252 UnicodeEncodeError by forcing UTF-8 stdout/stderr.
- Memory-efficient top-N selection (heap) for largest files.
- Fast duplicate detection: optional prehash + threaded full hashing; selectable hash algo.
- Global output options: --absolute, --output, --encoding.
- 'du' command (directory usage) with --max-depth and sort controls.
- 'largest' command: any files (including extensionless) or filter by glob/type groups; CSV/JSON export.
- NEW: 'df' command: per-drive/mount free/used/total + %used (cross-platform), CSV/JSON export.
- Console output shows filenames by default; full paths when --absolute or --output.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import heapq
import io
import json
import os
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Generator, Iterable, List, Optional, Set, Tuple

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
            try:
                wrapped = io.TextIOWrapper(stream.buffer, encoding=encoding, errors="backslashreplace")  # type: ignore[attr-defined]
                setattr(sys, stream_name, wrapped)
            except Exception:
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
    return p.name

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

# -------- Largest files (any/glob/type groups, CSV/JSON) --------

TYPE_GROUPS: Dict[str, Set[str]] = {
    "images": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif", ".heic", ".heif", ".svg", ".ico", ".avif"},
    "images_raw": {".cr2", ".arw", ".nef", ".rw2", ".orf", ".dng", ".raf", ".sr2"},
    "videos": {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".flv", ".webm", ".m4v", ".mpeg", ".mpg"},
    "audio": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".opus", ".aiff", ".alac"},
    "archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".zst", ".tgz", ".tbz", ".txz"},
    "docs": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".md", ".rtf", ".odt", ".ods", ".odp", ".csv"},
    "code": {".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".hpp", ".cs", ".go", ".rb", ".php", ".rs", ".swift", ".kt", ".m", ".mm",
             ".sh", ".ps1", ".bat", ".pl", ".lua", ".sql", ".yml", ".yaml", ".json", ".toml", ".ini", ".cfg", ".conf", ".tsx", ".jsx"},
}

def _ext_matches_group(path: Path, groups: Iterable[str]) -> bool:
    if not groups:
        return True
    ext = path.suffix.lower()
    if not ext:
        return False
    allowed: Set[str] = set()
    for g in groups:
        allowed |= TYPE_GROUPS.get(g, set())
    return ext in allowed

def handle_largest(args: argparse.Namespace) -> None:
    """
    Print the largest files (top-N) restricting by:
      - glob pattern (default '*', includes extensionless)
      - one or more type groups (-g/--group)
      - minimum size
    Output: console table (default), or --csv / --json.
    """
    if args.csv and args.json:
        print("Error: Choose either --csv or --json, not both.", file=sys.stderr)
        sys.exit(2)

    search_type = "recursively" if args.recursive else "in the top-level directory"
    with TeeWriter(Path(args.output) if args.output else None, args.encoding) as w:
        if not (args.csv or args.json):
            w.write(
                f"Finding largest files {search_type} of '{args.path}' "
                f"(filter='{args.filter}', groups={args.group or 'none'}, min={format_bytes(args.min_size)})..."
            )

        heap: List[Tuple[int, str, Path, os.stat_result]] = []
        for p, st in get_files_from_path(args.path, args.filter, args.recursive):
            if st.st_size < args.min_size:
                continue
            if not _ext_matches_group(p, args.group or []):
                continue
            item = (st.st_size, p.name, p, st)
            if len(heap) < args.top:
                heapq.heappush(heap, item)
            else:
                if item > heap[0]:
                    heapq.heapreplace(heap, item)

        if not heap:
            if not (args.csv or args.json):
                w.write("No matching files found.")
            else:
                if args.csv:
                    w.write("size_bytes,size_human,mtime,atime,path")
                elif args.json:
                    w.write(json.dumps([], ensure_ascii=False))
            return

        rows = sorted(heap, key=lambda x: (x[0], x[1]), reverse=True)

        if args.csv or args.json:
            records = []
            for size, _, p, st in rows:
                record = {
                    "size_bytes": int(size),
                    "size_human": format_bytes(size),
                    "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(sep=" ", timespec="seconds"),
                    "atime": datetime.fromtimestamp(st.st_atime).isoformat(sep=" ", timespec="seconds"),
                    "path": safe_path_display(p, args.absolute),
                }
                records.append(record)
            if args.csv:
                w.write("size_bytes,size_human,mtime,atime,path")
                for r in records:
                    w.write(f"{r['size_bytes']},{r['size_human']},{r['mtime']},{r['atime']},{r['path']}")
            else:
                w.write(json.dumps(records, ensure_ascii=False))
            return

        try:
            console_width = shutil.get_terminal_size().columns
        except OSError:
            console_width = 120

        SIZE_W, DATE_W, SP = 10, 25, 2
        name_w = max(20, console_width - SIZE_W - DATE_W - SP)
        w.write("-" * console_width)
        w.write(f"{'Name':<{name_w}} {'Size':>{SIZE_W}} {'Modified':>{DATE_W}}")
        w.write(f"{'-'*name_w:<{name_w}} {'-'*SIZE_W:>{SIZE_W}} {'-'*DATE_W:>{DATE_W}}")
        for size, _, p, st in rows:
            size_str = format_bytes(size)
            date_str = datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            name_str = _name_for_console(p, args)
            if not args.output and not args.absolute and len(name_str) > name_w:
                name_str = name_str[: name_w - 3] + "..."
            w.write(f"{name_str:<{name_w}} {size_str:>{SIZE_W}} {date_str:>{DATE_W}}")
        w.write("-" * console_width)

# -------- Disk Free (df) ------------------------------------------------------

# POSIX pseudo FS types commonly excluded unless --all is provided
_SKIP_FSTYPES = {
    "proc", "sysfs", "devtmpfs", "tmpfs", "squashfs", "overlay", "ramfs",
    "cgroup", "cgroup2", "fusectl", "debugfs", "tracefs", "nsfs", "securityfs",
    "selinuxfs", "configfs", "efivarfs", "autofs", "binfmt_misc", "mqueue", "hugetlbfs",
}

# Filesystem types to *include* by default on POSIX
_INCLUDE_FSTYPES = {
    "ext2", "ext3", "ext4", "xfs", "btrfs", "zfs", "ntfs", "exfat", "vfat", "f2fs", "apfs", "hfs", "hfsplus"
}

def _posix_mounts(include_all: bool) -> List[Tuple[str, str]]:
    """
    Return list of (mount_point, fstype) on POSIX.
    Uses /proc/mounts if available; otherwise falls back to /etc/mtab.
    Filters out pseudo filesystems unless include_all is True.
    Deduplicates by real path (bind mounts).
    """
    candidates = []
    mounts_file = "/proc/mounts" if os.path.exists("/proc/mounts") else "/etc/mtab"
    try:
        with open(mounts_file, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 3:
                    continue
                _dev, mnt, fstype = parts[0], parts[1], parts[2]
                if not include_all:
                    if fstype in _SKIP_FSTYPES:
                        continue
                    if fstype not in _INCLUDE_FSTYPES and not mnt.startswith("/mnt"):
                        # allow external/mounted paths under /mnt even if fstype unknown
                        continue
                candidates.append((mnt, fstype))
    except Exception:
        # Best-effort: at least include root
        candidates = [("/", "unknown")]

    # Deduplicate by realpath
    seen = set()
    out: List[Tuple[str, str]] = []
    for mnt, fstype in candidates:
        try:
            rp = os.path.realpath(mnt)
        except Exception:
            rp = mnt
        if rp in seen:
            continue
        seen.add(rp)
        out.append((mnt, fstype))
    return out

def _windows_drives(include_all: bool) -> List[Tuple[str, str]]:
    """
    Return list of (mount_point, type_label) for Windows.
    Uses ctypes GetLogicalDrives/GetDriveTypeW to avoid extra deps.
    Filters to FIXED + REMOTE by default; includes REMOVABLE/CDROM/UNKNOWN when include_all.
    """
    drives: List[Tuple[str, str]] = []
    try:
        import ctypes  # lazy import
        GetLogicalDrives = ctypes.windll.kernel32.GetLogicalDrives
        GetDriveTypeW = ctypes.windll.kernel32.GetDriveTypeW
        DRIVE_UNKNOWN, DRIVE_NO_ROOT_DIR, DRIVE_REMOVABLE, DRIVE_FIXED, DRIVE_REMOTE, DRIVE_CDROM, DRIVE_RAMDISK = range(0, 7)
        bitmask = GetLogicalDrives()
        for i in range(26):
            if bitmask & (1 << i):
                root = f"{chr(ord('A') + i)}:\\"
                dtype = GetDriveTypeW(ctypes.c_wchar_p(root))
                label_map = {
                    DRIVE_UNKNOWN: "UNKNOWN",
                    DRIVE_NO_ROOT_DIR: "NO_ROOT",
                    DRIVE_REMOVABLE: "REMOVABLE",
                    DRIVE_FIXED: "FIXED",
                    DRIVE_REMOTE: "REMOTE",
                    DRIVE_CDROM: "CDROM",
                    DRIVE_RAMDISK: "RAMDISK",
                }
                label = label_map.get(dtype, "UNKNOWN")
                if not include_all and label not in {"FIXED", "REMOTE"}:
                    continue
                if os.path.exists(root):
                    drives.append((root, label))
    except Exception:
        # fallback: exists check
        for c in range(ord("A"), ord("Z") + 1):
            root = f"{chr(c)}:\\"
            if os.path.exists(root):
                drives.append((root, "FIXED"))
    return drives

def _gather_df(include_all: bool) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    if os.name == "nt":
        mounts = _windows_drives(include_all)
    else:
        mounts = _posix_mounts(include_all)

    for mnt, fstype in mounts:
        try:
            usage = shutil.disk_usage(mnt)
            total, used, free = int(usage.total), int(usage.used), int(usage.free)
            pct = (used / total * 100.0) if total > 0 else 0.0
            rows.append({
                "mount": mnt,
                "type": fstype,
                "total": total,
                "used": used,
                "free": free,
                "use_pct": pct,
            })
        except Exception:
            # Skip mounts we cannot stat (e.g., permissions/unavailable)
            continue
    return rows

def handle_df(args: argparse.Namespace) -> None:
    """Show per-drive/mount disk free/used/total with sorting and CSV/JSON export."""
    rows = _gather_df(include_all=args.all)

    # optional filter substring on mount path
    if args.filter:
        needle = args.filter.lower()
        rows = [r for r in rows if needle in str(r["mount"]).lower()]

    # sort
    sort_key_map = {
        "name": lambda r: str(r["mount"]),
        "total": lambda r: r["total"],
        "used":  lambda r: r["used"],
        "free":  lambda r: r["free"],
        "use%":  lambda r: r["use_pct"],
    }
    key_fn = sort_key_map[args.sort]
    reverse = args.sort in {"total", "used", "free", "use%"}
    rows.sort(key=key_fn, reverse=reverse)

    # truncate to top N if requested
    if args.top and args.top > 0:
        rows = rows[: args.top]

    with TeeWriter(Path(args.output) if args.output else None, args.encoding) as w:
        if args.json:
            out = [
                {
                    "mount": r["mount"],
                    "type": r["type"],
                    "total_bytes": r["total"],
                    "used_bytes": r["used"],
                    "free_bytes": r["free"],
                    "use_pct": round(r["use_pct"], 2),
                }
                for r in rows
            ]
            w.write(json.dumps(out, ensure_ascii=False))
            return

        if args.csv:
            w.write("mount,type,total,used,free,use_pct")
            for r in rows:
                w.write(f"{r['mount']},{r['type']},{r['total']},{r['used']},{r['free']},{r['use_pct']:.2f}")
            return

        # pretty table
        try:
            console_width = shutil.get_terminal_size().columns
        except OSError:
            console_width = 120
        NAME_W, TYPE_W, SIZE_W = 28, 10, 12
        # adjust a bit for very small/very large terminals
        NAME_W = max(12, min(40, console_width - (TYPE_W + SIZE_W * 3 + 12)))

        w.write(f"Disk free for {'ALL' if args.all else 'primary'} mounts...")
        w.write("-" * console_width)
        w.write(f"{'Mount':<{NAME_W}} {'Type':<{TYPE_W}} {'Total':>{SIZE_W}} {'Used':>{SIZE_W}} {'Free':>{SIZE_W}} {'Use%':>6}")
        w.write(f"{'-'*NAME_W:<{NAME_W}} {'-'*TYPE_W:<{TYPE_W}} {'-'*SIZE_W:>{SIZE_W}} {'-'*SIZE_W:>{SIZE_W}} {'-'*SIZE_W:>{SIZE_W}} {'-'*6:>6}")
        for r in rows:
            w.write(
                f"{str(r['mount']):<{NAME_W}} "
                f"{str(r['type']):<{TYPE_W}} "
                f"{format_bytes(int(r['total'])):>{SIZE_W}} "
                f"{format_bytes(int(r['used'])):>{SIZE_W}} "
                f"{format_bytes(int(r['free'])):>{SIZE_W}} "
                f"{r['use_pct']:>5.1f}%"
            )
        w.write("-" * console_width)

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

    # top-size (kept for compatibility; 'largest' is the superset)
    p_top = subparsers.add_parser("top-size", help="Find the largest files (compat; see 'largest').", parents=[common])
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

    # largest (any/glob/type groups; CSV/JSON)
    p_lg = subparsers.add_parser("largest", help="Show the largest files (any/glob/type groups).", parents=[common])
    p_lg.add_argument("-t", "--top", type=int, default=10, help="Number of files to list (default: 10).")
    p_lg.add_argument("-f", "--filter", default="*", help="Glob pattern (default: '*', includes extensionless).")
    p_lg.add_argument("-s", "--min-size", type=parse_size, default="0", help="Minimum size filter (default: 0).")
    p_lg.add_argument("-g", "--group", choices=sorted(TYPE_GROUPS.keys()), nargs="+", help="Filter by one or more type groups.")
    p_lg.add_argument("--csv", action="store_true", help="Emit CSV (size_bytes,size_human,mtime,atime,path).")
    p_lg.add_argument("--json", action="store_true", help="Emit JSON array of records.")

    # df (disk free per drive/mount)
    p_df = subparsers.add_parser("df", help="Show disk free/used/total per drive/mount.", parents=[common])
    p_df.add_argument("-t", "--top", type=int, default=0, help="Limit to top N rows after sort (0 = all).")
    p_df.add_argument("--sort", choices=["name", "total", "used", "free", "use%"], default="free",
                      help="Sort by column (default: free).")
    p_df.add_argument("--all", action="store_true", help="Include pseudo/temporary/removable mounts.")
    p_df.add_argument("--filter", default=None, help="Substring to match mount path (case-insensitive).")
    p_df.add_argument("--csv", action="store_true", help="Emit CSV.")
    p_df.add_argument("--json", action="store_true", help="Emit JSON.")

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
        "largest": handle_largest,
        "df": handle_df,
    }
    handler = handler_map[args.command]
    handler(args)

if __name__ == "__main__":
    main()
