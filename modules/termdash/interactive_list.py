from __future__ import annotations

import curses
import sys
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any, Callable, Dict, List, Sequence, Optional

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

class InteractiveList:
    """A reusable, curses-based interactive list component."""

    def __init__(
        self,
        items: List[Any],
        sorters: Dict[str, Callable[[Any], object]],
        formatter: Callable[[Any, str, int], str],
        filter_func: Callable[[Any, str], bool] = lambda item, p: fnmatch(str(item), p),
        initial_sort: Optional[str] = None,
        initial_order: str = "desc",
        header: str = "Interactive List",
        sort_keys_mapping: Optional[Dict[int, str]] = None,
        footer_lines: Optional[List[str]] = None,
    ):
        ensure_curses_available()
        self.formatter = formatter
        self.sort_keys_mapping = sort_keys_mapping or {}
        self.footer_lines = footer_lines or [
            "Up/Down/j/k: move | f: filter | Ctrl+Q: quit",
            "Use sort keys to change sort field, repeat to toggle order.",
        ]

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
            curses.init_pair(1, curses.COLOR_WHITE, -1)
            curses.init_pair(2, curses.COLOR_CYAN, -1)
            curses.init_pair(3, curses.COLOR_YELLOW, -1)

        self._update_visible_items(reset_selection=True)

        while True:
            self._draw_screen(stdscr)
            key = stdscr.getch()

            if key in (17,):  # Ctrl+Q
                break

            if self.state.editing_filter:
                if self._handle_filter_input(key):
                    self._update_visible_items(reset_selection=True)
                continue

            if key in (curses.KEY_UP, ord("k")):
                self._move_selection(-1)
            elif key in (curses.KEY_DOWN, ord("j")):
                self._move_selection(1)
            elif key == ord("f"):
                self._start_filter_edit()
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

    def _draw_screen(self, stdscr) -> None:
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()

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
        sort_line = f"{self.state.header} | Sort: {self.state.sort_field} ({sort_order}) | Items: {len(self.state.visible)}"
        stdscr.addnstr(1, 0, sort_line[:max_x - 1], max_x - 1, curses.color_pair(2))

        if self.state.editing_filter:
            cursor_x = min(len("Filter: ") + len(self.state.edit_buffer), max_x - 1)
            stdscr.move(0, cursor_x)

        # List items
        if self.state.visible:
            for draw_idx in range(list_height):
                entry_idx = self.state.top_index + draw_idx
                if entry_idx >= len(self.state.visible):
                    break
                
                item = self.state.visible[entry_idx]
                line = self.formatter(item, self.state.sort_field, max_x)
                
                attr = curses.color_pair(1)
                if entry_idx == self.state.selected_index:
                    attr = curses.color_pair(3) | curses.A_REVERSE
                stdscr.addnstr(list_start + draw_idx, 0, line, max_x - 1, attr)
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
            stdscr.addnstr(
                max_y - footer_lines + idx, 0, text.ljust(max_x), max_x - 1, curses.color_pair(2)
            )

        stdscr.refresh()