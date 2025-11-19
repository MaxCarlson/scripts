from __future__ import annotations

import argparse
try:
    import curses  # type: ignore
except Exception:  # On Windows without windows-curses
    curses = None  # type: ignore
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path
from typing import Callable, Dict, List, Any, Tuple, Optional

# Cross-platform utilities
from cross_platform.size_utils import format_bytes_binary, parse_size_to_bytes
from cross_platform.fs_utils import matches_ext

# TermDash components
from termdash.interactive_list import InteractiveList
from termdash.search_stats import SearchStats

# File utils components
from .filter_stack import FilterStack, FilterCriterion, FilterMode, FilterType

try:
    from cross_platform.clipboard_utils import set_clipboard
    CLIPBOARD_AVAILABLE = True
except ImportError:
    CLIPBOARD_AVAILABLE = False

import re

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
    collapsed_path: Optional[str] = None  # Collapsed path representation (e.g., "foo/.../bar")
    original_depth: Optional[int] = None  # Original depth before collapsing

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
    "size": lambda entry: entry.get_display_size(),  # Use calculated size if available
    "name": lambda entry: entry.name.lower(),
}

DATE_FIELDS = {"created", "modified", "accessed"}

# Alias for backward compatibility (uses cross_platform.size_utils)
human_size = format_bytes_binary


@dataclass
class SearchFilter:
    """
    Comprehensive file search filter with multiple criteria.

    All criteria are applied with AND logic (file must match all active filters).
    """
    extensions: Optional[List[str]] = None  # List of extensions (OR logic within)
    min_size: Optional[int] = None  # Minimum size in bytes
    max_size: Optional[int] = None  # Maximum size in bytes
    name_pattern: Optional[str] = None  # Glob pattern for filename
    name_regex: Optional[re.Pattern] = None  # Compiled regex for filename
    case_sensitive: bool = False  # Case sensitivity for name/extension matching

    def matches(self, entry: Entry) -> bool:
        """Check if entry matches all active filter criteria."""
        # Extension filter (only for files)
        if self.extensions and not entry.is_dir:
            if not any(matches_ext(entry.path, ext, case_sensitive=self.case_sensitive)
                      for ext in self.extensions):
                return False

        # Size filters (only for files)
        if not entry.is_dir:
            if self.min_size is not None and entry.size < self.min_size:
                return False
            if self.max_size is not None and entry.size > self.max_size:
                return False

        # Name pattern filter (glob)
        if self.name_pattern:
            name = entry.name if self.case_sensitive else entry.name.lower()
            pattern = self.name_pattern if self.case_sensitive else self.name_pattern.lower()
            if not fnmatch(name, pattern):
                return False

        # Name regex filter
        if self.name_regex:
            if not self.name_regex.search(entry.name):
                return False

        return True

    def describe(self) -> str:
        """Return human-readable description of active filters."""
        parts = []

        if self.extensions:
            if len(self.extensions) == 1:
                parts.append(f"ext={self.extensions[0]}")
            else:
                parts.append(f"ext={{{','.join(self.extensions)}}}")

        if self.min_size is not None:
            parts.append(f"size>={format_bytes_binary(self.min_size)}")

        if self.max_size is not None:
            parts.append(f"size<={format_bytes_binary(self.max_size)}")

        if self.name_pattern:
            parts.append(f"name={self.name_pattern}")

        if self.name_regex:
            parts.append(f"regex={self.name_regex.pattern}")

        return " AND ".join(parts) if parts else "No filters"

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> 'SearchFilter':
        """Create SearchFilter from CLI arguments."""
        # Parse extensions (support pipe-separated list)
        extensions = None
        ext_arg = getattr(args, 'extension', None) or getattr(args, 'type', None)
        if ext_arg:
            # Split by pipe and normalize
            extensions = [e.strip().lstrip('*').lstrip('.') for e in ext_arg.split('|')]
            extensions = [e for e in extensions if e]  # Remove empty strings

        # Parse size filters
        min_size = None
        max_size = None
        if getattr(args, 'min_size', None):
            try:
                min_size = parse_size_to_bytes(args.min_size)
            except ValueError as e:
                sys.stderr.write(f"Invalid --min-size: {e}\n")
                sys.exit(1)

        if getattr(args, 'max_size', None):
            try:
                max_size = parse_size_to_bytes(args.max_size)
            except ValueError as e:
                sys.stderr.write(f"Invalid --max-size: {e}\n")
                sys.exit(1)

        # Validate size range
        if min_size is not None and max_size is not None and min_size > max_size:
            sys.stderr.write(f"Error: --min-size ({format_bytes_binary(min_size)}) "
                           f"cannot be greater than --max-size ({format_bytes_binary(max_size)})\n")
            sys.exit(1)

        # Parse name filters
        name_pattern = getattr(args, 'name', None)
        name_regex = None
        if getattr(args, 'name_regex', None):
            try:
                flags = 0 if getattr(args, 'case_sensitive', False) else re.IGNORECASE
                name_regex = re.compile(args.name_regex, flags)
            except re.error as e:
                sys.stderr.write(f"Invalid --name-regex: {e}\n")
                sys.exit(1)

        case_sensitive = getattr(args, 'case_sensitive', False)

        return cls(
            extensions=extensions,
            min_size=min_size,
            max_size=max_size,
            name_pattern=name_pattern,
            name_regex=name_regex,
            case_sensitive=case_sensitive,
        )

    def has_filters(self) -> bool:
        """Check if any filters are active."""
        return bool(
            self.extensions or
            self.min_size is not None or
            self.max_size is not None or
            self.name_pattern or
            self.name_regex
        )

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

def matches_extension(path: Path, extension: Optional[str]) -> bool:
    """
    Check if file matches the extension filter.
    Wrapper around cross_platform.fs_utils.matches_ext for compatibility.
    """
    if not extension:
        return True
    # Normalize extension (remove leading *. or .)
    ext = extension.lstrip('*').lstrip('.')
    return matches_ext(path, ext, case_sensitive=False)

def collapse_intermediate_paths(entries: List[Entry], search_root: Path) -> List[Entry]:
    """
    Collapse intermediate folders that don't contain matching files.

    When searching for specific files (e.g., PDFs), we often have deep
    folder hierarchies where most folders are just containers. This function
    collapses those paths to make the results cleaner.

    Example:
        Before: documents/2024/reports/Q1/file.pdf
        After:  documents/.../Q1/file.pdf (collapsed_path)

    Args:
        entries: List of Entry objects (should only contain matching files)
        search_root: Root directory of the search

    Returns:
        List of Entry objects with collapsed_path set
    """
    if not entries:
        return entries

    # Build a map of path -> entry for quick lookup
    path_to_entry = {e.path: e for e in entries}

    # For each entry, build a collapsed path
    for entry in entries:
        try:
            # Get all parents from search_root to this entry
            parents = []
            current = entry.path.parent

            while current != search_root and current != current.parent:
                parents.append(current)
                current = current.parent

            if not parents:
                # Entry is directly in search_root
                entry.collapsed_path = entry.name
                continue

            # Reverse to go from root to entry
            parents.reverse()

            # Find significant parents (those with multiple children)
            significant_parents = []
            for parent in parents:
                # Count children in this parent that are either:
                # 1. In our entries list (matching files)
                # 2. Parent of something in our entries list
                children_count = sum(
                    1 for e in entries
                    if e.path.parent == parent or (
                        e.path != parent and parent in e.path.parents
                    )
                )

                # If this parent has multiple children, it's significant
                if children_count > 1 or parent == parents[0] or parent == parents[-1]:
                    significant_parents.append(parent)

            # Build collapsed path
            if len(significant_parents) <= 1:
                # Simple case: just the filename
                collapsed = entry.name
            elif len(significant_parents) == len(parents):
                # No collapsing needed - all parents are significant
                collapsed = str(entry.path.relative_to(search_root))
            else:
                # Build path with "..." for collapsed sections
                parts = []

                # Add first significant parent
                if significant_parents:
                    parts.append(significant_parents[0].name)

                # Add "..." if we skipped some parents
                if len(significant_parents) < len(parents):
                    parts.append("...")

                # Add last significant parent if different from first
                if len(significant_parents) > 1 and significant_parents[-1] != significant_parents[0]:
                    parts.append(significant_parents[-1].name)

                # Add filename
                parts.append(entry.name)

                collapsed = "/".join(parts)

            entry.collapsed_path = collapsed

        except (ValueError, OSError):
            # Fallback to full path if something goes wrong
            entry.collapsed_path = entry.name

    return entries

def read_entries_recursive(
    target: Path,
    max_depth: int,
    parent_path: Path = None,
    search_filter: Optional[SearchFilter] = None,
    stats: Optional[SearchStats] = None,
    progress_callback: Optional[Callable[[SearchStats], None]] = None
) -> List[Entry]:
    """
    Recursively read directory entries with optional filtering.

    Args:
        target: Root directory to search
        max_depth: Maximum recursion depth
        parent_path: Parent path for hierarchical tracking
        search_filter: Optional SearchFilter with multiple criteria
        stats: Optional SearchStats object to track progress
        progress_callback: Optional callback for progress updates

    Returns:
        List of Entry objects matching the filter criteria
    """
    entries: List[Entry] = []
    if stats is None:
        stats = SearchStats()

    # Call progress callback periodically
    last_progress_time = time.time()
    progress_interval = 0.1  # Update every 100ms

    def _walk(curr_path: Path, current_depth: int, parent: Path = None):
        nonlocal last_progress_time

        if current_depth > max_depth:
            return

        try:
            for item in curr_path.iterdir():
                try:
                    item_stats = item.stat()
                    is_dir = item.is_dir()

                    # Update statistics
                    if is_dir:
                        stats.dirs_searched += 1
                    else:
                        stats.files_searched += 1
                        stats.bytes_searched += item_stats.st_size

                    # Create temporary entry for filter matching
                    temp_entry = Entry(
                        path=item,
                        name=item.name,
                        is_dir=is_dir,
                        size=item_stats.st_size,
                        created=datetime.fromtimestamp(item_stats.st_ctime),
                        modified=datetime.fromtimestamp(item_stats.st_mtime),
                        accessed=datetime.fromtimestamp(item_stats.st_atime),
                        depth=current_depth,
                        expanded=False,
                        parent_path=parent,
                    )

                    # Check if entry matches search filter
                    matches_filter = True
                    if search_filter:
                        matches_filter = search_filter.matches(temp_entry)

                    # Skip non-matching files
                    if not is_dir and not matches_filter:
                        continue

                    # Update found stats for matching files
                    if not is_dir and matches_filter:
                        stats.files_found += 1
                        stats.bytes_found += item_stats.st_size

                    # When search filter is active, only add matching files (not directories)
                    # This gives a clean list of just the matching files
                    if search_filter and search_filter.has_filters() and is_dir:
                        # Skip adding directories to entries when filtering
                        # But still recurse into them to find matching files
                        pass
                    else:
                        entries.append(temp_entry)

                    # Call progress callback periodically
                    current_time = time.time()
                    if progress_callback and (current_time - last_progress_time) >= progress_interval:
                        progress_callback(stats)
                        last_progress_time = current_time

                    if is_dir:
                        # Recurse into subdirectories
                        _walk(item, current_depth + 1, item)
                except OSError:
                    continue
        except OSError as exc:
            sys.stderr.write(f"Cannot read directory {curr_path}: {exc}\n")

    _walk(target, 0, parent_path)
    stats.end_time = time.time()

    # Final progress callback
    if progress_callback:
        progress_callback(stats)

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
            # Add abbreviated item count for expanded folders
            if entry.expanded and entry.item_count is not None:
                # Abbreviate counts to save space
                if entry.item_count < 1000:
                    count_str = f"{entry.item_count}"
                elif entry.item_count < 1000000:
                    count_str = f"{entry.item_count / 1000:.0f}k"
                else:
                    count_str = f"{entry.item_count / 1000000:.1f}M"
                size_text = f"{size_text} ({count_str})"
        else:
            size_text = ""  # Blank if not calculated
    else:
        size_text = human_size(entry.size)

    indent = "  " * entry.depth
    # Add expansion indicator for directories
    if entry.is_dir:
        indicator = "▼ " if entry.expanded else "▶ "
        display_name = entry.collapsed_path if entry.collapsed_path else entry.name
        name = f"{indent}{indicator}{display_name}/"
    else:
        # Use collapsed_path if available, otherwise use regular name
        display_name = entry.collapsed_path if entry.collapsed_path else entry.name
        name = f"{indent}  {display_name}"

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

    def get_visible_entries(self, sort_func: Optional[Callable[[Entry], object]] = None, descending: bool = True, dirs_first: bool = True) -> List[Entry]:
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
                    if dirs_first:
                        # Use stable sort: first by field, then by is_dir
                        # This ensures dirs_first works regardless of descending flag
                        children.sort(key=sort_func, reverse=descending)
                        children.sort(key=lambda x: not x.is_dir)  # Stable sort: dirs (False) before files (True)
                    else:
                        children.sort(key=sort_func, reverse=descending)

                # Recursively add each child and their children
                for child in children:
                    add_entry_and_children(child)

        # Get top-level entries (those with no parent or parent not in our list)
        top_level = [e for e in self.all_entries if e.parent_path is None or
                     not any(p.path == e.parent_path for p in self.all_entries)]

        # Sort top-level entries
        if sort_func:
            if dirs_first:
                # Use stable sort: first by field, then by is_dir
                # This ensures dirs_first works regardless of descending flag
                top_level.sort(key=sort_func, reverse=descending)
                top_level.sort(key=lambda x: not x.is_dir)  # Stable sort: dirs (False) before files (True)
            else:
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

    # Create search filter from arguments
    search_filter = SearchFilter.from_args(args)

    # Determine depth: max_depth > depth > default
    # Default is 0 (current dir only), unless any filter is set (then 999999)
    if getattr(args, 'max_depth', None) is not None:
        depth = args.max_depth
    elif getattr(args, 'depth', None) is not None:
        depth = args.depth
    elif search_filter.has_filters():
        depth = 999999  # Deep search when filtering
    else:
        depth = 0  # Default: current directory only

    # Determine path collapse setting
    collapse_paths = getattr(args, 'collapse_paths', False)
    if getattr(args, 'no_collapse_paths', False):
        collapse_paths = False

    # Create search stats tracker
    search_stats = SearchStats()

    # Progress callback for terminal output
    last_update = [time.time()]  # Use list to allow modification in closure

    def progress_callback(stats: SearchStats):
        """Display progress during scan."""
        current = time.time()
        # Update every 0.5 seconds to avoid flooding terminal
        if current - last_update[0] >= 0.5:
            sys.stderr.write(
                f"\rScanning... {stats.files_searched:,} files searched, "
                f"{stats.files_found:,} found ({stats.match_percentage():.1f}%), "
                f"{stats.files_per_second():.0f} files/sec"
            )
            sys.stderr.flush()
            last_update[0] = current

    # Show initial message
    if search_filter.has_filters():
        sys.stderr.write(f"Searching in {target} (depth: {depth}, filters: {search_filter.describe()})...\n")
    else:
        sys.stderr.write(f"Listing files in {target} (depth: {depth})...\n")
    sys.stderr.flush()

    # Read entries with progress tracking
    entries = read_entries_recursive(
        target,
        depth,
        search_filter=search_filter,
        stats=search_stats,
        progress_callback=progress_callback
    )

    # Clear progress line and show final stats
    sys.stderr.write("\r" + " " * 100 + "\r")  # Clear line
    if search_filter.has_filters() or depth > 0:
        sys.stderr.write(f"{search_stats.format_summary()}\n")
    sys.stderr.flush()

    # Apply path collapsing if enabled and filters are active
    if collapse_paths and search_filter.has_filters():
        sys.stderr.write("Collapsing intermediate paths...\n")
        entries = collapse_intermediate_paths(entries, target)
        sys.stderr.write(f"Collapsed paths for {len(entries)} entries.\n")

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
                    new_visible = manager.get_visible_entries(sort_func, list_view.state.descending, list_view.state.dirs_first)
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
                list_view.state.items = manager.get_visible_entries(sort_func, list_view.state.descending, list_view.state.dirs_first)

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
            list_view.state.items = manager.get_visible_entries(sort_func, list_view.state.descending, list_view.state.dirs_first)
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
                list_view.state.items = manager.get_visible_entries(sort_func, list_view.state.descending, list_view.state.dirs_first)
                return True, True  # Handled, refresh to update state.visible

        return False, False  # Not handled

    sort_keys_mapping = {
        ord("c"): "created",
        ord("m"): "modified",
        ord("a"): "accessed",
        ord("s"): "size",
        ord("n"): "name",
    }

    # Store search stats for header updates
    initial_search_stats = search_stats

    # Build header template function
    def build_header(visible_count: Optional[int] = None, filter_active: bool = False):
        """Build header with current filter state."""
        parts = [f"Path: {target}"]

        # Show active search filters
        if search_filter.has_filters():
            parts.append(f"Filters: {search_filter.describe()}")

        # Show counts
        if search_filter.has_filters() or depth > 0:
            total_found = initial_search_stats.files_found
            total_scanned = initial_search_stats.files_searched

            if visible_count is not None and filter_active:
                # TUI filter is active, show subset
                parts.append(f"Showing: {visible_count:,} of {total_found:,} files")
            elif visible_count is not None:
                # No TUI filter, show all found files
                parts.append(f"Showing: {visible_count:,} files (scanned {total_scanned:,}, {initial_search_stats.match_percentage():.1f}% match)")
            else:
                # Initial state
                parts.append(f"Found: {total_found:,} of {total_scanned:,} files ({initial_search_stats.match_percentage():.1f}%)")

        return " │ ".join(parts)

    # Initial header
    header = build_header(len(entries), bool(args.glob))

    # Build footer with search stats
    footer_lines = [
        "↑↓/jk/PgUp/Dn │ f:filter x:exclude │ ↵:expand ESC:collapse ^Q:quit",
        "Sort c/m/a/n/s │ e:all o:open F:dirs │ d:date t:time │ y:copy S:calc │ ←→",
    ]

    # Add search stats line if filters were used or deep search
    if search_filter.has_filters() or depth > 0:
        stats_line = (
            f"Found: {search_stats.files_found:,} files ({human_size(search_stats.bytes_found)}) │ "
            f"Match: {search_stats.match_percentage():.1f}% │ "
            f"Rate: {search_stats.files_per_second():.0f} files/sec"
        )
        footer_lines.insert(0, stats_line)

    list_view = InteractiveList(
        items=manager.get_visible_entries(SORT_FUNCS[sort_field], args.order == "desc", not getattr(args, 'no_dirs_first', False)),
        sorters=SORT_FUNCS,
        formatter=format_entry_line,
        filter_func=filter_entry,
        initial_sort=sort_field,
        initial_order=args.order,
        header=header,
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

    # If curses is unavailable (e.g., Windows without windows-curses), print a plain listing
    if curses is None:
        sys.stderr.write(
            "Curses UI not available. On Windows, install windows-curses or use -j for JSON.\n"
        )
        width = 120
        # Filter and sort like the TUI would
        sort_field_map = {"c": "created", "m": "modified", "a": "accessed", "s": "size", "n": "name"}
        sort_field = sort_field_map.get(args.sort, args.sort)
        if args.glob:
            entries = [e for e in entries if filter_entry(e, args.glob)]
        entries.sort(key=SORT_FUNCS[sort_field], reverse=(args.order == "desc"))
        for e in entries:
            print(format_entry_line(e, sort_field, width, True, True, 0))
        return 0

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

    # Try to launch curses TUI; if terminal/terminfo unavailable, fall back to plain output.
    try:
        list_view.run()
        return 0
    except SystemExit as exc:
        # InteractiveList emits SystemExit(2) on terminal capability failures.
        if getattr(exc, "code", None) == 2:
            sys.stderr.write("Terminal UI unavailable; showing plain listing. Use -j for JSON.\n")
            # Render a simple table-like listing using formatter.
            width = 120
            # Recompute visible list consistent with current sort/order/dirs_first
            sort_func = SORT_FUNCS[sort_field]
            visible = manager.get_visible_entries(sort_func, args.order == "desc", not getattr(args, 'no_dirs_first', False))
            for e in visible:
                line = format_entry_line(e, sort_field, width, show_date=True, show_time=True, scroll_offset=0)
                print(line)
            return 0
        raise
