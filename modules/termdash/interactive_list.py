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

def calculate_size_color(size: int, min_size: int, max_size: int) -> int:
    """
    Calculate color pair based on size using a gradient from green->yellow->red.
    Returns color pair number (4-9).
    """
    if max_size == min_size:
        return 4  # green if all same size

    ratio = (size - min_size) / (max_size - min_size) if max_size > min_size else 0

    if ratio < 0.33:
        return 4  # green
    elif ratio < 0.50:
        return 5  # cyan
    elif ratio < 0.66:
        return 6  # yellow
    elif ratio < 0.83:
        return 7  # magenta
    else:
        return 8  # red

class InteractiveList:
    """A reusable, curses-based interactive list component with advanced features."""

    def __init__(
        self,
        items: List[Any],
        sorters: Dict[str, Callable[[Any], object]],
        formatter: Callable[[Any, str, int, bool, bool], str],
        filter_func: Callable[[Any, str], bool] = lambda item, p: fnmatch(str(item), p),
        initial_sort: Optional[str] = None,
        initial_order: str = "desc",
        header: str = "Interactive List",
        sort_keys_mapping: Optional[Dict[int, str]] = None,
        footer_lines: Optional[List[str]] = None,
        detail_formatter: Optional[Callable[[Any], List[str]]] = None,
        size_extractor: Optional[Callable[[Any], int]] = None,
        enable_color_gradient: bool = False,
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
            elif key == ord("f"):
                self._start_filter_edit()
            elif key == ord("d"):
                # Toggle date visibility
                self.state.show_date = not self.state.show_date
            elif key == ord("t"):
                # Toggle time visibility
                self.state.show_time = not self.state.show_time
            elif key == curses.KEY_RIGHT:
                # Scroll name to the right
                self.state.scroll_offset += 1
            elif key == curses.KEY_LEFT:
                # Scroll name to the left
                self.state.scroll_offset = max(0, self.state.scroll_offset - 1)
            elif key in (curses.KEY_ENTER, 10, 13):
                # Enter detail view
                if self.state.visible and self.state.selected_index < len(self.state.visible):
                    self.state.detail_view = True
                    self.state.detail_item = self.state.visible[self.state.selected_index]
            else:
                if self._handle_sort_key(key):
                    self._update_visible_items()

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

        # Sort
        sort_func = self.state.sorters[self.state.sort_field]
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
            for draw_idx in range(list_height):
                entry_idx = self.state.top_index + draw_idx
                if entry_idx >= len(self.state.visible):
                    break

                item = self.state.visible[entry_idx]
                line = self.formatter(item, self.state.sort_field, max_x, self.state.show_date, self.state.show_time)

                # Apply horizontal scrolling to selected item
                if entry_idx == self.state.selected_index and self.state.scroll_offset > 0:
                    # Extract the scrollable part (after timestamp and before size)
                    # This is a simple implementation; can be enhanced based on formatter structure
                    if len(line) > max_x:
                        visible_line = line[self.state.scroll_offset:self.state.scroll_offset + max_x]
                        line = visible_line

                # Determine color
                color_pair = self._get_size_color_pair(item, min_size, max_size)
                attr = curses.color_pair(color_pair)

                if entry_idx == self.state.selected_index:
                    attr = curses.color_pair(3) | curses.A_REVERSE

                try:
                    stdscr.addnstr(list_start + draw_idx, 0, line, max_x - 1, attr)
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
        """Draw the detail view for the selected item."""
        detail_lines = self.detail_formatter(self.state.detail_item)

        # Header
        stdscr.addnstr(0, 0, "Detail View (press ESC/Enter/q to return)".ljust(max_x), max_x - 1,
                      curses.color_pair(2) | curses.A_BOLD)
        stdscr.addnstr(1, 0, "─" * (max_x - 1), max_x - 1, curses.color_pair(2))

        # Content
        content_start = 2
        content_height = max_y - content_start - 1

        for idx, line in enumerate(detail_lines[:content_height]):
            try:
                stdscr.addnstr(content_start + idx, 0, line[:max_x - 1], max_x - 1, curses.color_pair(1))
            except curses.error:
                pass

        stdscr.refresh()
