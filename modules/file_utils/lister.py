from __future__ import annotations

import argparse
import curses
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path
from typing import Callable, Dict, List, Any, Tuple, Optional

from termdash.interactive_list import InteractiveList

try:
    from cross_platform.clipboard_utils import set_clipboard
    CLIPBOARD_AVAILABLE = True
except ImportError:
    CLIPBOARD_AVAILABLE = False

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
    expanded: bool = False  # Track if directory is expanded
    parent_path: Path = None  # Track parent for filtering
    calculated_size: Optional[int] = None  # Actual recursive size for folders
    item_count: Optional[int] = None  # Number of items in folder
    size_calculating: bool = False  # Show spinner while calculating

    def get_display_size(self) -> int:
        """Return calculated size if available, else stat size."""
        return self.calculated_size if self.calculated_size is not None else self.size

    def has_calculated_size(self) -> bool:
        """Check if folder size has been calculated."""
        return self.calculated_size is not None

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

def calculate_folder_size(path: Path) -> Tuple[int, int]:
    """Calculate total size and item count for a folder recursively.
    Returns (total_bytes, item_count)."""
    total_size = 0
    item_count = 0

    try:
        for item in path.rglob('*'):
            try:
                if item.is_file():
                    total_size += item.stat().st_size
                    item_count += 1
                elif item.is_dir():
                    item_count += 1
            except (OSError, PermissionError):
                continue
    except (OSError, PermissionError):
        pass

    return total_size, item_count

def read_entries_recursive(target: Path, max_depth: int, parent_path: Path = None) -> List[Entry]:
    entries: List[Entry] = []

    def _walk(curr_path: Path, current_depth: int, parent: Path = None):
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
                            expanded=False,
                            parent_path=parent,
                        )
                    )
                    if item.is_dir():
                        # Pass the current item's path as parent for its children
                        _walk(item, current_depth + 1, item)
                except OSError:
                    continue
        except OSError as exc:
            sys.stderr.write(f"Cannot read directory {curr_path}: {exc}\n")

    _walk(target, 0, parent_path)
    return entries

def format_entry_line(entry: Entry, sort_field: str, width: int, show_date: bool = True, show_time: bool = True, scroll_offset: int = 0) -> str:
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

    # For folders, show calculated size if available, otherwise show blank or spinner
    if entry.is_dir:
        if entry.size_calculating:
            size_text = "[...]"  # Spinner/progress indicator
        elif entry.has_calculated_size():
            size_text = human_size(entry.get_display_size())
            # Add item count for expanded folders
            if entry.expanded and entry.item_count is not None:
                size_text = f"{size_text} ({entry.item_count} items)"
        else:
            size_text = ""  # Blank if not calculated
    else:
        size_text = human_size(entry.size)

    indent = "  " * entry.depth
    # Add expansion indicator for directories
    if entry.is_dir:
        indicator = "▼ " if entry.expanded else "▶ "
        name = f"{indent}{indicator}{entry.name}/"
    else:
        name = f"{indent}  {entry.name}"

    # Calculate available space for name
    timestamp_len = len(timestamp) + 2 if timestamp else 0
    size_len = len(size_text) + 2
    name_space = max(1, width - timestamp_len - size_len)

    # Apply scroll offset to the name (not the whole line)
    if scroll_offset > 0 and len(name) > name_space:
        # Scroll through the name part only
        max_scroll = max(0, len(name) - name_space)
        actual_offset = min(scroll_offset, max_scroll)
        scrolled_name = name[actual_offset:]
        if len(scrolled_name) > name_space:
            scrolled_name = scrolled_name[:name_space - 3] + "..."
        name = scrolled_name.ljust(name_space)
    elif len(name) > name_space:
        name = name[:name_space - 3] + "..." if name_space > 3 else name[:name_space]
    else:
        name = name.ljust(name_space)

    # Build final line
    if timestamp:
        line = f"{timestamp}  {name}  {size_text}"
    else:
        line = f"{name}  {size_text}"

    return line

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

class FileTypeColorManager:
    """Manages file type to color mappings."""

    # Map color names to curses color pair numbers
    COLOR_MAP = {
        "white": 1,
        "cyan": 2,
        "yellow": 3,
        "green": 9,
        "red": 10,
        "blue": 11,
        "magenta": 12,
    }

    def __init__(self, config_path: Optional[Path] = None):
        self.config: Dict[str, Any] = {}
        self.load_config(config_path)

    def load_config(self, config_path: Optional[Path] = None):
        """Load color config from JSON file."""
        import json

        if config_path is None:
            # Try XDG first, fallback to module dir
            xdg_path = Path.home() / ".config" / "file-util" / "file_type_colors.json"
            module_path = Path(__file__).parent / "file_type_colors.json"

            if xdg_path.exists():
                config_path = xdg_path
            elif module_path.exists():
                config_path = module_path
            else:
                # Use defaults
                self.config = {"directories": "cyan", "extensions": {}, "default": "white"}
                return

        try:
            with open(config_path, 'r') as f:
                self.config = json.load(f)
        except Exception as e:
            sys.stderr.write(f"Failed to load color config from {config_path}: {e}\n")
            self.config = {"directories": "cyan", "extensions": {}, "default": "white"}

    def get_color_pair(self, entry: Entry) -> int:
        """Get curses color pair number for an entry."""
        if entry.is_dir:
            color_name = self.config.get("directories", "cyan")
        else:
            ext = entry.path.suffix.lower()
            extensions = self.config.get("extensions", {})
            # Skip comment entries (those starting with _comment)
            color_name = extensions.get(ext, self.config.get("default", "white"))

        return self.COLOR_MAP.get(color_name, 1)  # Default to white

class ListerManager:
    """Manages the state and actions for the interactive file lister."""

    def __init__(self, all_entries: List[Entry], max_depth: int):
        self.all_entries = all_entries
        self.max_depth = max_depth
        self.expanded_folders = set()  # Set of expanded folder paths
        self.hidden_entries = set()  # Set of hidden entry paths

    def get_visible_entries(self, sort_func: Optional[Callable[[Entry], object]] = None, descending: bool = True) -> List[Entry]:
        """Get the list of currently visible entries in hierarchical order.

        Returns entries sorted hierarchically: parent, then its children, then next parent.
        This maintains the tree structure while respecting the sort order.
        """
        visible = []

        def add_entry_and_children(entry: Entry):
            """Recursively add entry and its children if expanded."""
            visible.append(entry)

            # If this entry is an expanded folder, add its children
            if entry.is_dir and entry.path in self.expanded_folders:
                # Get all direct children
                children = [e for e in self.all_entries if e.parent_path == entry.path]

                # Sort children if sort function provided
                if sort_func:
                    children.sort(key=sort_func, reverse=descending)

                # Recursively add each child and their children
                for child in children:
                    add_entry_and_children(child)

        # Get top-level entries (those with no parent or parent not in our list)
        top_level = [e for e in self.all_entries if e.parent_path is None or
                     not any(p.path == e.parent_path for p in self.all_entries)]

        # Sort top-level entries
        if sort_func:
            top_level.sort(key=sort_func, reverse=descending)

        # Build hierarchical list
        for entry in top_level:
            add_entry_and_children(entry)

        return visible

    def _should_hide(self, entry: Entry) -> bool:
        """Check if entry should be hidden due to collapsed parent."""
        # Walk up the parent chain
        current_path = entry.parent_path
        while current_path:
            if current_path not in self.expanded_folders:
                # Parent is not expanded, so hide this entry
                return True
            # Find parent entry to continue walking up
            parent_entry = next((e for e in self.all_entries if e.path == current_path), None)
            if not parent_entry:
                break
            current_path = parent_entry.parent_path
        return False

    def toggle_folder(self, entry: Entry) -> bool:
        """Toggle folder expansion. Dynamically loads contents if not already loaded. Returns True if state changed."""
        if not entry.is_dir:
            return False

        if entry.path in self.expanded_folders:
            # Collapse
            self.expanded_folders.discard(entry.path)
            entry.expanded = False
        else:
            # Expand - check if children need to be loaded
            has_children = any(e.parent_path == entry.path for e in self.all_entries)

            if not has_children:
                # Dynamically load this folder's contents (1 level only)
                try:
                    new_entries = []
                    stats_list = []
                    for item in entry.path.iterdir():
                        try:
                            stats = item.stat()
                            stats_list.append((item, stats))
                        except OSError:
                            continue

                    for item, stats in stats_list:
                        new_entries.append(
                            Entry(
                                path=item,
                                name=item.name,
                                is_dir=item.is_dir(),
                                size=stats.st_size,
                                created=datetime.fromtimestamp(stats.st_ctime),
                                modified=datetime.fromtimestamp(stats.st_mtime),
                                accessed=datetime.fromtimestamp(stats.st_atime),
                                depth=entry.depth + 1,
                                expanded=False,
                                parent_path=entry.path,
                            )
                        )

                    self.all_entries.extend(new_entries)
                except OSError as e:
                    sys.stderr.write(f"Failed to read directory {entry.path}: {e}\n")

            self.expanded_folders.add(entry.path)
            entry.expanded = True
        return True

    def expand_all_at_depth(self, depth: int):
        """Expand all folders at the specified depth."""
        for entry in self.all_entries:
            if entry.is_dir and entry.depth == depth and not self._should_hide(entry):
                self.expanded_folders.add(entry.path)
                entry.expanded = True

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

    # Initialize the lister manager
    manager = ListerManager(entries, args.depth)

    # Initialize file type color manager
    file_color_manager = FileTypeColorManager()

    # Note: Depth 0 items are visible by default since their parent_path is None

    def action_handler(key: int, item: Entry) -> Tuple[bool, bool]:
        """Handle custom actions for folder navigation.
        Returns (handled, should_refresh)"""
        # ESC key - cancel calculation or collapse parent folder
        if key == 27:  # ESC
            # Check if calculation is running
            if list_view.state.calculating_sizes:
                list_view.state.calc_cancel = True
                list_view.state.calculating_sizes = False
                return True, False

            if item.parent_path:
                # Find the parent folder
                parent = next((e for e in manager.all_entries if e.path == item.parent_path), None)
                if parent and parent.expanded:
                    # Collapse the parent
                    manager.toggle_folder(parent)
                    # Update visible entries
                    sort_func = SORT_FUNCS[list_view.state.sort_field]
                    new_visible = manager.get_visible_entries(sort_func, list_view.state.descending)
                    list_view.state.items = new_visible
                    list_view.state.visible = new_visible

                    # Find parent in new visible list and move selection to it
                    try:
                        parent_idx = new_visible.index(parent)
                        list_view.state.selected_index = parent_idx
                        # Adjust scroll if needed
                        if parent_idx < list_view.state.top_index:
                            list_view.state.top_index = parent_idx
                        elif parent_idx >= list_view.state.top_index + list_view.state.viewport_height:
                            list_view.state.top_index = parent_idx - list_view.state.viewport_height + 1
                    except ValueError:
                        pass  # Parent not in visible list

                    return True, False  # Handled, don't call _update_visible_items
            return False, False  # Not in expanded folder, let default ESC handling

        # Enter key - toggle folder expansion inline
        elif key in (curses.KEY_ENTER, 10, 13):
            if item.is_dir:
                manager.toggle_folder(item)
                # Update the items list to reflect expansion (with hierarchical sorting)
                sort_func = SORT_FUNCS[list_view.state.sort_field]
                list_view.state.items = manager.get_visible_entries(sort_func, list_view.state.descending)

                # Calculate size for this folder if not already calculated
                if not item.has_calculated_size() and not item.size_calculating:
                    def calc_single():
                        item.size_calculating = True
                        try:
                            total_size, item_count = calculate_folder_size(item.path)
                            item.calculated_size = total_size
                            item.item_count = item_count
                        except Exception:
                            pass
                        item.size_calculating = False

                    threading.Thread(target=calc_single, daemon=True).start()

                # Need to refresh to copy items to visible
                return True, True  # Handled, call _update_visible_items to update state.visible
            return False, False  # Not handled, let default detail view happen

        # Ctrl+Enter (key code 10 with Ctrl modifier, or we use 'o' as alternative)
        # Using 'o' for "open in new window" since Ctrl+Enter is hard to detect
        elif key == ord('o'):
            if item.is_dir:
                # Open folder in new terminal window
                try:
                    if sys.platform == 'win32':
                        # Windows - open new cmd window with file-util
                        subprocess.Popen(['start', 'cmd', '/k', 'file-util', 'ls', str(item.path)], shell=True)
                    else:
                        # Linux/Mac - try various terminal emulators
                        for term in ['x-terminal-emulator', 'gnome-terminal', 'xterm']:
                            try:
                                subprocess.Popen([term, '-e', f'file-util ls {item.path}'])
                                break
                            except FileNotFoundError:
                                continue
                except Exception as e:
                    sys.stderr.write(f"Failed to open new window: {e}\n")
                return True, False  # Handled, no refresh needed
            return False, False

        # 'e' key - expand all at current depth
        elif key == ord('e'):
            # Find the depth of the current item
            current_depth = item.depth
            manager.expand_all_at_depth(current_depth)
            # Update the items list (with hierarchical sorting)
            sort_func = SORT_FUNCS[list_view.state.sort_field]
            list_view.state.items = manager.get_visible_entries(sort_func, list_view.state.descending)
            return True, True  # Handled, refresh to update state.visible

        # 'y' key - copy path to clipboard (vim-style "yank")
        elif key == ord('y'):
            if CLIPBOARD_AVAILABLE:
                try:
                    full_path = str(item.path.resolve())
                    set_clipboard(full_path)
                    # Could show a brief message, but for now just do it silently
                except Exception as e:
                    sys.stderr.write(f"Failed to copy path to clipboard: {e}\n")
            else:
                sys.stderr.write("Clipboard utilities not available\n")
            return True, False  # Handled, no refresh needed

        # 'S' key - calculate folder sizes
        elif key == ord('S'):
            if list_view.state.calculating_sizes:
                # Already calculating
                return True, False

            # Start calculation in background thread
            def calc_thread():
                # Get all directories
                folders = [e for e in manager.all_entries if e.is_dir]
                list_view.state.calc_progress = (0, len(folders))
                list_view.state.calc_cancel = False

                for idx, folder in enumerate(folders):
                    # Check for cancellation
                    if list_view.state.calc_cancel:
                        break

                    # Mark folder as calculating
                    folder.size_calculating = True

                    # Calculate size
                    try:
                        total_size, item_count = calculate_folder_size(folder.path)
                        folder.calculated_size = total_size
                        folder.item_count = item_count
                    except Exception:
                        pass  # Silently skip errors

                    folder.size_calculating = False

                    # Update progress
                    list_view.state.calc_progress = (idx + 1, len(folders))

                # Done
                list_view.state.calculating_sizes = False

            list_view.state.calculating_sizes = True
            threading.Thread(target=calc_thread, daemon=True).start()
            return True, False  # Handled, no refresh needed (progress updates will trigger redraws)

        # Handle sort key changes (c/m/a/s/n) with hierarchical sorting
        elif key in (ord('c'), ord('m'), ord('a'), ord('s'), ord('n')):
            # Map key to sort field
            sort_key_map = {
                ord('c'): 'created',
                ord('m'): 'modified',
                ord('a'): 'accessed',
                ord('s'): 'size',
                ord('n'): 'name',
            }
            new_field = sort_key_map.get(key)
            if new_field:
                # Toggle descending if same field, otherwise default to descending
                if list_view.state.sort_field == new_field:
                    list_view.state.descending = not list_view.state.descending
                else:
                    list_view.state.sort_field = new_field
                    list_view.state.descending = True

                # Re-sort hierarchically
                sort_func = SORT_FUNCS[list_view.state.sort_field]
                list_view.state.items = manager.get_visible_entries(sort_func, list_view.state.descending)
                return True, True  # Handled, refresh to update state.visible

        return False, False  # Not handled

    sort_keys_mapping = {
        ord("c"): "created",
        ord("m"): "modified",
        ord("a"): "accessed",
        ord("s"): "size",
        ord("n"): "name",
    }

    footer_lines = [
        "↑↓/j/k/PgUp/PgDn: move | f: filter | Enter: toggle folder/details | ESC: collapse/cancel | Ctrl+Q: quit",
        "c: created | m: modified | a: accessed | n: name | s: size | e: expand all | o: open new",
        "d: toggle date | t: toggle time | F: toggle dirs-first | y: copy path | S: calc sizes | ←→: scroll",
    ]

    list_view = InteractiveList(
        items=manager.get_visible_entries(SORT_FUNCS[sort_field], args.order == "desc"),
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
        custom_action_handler=action_handler,
        dirs_first=not getattr(args, 'no_dirs_first', False),
        name_color_getter=file_color_manager.get_color_pair,
    )

    if args.glob:
        list_view.state.filter_pattern = args.glob

    # Start size calculation if requested via CLI
    if getattr(args, 'calc_sizes', False):
        # Trigger calculation after TUI starts
        def start_calc():
            import time
            time.sleep(0.1)  # Brief delay to let TUI initialize
            # Simulate pressing 'S' key
            folders = [e for e in manager.all_entries if e.is_dir]
            list_view.state.calc_progress = (0, len(folders))
            list_view.state.calc_cancel = False
            list_view.state.calculating_sizes = True

            for idx, folder in enumerate(folders):
                if list_view.state.calc_cancel:
                    break

                folder.size_calculating = True
                try:
                    total_size, item_count = calculate_folder_size(folder.path)
                    folder.calculated_size = total_size
                    folder.item_count = item_count
                except Exception:
                    pass
                folder.size_calculating = False
                list_view.state.calc_progress = (idx + 1, len(folders))

            list_view.state.calculating_sizes = False

        threading.Thread(target=start_calc, daemon=True).start()

    list_view.run()
    return 0
