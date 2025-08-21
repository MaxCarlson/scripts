#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
A command-line utility for finding and listing files based on size, date, and other criteria.
"""

import argparse
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

def get_files_from_path(search_path, file_filter):
    """Walks a path and yields file info, handling errors."""
    try:
        if not Path(search_path).is_dir():
            print(f"Error: Path '{search_path}' is not a valid directory.", file=sys.stderr)
            sys.exit(1)

        for path_obj in Path(search_path).rglob(file_filter):
            if path_obj.is_file():
                try:
                    yield path_obj, path_obj.stat()
                except FileNotFoundError:
                    # File might have been deleted between rglob and stat
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

def handle_top_size(args):
    """
    Finds the top N largest files and formats the output to fit the console width.
    """
    print(f"Searching for the {args.top} largest '{args.filter}' files in '{args.path}'...")
    all_files = []
    for path_obj, stats in get_files_from_path(args.path, args.filter):
        all_files.append((path_obj, stats.st_size))

    # Sort by size (item[1]) in descending order
    all_files.sort(key=lambda x: x[1], reverse=True)

    # Get terminal width for formatting
    try:
        console_width = shutil.get_terminal_size().columns
    except OSError:
        console_width = 80 # Default if not in a real terminal

    print("-" * console_width)
    for path_obj, size in all_files[:args.top]:
        size_gb = size / (1024**3)
        size_string = f"{size_gb:9.2f} GB " # e.g., "   123.45 GB "

        remaining_width = console_width - len(size_string) - 1
        if remaining_width < 10: # Ensure there's reasonable space
            remaining_width = 10
        
        filename = path_obj.name
        if len(filename) > remaining_width:
            filename = filename[:remaining_width]

        print(f"{size_string}{filename}")
    print("-" * console_width)


def handle_find_recent(args):
    """
    Finds files larger than a given size that were accessed within N days.
    """
    print(f"Searching in '{args.path}' for '{args.filter}' files > {args.size} GB accessed in the last {args.days} days...")
    
    size_threshold_bytes = args.size * (1024**3)
    cutoff_datetime = datetime.now() - timedelta(days=args.days)
    cutoff_timestamp = cutoff_datetime.timestamp()
    
    recent_files = []
    for path_obj, stats in get_files_from_path(args.path, args.filter):
        if stats.st_size > size_threshold_bytes and stats.st_atime > cutoff_timestamp:
            recent_files.append((path_obj, stats))

    # Sort by size in descending order
    recent_files.sort(key=lambda x: x[1].st_size, reverse=True)

    if not recent_files:
        print("No matching files found.")
        return

    # Dynamic column formatting
    try:
        console_width = shutil.get_terminal_size().columns
    except OSError:
        console_width = 80
    
    SIZE_WIDTH = 10
    DATE_WIDTH = 25
    SPACING = 2
    name_width = console_width - SIZE_WIDTH - DATE_WIDTH - SPACING
    if name_width < 20: name_width = 20

    header_name = "Name"
    header_date = "Last Accessed"
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
    """
    Finds the largest files that are older than a specified cutoff date.
    """
    # Normalize date_type abbreviation
    date_type_full = args.date_type
    if date_type_full in ('a', 'm', 'c'):
        mapper = {'a': 'accessed', 'm': 'modified', 'c': 'created'}
        date_type_full = mapper[date_type_full]

    print(f"Searching in '{args.path}' for top {args.top} '{args.filter}' files not {date_type_full} since {args.cutoff_days} days ago...")

    cutoff_datetime = datetime.now() - timedelta(days=args.cutoff_days)
    cutoff_timestamp = cutoff_datetime.timestamp()

    date_type_map = {
        'accessed': 'st_atime',
        'modified': 'st_mtime',
        'created': 'st_ctime'
    }
    date_attr = date_type_map[date_type_full]

    old_files = []
    for path_obj, stats in get_files_from_path(args.path, args.filter):
        file_timestamp = getattr(stats, date_attr)
        if file_timestamp < cutoff_timestamp:
            old_files.append((path_obj, stats))
    
    # Sort by size in descending order
    old_files.sort(key=lambda x: x[1].st_size, reverse=True)

    if not old_files:
        print("No matching files found.")
        return

    # Dynamic column formatting
    try:
        console_width = shutil.get_terminal_size().columns
    except OSError:
        console_width = 80
    
    SIZE_WIDTH = 10
    DATE_WIDTH = 25
    SPACING = 2
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


def main():
    """Main function to parse arguments and call the appropriate handler."""
    parser = argparse.ArgumentParser(
        description="A command-line utility for finding files.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", help="Available utilities", required=True)

    # --- Parser for 'top-size' utility ---
    parser_top = subparsers.add_parser(
        'top-size', 
        help='Find the largest files and format output to fit the console.'
    )
    parser_top.add_argument('-p', '--path', default='.', help='The directory to search (default: current directory).')
    parser_top.add_argument('-t', '--top', type=int, default=10, help='The number of files to list (default: 10).')
    parser_top.add_argument('-f', '--filter', default='*.*', help='The file filter/pattern to use (default: "*.*").')

    # --- Parser for 'find-recent' utility ---
    parser_recent = subparsers.add_parser(
        'find-recent', 
        help='Find files larger than a given size accessed recently.'
    )
    parser_recent.add_argument('-p', '--path', default='.', help='The directory to search (default: current directory).')
    parser_recent.add_argument('-s', '--size', type=float, default=1.0, help='The minimum file size in GB (default: 1.0).')
    parser_recent.add_argument('-d', '--days', type=int, default=30, help='How many days back to consider "recent" (default: 30).')
    parser_recent.add_argument('-f', '--filter', default='*.*', help='The file filter/pattern to use (default: "*.*").')

    # --- Parser for 'find-old' utility ---
    parser_old = subparsers.add_parser(
        'find-old', 
        help='Find the largest files untouched since a cutoff date.'
    )
    parser_old.add_argument('-p', '--path', default='.', help='The directory to search (default: current directory).')
    parser_old.add_argument('-c', '--cutoff-days', type=int, default=30, help='The number of days ago for the cutoff (default: 30).')
    parser_old.add_argument('-t', '--top', type=int, default=10, help='The number of files to list (default: 10).')
    parser_old.add_argument(
        '-d', '--date-type', 
        choices=['accessed', 'a', 'modified', 'm', 'created', 'c'], 
        default='accessed', 
        help='''The date timestamp to check.
Can be abbreviated: a=accessed, m=modified, c=created.
(default: accessed)'''
    )
    parser_old.add_argument('-f', '--filter', default='*.*', help='The file filter/pattern to use (default: "*.*").')

    args = parser.parse_args()

    # Dispatch to the correct handler function
    if args.command == 'top-size':
        handle_top_size(args)
    elif args.command == 'find-recent':
        handle_find_recent(args)
    elif args.command == 'find-old':
        handle_find_old(args)

if __name__ == "__main__":
    main()
