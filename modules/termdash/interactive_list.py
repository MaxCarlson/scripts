from __future__ import annotations

import curses
import sys
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any, Callable, Dict, List, Sequence, Optional, Tuple

def ensure_curses_available() -> None:
    """Checks if the curses module is available and raises SystemExit if not."""
    if curses is None:
        sys.stderr.write(
            "This tool requires curses for the TUI. On Windows, please install the 'windows-curses' package.\n"
        )
        raise SystemExit(2)

@dataclass
class ListState:
    """Holds the state of the interactive list."""
    items: List[Any]
    sorters: Dict[str, Callable[[Any], object]]
    filter_func: Callable[[Any, str], bool]

    header: str = "Interactive List"
    filter_pattern: str = ""
    sort_field: str = ""
    descending: bool = True

    visible: List[Any] = field(default_factory=list)
    selected_index: int = 0
    top_index: int = 0
    viewport_height: int = 1

    editing_filter: bool = False
    edit_buffer: str = ""

    # Detail view state
    detail_view: bool = False
    detail_item: Any = None

    # Horizontal scroll state
    scroll_offset: int = 0

    # Display options
    show_date: bool = True
    show_time: bool = True
    dirs_first: bool = True  # Group directories before files

def calculate_size_color(size: int, min_size: int, max_size: int) -> int:
    """
    Calculate color pair based on size using logarithmic scale for better distribution.
    Returns color pair number (4-8).
    """
    import math

    if max_size == min_size:
        return 4  # green if all same size

    # Use logarithmic scale to spread colors better across file sizes
    # Add 1 to avoid log(0)
    if size > 0 and max_size > 0:
        log_size = math.log10(size + 1)
        log_min = math.log10(min_size + 1)
        log_max = math.log10(max_size + 1)
        ratio = (log_size - log_min) / (log_max - log_min) if log_max > log_min else 0
    else:
        ratio = 0

    # Map to 5 colors with adjusted thresholds for better distribution
    if ratio < 0.20:
        return 4  # green
    elif ratio < 0.40:
        return 5  # cyan
    elif ratio < 0.60:
        return 6  # yellow
    elif ratio < 0.80:
        return 7  # magenta
    else:
        return 8  # red

class InteractiveList:
    """A reusable, curses-based interactive list component with advanced features."""

    def __init__(
        self,
        items: List[Any],
        sorters: Dict[str, Callable[[Any], object]],
        formatter: Callable[[Any, str, int, bool, bool, int], str],
        filter_func: Callable[[Any, str], bool] = lambda item, p: fnmatch(str(item), p),
        initial_sort: Optional[str] = None,
        initial_order: str = "desc",
        header: str = "Interactive List",
        sort_keys_mapping: Optional[Dict[int, str]] = None,
        footer_lines: Optional[List[str]] = None,
        detail_formatter: Optional[Callable[[Any], List[str]]] = None,
        size_extractor: Optional[Callable[[Any], int]] = None,
        enable_color_gradient: bool = False,
        custom_action_handler: Optional[Callable[[int, Any], Tuple[bool, bool]]] = None,
        dirs_first: bool = True,
        name_color_getter: Optional[Callable[[Any], int]] = None,
    ):
        ensure_curses_available()
        self.formatter = formatter
        self.sort_keys_mapping = sort_keys_mapping or {}
        self.footer_lines = footer_lines or [
            "Up/Down/j/k: move | f: filter | Enter: details | Ctrl+Q: quit",
            "Use sort keys to change sort field, repeat to toggle order.",
        ]
        self.detail_formatter = detail_formatter or self._default_detail_formatter
        self.size_extractor = size_extractor
        self.enable_color_gradient = enable_color_gradient
        self.custom_action_handler = custom_action_handler
        self.name_color_getter = name_color_getter

        if not sorters:
            raise ValueError("At least one sorter must be provided.")

        default_sort_field = initial_sort or next(iter(sorters))

        self.state = ListState(
            items=items,
            sorters=sorters,
            filter_func=filter_func,
            header=header,
            sort_field=default_sort_field,
            descending=initial_order == "desc",
            dirs_first=dirs_first,
        )

    def _default_detail_formatter(self, item: Any) -> List[str]:
        """Default detail formatter shows item representation."""
        return [str(item)]

    def run(self) -> None:
        """Starts the curses-based TUI."""
        curses.wrapper(self._tui_main)

    def _tui_main(self, stdscr) -> None:
        try:
            curses.curs_set(0)
        except curses.error:
            pass

        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_WHITE, -1)   # default text
            curses.init_pair(2, curses.COLOR_CYAN, -1)    # header/footer
            curses.init_pair(3, curses.COLOR_YELLOW, -1)  # highlight
            # Color gradient pairs for file sizes
            curses.init_pair(4, curses.COLOR_GREEN, -1)   # smallest
            curses.init_pair(5, curses.COLOR_CYAN, -1)
            curses.init_pair(6, curses.COLOR_YELLOW, -1)  # medium
            curses.init_pair(7, curses.COLOR_MAGENTA, -1)
            curses.init_pair(8, curses.COLOR_RED, -1)     # largest
            # File type color pairs
            curses.init_pair(9, curses.COLOR_GREEN, -1)   # executables, code
            curses.init_pair(10, curses.COLOR_RED, -1)    # media, archives
            curses.init_pair(11, curses.COLOR_BLUE, -1)   # documents, code
            curses.init_pair(12, curses.COLOR_MAGENTA, -1) # images

        self._update_visible_items(reset_selection=True)

        while True:
            self._draw_screen(stdscr)
            key = stdscr.getch()

            if key in (17,):  # Ctrl+Q
                break

            # Detail view mode
            if self.state.detail_view:
                if key in (27, ord('q'), curses.KEY_ENTER, 10, 13):  # Escape, q, or Enter to exit
                    self.state.detail_view = False
                    self.state.detail_item = None
                continue

            if self.state.editing_filter:
                if self._handle_filter_input(key):
                    self._update_visible_items(reset_selection=True)
                continue

            if key in (curses.KEY_UP, ord("k")):
                self._move_selection(-1)
                self.state.scroll_offset = 0  # Reset scroll on selection change
            elif key in (curses.KEY_DOWN, ord("j")):
                self._move_selection(1)
                self.state.scroll_offset = 0
            elif key == curses.KEY_PPAGE:  # Page Up
                self._move_selection(-self.state.viewport_height)
                self.state.scroll_offset = 0
            elif key == curses.KEY_NPAGE:  # Page Down
                self._move_selection(self.state.viewport_height)
                self.state.scroll_offset = 0
            elif key == ord("f"):
                self._start_filter_edit()
            elif key == ord("d"):
                # Toggle date visibility
                self.state.show_date = not self.state.show_date
                self.state.scroll_offset = 0
            elif key == ord("t"):
                # Toggle time visibility
                self.state.show_time = not self.state.show_time
                self.state.scroll_offset = 0
            elif key == ord("F"):
                # Toggle folders-first mode
                self.state.dirs_first = not self.state.dirs_first
                self._update_visible_items()
                self.state.scroll_offset = 0
            elif key == curses.KEY_RIGHT:
                # Scroll name to the right (increment by 5 for smoother feel)
                self.state.scroll_offset += 5
            elif key == curses.KEY_LEFT:
                # Scroll name to the left
                self.state.scroll_offset = max(0, self.state.scroll_offset - 5)
            elif key in (curses.KEY_ENTER, 10, 13):
                # Check if custom handler wants to handle this key
                handled = False
                if self.custom_action_handler and self.state.visible and self.state.selected_index < len(self.state.visible):
                    current_item = self.state.visible[self.state.selected_index]
                    handled, should_refresh = self.custom_action_handler(key, current_item)
                    if should_refresh:
                        self._update_visible_items()

                # Default behavior: Enter detail view
                if not handled and self.state.visible and self.state.selected_index < len(self.state.visible):
                    self.state.detail_view = True
                    self.state.detail_item = self.state.visible[self.state.selected_index]
                    self.state.scroll_offset = 0
            else:
                # Check if custom handler wants to handle this key
                if self.custom_action_handler and self.state.visible and self.state.selected_index < len(self.state.visible):
                    current_item = self.state.visible[self.state.selected_index]
                    handled, should_refresh = self.custom_action_handler(key, current_item)
                    if handled:
                        if should_refresh:
                            self._update_visible_items()
                        continue

                if self._handle_sort_key(key):
                    self._update_visible_items()
                    self.state.scroll_offset = 0

    def _start_filter_edit(self) -> None:
        self.state.editing_filter = True
        self.state.edit_buffer = self.state.filter_pattern
        try:
            curses.curs_set(1)
        except curses.error:
            pass

    def _handle_filter_input(self, key: int) -> bool:
        if key in (curses.KEY_ENTER, 10, 13):
            self.state.filter_pattern = self.state.edit_buffer
            self.state.editing_filter = False
            try:
                curses.curs_set(0)
            except curses.error:
                pass
            return True
        if key in (27,):  # Escape
            self.state.editing_filter = False
            self.state.edit_buffer = self.state.filter_pattern
            try:
                curses.curs_set(0)
            except curses.error:
                pass
            return False
        if key in (curses.KEY_BACKSPACE, 127, 8):
            self.state.edit_buffer = self.state.edit_buffer[:-1]
        elif 32 <= key <= 126:
            self.state.edit_buffer += chr(key)
        return False

    def _handle_sort_key(self, key: int) -> bool:
        field = self.sort_keys_mapping.get(key)
        if not field:
            return False
        if self.state.sort_field == field:
            self.state.descending = not self.state.descending
        else:
            self.state.sort_field = field
            self.state.descending = True  # Default to descending for new fields
        return True

    def _move_selection(self, delta: int) -> None:
        if not self.state.visible:
            return
        self.state.selected_index = max(
            0, min(self.state.selected_index + delta, len(self.state.visible) - 1)
        )
        if self.state.selected_index < self.state.top_index:
            self.state.top_index = self.state.selected_index
        elif self.state.selected_index >= self.state.top_index + self.state.viewport_height:
            self.state.top_index = self.state.selected_index - self.state.viewport_height + 1

    def _update_visible_items(self, reset_selection: bool = False) -> None:
        # Filter
        if self.state.filter_pattern:
            self.state.visible = [
                item for item in self.state.items if self.state.filter_func(item, self.state.filter_pattern)
            ]
        else:
            self.state.visible = list(self.state.items)

        # Check if items have hierarchical structure (parent_path attribute)
        # If so, preserve order (items are pre-sorted hierarchically)
        has_hierarchy = bool(self.state.visible and hasattr(self.state.visible[0], 'parent_path'))

        if not has_hierarchy:
            # Sort (only for flat lists)
            sort_func = self.state.sorters[self.state.sort_field]
            if self.state.dirs_first and hasattr(self.state.visible[0] if self.state.visible else None, 'is_dir'):
                # Directories first, then by sort field
                # Primary sort: is_dir (True before False = not is_dir False before True)
                # Secondary sort: the chosen sort field
                self.state.visible.sort(
                    key=lambda x: (not x.is_dir, sort_func(x)),
                    reverse=self.state.descending
                )
            else:
                self.state.visible.sort(key=sort_func, reverse=self.state.descending)

        if not self.state.visible:
            self.state.selected_index = 0
            self.state.top_index = 0
            return

        if reset_selection or self.state.selected_index >= len(self.state.visible):
            self.state.selected_index = 0
            self.state.top_index = 0

    def _get_size_color_pair(self, item: Any, min_size: int, max_size: int) -> int:
        """Get the appropriate color pair for an item based on its size."""
        if not self.enable_color_gradient or not self.size_extractor:
            return 1

        try:
            size = self.size_extractor(item)
            return calculate_size_color(size, min_size, max_size)
        except Exception:
            return 1

    def _draw_screen(self, stdscr) -> None:
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()

        # Detail view mode
        if self.state.detail_view and self.state.detail_item:
            self._draw_detail_view(stdscr, max_y, max_x)
            return

        header_lines = 2
        footer_lines = len(self.footer_lines) + 1
        list_start = header_lines
        list_height = max(1, max_y - (header_lines + footer_lines))
        self.state.viewport_height = list_height

        # Header
        filter_display = self.state.edit_buffer if self.state.editing_filter else self.state.filter_pattern or "*"
        filter_line = f"Filter: {filter_display}"
        stdscr.addnstr(0, 0, filter_line.ljust(max_x), max_x - 1, curses.color_pair(2) | curses.A_BOLD)

        sort_order = 'desc' if self.state.descending else 'asc'
        toggles = []
        if not self.state.show_date:
            toggles.append("NoDate")
        if not self.state.show_time:
            toggles.append("NoTime")
        if not self.state.dirs_first:
            toggles.append("NoDirsFirst")
        toggle_str = f" [{', '.join(toggles)}]" if toggles else ""
        sort_line = f"{self.state.header} | Sort: {self.state.sort_field} ({sort_order}) | Items: {len(self.state.visible)}{toggle_str}"
        stdscr.addnstr(1, 0, sort_line[:max_x - 1], max_x - 1, curses.color_pair(2))

        if self.state.editing_filter:
            cursor_x = min(len("Filter: ") + len(self.state.edit_buffer), max_x - 1)
            stdscr.move(0, cursor_x)

        # Calculate size range for color gradient
        min_size, max_size = 0, 0
        if self.enable_color_gradient and self.size_extractor and self.state.visible:
            try:
                sizes = [self.size_extractor(item) for item in self.state.visible]
                min_size, max_size = min(sizes), max(sizes)
            except Exception:
                pass

        # List items
        if self.state.visible:
            items_drawn = 0
            for draw_idx in range(list_height):
                entry_idx = self.state.top_index + draw_idx
                if entry_idx >= len(self.state.visible):
                    break

                item = self.state.visible[entry_idx]

                # Pass scroll_offset only for the selected item
                scroll_off = self.state.scroll_offset if entry_idx == self.state.selected_index else 0
                line = self.formatter(item, self.state.sort_field, max_x, self.state.show_date, self.state.show_time, scroll_off)

                # Ensure line doesn't exceed terminal width
                if len(line) > max_x - 1:
                    line = line[:max_x - 1]

                # Determine colors
                size_color_pair = self._get_size_color_pair(item, min_size, max_size)
                name_color_pair = self.name_color_getter(item) if self.name_color_getter else 1

                # Check if selected
                is_selected = entry_idx == self.state.selected_index

                try:
                    # Clear the line first to avoid attribute bleeding
                    stdscr.move(list_start + draw_idx, 0)
                    stdscr.clrtoeol()

                    # If we have a name color getter, render in two parts
                    if self.name_color_getter and self.size_extractor:
                        # Find where the size part starts (look for last "  " + size pattern)
                        # Size is right-aligned and preceded by at least 2 spaces
                        # Extract size text by finding the last token that looks like a size
                        parts = line.rsplit('  ', 1)  # Split on last double-space
                        if len(parts) == 2:
                            name_part = parts[0] + '  '  # Include the spacing
                            size_part = parts[1]

                            # Render name part with name color
                            name_attr = curses.color_pair(name_color_pair)
                            if is_selected:
                                name_attr |= curses.A_REVERSE

                            stdscr.addnstr(list_start + draw_idx, 0, name_part, len(name_part), name_attr)

                            # Render size part with size gradient color
                            size_attr = curses.color_pair(size_color_pair)
                            if is_selected:
                                size_attr |= curses.A_REVERSE

                            size_x = len(name_part)
                            if size_x < max_x:
                                stdscr.addnstr(list_start + draw_idx, size_x, size_part, max_x - size_x - 1, size_attr)
                        else:
                            # Fallback: render whole line with name color
                            attr = curses.color_pair(name_color_pair)
                            if is_selected:
                                attr |= curses.A_REVERSE
                            stdscr.addnstr(list_start + draw_idx, 0, line, max_x - 1, attr)
                    else:
                        # Single color rendering (original behavior)
                        attr = curses.color_pair(size_color_pair)
                        if is_selected:
                            attr |= curses.A_REVERSE
                        stdscr.addnstr(list_start + draw_idx, 0, line, max_x - 1, attr)

                    # Reset attributes after drawing
                    stdscr.attrset(curses.color_pair(1))
                    items_drawn += 1
                except curses.error:
                    pass

            # Clear any remaining lines in the viewport
            for clear_idx in range(items_drawn, list_height):
                try:
                    stdscr.move(list_start + clear_idx, 0)
                    stdscr.clrtoeol()
                except curses.error:
                    pass
        else:
            stdscr.addnstr(list_start, 0, "-- no matches --", max_x - 1, curses.color_pair(1))

        # Footer
        footer_y = max_y - footer_lines
        if footer_y > 1:
            try:
                stdscr.hline(footer_y, 0, curses.ACS_HLINE, max_x)
            except curses.error:
                pass

        for idx, text in enumerate(self.footer_lines):
            try:
                stdscr.addnstr(
                    max_y - footer_lines + idx, 0, text.ljust(max_x), max_x - 1, curses.color_pair(2)
                )
            except curses.error:
                pass

        stdscr.refresh()

    def _draw_detail_view(self, stdscr, max_y: int, max_x: int) -> None:
        """Draw the detail view for the selected item with text wrapping."""
        detail_lines = self.detail_formatter(self.state.detail_item)

        # Header
        stdscr.addnstr(0, 0, "Detail View (press ESC/Enter/q to return)".ljust(max_x), max_x - 1,
                      curses.color_pair(2) | curses.A_BOLD)
        stdscr.addnstr(1, 0, "─" * (max_x - 1), max_x - 1, curses.color_pair(2))

        # Content with wrapping
        content_start = 2
        content_height = max_y - content_start - 1
        current_row = 0

        for line in detail_lines:
            if current_row >= content_height:
                break

            # Wrap long lines
            if len(line) > max_x - 1:
                # Split into chunks
                remaining = line
                while remaining and current_row < content_height:
                    chunk = remaining[:max_x - 1]
                    try:
                        stdscr.addnstr(content_start + current_row, 0, chunk, max_x - 1, curses.color_pair(1))
                    except curses.error:
                        pass
                    remaining = remaining[max_x - 1:]
                    current_row += 1
            else:
                try:
                    stdscr.addnstr(content_start + current_row, 0, line, max_x - 1, curses.color_pair(1))
                except curses.error:
                    pass
                current_row += 1

        stdscr.refresh()
