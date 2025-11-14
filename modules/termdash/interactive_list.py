from __future__ import annotations

import curses
import os
import shutil
import sys
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any, Callable, Dict, List, Sequence, Optional, Tuple


@dataclass
class DetailEntry:
    """Represents a collapsible block within the detail view."""

    summary: str
    body: List[str] = field(default_factory=list)
    focusable: bool = True
    expanded: bool = False


@dataclass
class DetailViewData:
    """Container object produced by detail formatters."""

    title: str
    entries: List[DetailEntry]
    footer: Optional[str] = None


DETAIL_FOOTER_DEFAULT = (
    "Up/Down: move | Enter: toggle | e: expand | c: collapse | g/G: start/end | Esc/q: back"
)


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
    exclusion_pattern: str = ""
    sort_field: str = ""
    descending: bool = True

    visible: List[Any] = field(default_factory=list)
    selected_index: int = 0
    top_index: int = 0
    viewport_height: int = 1

    editing_filter: bool = False
    editing_exclusion: bool = False
    edit_buffer: str = ""
    exclusion_edit_buffer: str = ""

    # Detail view state
    detail_view: bool = False
    detail_item: Any = None
    detail_entries: List[DetailEntry] = field(default_factory=list)
    detail_selection: int = 0
    detail_title: str = ""
    detail_footer: str = DETAIL_FOOTER_DEFAULT

    # Horizontal scroll state
    scroll_offset: int = 0
    detail_scroll: int = 0
    columns_line: Optional[str] = None

    # Display options
    show_date: bool = True
    show_time: bool = True
    dirs_first: bool = True  # Group directories before files

    # Folder size calculation state
    calculating_sizes: bool = False
    calc_progress: Tuple[int, int] = (0, 0)  # (current, total)
    calc_cancel: bool = False
    # Quit confirmation state
    confirm_quit: bool = False

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
        columns_line: Optional[str] = None,
        sort_change_handler: Optional[Callable[[str, bool], None]] = None,
    ):
        # Keep the import-availability check here so construction fails fast on
        # platforms that truly lack curses. More detailed terminal checks are
        # deferred to run(), so tests can instantiate without a TTY.
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
        self.sort_change_handler = sort_change_handler
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
        self.state.columns_line = columns_line
        self._detail_lines: List[str] = []
        self._detail_meta: List[Tuple[int, bool]] = []
        self._detail_focusable: List[int] = []
        self._detail_content_height = 0
        self._detail_lines: List[str] = []
        self._detail_meta: List[Tuple[int, bool]] = []
        self._detail_content_height: int = 0

    def _default_detail_formatter(self, item: Any) -> List[str]:
        """Default detail formatter shows item representation."""
        if item is None:
            return []
        if isinstance(item, list):
            return list(item)
        return [str(item)]

    def _matches_pattern(self, item: Any, pattern: str) -> bool:
        """Check if item matches pattern. Supports multiple patterns with | separator."""
        if not pattern:
            return True
        if '|' in pattern:
            return any(self.state.filter_func(item, p.strip()) for p in pattern.split('|'))
        return self.state.filter_func(item, pattern)

    def run(self) -> None:
        """Starts the curses-based TUI."""
        # Perform runtime terminal readiness checks before initializing curses.
        self._ensure_terminal_ready()
        try:
            curses.wrapper(self._tui_main)
        except curses.error as e:
            # Convert low-level curses errors into an actionable message.
            term = os.environ.get("TERM", "unknown")
            sys.stderr.write(
                "Failed to initialize the interactive UI (curses error).\n"
                f"TERM={term}. Error: {e}\n"
                "Tips: install the terminfo database (ncurses) for your system,\n"
                "and run in a real TTY. Examples:\n"
                "  - Debian/Ubuntu: sudo apt-get install ncurses-term\n"
                "  - Fedora:        sudo dnf install ncurses-term\n"
                "  - Arch:          sudo pacman -S ncurses\n"
                "  - Termux:        pkg install ncurses\n"
                "Alternatively, use a non-TUI mode if available (e.g., --json).\n"
            )
            raise SystemExit(2)

    def _ensure_terminal_ready(self) -> None:
        """Validate that a TTY and terminfo database are available.

        This is stricter than a mere 'curses' import: it checks that stdin/stdout
        are TTYs and that the terminfo database can be initialized. It avoids
        running `curses.wrapper(...)` only to crash with a cryptic error.
        """
        # Ensure we are attached to an interactive terminal.
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            sys.stderr.write(
                "An interactive terminal (TTY) is required for the TUI.\n"
                "Run this command directly in a terminal, or use a non-TUI mode (e.g., --json).\n"
            )
            raise SystemExit(2)

        # Attempt to initialize terminfo if supported by the platform.
        # Some Windows curses builds might not expose setupterm; guard accordingly.
        if hasattr(curses, "setupterm"):
            try:
                curses.setupterm()
            except Exception as e:  # pragma: no cover - platform dependent
                # Try safe fallbacks for TERM if a specific entry is missing.
                current_term = os.environ.get("TERM", "unknown")
                for fallback_term in ("xterm-256color", "screen-256color"):
                    if current_term == fallback_term:
                        continue
                    try:
                        os.environ["TERM"] = fallback_term
                        curses.setupterm()
                        sys.stderr.write(
                            f"Warning: TERM={current_term} failed; using TERM={fallback_term} as a fallback.\n"
                        )
                        break
                    except Exception:
                        continue
                else:
                    # No TERM fallback worked — try to set TERMINFO_DIRS to common locations and retry.
                    candidates = [
                        "/usr/share/terminfo",
                        "/lib/terminfo",
                        "/usr/lib/terminfo",
                        "/data/data/com.termux/files/usr/share/terminfo",
                    ]
                    existing = os.environ.get("TERMINFO_DIRS", "")
                    probe_dirs = [d for d in candidates if os.path.isdir(d)]
                    merged = ":".join([p for p in [existing] if p] + probe_dirs)
                    if merged:
                        os.environ["TERMINFO_DIRS"] = merged
                    try:
                        curses.setupterm()
                        if merged:
                            sys.stderr.write(
                                f"Warning: terminfo database not found initially; set TERMINFO_DIRS={merged} and continued.\n"
                            )
                        return
                    except Exception:
                        pass
                    # Still failing — provide actionable guidance and exit.
                    term = current_term
                    sys.stderr.write(
                        "Unable to initialize terminal capabilities (terminfo).\n"
                        f"TERM={term}. Error: {e}\n"
                        "Install the terminfo database for your system. Examples:\n"
                        "  - Debian/Ubuntu: sudo apt-get install ncurses-term\n"
                        "  - Fedora:        sudo dnf install ncurses-term\n"
                        "  - Arch:          sudo pacman -S ncurses\n"
                        "  - Termux:        pkg install ncurses\n"
                        "Alternatively, export TERMINFO_DIRS to the correct terminfo path.\n"
                        "Then re-run this command, or use a non-TUI mode (e.g., --json).\n"
                    )
                    raise SystemExit(2)

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
            # Set timeout for auto-refresh when calculating sizes
            if self.state.calculating_sizes:
                stdscr.timeout(100)  # 100ms timeout for auto-refresh
            else:
                stdscr.timeout(-1)   # Blocking wait for input

            self._draw_screen(stdscr)
            key = stdscr.getch()

            # Handle timeout (no key pressed)
            if key == -1:
                continue  # Just redraw and continue

            # Quit handling
            if key in (17, ord('Q')):  # Ctrl+Q or uppercase Q => immediate
                break
            # If awaiting confirmation, handle y/n
            if getattr(self.state, "confirm_quit", False):
                if key in (ord('y'), ord('Y')):
                    break
                if key in (ord('n'), ord('N'), 27):  # ESC cancels
                    self.state.confirm_quit = False
                continue

            # Detail view mode
            if self.state.detail_view:
                if self._handle_detail_key(key):
                    continue
                # Unhandled keys just refresh view without exiting detail mode
                continue

            if self.state.editing_filter:
                if self._handle_filter_input(key):
                    self._update_visible_items(reset_selection=True)
                continue

            if self.state.editing_exclusion:
                if self._handle_exclusion_input(key):
                    self._update_visible_items(reset_selection=True)
                continue

            if key in (curses.KEY_UP, ord("k")):
                self._move_selection(-1)
            elif key in (curses.KEY_DOWN, ord("j")):
                self._move_selection(1)
            elif key == curses.KEY_PPAGE:  # Page Up
                self._move_selection(-self.state.viewport_height)
                self.state.scroll_offset = 0
            elif key == curses.KEY_NPAGE:  # Page Down
                self._move_selection(self.state.viewport_height)
                self.state.scroll_offset = 0
            elif key == ord("f"):
                self._start_filter_edit()
            elif key == ord("x"):
                self._start_exclusion_edit()
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
            elif key == ord('q'):
                # Prompt before quitting; use Ctrl+Q for immediate exit
                self.state.confirm_quit = True
            elif key == curses.KEY_RIGHT:
                # Scroll name to the right (increment by 5 for smoother feel)
                self.state.scroll_offset += 5
            elif key == curses.KEY_LEFT:
                # Scroll name to the left
                self.state.scroll_offset = max(0, self.state.scroll_offset - 5)
            elif key == ord("i"):
                if self.state.visible and self.state.selected_index < len(self.state.visible):
                    self._prepare_detail_view(self.state.visible[self.state.selected_index])
                    self.state.scroll_offset = 0
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
                    self._prepare_detail_view(self.state.visible[self.state.selected_index])
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

    def _start_filter_edit(self) -> None:
        self.state.editing_filter = True
        self.state.edit_buffer = self.state.filter_pattern
        try:
            curses.curs_set(1)
        except curses.error:
            pass

    def _start_exclusion_edit(self) -> None:
        self.state.editing_exclusion = True
        self.state.exclusion_edit_buffer = self.state.exclusion_pattern
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

    def _handle_exclusion_input(self, key: int) -> bool:
        if key in (curses.KEY_ENTER, 10, 13):
            self.state.exclusion_pattern = self.state.exclusion_edit_buffer
            self.state.editing_exclusion = False
            try:
                curses.curs_set(0)
            except curses.error:
                pass
            return True
        if key in (27,):  # Escape
            self.state.editing_exclusion = False
            self.state.exclusion_edit_buffer = self.state.exclusion_pattern
            try:
                curses.curs_set(0)
            except curses.error:
                pass
            return False
        if key in (curses.KEY_BACKSPACE, 127, 8):
            self.state.exclusion_edit_buffer = self.state.exclusion_edit_buffer[:-1]
        elif 32 <= key <= 126:
            self.state.exclusion_edit_buffer += chr(key)
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
        if self.sort_change_handler:
            try:
                self.sort_change_handler(self.state.sort_field, self.state.descending)
            except Exception:
                pass
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
        # Apply inclusion filter
        if self.state.filter_pattern:
            self.state.visible = [
                item for item in self.state.items if self._matches_pattern(item, self.state.filter_pattern)
            ]
        else:
            self.state.visible = list(self.state.items)

        # Apply exclusion filter
        if self.state.exclusion_pattern:
            self.state.visible = [
                item for item in self.state.visible if not self._matches_pattern(item, self.state.exclusion_pattern)
            ]

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
        # Clear entire screen to prevent corruption
        stdscr.clear()
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
        if self.state.editing_filter:
            filter_display = f"Filter: {self.state.edit_buffer}"
        elif self.state.editing_exclusion:
            filter_display = f"Exclude: {self.state.exclusion_edit_buffer}"
        else:
            filter_display = self.state.filter_pattern or "*"
            if self.state.exclusion_pattern:
                filter_display = f"{filter_display} !{self.state.exclusion_pattern}"
            filter_display = f"Filter: {filter_display}"

        # Clear line and render with addstr
        stdscr.move(0, 0)
        stdscr.clrtoeol()
        stdscr.addstr(0, 0, filter_display.ljust(max_x)[:max_x - 1], curses.color_pair(2) | curses.A_BOLD)

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

        # Clear line and render with addstr
        stdscr.move(1, 0)
        stdscr.clrtoeol()
        stdscr.addstr(1, 0, sort_line[:max_x - 1], curses.color_pair(2))

        if self.state.columns_line:
            try:
                stdscr.move(header_lines, 0)
                stdscr.clrtoeol()
                columns_line = self.state.columns_line
                if self.state.scroll_offset:
                    max_scroll = max(0, len(columns_line) - (max_x - 1))
                    offset = min(self.state.scroll_offset, max_scroll)
                    columns_line = columns_line[offset:]
                stdscr.addstr(
                    header_lines,
                    0,
                    columns_line[: max_x - 1],
                    curses.color_pair(2) | curses.A_BOLD,
                )
                header_lines += 1
                list_start += 1
                list_height = max(1, max_y - (header_lines + footer_lines))
                self.state.viewport_height = list_height
            except curses.error:
                pass

        # Progress bar (if calculating sizes)
        if self.state.calculating_sizes:
            current, total = self.state.calc_progress
            if total > 0:
                progress_pct = int((current / total) * 100)
                bar_width = min(40, max_x - 30)
                filled = int((current / total) * bar_width)
                bar = "#" * filled + "-" * (bar_width - filled)
                progress_line = f"Calculating sizes: [{bar}] {progress_pct}% ({current}/{total})"
                try:
                    stdscr.move(header_lines, 0)
                    stdscr.clrtoeol()
                    stdscr.addstr(header_lines, 0, progress_line[:max_x - 1], curses.color_pair(3))
                    header_lines += 1
                    list_start += 1
                    list_height = max(1, max_y - (header_lines + footer_lines))
                    self.state.viewport_height = list_height
                except curses.error:
                    pass

        if self.state.editing_filter:
            cursor_x = min(len("Filter: ") + len(self.state.edit_buffer), max_x - 1)
            stdscr.move(0, cursor_x)
        elif self.state.editing_exclusion:
            cursor_x = min(len("Exclude: ") + len(self.state.exclusion_edit_buffer), max_x - 1)
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

                # Pass scroll_offset for all rows to support horizontal panning
                # Use max_x - 1 to ensure line doesn't exceed terminal width
                scroll_off = self.state.scroll_offset
                line = self.formatter(
                    item,
                    self.state.sort_field,
                    max_x - 1,
                    self.state.show_date,
                    self.state.show_time,
                    scroll_off,
                )

                # Ensure line doesn't exceed terminal width
                if len(line) > max_x - 1:
                    line = line[:max_x - 1]

                # Determine colors
                size_color_pair = self._get_size_color_pair(item, min_size, max_size)
                name_color_pair = self.name_color_getter(item) if self.name_color_getter else 1

                # Check if selected
                is_selected = entry_idx == self.state.selected_index

                try:
                    # Clear the entire line first to prevent corruption from wide characters
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

                            # Use addstr and get cursor position to handle wide characters
                            try:
                                stdscr.addstr(list_start + draw_idx, 0, name_part[:max_x - 1], name_attr)
                                # Get actual cursor position after rendering (accounts for wide chars)
                                y, x = stdscr.getyx()
                            except curses.error:
                                # If name_part is too long, truncate it
                                safe_len = min(len(name_part), max_x - len(size_part) - 5)
                                stdscr.addstr(list_start + draw_idx, 0, name_part[:safe_len], name_attr)
                                y, x = stdscr.getyx()

                            # Render size part at cursor position
                            size_attr = curses.color_pair(size_color_pair)
                            if is_selected:
                                size_attr |= curses.A_REVERSE

                            if x < max_x - len(size_part):
                                try:
                                    stdscr.addstr(y, x, size_part[:max_x - x - 1], size_attr)
                                except curses.error:
                                    pass  # Ignore if we can't render size part
                        else:
                            # Fallback: render whole line with name color
                            attr = curses.color_pair(name_color_pair)
                            if is_selected:
                                attr |= curses.A_REVERSE
                            stdscr.addstr(list_start + draw_idx, 0, line[:max_x - 1], attr)
                    else:
                        # Single color rendering (original behavior)
                        attr = curses.color_pair(size_color_pair)
                        if is_selected:
                            attr |= curses.A_REVERSE
                        stdscr.addstr(list_start + draw_idx, 0, line[:max_x - 1], attr)

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
                # Clear the line first
                y_pos = max_y - footer_lines + idx + 1
                stdscr.move(y_pos, 0)
                stdscr.clrtoeol()
                # Use addstr instead of addnstr to handle wide characters better
                padded_text = text.ljust(max_x)[:max_x - 1]
                stdscr.addstr(y_pos, 0, padded_text, curses.color_pair(2))
            except curses.error:
                pass

        # Quit confirmation prompt overlay
        if getattr(self.state, "confirm_quit", False):
            prompt = "Quit? (y/N)"
            try:
                stdscr.move(max_y - 1, 0)
                stdscr.clrtoeol()
                stdscr.addstr(max_y - 1, 0, prompt.ljust(max_x)[:max_x - 1], curses.color_pair(3) | curses.A_REVERSE)
            except curses.error:
                pass

        stdscr.refresh()


 
    def _draw_detail_view(self, stdscr, max_y: int, max_x: int) -> None:
        """Render the structured detail view with navigation support."""
        title = self.state.detail_title or "Detail View"
        footer = self.state.detail_footer or DETAIL_FOOTER_DEFAULT

        stdscr.addnstr(0, 0, title.ljust(max_x)[: max_x - 1], max_x - 1, curses.color_pair(2) | curses.A_BOLD)
        stdscr.addnstr(1, 0, "-" * (max_x - 1), max_x - 1, curses.color_pair(2))

        content_start = 2
        content_height = max(1, max_y - content_start - 1)
        self._detail_content_height = content_height

        lines = self._detail_lines
        total_lines = len(lines)
        max_scroll = max(0, total_lines - content_height)
        if self.state.detail_scroll > max_scroll:
            self.state.detail_scroll = max_scroll

        visible_end = min(total_lines, self.state.detail_scroll + content_height)

        # Clear content area
        for row in range(content_height):
            try:
                stdscr.move(content_start + row, 0)
                stdscr.clrtoeol()
            except curses.error:
                pass

        for idx, line_index in enumerate(range(self.state.detail_scroll, visible_end)):
            text = lines[line_index] if line_index < total_lines else ""
            attr = curses.color_pair(1)
            if self._detail_meta and line_index < len(self._detail_meta):
                entry_idx, is_summary = self._detail_meta[line_index]
                if is_summary:
                    attr = curses.color_pair(3)
                    if (
                        self.state.detail_entries
                        and entry_idx == self.state.detail_selection
                        and entry_idx < len(self.state.detail_entries)
                    ):
                        attr |= curses.A_REVERSE
            try:
                stdscr.addnstr(content_start + idx, 0, text.ljust(max_x)[: max_x - 1], max_x - 1, attr)
            except curses.error:
                pass

        # Footer
        try:
            stdscr.addnstr(
                max_y - 1,
                0,
                footer.ljust(max_x)[: max_x - 1],
                max_x - 1,
                curses.color_pair(2),
            )
        except curses.error:
            pass

    def _handle_detail_key(self, key: int) -> bool:
        """Handle keypresses while the detail pane is active."""
        if not self.state.detail_view:
            return False

        if self.state.detail_entries:
            if key in (curses.KEY_UP, ord("k")):
                self._detail_move_selection(-1)
            elif key in (curses.KEY_DOWN, ord("j")):
                self._detail_move_selection(1)
            elif key == curses.KEY_PPAGE:
                self._detail_page(-1)
            elif key == curses.KEY_NPAGE:
                self._detail_page(1)
            elif key in (ord("g"),):
                self._detail_jump(start=True)
            elif key in (ord("G"),):
                self._detail_jump(start=False)
            elif key == ord("e"):
                self._detail_set_expanded(True)
            elif key == ord("c"):
                self._detail_set_expanded(False)
            elif key in (curses.KEY_ENTER, 10, 13):
                self._detail_toggle_selected()
            elif key in (27, ord("q")):
                self._exit_detail_view()
            else:
                return False
            return True

        # Fallback handling when detail formatter returns simple text
        total_lines = len(self._detail_lines)
        content_height = max(1, self._detail_content_height or 1)
        max_scroll = max(0, total_lines - content_height)

        if key in (curses.KEY_UP, ord("k")):
            if self.state.detail_scroll > 0:
                self.state.detail_scroll -= 1
        elif key in (curses.KEY_DOWN, ord("j")):
            if self.state.detail_scroll < max_scroll:
                self.state.detail_scroll += 1
        elif key == curses.KEY_PPAGE:
            self.state.detail_scroll = max(0, self.state.detail_scroll - content_height)
        elif key == curses.KEY_NPAGE:
            self.state.detail_scroll = min(max_scroll, self.state.detail_scroll + content_height)
        elif key in (27, ord("q"), curses.KEY_ENTER, 10, 13):
            self._exit_detail_view()
        else:
            return False
        return True

    def _normalize_detail_payload(self, payload: Any) -> Tuple[DetailViewData, Optional[List[str]]]:
        if isinstance(payload, DetailViewData):
            return payload, None
        if isinstance(payload, list):
            fallback = [str(line) for line in payload]
        elif payload is None:
            fallback = []
        else:
            fallback = [str(payload)]
        return DetailViewData(title="Detail View", entries=[], footer=None), fallback

    def _prepare_detail_view(self, item: Any) -> None:
        """Initialise detail view state for the selected item."""
        raw = self.detail_formatter(item) if self.detail_formatter else []
        data, fallback = self._normalize_detail_payload(raw)

        self.state.detail_view = True
        self.state.detail_item = item
        self.state.detail_title = data.title
        self.state.detail_footer = data.footer or DETAIL_FOOTER_DEFAULT
        self.state.detail_entries = list(data.entries)
        self.state.detail_selection = 0
        self.state.detail_scroll = 0

        if self.state.detail_entries:
            self._detail_rebuild_lines()
            self._detail_ensure_visible()
        else:
            self._detail_lines = list(fallback or [])
            self._detail_meta = []
            self._detail_focusable = []

    def _detail_rebuild_lines(self) -> None:
        """Recompute flattened detail lines for rendering."""
        lines: List[str] = []
        meta: List[Tuple[int, bool]] = []
        focusable: List[int] = []

        for idx, entry in enumerate(self.state.detail_entries):
            marker = "-" if entry.expanded else "+"
            summary = f"{marker} {entry.summary}"
            lines.append(summary)
            meta.append((idx, True))
            if entry.focusable:
                focusable.append(idx)
            if entry.expanded:
                for body in entry.body:
                    body_line = f"    {body}"
                    lines.append(body_line)
                    meta.append((idx, False))

        self._detail_lines = lines
        self._detail_meta = meta
        self._detail_focusable = focusable or ([0] if self.state.detail_entries else [])

        if self.state.detail_entries and self._detail_focusable:
            if self.state.detail_selection not in self._detail_focusable:
                self.state.detail_selection = self._detail_focusable[0]

    def _detail_move_selection(self, delta: int) -> None:
        if not self._detail_focusable:
            return
        current = self.state.detail_selection
        if current not in self._detail_focusable:
            current = self._detail_focusable[0]
        pos = self._detail_focusable.index(current)
        new_pos = max(0, min(len(self._detail_focusable) - 1, pos + delta))
        self.state.detail_selection = self._detail_focusable[new_pos]
        self._detail_ensure_visible()

    def _detail_page(self, direction: int) -> None:
        if not self._detail_focusable:
            return
        step = max(1, self._detail_content_height or 1) * direction
        self._detail_move_selection(step)

    def _detail_toggle_selected(self) -> None:
        idx = self.state.detail_selection
        if not (0 <= idx < len(self.state.detail_entries)):
            return
        entry = self.state.detail_entries[idx]
        if not entry.focusable:
            return
        entry.expanded = not entry.expanded
        self._detail_rebuild_lines()
        self._detail_ensure_visible()

    def _detail_set_expanded(self, value: bool) -> None:
        changed = False
        for entry in self.state.detail_entries:
            if entry.focusable and entry.expanded != value:
                entry.expanded = value
                changed = True
        if changed:
            self._detail_rebuild_lines()
            self._detail_ensure_visible()

    def _detail_jump(self, start: bool) -> None:
        if not self._detail_focusable:
            return
        target = self._detail_focusable[0] if start else self._detail_focusable[-1]
        self.state.detail_selection = target
        self._detail_ensure_visible(force=True)

    def _detail_ensure_visible(self, force: bool = False) -> None:
        if not self._detail_meta:
            return
        if self._detail_content_height <= 0:
            return
        selected = self.state.detail_selection
        summary_line = next(
            (idx for idx, (entry_idx, is_summary) in enumerate(self._detail_meta) if is_summary and entry_idx == selected),
            None,
        )
        if summary_line is None:
            return
        top = self.state.detail_scroll
        bottom = top + self._detail_content_height - 1
        if force or summary_line < top:
            self.state.detail_scroll = summary_line
        elif summary_line > bottom:
            self.state.detail_scroll = summary_line - self._detail_content_height + 1
        max_scroll = max(0, len(self._detail_lines) - self._detail_content_height)
        if self.state.detail_scroll > max_scroll:
            self.state.detail_scroll = max_scroll

    def _exit_detail_view(self) -> None:
        self.state.detail_view = False
        self.state.detail_item = None
        self.state.detail_entries = []
        self.state.detail_scroll = 0
        self.state.detail_selection = 0
        self._detail_lines = []
        self._detail_meta = []
        self._detail_focusable = []


def render_items_to_text(
    items: Sequence[Any],
    formatter: Callable[[Any, str, int, bool, bool, int], str],
    *,
    sort_field: str = "",
    width: Optional[int] = None,
    show_date: bool = True,
    show_time: bool = True,
) -> List[str]:
    """
    Render list items using the provided formatter into plain text lines.

    Args:
        items: sequence of items matching the formatter signature.
        formatter: same formatter used by InteractiveList.
        sort_field: name of the active sort field (passed to formatter).
        width: optional target width (defaults to terminal width or 120 fallback).
        show_date: whether formatter should include date information.
        show_time: whether formatter should include time information.
    """
    if width is None:
        width = shutil.get_terminal_size(fallback=(120, 40)).columns

    lines: List[str] = []
    for item in items:
        lines.append(formatter(item, sort_field, max(10, width), show_date, show_time, 0))
    return lines
