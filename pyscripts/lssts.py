from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Sequence

try:
    import curses
except ImportError:  # pragma: no cover - platform dependent
    curses = None  # type: ignore[assignment]


@dataclass
class Entry:
    path: Path
    name: str
    is_dir: bool
    size: int
    created: datetime
    modified: datetime
    accessed: datetime


@dataclass
class AppState:
    directory: Path
    entries: List[Entry]
    filter_pattern: str = ""
    sort_field: str = "created"
    descending: bool = True
    visible: List[Entry] = field(default_factory=list)
    selected_index: int = 0
    top_index: int = 0
    viewport_height: int = 1
    editing_filter: bool = False
    edit_buffer: str = ""


SORT_FUNCS: Dict[str, Callable[[Entry], object]] = {
    "created": lambda entry: entry.created.timestamp(),
    "modified": lambda entry: entry.modified.timestamp(),
    "accessed": lambda entry: entry.accessed.timestamp(),
    "size": lambda entry: entry.size,
    "name": lambda entry: entry.name.lower(),
}

DATE_FIELDS = {"created", "modified", "accessed"}


def read_entries(target: Path) -> List[Entry]:
    entries: List[Entry] = []
    try:
        candidates: Iterable[Path] = target.iterdir()
    except OSError as exc:
        raise RuntimeError(f"Cannot read directory {target}: {exc}") from exc

    for item in candidates:
        try:
            stats = item.stat()
        except OSError:
            continue

        entries.append(
            Entry(
                path=item,
                name=item.name,
                is_dir=item.is_dir(),
                size=stats.st_size,
                created=datetime.fromtimestamp(stats.st_ctime),
                modified=datetime.fromtimestamp(stats.st_mtime),
                accessed=datetime.fromtimestamp(stats.st_atime),
            )
        )
    return entries


def filter_entries(entries: Sequence[Entry], pattern: str) -> List[Entry]:
    if not pattern:
        return list(entries)
    return [entry for entry in entries if fnmatch(entry.name, pattern)]


def sort_entries(entries: List[Entry], field: str, descending: bool) -> None:
    sort_func = SORT_FUNCS[field]
    entries.sort(key=sort_func, reverse=descending)


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


def to_json(entries: Sequence[Entry]) -> str:
    payload = [
        {
            "name": entry.name,
            "path": str(entry.path.resolve()),
            "is_dir": entry.is_dir,
            "size": entry.size,
            "created": entry.created.isoformat(),
            "modified": entry.modified.isoformat(),
            "accessed": entry.accessed.isoformat(),
        }
        for entry in entries
    ]
    return json.dumps(payload, indent=2)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interactive directory browser with sorting, filtering, and JSON export."
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to inspect (defaults to current directory).",
    )
    parser.add_argument(
        "-g",
        "--glob",
        metavar="PATTERN",
        help="Initial glob pattern to filter entries (e.g. '*.py').",
    )
    parser.add_argument(
        "-s",
        "--sort",
        choices=("created", "modified", "accessed", "size", "name"),
        default="created",
        help="Initial sort field to use.",
    )
    parser.add_argument(
        "-o",
        "--order",
        choices=("asc", "desc"),
        default="desc",
        help="Initial sort order to use.",
    )
    parser.add_argument(
        "-J",
        "--json",
        action="store_true",
        help="Emit JSON to stdout instead of launching the TUI.",
    )
    return parser.parse_args(argv)


def ensure_curses_available() -> None:
    if curses is None:  # pragma: no cover - platform dependent
        sys.stderr.write(
            "This tool requires curses for the TUI. On Windows install the 'windows-curses' package.\n"
        )
        raise SystemExit(2)


def run_tui(state: AppState) -> None:
    ensure_curses_available()
    curses.wrapper(_tui_main, state)


def _tui_main(stdscr, state: AppState) -> None:
    try:
        curses.curs_set(0)
    except curses.error:
        pass

    if curses.has_colors():
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_WHITE, -1)  # default text
        curses.init_pair(2, curses.COLOR_CYAN, -1)  # header / footer
        curses.init_pair(3, curses.COLOR_YELLOW, -1)  # highlight

    update_visible_entries(state, reset_selection=True)

    while True:
        draw_screen(stdscr, state)
        key = stdscr.getch()

        if key in (17,):  # Ctrl+Q
            break

        if state.editing_filter:
            if handle_filter_input(state, key):
                update_visible_entries(state, reset_selection=True)
            continue

        if key in (curses.KEY_UP, ord("k")):
            move_selection(state, -1)
        elif key in (curses.KEY_DOWN, ord("j")):
            move_selection(state, 1)
        elif key == ord("f"):
            start_filter_edit(state)
        else:
            handled_sort = handle_sort_key(state, key)
            if handled_sort:
                update_visible_entries(state)


def start_filter_edit(state: AppState) -> None:
    state.editing_filter = True
    state.edit_buffer = state.filter_pattern
    if curses:
        try:
            curses.curs_set(1)
        except curses.error:
            pass


def handle_filter_input(state: AppState, key: int) -> bool:
    if key in (curses.KEY_ENTER, 10, 13):
        state.filter_pattern = state.edit_buffer
        state.editing_filter = False
        if curses:
            try:
                curses.curs_set(0)
            except curses.error:
                pass
        return True
    if key in (27,):  # Escape
        state.editing_filter = False
        state.edit_buffer = state.filter_pattern
        if curses:
            try:
                curses.curs_set(0)
            except curses.error:
                pass
        return False
    if key in (curses.KEY_BACKSPACE, 127, 8):
        state.edit_buffer = state.edit_buffer[:-1]
        return False
    if 32 <= key <= 126:
        state.edit_buffer += chr(key)
    return False


def handle_sort_key(state: AppState, key: int) -> bool:
    mapping = {
        ord("c"): "created",
        ord("m"): "modified",
        ord("a"): "accessed",
        ord("s"): "size",
        ord("n"): "name",
    }
    field = mapping.get(key)
    if not field:
        return False
    if state.sort_field == field:
        state.descending = not state.descending
    else:
        state.sort_field = field
        # Dates and size default to descending; name defaults to ascending.
        state.descending = field != "name"
    return True


def move_selection(state: AppState, delta: int) -> None:
    if not state.visible:
        return
    state.selected_index = max(
        0, min(state.selected_index + delta, len(state.visible) - 1)
    )
    if state.selected_index < state.top_index:
        state.top_index = state.selected_index
    elif state.selected_index >= state.top_index + state.viewport_height:
        state.top_index = state.selected_index - state.viewport_height + 1


def update_visible_entries(state: AppState, reset_selection: bool = False) -> None:
    state.visible = filter_entries(state.entries, state.filter_pattern)
    sort_entries(state.visible, state.sort_field, state.descending)
    if not state.visible:
        state.selected_index = 0
        state.top_index = 0
        return
    if reset_selection or state.selected_index >= len(state.visible):
        state.selected_index = 0
        state.top_index = 0
    else:
        if state.selected_index < state.top_index:
            state.top_index = state.selected_index
        elif state.selected_index >= state.top_index + state.viewport_height:
            state.top_index = max(
                0, state.selected_index - state.viewport_height + 1
            )


def draw_screen(stdscr, state: AppState) -> None:
    stdscr.erase()
    max_y, max_x = stdscr.getmaxyx()

    header_lines = 2
    footer_lines = 3
    list_start = header_lines
    list_height = max(1, max_y - (header_lines + footer_lines))
    state.viewport_height = list_height

    filter_display = state.edit_buffer if state.editing_filter else state.filter_pattern
    if not filter_display:
        filter_display = "*"
    filter_prefix = "Filter: "
    filter_line = f"{filter_prefix}{filter_display}"
    stdscr.addnstr(
        0,
        0,
        filter_line.ljust(max_x),
        max_x - 1,
        curses.color_pair(2) | curses.A_BOLD if curses and curses.has_colors() else 0,
    )

    sort_line = (
        f"Path: {state.directory} | "
        f"Sort: {state.sort_field} ({'desc' if state.descending else 'asc'}) | "
        f"Items: {len(state.visible)}"
    )
    stdscr.addnstr(
        1,
        0,
        sort_line[: max_x - 1],
        max_x - 1,
        curses.color_pair(2) if curses and curses.has_colors() else 0,
    )

    if state.editing_filter:
        cursor_x = min(len(filter_prefix) + len(state.edit_buffer), max_x - 1)
        stdscr.move(0, cursor_x)

    if state.visible:
        for draw_idx in range(list_height):
            entry_idx = state.top_index + draw_idx
            if entry_idx >= len(state.visible):
                break
            entry = state.visible[entry_idx]
            line = format_entry_line(entry, state.sort_field, max_x)
            attr = curses.color_pair(1) if curses and curses.has_colors() else 0
            if entry.is_dir:
                attr |= curses.A_BOLD
            if entry_idx == state.selected_index:
                highlight = curses.color_pair(3) | curses.A_REVERSE
                attr = highlight
            stdscr.addnstr(list_start + draw_idx, 0, line, max_x - 1, attr)
    else:
        stdscr.addnstr(
            list_start,
            0,
            "-- no matches --",
            max_x - 1,
            curses.color_pair(1) if curses and curses.has_colors() else 0,
        )

    footer_y = max_y - footer_lines
    if footer_y > 1:
        try:
            stdscr.hline(footer_y, 0, curses.ACS_HLINE, max_x)
        except curses.error:
            pass

    footer_lines_text = [
        "Up/Down: move  |  f: filter  |  Ctrl+Q: quit",
        "c: created  m: modified  a: accessed  n: name  s: size",
        "Repeat sort key to toggle order  |  --json for machine output",
    ]
    for idx, text in enumerate(footer_lines_text):
        stdscr.addnstr(
            max_y - footer_lines + idx,
            0,
            text.ljust(max_x),
            max_x - 1,
            curses.color_pair(2) if curses and curses.has_colors() else 0,
        )

    stdscr.refresh()


def format_entry_line(entry: Entry, sort_field: str, width: int) -> str:
    time_source = entry.created
    if sort_field in DATE_FIELDS:
        time_source = getattr(entry, sort_field)
    timestamp = time_source.strftime("%Y-%m-%d %H:%M:%S")
    size_text = human_size(entry.size)
    name = entry.name + ("/" if entry.is_dir else "")

    name_space = max(1, width - len(timestamp) - len(size_text) - 4)
    if len(name) > name_space:
        if name_space <= 3:
            name = name[: name_space]
        else:
            name = name[: name_space - 3] + "..."
    name = name.ljust(name_space)
    return f"{timestamp}  {name}  {size_text}"


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    target = Path(args.directory).expanduser()

    if not target.exists() or not target.is_dir():
        sys.stderr.write(f"Path does not exist or is not a directory: {target}\n")
        return 1

    entries = read_entries(target)
    initial_filter = args.glob or ""
    initial_desc = args.order == "desc"

    visible = filter_entries(entries, initial_filter)
    sort_entries(visible, args.sort, initial_desc)

    if args.json:
        sys.stdout.write(to_json(visible) + "\n")
        return 0

    state = AppState(
        directory=target,
        entries=entries,
        filter_pattern=initial_filter,
        sort_field=args.sort,
        descending=initial_desc,
        visible=visible,
    )
    run_tui(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
