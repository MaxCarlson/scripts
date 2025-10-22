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

def format_entry_line(entry: Entry, sort_field: str, width: int) -> str:
    time_source = entry.created
    if sort_field in DATE_FIELDS:
        time_source = getattr(entry, sort_field)
    timestamp = time_source.strftime("%Y-%m-%d %H:%M:%S")
    size_text = human_size(entry.size)
    
    indent = "  " * entry.depth
    name = f"{indent}{entry.name}" + ("/" if entry.is_dir else "")

    name_space = max(1, width - len(timestamp) - len(size_text) - 4)
    if len(name) > name_space:
        name = name[:name_space - 3] + "..." if name_space > 3 else name[:name_space]
    
    return f"{timestamp}  {name.ljust(name_space)}  {size_text}"

def filter_entry(entry: Entry, pattern: str) -> bool:
    return fnmatch(entry.name, pattern)

def run_lister(args: argparse.Namespace) -> int:
    target = Path(args.directory).expanduser()

    if not target.exists() or not target.is_dir():
        sys.stderr.write(f"Path does not exist or is not a directory: {target}\n")
        return 1

    entries = read_entries_recursive(target, args.depth)

    sort_keys_mapping = {
        ord("c"): "created",
        ord("m"): "modified",
        ord("a"): "accessed",
        ord("s"): "size",
        ord("n"): "name",
    }

    footer_lines = [
        "Up/Down: move | f: filter | Ctrl+Q: quit",
        "c: created | m: modified | a: accessed | n: name | s: size",
        "Repeat sort key to toggle order",
    ]

    list_view = InteractiveList(
        items=entries,
        sorters=SORT_FUNCS,
        formatter=format_entry_line,
        filter_func=filter_entry,
        initial_sort=args.sort,
        initial_order=args.order,
        header=f"Path: {target}",
        sort_keys_mapping=sort_keys_mapping,
        footer_lines=footer_lines,
    )
    
    if args.glob:
        list_view.state.filter_pattern = args.glob

    list_view.run()
    return 0
