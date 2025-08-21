#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
A command-line utility for finding and listing files based on size, date, and other criteria.
"""

import argparse
import hashlib
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

def get_files_from_path(search_path, file_filter, recursive):
    """Walks a path and yields file info, handling errors."""
    try:
        path_obj = Path(search_path)
        if not path_obj.is_dir():
            print(f"Error: Path '{search_path}' is not a valid directory.", file=sys.stderr)
            sys.exit(1)
        
        # Use rglob for recursive search, glob for non-recursive
        search_method = path_obj.rglob if recursive else path_obj.glob
        
        for file_path in search_method(file_filter):
            if file_path.is_file():
                try:
                    yield file_path, file_path.stat()
                except FileNotFoundError:
                    # File might have been deleted between glob and stat
                    continue
    except PermissionError:
        print(f"Error: Permission denied to read '{search_path}'.", file=sys.stderr)
        sys.exit(1)

def format_bytes(size_bytes):
    """Formats bytes into KB, MB, GB, etc."""
    if size_bytes == 0:
        return "0B"
    power = 1024
    n = 0
    power_labels = {0: '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while size_bytes >= power and n < len(power_labels):
        size_bytes /= power
        n += 1
    return f"{size_bytes:.2f}{power_labels[n]}B"

# --- Handler Functions for each utility ---

def handle_top_size(args):
    """Finds the top N largest files and formats the output to fit the console width."""
    search_type = "recursively" if args.recursive else "in the top-level directory"
    print(f"Searching for the {args.top} largest '{args.filter}' files {search_type} of '{args.path}'...")
    all_files = []
    for path_obj, stats in get_files_from_path(args.path, args.filter, args.recursive):
        all_files.append((path_obj, stats.st_size))

    all_files.sort(key=lambda x: x[1], reverse=True)

    try:
        console_width = shutil.get_terminal_size().columns
    except OSError:
        console_width = 80

    print("-" * console_width)
    for path_obj, size in all_files[:args.top]:
        size_gb = size / (1024**3)
        size_string = f"{size_gb:9.2f} GB "
        remaining_width = console_width - len(size_string) - 1
        if remaining_width < 10: remaining_width = 10
        filename = path_obj.name
        if len(filename) > remaining_width:
            filename = filename[:remaining_width]
        print(f"{size_string}{filename}")
    print("-" * console_width)

def handle_find_recent(args):
    """Finds files larger than a given size that were accessed within N days."""
    search_type = "recursively" if args.recursive else "in the top-level directory"
    print(f"Searching {search_type} of '{args.path}' for '{args.filter}' files > {args.size} GB accessed in the last {args.days} days...")
    
    size_threshold_bytes = args.size * (1024**3)
    cutoff_datetime = datetime.now() - timedelta(days=args.days)
    cutoff_timestamp = cutoff_datetime.timestamp()
    
    recent_files = []
    for path_obj, stats in get_files_from_path(args.path, args.filter, args.recursive):
        if stats.st_size > size_threshold_bytes and stats.st_atime > cutoff_timestamp:
            recent_files.append((path_obj, stats))

    recent_files.sort(key=lambda x: x[1].st_size, reverse=True)

    if not recent_files:
        print("No matching files found.")
        return

    try:
        console_width = shutil.get_terminal_size().columns
    except OSError:
        console_width = 80
    
    SIZE_WIDTH, DATE_WIDTH, SPACING = 10, 25, 2
    name_width = console_width - SIZE_WIDTH - DATE_WIDTH - SPACING
    if name_width < 20: name_width = 20

    header_name, header_date = "Name", "Last Accessed"
    print(f"\n{header_name:<{name_width}} {'Size':>{SIZE_WIDTH}} {header_date:>{DATE_WIDTH}}")
    print(f"{'-'*name_width:<{name_width}} {'-'*SIZE_WIDTH:>{SIZE_WIDTH}} {'-'*DATE_WIDTH:>{DATE_WIDTH}}")
    
    for path_obj, stats in recent_files:
        size_str = format_bytes(stats.st_size)
        access_time = datetime.fromtimestamp(stats.st_atime).strftime('%Y-%m-%d %H:%M:%S')
        filename = path_obj.name
        if len(filename) > name_width:
            filename = filename[:name_width - 3] + '...'
        print(f"{filename:<{name_width}} {size_str:>{SIZE_WIDTH}} {access_time:>{DATE_WIDTH}}")

def handle_find_old(args):
    """Finds the largest files that are older than a specified cutoff date."""
    date_type_full = args.date_type
    if date_type_full in ('a', 'm', 'c'):
        mapper = {'a': 'accessed', 'm': 'modified', 'c': 'created'}
        date_type_full = mapper[date_type_full]

    search_type = "recursively" if args.recursive else "in the top-level directory"
    print(f"Searching {search_type} of '{args.path}' for top {args.top} '{args.filter}' files not {date_type_full} since {args.cutoff_days} days ago...")

    cutoff_datetime = datetime.now() - timedelta(days=args.cutoff_days)
    cutoff_timestamp = cutoff_datetime.timestamp()

    date_type_map = {'accessed': 'st_atime', 'modified': 'st_mtime', 'created': 'st_ctime'}
    date_attr = date_type_map[date_type_full]

    old_files = []
    for path_obj, stats in get_files_from_path(args.path, args.filter, args.recursive):
        if getattr(stats, date_attr) < cutoff_timestamp:
            old_files.append((path_obj, stats))
    
    old_files.sort(key=lambda x: x[1].st_size, reverse=True)

    if not old_files:
        print("No matching files found.")
        return

    try:
        console_width = shutil.get_terminal_size().columns
    except OSError:
        console_width = 80
    
    SIZE_WIDTH, DATE_WIDTH, SPACING = 10, 25, 2
    name_width = console_width - SIZE_WIDTH - DATE_WIDTH - SPACING
    if name_width < 20: name_width = 20
    
    header_name = "Name"
    header_date = f"{date_type_full.capitalize()} Date"
    print(f"\n{header_name:<{name_width}} {'Size':>{SIZE_WIDTH}} {header_date:>{DATE_WIDTH}}")
    print(f"{'-'*name_width:<{name_width}} {'-'*SIZE_WIDTH:>{SIZE_WIDTH}} {'-'*DATE_WIDTH:>{DATE_WIDTH}}")

    for path_obj, stats in old_files[:args.top]:
        size_str = format_bytes(stats.st_size)
        date_str = datetime.fromtimestamp(getattr(stats, date_attr)).strftime('%Y-%m-%d %H:%M:%S')
        filename = path_obj.name
        if len(filename) > name_width:
            filename = filename[:name_width - 3] + '...'
        print(f"{filename:<{name_width}} {size_str:>{SIZE_WIDTH}} {date_str:>{DATE_WIDTH}}")

def handle_find_dupes(args):
    """Finds files with identical content."""
    search_type = "recursively" if args.recursive else "in the top-level directory"
    min_size_str = format_bytes(args.min_size)
    print(f"Scanning for duplicate files {search_type} in '{args.path}' (min size: {min_size_str})...")

    files_by_size = defaultdict(list)
    for path_obj, stats in get_files_from_path(args.path, "*.*", args.recursive):
        if stats.st_size >= args.min_size:
            files_by_size[stats.st_size].append(path_obj)
    
    files_by_hash = defaultdict(list)
    potential_dupes = {size: paths for size, paths in files_by_size.items() if len(paths) > 1}
    
    print("Analyzing potential duplicates...")
    for size, paths in potential_dupes.items():
        for path in paths:
            try:
                hasher = hashlib.sha256()
                with open(path, 'rb') as f:
                    while chunk := f.read(8192):
                        hasher.update(chunk)
                files_by_hash[hasher.hexdigest()].append(path)
            except (IOError, OSError):
                continue
    
    actual_dupes = {h: paths for h, paths in files_by_hash.items() if len(paths) > 1}
    
    if not actual_dupes:
        print("No duplicate files found.")
        return

    print("\n--- Found Duplicate Sets ---")
    for h, paths in actual_dupes.items():
        size_str = format_bytes(paths[0].stat().st_size)
        print(f"\nHash: {h[:16]}... ({len(paths)} files, size: {size_str})")
        for path in paths:
            print(f"  - {path}")

def handle_summarize(args):
    """Provides a summary of directory contents by file extension."""
    search_type = "recursively" if args.recursive else "in the top-level directory"
    print(f"Summarizing directory '{args.path}' {search_type}...")
    
    summary = defaultdict(lambda: {'count': 0, 'size': 0})
    for path_obj, stats in get_files_from_path(args.path, "*.*", args.recursive):
        ext = path_obj.suffix.lower() or '[no extension]'
        summary[ext]['count'] += 1
        summary[ext]['size'] += stats.st_size
    
    if not summary:
        print("No files found to summarize.")
        return
        
    sorted_summary = sorted(summary.items(), key=lambda item: item[1]['size'], reverse=True)
    
    print(f"\n{'Extension':<20} {'Count':>10} {'Total Size':>15}")
    print(f"{'-'*20:<20} {'-'*10:>10} {'-'*15:>15}")
    
    for ext, data in sorted_summary[:args.top]:
        size_str = format_bytes(data['size'])
        print(f"{ext:<20} {data['count']:>10} {size_str:>15}")

def main():
    """Main function to parse arguments and call the appropriate handler."""
    parser = argparse.ArgumentParser(
        description="A command-line utility for finding and managing files.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", help="Available utilities", required=True)

    # --- Parent parser for common arguments ---
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument('-p', '--path', default='.', help='The directory to search (default: current directory).')
    common_parser.add_argument('-r', '--recursive', action='store_true', help='Enable recursive search into subdirectories.')

    # --- Parser for 'top-size' utility ---
    parser_top = subparsers.add_parser('top-size', help='Find the largest files.', parents=[common_parser])
    parser_top.add_argument('-t', '--top', type=int, default=10, help='The number of files to list (default: 10).')
    parser_top.add_argument('-f', '--filter', default='*.*', help='The file filter/pattern to use (default: "*.*").')

    # --- Parser for 'find-recent' utility ---
    parser_recent = subparsers.add_parser('find-recent', help='Find large files accessed recently.', parents=[common_parser])
    parser_recent.add_argument('-s', '--size', type=float, default=1.0, help='The minimum file size in GB (default: 1.0).')
    parser_recent.add_argument('-d', '--days', type=int, default=30, help='How many days back to consider "recent" (default: 30).')
    parser_recent.add_argument('-f', '--filter', default='*.*', help='The file filter/pattern to use (default: "*.*").')

    # --- Parser for 'find-old' utility ---
    parser_old = subparsers.add_parser('find-old', help='Find large files untouched since a cutoff date.', parents=[common_parser])
    parser_old.add_argument('-c', '--cutoff-days', type=int, default=30, help='The number of days ago for the cutoff (default: 30).')
    parser_old.add_argument('-t', '--top', type=int, default=10, help='The number of files to list (default: 10).')
    parser_old.add_argument('-d', '--date-type', choices=['accessed', 'a', 'modified', 'm', 'created', 'c'], default='a', help='Date to check. Abbreviate: a, m, c (default: accessed).')
    parser_old.add_argument('-f', '--filter', default='*.*', help='The file filter/pattern to use (default: "*.*").')
    
    # --- Parser for 'find-dupes' utility ---
    parser_dupes = subparsers.add_parser('find-dupes', help='Find files with identical content.', parents=[common_parser])
    parser_dupes.add_argument('-m', '--min-size', type=int, default=1, help='Minimum file size in bytes to check (default: 1).')

    # --- Parser for 'summarize' utility ---
    parser_summary = subparsers.add_parser('summarize', help='Show a breakdown of disk usage by file type.', parents=[common_parser])
    parser_summary.add_argument('-t', '--top', type=int, default=20, help='Show the top N extensions by size (default: 20).')

    args = parser.parse_args()
    handler_map = {
        'top-size': handle_top_size,
        'find-recent': handle_find_recent,
        'find-old': handle_find_old,
        'find-dupes': handle_find_dupes,
        'summarize': handle_summarize
    }
    handler_map[args.command](args)

if __name__ == "__main__":
    main()
