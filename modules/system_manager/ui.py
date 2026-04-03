#!/usr/bin/env python3
"""
UI helpers for System Manager using TermDash.
"""

from __future__ import annotations
import sys
from typing import List, Dict, Any, Optional, Callable
from termdash.interactive_list import InteractiveList, render_items_to_text
from cross_platform.size_utils import format_bytes_binary

def generic_formatter(item: Dict[str, Any], sort_field: str, width: int, show_date: bool, show_time: bool, scroll_offset: int) -> str:
    """
    Format a dictionary as a space-separated string of its values.
    """
    # Exclude internal/private keys
    keys = [k for k in item.keys() if not k.startswith('_')]
    
    parts = []
    for k in keys:
        v = item[k]
        # Format sizes nicely if key looks like memory/size
        if any(term in k.lower() for term in ('memory', 'size', 'rss', 'vms')) and isinstance(v, (int, float)):
            v_str = format_bytes_binary(v)
        elif isinstance(v, float):
            v_str = f"{v:.1f}"
        else:
            v_str = str(v)
        parts.append(v_str)
    
    line = "  ".join(parts)
    
    # Simple horizontal scroll handling
    if scroll_offset > 0 and len(line) > width:
        line = line[scroll_offset:]
    
    return line.ljust(width)[:width]

def show_list(
    items: List[Dict[str, Any]], 
    title: str = "System Manager", 
    sort_field: Optional[str] = None,
    columns: Optional[List[str]] = None
):
    """
    Display a list of dictionaries in an interactive TUI.
    """
    if not items:
        print("No data to display.")
        return

    # If no items have the sort_field, pick the first key
    if not sort_field or sort_field not in items[0]:
        sort_field = next(iter(items[0].keys()))

    # Sorters: simple lambda for dict keys
    sorters = {k: (lambda x, key=k: x.get(key, "")) for k in items[0].keys()}
    
    # Column headers line
    if columns:
        col_line = "  ".join(columns)
    else:
        col_line = "  ".join([k.upper() for k in items[0].keys() if not k.startswith('_')])

    list_view = InteractiveList(
        items=items,
        sorters=sorters,
        formatter=generic_formatter,
        initial_sort=sort_field,
        header=title,
        columns_line=col_line,
        footer_lines=[
            "Up/Down/j/k: move | Left/Right: scroll | f: filter | x: exclude | ^Q: quit",
            "Enter: Details | q: Quit prompt"
        ]
    )
    
    try:
        list_view.run()
    except SystemExit as e:
        if e.code == 2:
            # Fallback to plain text if TUI fails
            lines = render_items_to_text(items, generic_formatter, sort_field=sort_field)
            print(f"=== {title} ===")
            print(col_line)
            for line in lines:
                print(line)
        else:
            raise
