"""Interactive full-screen browser for scripts-help."""

from __future__ import annotations

import os
import re
import select
import shutil
import subprocess
import sys
import textwrap
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts_help._repo_root import find_repo_root
from scripts_help.help_parser import format_argument, parse_help_text
from scripts_help.inventory import HelpCategory, HelpItem, build_categories


_CLEAR = "\x1b[2J\x1b[H"
_HIDE_CURSOR = "\x1b[?25l"
_SHOW_CURSOR = "\x1b[?25h"
_INVERSE = "\x1b[7m"
_RESET = "\x1b[0m"
_NUMBER_WAIT = 0.65


@dataclass(frozen=True)
class MenuEntry:
    number: int
    label: str
    description: str
    payload: Any
    search_text: str = ""


class KeyReader:
    """Cross-platform single-key reader for Windows Terminal and POSIX TTYs."""

    def __init__(self) -> None:
        self._fd: int | None = None
        self._saved: Any = None

    def __enter__(self) -> "KeyReader":
        self._enable_raw()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._disable_raw()

    def _enable_raw(self) -> None:
        if os.name == "nt":
            return
        if not sys.stdin.isatty():
            return
        import termios
        import tty

        self._fd = sys.stdin.fileno()
        if self._saved is None:
            self._saved = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)

    def _disable_raw(self) -> None:
        if os.name == "nt":
            return
        if self._fd is None or self._saved is None:
            return
        import termios

        termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)

    @contextmanager
    def suspended(self):
        self._disable_raw()
        sys.stdout.write(_SHOW_CURSOR)
        sys.stdout.flush()
        try:
            yield
        finally:
            self._enable_raw()
            sys.stdout.write(_HIDE_CURSOR)
            sys.stdout.flush()

    def read(self, timeout: float | None = None) -> str:
        if os.name == "nt":
            return self._read_windows(timeout)
        return self._read_posix(timeout)

    def _read_windows(self, timeout: float | None) -> str:
        import msvcrt

        deadline = None if timeout is None else time.monotonic() + max(timeout, 0)
        while not msvcrt.kbhit():
            if deadline is not None and time.monotonic() >= deadline:
                return "TIMEOUT"
            time.sleep(0.01)

        char = msvcrt.getwch()
        if char in ("\x00", "\xe0"):
            code = msvcrt.getwch()
            return {
                "H": "UP",
                "P": "DOWN",
                "I": "PAGEUP",
                "Q": "PAGEDOWN",
                "G": "HOME",
                "O": "END",
            }.get(code, "UNKNOWN")
        if char == "\r":
            return "ENTER"
        if char == "\x1b":
            return "ESC"
        if char in ("\x08", "\x7f"):
            return "BACKSPACE"
        return char

    def _read_posix(self, timeout: float | None) -> str:
        if timeout is not None:
            ready, _, _ = select.select([sys.stdin], [], [], max(timeout, 0))
            if not ready:
                return "TIMEOUT"

        char = sys.stdin.read(1)
        if char == "":
            return "ESC"
        if char in ("\r", "\n"):
            return "ENTER"
        if char in ("\x7f", "\x08"):
            return "BACKSPACE"
        if char != "\x1b":
            return char

        ready, _, _ = select.select([sys.stdin], [], [], 0.025)
        if not ready:
            return "ESC"
        seq = sys.stdin.read(1)
        if seq not in ("[", "O"):
            return "ESC"

        tail = sys.stdin.read(1)
        if tail in "ABHF":
            return {
                "A": "UP",
                "B": "DOWN",
                "H": "HOME",
                "F": "END",
            }[tail]
        if seq == "O":
            return "UNKNOWN"
        if tail in "56":
            maybe = sys.stdin.read(1)
            if maybe == "~":
                return "PAGEUP" if tail == "5" else "PAGEDOWN"
        return "UNKNOWN"


def filter_entries(entries: list[MenuEntry], query: str) -> list[MenuEntry]:
    """Filter without renumbering; original numbers remain stable."""

    needle = query.casefold().strip()
    if not needle:
        return list(entries)
    return [
        entry
        for entry in entries
        if needle
        in " ".join(
            (entry.label, entry.description, entry.search_text)
        ).casefold()
    ]


def _terminal_size() -> tuple[int, int]:
    size = shutil.get_terminal_size((100, 30))
    return max(50, size.columns), max(16, size.lines)


def _clip(text: str, width: int) -> str:
    """Compact and clip prose used inside single-line menu rows."""

    clean = re.sub(r"\s+", " ", text).strip()
    if len(clean) <= width:
        return clean
    if width <= 1:
        return clean[:width]
    return clean[: width - 1] + "…"


def _clip_display_line(text: str, width: int) -> str:
    """Clip terminal content without destroying indentation or column spacing."""

    line = text.expandtabs(4).rstrip("\r\n")
    if len(line) <= width:
        return line
    if width <= 1:
        return line[:width]
    return line[: width - 1] + "…"


def _write_screen(lines: list[str], footer: str) -> None:
    width, height = _terminal_size()
    body_height = max(1, height - 1)
    output = [_CLEAR]
    for line in lines[:body_height]:
        output.append(_clip_display_line(line, width) if "\x1b[" not in line else line)
        output.append("\n")
    for _ in range(max(0, body_height - min(len(lines), body_height))):
        output.append("\n")
    output.append(_clip_display_line(footer, width))
    sys.stdout.write("".join(output))
    sys.stdout.flush()


def _wrapped_lines(text: str, width: int, indent: str = "") -> list[str]:
    return textwrap.wrap(
        " ".join(text.split()),
        width=max(20, width - len(indent)),
        initial_indent=indent,
        subsequent_indent=indent,
    ) or [indent]


def _confirm_exit(reader: KeyReader) -> bool:
    while True:
        _write_screen(
            [
                "SCRIPTS HELP",
                "",
                "Exit the repository help browser?",
                "",
                "  y  Yes",
                "  n  No",
            ],
            "Y Exit   N/Esc Return",
        )
        key = reader.read()
        if key.casefold() == "y":
            return True
        if key.casefold() == "n" or key == "ESC":
            return False


def _select_menu(
    reader: KeyReader,
    title: str,
    subtitle: str,
    entries: list[MenuEntry],
    *,
    allow_search: bool,
    root: bool = False,
    intro_lines: list[str] | None = None,
) -> MenuEntry | None:
    selected = 0
    query = ""
    editing_search = False
    number_buffer = ""
    number_deadline: float | None = None

    while True:
        visible = filter_entries(entries, query)
        if visible:
            selected = min(selected, len(visible) - 1)
        else:
            selected = 0

        width, height = _terminal_size()
        lines = [title, "=" * min(width, 72)]
        if subtitle:
            lines.extend(_wrapped_lines(subtitle, width))
        if intro_lines:
            lines.append("")
            max_intro = max(3, height // 2)
            shown_intro = list(intro_lines[:max_intro])
            if len(intro_lines) > max_intro:
                shown_intro[-1] = (
                    f"  … {len(intro_lines) - max_intro + 1} more detail line(s); "
                    "open the relevant viewer to see all."
                )
            lines.extend(shown_intro)

        if query or editing_search:
            lines.append("")
            cursor = "▌" if editing_search else ""
            lines.append(f"Filter: {query}{cursor}")

        lines.append("")
        fixed = len(lines) + 1
        capacity = max(3, height - fixed - 1)
        if visible:
            start = max(0, selected - capacity // 2)
            start = min(start, max(0, len(visible) - capacity))
            for pos, entry in enumerate(visible[start : start + capacity], start):
                marker = ">" if pos == selected else " "
                row = f"{marker} {entry.number:>3}. {entry.label}"
                if entry.description:
                    room = max(0, width - len(row) - 3)
                    row += " — " + _clip(entry.description, room)
                if pos == selected:
                    row = f"{_INVERSE}{row}{_RESET}"
                lines.append(row)
        else:
            lines.append("  No matching items.")

        if editing_search:
            footer = "Type to filter   Backspace Delete   Enter Open   Esc Finish search"
        else:
            search_hint = "   / Search" if allow_search else ""
            back_hint = "Esc Exit" if root else "Esc Back"
            max_number = max((entry.number for entry in entries), default=0)
            number_hint = f"1-{max_number}" if max_number else "number"
            footer = (
                f"↑/↓ Select   Enter Open   {number_hint} Jump"
                f"{search_hint}   {back_hint}"
            )
            if query:
                footer += "   Esc Clear filter"
            if number_buffer:
                footer += f"   Number: {number_buffer}"

        _write_screen(lines, footer)

        timeout = None
        if number_deadline is not None:
            timeout = max(0.0, number_deadline - time.monotonic())
        key = reader.read(timeout)

        if key == "TIMEOUT":
            if number_buffer:
                exact = next(
                    (entry for entry in visible if str(entry.number) == number_buffer),
                    None,
                )
                if exact is not None:
                    return exact
            number_buffer = ""
            number_deadline = None
            continue

        if editing_search:
            if key == "ESC":
                editing_search = False
                number_buffer = ""
                continue
            if key == "BACKSPACE":
                query = query[:-1]
                selected = 0
                continue
            if key == "ENTER":
                if visible:
                    return visible[selected]
                continue
            if len(key) == 1 and key.isprintable():
                query += key
                selected = 0
            continue

        if key == "UP" and visible:
            selected = (selected - 1) % len(visible)
            number_buffer = ""
            number_deadline = None
            continue
        if key == "DOWN" and visible:
            selected = (selected + 1) % len(visible)
            number_buffer = ""
            number_deadline = None
            continue
        if key == "HOME" and visible:
            selected = 0
            continue
        if key == "END" and visible:
            selected = len(visible) - 1
            continue
        if key == "PAGEUP" and visible:
            selected = max(0, selected - max(3, capacity - 1))
            continue
        if key == "PAGEDOWN" and visible:
            selected = min(len(visible) - 1, selected + max(3, capacity - 1))
            continue
        if key == "ENTER" and number_buffer:
            exact = next(
                (entry for entry in visible if str(entry.number) == number_buffer),
                None,
            )
            number_buffer = ""
            number_deadline = None
            if exact is not None:
                return exact
            continue
        if key == "ENTER" and visible:
            return visible[selected]

        if key == "/" and allow_search:
            editing_search = True
            number_buffer = ""
            number_deadline = None
            continue

        if key == "ESC":
            number_buffer = ""
            number_deadline = None
            if query:
                query = ""
                selected = 0
                continue
            if root:
                if _confirm_exit(reader):
                    return None
                continue
            return None

        if len(key) == 1 and key.isdigit():
            number_buffer += key
            candidates = [
                entry for entry in visible if str(entry.number).startswith(number_buffer)
            ]
            exact = next(
                (entry for entry in candidates if str(entry.number) == number_buffer),
                None,
            )
            longer = any(str(entry.number) != number_buffer for entry in candidates)
            if exact is not None and not longer:
                return exact
            if not candidates:
                number_buffer = ""
                number_deadline = None
            else:
                number_deadline = time.monotonic() + _NUMBER_WAIT


def _readme_path(item: HelpItem, repo: Path) -> Path | None:
    target = repo / item.path
    if target.is_dir():
        for name in ("README.md", "readme.md", "README.MD"):
            candidate = target / name
            if candidate.is_file():
                return candidate
    rel = Path(item.path)
    if item.path.startswith("pyscripts/") and rel.suffix.lower() == ".py":
        candidate = repo / "pyscripts" / "readme" / f"{rel.stem}.md"
        if candidate.is_file():
            return candidate
    return None


def _resolve_help_command(item: HelpItem, repo: Path, subcommands: tuple[str, ...] = ()) -> list[str]:
    if not item.help_cmd:
        return []

    parts = list(item.help_cmd)
    if parts and parts[-1] in ("--help", "-h"):
        parts.pop()

    resolved: list[str] = []
    for part in parts:
        if part == "python":
            resolved.append(sys.executable)
            continue
        candidate = repo / part
        if candidate.is_file():
            resolved.append(str(candidate))
        else:
            resolved.append(part)

    resolved.extend(subcommands)
    resolved.append("--help")
    return resolved


def _run_help(item: HelpItem, repo: Path, subcommands: tuple[str, ...] = ()) -> tuple[str, list[str]]:
    command = _resolve_help_command(item, repo, subcommands)
    if not command:
        return "", []
    try:
        result = subprocess.run(
            command,
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"Unable to run help command: {exc}", command

    output = (result.stdout or "") + (result.stderr or "")
    return output.strip() or "(No help output was produced.)", command


def _view_text(reader: KeyReader, title: str, text: str, footer_extra: str = "") -> None:
    raw_lines = text.splitlines() or [""]
    offset = 0
    while True:
        width, height = _terminal_size()
        capacity = max(4, height - 4)
        offset = min(offset, max(0, len(raw_lines) - capacity))
        lines = [title, "=" * min(width, 72), ""]
        lines.extend(raw_lines[offset : offset + capacity])
        footer = "↑/↓ Scroll   PgUp/PgDn Page   Home/End   Esc Back"
        if footer_extra:
            footer += "   " + footer_extra
        _write_screen(lines, footer)
        key = reader.read()
        if key == "ESC" or key.casefold() == "q":
            return
        if key == "UP":
            offset = max(0, offset - 1)
        elif key == "DOWN":
            offset = min(max(0, len(raw_lines) - capacity), offset + 1)
        elif key == "PAGEUP":
            offset = max(0, offset - capacity)
        elif key == "PAGEDOWN":
            offset = min(max(0, len(raw_lines) - capacity), offset + capacity)
        elif key == "HOME":
            offset = 0
        elif key == "END":
            offset = max(0, len(raw_lines) - capacity)


def _argument_lines(output: str) -> list[str]:
    parsed = parse_help_text(output)
    if not parsed.arguments:
        return ["  (No option rows could be parsed from live help.)"]
    return ["  " + format_argument(argument) for argument in parsed.arguments]


def _show_arguments(
    reader: KeyReader,
    item: HelpItem,
    repo: Path,
    subcommands: tuple[str, ...] = (),
) -> None:
    output, command = _run_help(item, repo, subcommands)
    parsed = parse_help_text(output)
    command_name = " ".join(subcommands) if subcommands else "top level"
    title = f"{item.name} — arguments — {command_name}"
    argument_lines = _argument_lines(output)

    if not parsed.arguments and not parsed.subcommands:
        lines = [
            "No structured arguments or subcommands could be parsed.",
            "",
            "Raw live help/output:",
            output or "(No output.)",
            "",
            "Live command:",
            "  " + " ".join(command),
        ]
        _view_text(reader, title, "\n".join(lines))
        return

    if not parsed.subcommands:
        lines = argument_lines
        lines.extend(["", "Live command:", "  " + " ".join(command)])
        _view_text(reader, title, "\n".join(lines))
        return

    intro = list(argument_lines)
    intro.extend(["", "Subcommands:"])
    entries = [
        MenuEntry(
            number=1,
            label="View all top-level arguments",
            description="Open the complete live argument list in the scroll viewer.",
            payload="__all_args__",
            search_text="arguments options flags",
        )
    ]
    entries.extend(
        MenuEntry(
            number=index,
            label=sub.name,
            description=sub.description,
            payload=sub,
            search_text=sub.name,
        )
        for index, sub in enumerate(parsed.subcommands, 2)
    )

    while True:
        chosen = _select_menu(
            reader,
            title,
            "Top-level options are parsed from the live --help output. "
            "Select a subcommand to inspect its own arguments.",
            entries,
            allow_search=True,
            intro_lines=intro,
        )
        if chosen is None:
            return
        if chosen.payload == "__all_args__":
            lines = list(argument_lines)
            lines.extend(["", "Live command:", "  " + " ".join(command)])
            _view_text(reader, title + " — complete list", "\n".join(lines))
            continue
        _show_arguments(reader, item, repo, subcommands + (chosen.payload.name,))


def _show_readme(reader: KeyReader, item: HelpItem, repo: Path, readme: Path) -> None:
    if shutil.which("glow"):
        with reader.suspended():
            subprocess.run(["glow", str(readme)], cwd=str(repo), check=False)
        return
    try:
        text = readme.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        text = f"Unable to read {readme}: {exc}"
    _view_text(reader, f"{item.name} — README", text)


def _show_git_history(reader: KeyReader, item: HelpItem, repo: Path) -> None:
    if shutil.which("tig"):
        with reader.suspended():
            subprocess.run(["tig", "--", item.path], cwd=str(repo), check=False)
        return

    command = [
        "git",
        "log",
        "--graph",
        "--decorate",
        "--date=short",
        "--pretty=format:%h  %ad  %d %s",
        "--",
        item.path,
    ]
    try:
        result = subprocess.run(
            command,
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=20,
        )
        text = (result.stdout or "") + (result.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as exc:
        text = f"Unable to read Git history: {exc}"
    _view_text(reader, f"{item.name} — Git history", text.strip() or "(No commits found.)")


def _open_files(reader: KeyReader, item: HelpItem, repo: Path) -> None:
    target = repo / item.path
    if target.is_file():
        target = target.parent

    with reader.suspended():
        try:
            subprocess.run(
                ["file-util", "ls", str(target)],
                cwd=str(repo),
                check=False,
            )
        except FileNotFoundError:
            print("file-util was not found on PATH; cannot open the file viewer.")
            try:
                input("Press Enter to return...")
            except (EOFError, KeyboardInterrupt):
                pass


def _detail_intro(item: HelpItem, repo: Path) -> list[str]:
    width, _ = _terminal_size()
    lines = _wrapped_lines(item.long_description, width, indent="  ")
    lines.append("")
    lines.append(f"  Path: {item.path}")
    if item.version:
        lines.append(f"  Version: {item.version}")
    if item.help_cmd:
        invoke = " ".join(item.help_cmd[:-1] if item.help_cmd[-1:] == ("--help",) else item.help_cmd)
        lines.append(f"  Invoke: {invoke}")
    return lines


def _show_item(reader: KeyReader, item: HelpItem, repo: Path) -> None:
    while True:
        readme = _readme_path(item, repo)
        actions: list[MenuEntry] = []
        n = 1
        if item.help_cmd:
            actions.append(MenuEntry(n, "Arguments", "Parse the program's live --help output.", "args"))
            n += 1
        if readme:
            actions.append(MenuEntry(n, "README", "Open with glow when available.", "readme"))
            n += 1
        actions.append(MenuEntry(n, "Commit history", "Path-scoped Git history; uses tig when available.", "git"))
        n += 1
        actions.append(MenuEntry(n, "View files", "Open this location with file-util ls.", "files"))

        chosen = _select_menu(
            reader,
            item.name,
            item.description,
            actions,
            allow_search=True,
            intro_lines=_detail_intro(item, repo),
        )
        if chosen is None:
            return
        if chosen.payload == "args":
            _show_arguments(reader, item, repo)
        elif chosen.payload == "readme" and readme:
            _show_readme(reader, item, repo, readme)
        elif chosen.payload == "git":
            _show_git_history(reader, item, repo)
        elif chosen.payload == "files":
            _open_files(reader, item, repo)


def _drift_summary(drift: dict | None) -> str:
    if not drift:
        return ""
    pieces = []
    if drift.get("new"):
        pieces.append(f"{len(drift['new'])} unregistered")
    if drift.get("stale"):
        pieces.append(f"{len(drift['stale'])} stale")
    if drift.get("deleted"):
        pieces.append(f"{len(drift['deleted'])} deleted")
    actionable_readme = [
        row for row in drift.get("readme", ()) if row.get("issue") != "missing"
    ]
    if actionable_readme:
        pieces.append(f"{len(actionable_readme)} README")
    return ", ".join(pieces)


def run_browser(drift: dict | None = None) -> None:
    """Run the structure-first interactive browser."""

    repo = find_repo_root()
    categories = build_categories(repo)
    entries = [
        MenuEntry(
            number=index,
            label=f"{category.title} ({len(category.items)})",
            description=category.description,
            payload=category,
            search_text=category.key,
        )
        for index, category in enumerate(categories, 1)
    ]

    sys.stdout.write(_HIDE_CURSOR)
    sys.stdout.flush()
    try:
        with KeyReader() as reader:
            while True:
                drift_text = _drift_summary(drift)
                subtitle = "Browse the current scripts repository by structure."
                if drift_text:
                    subtitle += f"  Metadata drift: {drift_text}."
                chosen_category = _select_menu(
                    reader,
                    "SCRIPTS REPOSITORY HELP",
                    subtitle,
                    entries,
                    allow_search=False,
                    root=True,
                )
                if chosen_category is None:
                    return

                category: HelpCategory = chosen_category.payload
                item_entries = [
                    MenuEntry(
                        number=index,
                        label=item.name,
                        description=item.description,
                        payload=item,
                        search_text=item.path,
                    )
                    for index, item in enumerate(category.items, 1)
                ]
                while True:
                    chosen_item = _select_menu(
                        reader,
                        category.title,
                        category.description,
                        item_entries,
                        allow_search=True,
                    )
                    if chosen_item is None:
                        break
                    _show_item(reader, chosen_item.payload, repo)
    finally:
        sys.stdout.write(_SHOW_CURSOR + "\n")
        sys.stdout.flush()
