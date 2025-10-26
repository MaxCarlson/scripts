from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path
from typing import Callable, Dict, List, Any

from termdash.interactive_list import InteractiveList

@dataclass
class Entry:
    path: Path
    name: str
    is_dir: bool
    size: int
    created: datetime
    modified: datetime
    accessed: datetime
    depth: int

SORT_FUNCS: Dict[str, Callable[[Entry], object]] = {
    "created": lambda entry: entry.created.timestamp(),
    "modified": lambda entry: entry.modified.timestamp(),
    "accessed": lambda entry: entry.accessed.timestamp(),
    "size": lambda entry: entry.size,
    "name": lambda entry: entry.name.lower(),
}

DATE_FIELDS = {"created", "modified", "accessed"}

def human_size(num: int) -> str:
    step_unit = 1024.0
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if value < step_unit or unit == "PB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= step_unit
    return f"{value:.1f} PB"

def read_entries_recursive(target: Path, max_depth: int) -> List[Entry]:
    entries: List[Entry] = []
    
    def _walk(curr_path: Path, current_depth: int):
        if current_depth > max_depth:
            return
        try:
            for item in curr_path.iterdir():
                try:
                    stats = item.stat()
                    entries.append(
                        Entry(
                            path=item,
                            name=item.name,
                            is_dir=item.is_dir(),
                            size=stats.st_size,
                            created=datetime.fromtimestamp(stats.st_ctime),
                            modified=datetime.fromtimestamp(stats.st_mtime),
                            accessed=datetime.fromtimestamp(stats.st_atime),
                            depth=current_depth,
                        )
                    )
                    if item.is_dir():
                        _walk(item, current_depth + 1)
                except OSError:
                    continue
        except OSError as exc:
            sys.stderr.write(f"Cannot read directory {curr_path}: {exc}\n")

    _walk(target, 0)
    return entries

def format_entry_line(entry: Entry, sort_field: str, width: int, show_date: bool = True, show_time: bool = True) -> str:
    time_source = entry.created
    if sort_field in DATE_FIELDS:
        time_source = getattr(entry, sort_field)

    # Build timestamp based on visibility flags
    timestamp_parts = []
    if show_date:
        timestamp_parts.append(time_source.strftime("%Y-%m-%d"))
    if show_time:
        timestamp_parts.append(time_source.strftime("%H:%M:%S"))

    timestamp = " ".join(timestamp_parts) if timestamp_parts else ""
    size_text = human_size(entry.size)

    indent = "  " * entry.depth
    name = f"{indent}{entry.name}" + ("/" if entry.is_dir else "")

    # Calculate available space for name
    timestamp_len = len(timestamp) + 2 if timestamp else 0
    size_len = len(size_text) + 2
    name_space = max(1, width - timestamp_len - size_len)

    if len(name) > name_space:
        name = name[:name_space - 3] + "..." if name_space > 3 else name[:name_space]

    # Build final line
    if timestamp:
        return f"{timestamp}  {name.ljust(name_space)}  {size_text}"
    else:
        return f"{name.ljust(name_space)}  {size_text}"

def filter_entry(entry: Entry, pattern: str) -> bool:
    return fnmatch(entry.name, pattern)

def detail_formatter(entry: Entry) -> List[str]:
    """Format detailed information about a file/directory entry."""
    lines = []
    lines.append(f"Name: {entry.name}")
    lines.append(f"Path: {entry.path}")
    lines.append(f"Type: {'Directory' if entry.is_dir else 'File'}")
    lines.append(f"Size: {human_size(entry.size)} ({entry.size:,} bytes)")
    lines.append(f"Created:  {entry.created.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Modified: {entry.modified.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Accessed: {entry.accessed.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Depth: {entry.depth}")
    return lines

def size_extractor(entry: Entry) -> int:
    """Extract size from an entry for color gradient calculation."""
    return entry.size

def run_lister(args: argparse.Namespace) -> int:
    target = Path(args.directory).expanduser()

    if not target.exists() or not target.is_dir():
        sys.stderr.write(f"Path does not exist or is not a directory: {target}\n")
        return 1

    entries = read_entries_recursive(target, args.depth)

    # Normalize abbreviated sort field names
    sort_field_map = {
        "c": "created",
        "m": "modified",
        "a": "accessed",
        "s": "size",
        "n": "name",
    }
    sort_field = sort_field_map.get(args.sort, args.sort)

    # If JSON output requested, skip TUI
    if getattr(args, "json", False):
        import json
        from datetime import datetime

        # Apply filter if specified
        if args.glob:
            entries = [e for e in entries if filter_entry(e, args.glob)]

        # Sort entries
        entries.sort(key=SORT_FUNCS[sort_field], reverse=(args.order == "desc"))

        # Convert to JSON
        output = [
            {
                "path": str(e.path),
                "name": e.name,
                "is_dir": e.is_dir,
                "size": e.size,
                "size_human": human_size(e.size),
                "created": e.created.isoformat(),
                "modified": e.modified.isoformat(),
                "accessed": e.accessed.isoformat(),
                "depth": e.depth,
            }
            for e in entries
        ]
        print(json.dumps(output, indent=2))
        return 0

    sort_keys_mapping = {
        ord("c"): "created",
        ord("m"): "modified",
        ord("a"): "accessed",
        ord("s"): "size",
        ord("n"): "name",
    }

    footer_lines = [
        "Up/Down/j/k: move | f: filter | Enter: details | Left/Right: scroll | Ctrl+Q: quit",
        "c: created | m: modified | a: accessed | n: name | s: size",
        "d: toggle date | t: toggle time | Repeat sort key to toggle order",
    ]

    list_view = InteractiveList(
        items=entries,
        sorters=SORT_FUNCS,
        formatter=format_entry_line,
        filter_func=filter_entry,
        initial_sort=sort_field,
        initial_order=args.order,
        header=f"Path: {target}",
        sort_keys_mapping=sort_keys_mapping,
        footer_lines=footer_lines,
        detail_formatter=detail_formatter,
        size_extractor=size_extractor,
        enable_color_gradient=True,
    )

    if args.glob:
        list_view.state.filter_pattern = args.glob

    list_view.run()
    return 0
