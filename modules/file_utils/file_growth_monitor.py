#!/usr/bin/env python3
"""Interactive, cross-platform folder growth monitor."""

from __future__ import annotations

__version__ = "0.1.0"

import argparse
import csv
import os
import re
import select
import shutil
import sys
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Deque, Iterator, TextIO

if os.name == "nt":
    import msvcrt
else:
    import termios
    import tty

RESET = "\033[0m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
DIM = "\033[2m"
CLEAR = "\033[2J\033[H"
CLEAR_LINE = "\033[2K"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


@dataclass(frozen=True)
class Snapshot:
    timestamp: datetime
    monotonic_time: float
    folders: int
    files: int
    size: int
    scan_seconds: float
    errors: int


@dataclass(frozen=True)
class Delta:
    folders: int
    files: int
    size: int

    @property
    def changed(self) -> bool:
        return bool(self.folders or self.files or self.size)


@dataclass(frozen=True)
class Sample:
    snapshot: Snapshot
    last: Delta
    total: Delta
    elapsed: float
    files_per_second: float
    bytes_per_second: float
    changed_recently: bool
    change_age: float | None


@dataclass
class RuntimeConfig:
    scan_interval: float
    print_interval: float
    change_window: float
    mode: str
    history_display: str
    print_unchanged: bool
    color_enabled: bool
    interactive: bool
    paused: bool = False


class Palette:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def paint(self, text: str, code: str) -> str:
        return f"{code}{text}{RESET}" if self.enabled else text

    def delta(self, value: int | float, text: str) -> str:
        code = GREEN if value > 0 else RED if value < 0 else YELLOW
        return self.paint(text, code)

    def state(self, value: bool, text: str) -> str:
        return self.paint(text, GREEN if value else RED)


class Keyboard:
    """Non-blocking single-key input for Windows and POSIX terminals."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled and sys.stdin.isatty()
        self._active = False
        self._fd: int | None = None
        self._saved_attributes: list[object] | None = None

    def start(self) -> None:
        if not self.enabled or self._active:
            return
        if os.name != "nt":
            self._fd = sys.stdin.fileno()
            self._saved_attributes = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
        self._active = True

    def stop(self) -> None:
        if not self.enabled or not self._active:
            return
        if os.name != "nt" and self._fd is not None and self._saved_attributes is not None:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved_attributes)
        self._active = False

    @contextmanager
    def suspended(self) -> Iterator[None]:
        was_active = self._active
        if was_active:
            self.stop()
        try:
            yield
        finally:
            if was_active:
                self.start()

    def poll(self) -> str | None:
        if not self.enabled or not self._active:
            return None

        if os.name == "nt":
            if not msvcrt.kbhit():
                return None
            key = msvcrt.getwch()
            if key in ("\x00", "\xe0"):
                if msvcrt.kbhit():
                    msvcrt.getwch()
                return None
            return key

        assert self._fd is not None
        readable, _, _ = select.select([self._fd], [], [], 0)
        if not readable:
            return None
        return os.read(self._fd, 1).decode(errors="ignore")

    def read_key(self) -> str:
        while True:
            key = self.poll()
            if key is not None:
                return key
            time.sleep(0.03)


class AppendDisplay:
    """Append history while retaining a live two-line footer."""

    def __init__(self, stream: TextIO) -> None:
        self.stream = stream
        self.footer_drawn = False

    def clear_footer(self) -> None:
        if not self.footer_drawn:
            return
        self.stream.write(f"\r{CLEAR_LINE}\033[1A\r{CLEAR_LINE}")
        self.stream.flush()
        self.footer_drawn = False

    def draw_footer(self, footer: tuple[str, str]) -> None:
        self.stream.write(footer[0] + "\n" + footer[1])
        self.stream.flush()
        self.footer_drawn = True

    def write_line(self, text: str, footer: tuple[str, str]) -> None:
        self.clear_footer()
        self.stream.write(text + "\n")
        self.draw_footer(footer)

    def write_block(self, lines: list[str], footer: tuple[str, str]) -> None:
        self.clear_footer()
        if lines:
            self.stream.write("\n".join(lines) + "\n")
        self.draw_footer(footer)


def positive_float(value: str) -> float:
    result = float(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return result


def non_negative_int(value: str) -> int:
    result = int(value)
    if result < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return result


def normalize_intervals(scan_interval: float, print_interval: float) -> tuple[float, float]:
    """Ensure the print cadence never exceeds the scan cadence."""
    if print_interval < scan_interval:
        scan_interval = print_interval
    return scan_interval, print_interval


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Monitor immediate subfolders and recursively total their files and bytes."
        )
    )
    parser.add_argument("-P", "--path", default=".", help="Directory to monitor.")
    parser.add_argument(
        "-s",
        "--scan-interval",
        type=positive_float,
        default=10.0,
        help="Seconds between scans. Default: 10.",
    )
    parser.add_argument(
        "-p",
        "--print-interval",
        type=positive_float,
        default=None,
        help=(
            "Minimum seconds between outputs. Defaults to scan interval. If lower "
            "than scan interval, scan interval is lowered automatically."
        ),
    )
    parser.add_argument(
        "-a",
        "--change-window",
        type=positive_float,
        default=10.0,
        help="Seconds for the recent-change indicator. Default: 10.",
    )
    parser.add_argument(
        "-m",
        "--mode",
        choices=("dashboard", "history"),
        default="history",
        help="Display mode. Default: history.",
    )
    parser.add_argument(
        "-H",
        "--history-display",
        choices=("append", "viewport"),
        default="viewport",
        help="History style. Default: viewport.",
    )
    parser.add_argument(
        "-u",
        "--print-unchanged",
        action="store_true",
        help="Print unchanged history samples. Changed-only is the default.",
    )
    parser.add_argument(
        "-e",
        "--header-every",
        type=non_negative_int,
        default=20,
        help="Repeat append-mode header every N rows; 0 means only once.",
    )
    parser.add_argument(
        "-M",
        "--max-history",
        type=non_negative_int,
        default=0,
        help="Maximum viewport samples retained; 0 means unlimited.",
    )
    parser.add_argument(
        "-l",
        "--log-file",
        type=Path,
        help="Optional CSV file for each displayed history sample.",
    )
    parser.add_argument(
        "-R",
        "--include-root-files",
        action="store_true",
        help="Include files directly inside the monitored directory.",
    )
    parser.add_argument(
        "-L",
        "--follow-symlinks",
        action="store_true",
        help="Follow directory symlinks. Disabled by default.",
    )
    parser.add_argument("-C", "--no-color", action="store_true")
    parser.add_argument(
        "-X",
        "--no-interactive",
        action="store_true",
        help="Disable hotkeys and use Ctrl+C to stop.",
    )
    parser.add_argument(
        "-n",
        "--max-scans",
        type=non_negative_int,
        default=0,
        help="Stop after N scans including baseline; 0 means indefinitely.",
    )
    args = parser.parse_args(argv)
    args.print_interval = args.print_interval or args.scan_interval
    args.scan_interval, args.print_interval = normalize_intervals(
        args.scan_interval,
        args.print_interval,
    )
    return args


def scan_directory(
    root: Path,
    *,
    include_root_files: bool = False,
    follow_symlinks: bool = False,
) -> Snapshot:
    started = time.monotonic()
    folders = 0
    files = 0
    size = 0
    errors = 0
    first = True

    def on_error(_error: OSError) -> None:
        nonlocal errors
        errors += 1

    try:
        for current, dirnames, filenames in os.walk(
            root,
            topdown=True,
            onerror=on_error,
            followlinks=follow_symlinks,
        ):
            if first:
                folders = len(dirnames)
                first = False
                if not include_root_files:
                    filenames = []

            for filename in filenames:
                path = Path(current) / filename
                try:
                    if not follow_symlinks and path.is_symlink():
                        continue
                    stat = path.stat()
                    if not path.is_file():
                        continue
                except OSError:
                    errors += 1
                    continue
                files += 1
                size += int(stat.st_size)
    except OSError:
        errors += 1

    finished = time.monotonic()
    return Snapshot(
        timestamp=datetime.now(),
        monotonic_time=finished,
        folders=folders,
        files=files,
        size=size,
        scan_seconds=finished - started,
        errors=errors,
    )


def subtract(current: Snapshot, previous: Snapshot) -> Delta:
    return Delta(
        folders=current.folders - previous.folders,
        files=current.files - previous.files,
        size=current.size - previous.size,
    )


def make_sample(
    current: Snapshot,
    previous_output: Snapshot,
    initial: Snapshot,
    last_change: float | None,
    change_window: float,
) -> Sample:
    elapsed = max(0.0, current.monotonic_time - initial.monotonic_time)
    total = subtract(current, initial)
    change_age = (
        None
        if last_change is None
        else max(0.0, current.monotonic_time - last_change)
    )
    return Sample(
        snapshot=current,
        last=subtract(current, previous_output),
        total=total,
        elapsed=elapsed,
        files_per_second=total.files / elapsed if elapsed else 0.0,
        bytes_per_second=total.size / elapsed if elapsed else 0.0,
        changed_recently=(
            change_age is not None and change_age <= change_window
        ),
        change_age=change_age,
    )


def signed_int(value: int) -> str:
    return f"{value:+,}" if value else "0"


def human_size(
    value: int | float,
    *,
    signed: bool = False,
    compact: bool = False,
) -> str:
    number = float(value)
    sign = "+" if signed and number > 0 else "-" if number < 0 else ""
    magnitude = abs(number)
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    unit_index = 0
    while magnitude >= 1024 and unit_index < len(units) - 1:
        magnitude /= 1024
        unit_index += 1
    decimals = 0 if unit_index == 0 else 2
    separator = "" if compact else " "
    return f"{sign}{magnitude:.{decimals}f}{separator}{units[unit_index]}"


def elapsed_text(seconds: float) -> str:
    total = max(0, int(seconds))
    days, total = divmod(total, 86400)
    hours, total = divmod(total, 3600)
    minutes, seconds = divmod(total, 60)
    if days:
        return f"{days}d {hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def visible_length(text: str) -> int:
    return len(ANSI_ESCAPE.sub("", text))


def clip(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    return text[: width - 1] + "…"


def clip_ansi(text: str, width: int) -> str:
    """Clip by visible cells without cutting ANSI escape sequences."""
    if visible_length(text) <= width:
        return text
    if width <= 0:
        return ""

    target = max(0, width - 1)
    output: list[str] = []
    visible = 0
    index = 0
    while index < len(text) and visible < target:
        match = ANSI_ESCAPE.match(text, index)
        if match is not None:
            output.append(match.group(0))
            index = match.end()
            continue
        output.append(text[index])
        visible += 1
        index += 1
    output.append("…")
    if ANSI_ESCAPE.search(text):
        output.append(RESET)
    return "".join(output)


def plain_cell(text: str, width: int, *, align: str = "right") -> str:
    if len(text) > width:
        text = text[:width]
    if align == "left":
        return text.ljust(width)
    return text.rjust(width)


def colored_cell(
    palette: Palette,
    value: int | float,
    text: str,
    width: int,
) -> str:
    return palette.delta(value, plain_cell(text, width))


def summary_rows(
    sample: Sample,
    palette: Palette,
    change_window: float,
    width: int,
) -> list[str]:
    compact = width < 88
    total = sample.total
    change_age = "never" if sample.change_age is None else f"{sample.change_age:.1f}s"
    changed = palette.state(
        sample.changed_recently,
        "YES" if sample.changed_recently else "NO",
    )
    total_size = human_size(total.size, signed=True, compact=compact)
    byte_rate = human_size(
        sample.bytes_per_second,
        signed=True,
        compact=compact,
    )

    if compact:
        row1 = (
            f"RUN Δ D:{palette.delta(total.folders, signed_int(total.folders))} "
            f"F:{palette.delta(total.files, signed_int(total.files))} "
            f"S:{palette.delta(total.size, total_size)}"
        )
        row2 = (
            f"AVG F:{palette.delta(sample.files_per_second, f'{sample.files_per_second:+.2f}/s')} "
            f"S:{palette.delta(sample.bytes_per_second, f'{byte_rate}/s')} "
            f"T:{elapsed_text(sample.elapsed)} CHG:{changed}({change_age})"
        )
        row3 = (
            f"NOW D:{sample.snapshot.folders:,} F:{sample.snapshot.files:,} "
            f"S:{human_size(sample.snapshot.size, compact=True)} "
            f"CHG≤{change_window:g}s:{changed}({change_age})"
        )
    else:
        row1 = (
            f"RUN Δ  Dirs:{palette.delta(total.folders, signed_int(total.folders))}  "
            f"Files:{palette.delta(total.files, signed_int(total.files))}  "
            f"Size:{palette.delta(total.size, total_size)}"
        )
        row2 = (
            f"AVG    Files:{palette.delta(sample.files_per_second, f'{sample.files_per_second:+.2f}/s')}  "
            f"Size:{palette.delta(sample.bytes_per_second, f'{byte_rate}/s')}  "
            f"Elapsed:{elapsed_text(sample.elapsed)}  "
            f"Changed≤{change_window:g}s:{changed} ({change_age})"
        )
        row3 = (
            f"NOW    Dirs:{sample.snapshot.folders:,}  Files:{sample.snapshot.files:,}  "
            f"Size:{human_size(sample.snapshot.size)}  "
            f"Changed≤{change_window:g}s:{changed} ({change_age})"
        )
    return [clip_ansi(row, width) for row in (row1, row2, row3)]


def history_header(width: int) -> str:
    if width >= 76:
        return (
            f"{'TIME':<8} {'ΔDIR':>5} {'ΔFILES':>8} {'ΔSIZE':>11} "
            f"{'ΣDIR':>5} {'ΣFILES':>9} {'ΣSIZE':>11}"
        )
    return f"{'TIME':<8} {'LAST D/F/S':<24} {'TOTAL D/F/S':<24}"


def history_separator(width: int) -> str:
    return "─" * min(width, 76 if width >= 76 else 58)


def history_line(sample: Sample, palette: Palette, width: int) -> str:
    timestamp = sample.snapshot.timestamp.strftime("%H:%M:%S")
    last = sample.last
    total = sample.total

    if width >= 76:
        return (
            f"{timestamp:<8} "
            f"{colored_cell(palette, last.folders, signed_int(last.folders), 5)} "
            f"{colored_cell(palette, last.files, signed_int(last.files), 8)} "
            f"{colored_cell(palette, last.size, human_size(last.size, signed=True, compact=True), 11)} "
            f"{colored_cell(palette, total.folders, signed_int(total.folders), 5)} "
            f"{colored_cell(palette, total.files, signed_int(total.files), 9)} "
            f"{colored_cell(palette, total.size, human_size(total.size, signed=True, compact=True), 11)}"
        )

    last_text = (
        f"{signed_int(last.folders)}/"
        f"{signed_int(last.files)}/"
        f"{human_size(last.size, signed=True, compact=True)}"
    )
    total_text = (
        f"{signed_int(total.folders)}/"
        f"{signed_int(total.files)}/"
        f"{human_size(total.size, signed=True, compact=True)}"
    )
    last_signal = last.size or last.files or last.folders
    total_signal = total.size or total.files or total.folders
    last_cell = palette.delta(
        last_signal,
        plain_cell(last_text, 24, align="left"),
    )
    total_cell = palette.delta(
        total_signal,
        plain_cell(total_text, 24, align="left"),
    )
    return f"{timestamp:<8} {last_cell} {total_cell}"


def footer_lines(
    config: RuntimeConfig,
    width: int,
    palette: Palette,
) -> tuple[str, str]:
    run_state = "PAUSED" if config.paused else "RUNNING"
    row_mode = "all rows" if config.print_unchanged else "changed only"
    if config.interactive:
        first = "q Quit  Space Pause  s Scan  p Print  w Window  m Mode"
        second = (
            f"h History  u Rows  r Reset  c Color  ? Help | "
            f"{run_state} scan={config.scan_interval:g}s "
            f"print={config.print_interval:g}s window={config.change_window:g}s "
            f"{row_mode}"
        )
    else:
        first = "Ctrl+C to stop"
        second = (
            f"{run_state} scan={config.scan_interval:g}s "
            f"print={config.print_interval:g}s window={config.change_window:g}s "
            f"{row_mode}"
        )
    first = palette.paint(clip(first, width), CYAN)
    second = palette.paint(
        clip(second, width),
        YELLOW if config.paused else DIM,
    )
    return first, second


def help_lines(width: int) -> list[str]:
    rows = [
        "Interactive controls",
        "q      Quit with a direct y/n confirmation",
        "Space  Pause or resume scanning",
        "s      Set scan interval in seconds",
        "p      Set print interval; lowering it also lowers scan interval",
        "w      Set the recent-change window",
        "m      Toggle dashboard/history mode",
        "h      Toggle viewport/append history",
        "u      Toggle changed-only/all-row output",
        "r      Reset cumulative run statistics and history baseline",
        "c      Toggle ANSI colors",
        "?      Show this help",
        "Press any key to return.",
    ]
    return [clip(row, width) for row in rows]


def render_frame(
    content: list[str],
    footer: tuple[str, str],
    *,
    stream: TextIO = sys.stdout,
) -> None:
    terminal = shutil.get_terminal_size((80, 24))
    body_height = max(1, terminal.lines - 2)
    visible = [
        clip_ansi(line, terminal.columns)
        for line in content[:body_height]
    ]
    visible.extend("" for _ in range(body_height - len(visible)))
    stream.write(CLEAR)
    stream.write("\n".join(visible + [footer[0], footer[1]]))
    stream.flush()


def render_dashboard(
    sample: Sample,
    root: Path,
    palette: Palette,
    config: RuntimeConfig,
) -> None:
    terminal = shutil.get_terminal_size((80, 24))
    last = sample.last
    content = summary_rows(
        sample,
        palette,
        config.change_window,
        terminal.columns,
    )
    content.extend(
        [
            clip(f"PATH {root}", terminal.columns),
            clip_ansi(
                "LAST Δ "
                f"D:{palette.delta(last.folders, signed_int(last.folders))} "
                f"F:{palette.delta(last.files, signed_int(last.files))} "
                f"S:{palette.delta(last.size, human_size(last.size, signed=True, compact=True))} "
                f"Scan:{sample.snapshot.scan_seconds:.2f}s "
                f"Errors:{sample.snapshot.errors}",
                terminal.columns,
            ),
        ]
    )
    render_frame(
        content,
        footer_lines(config, terminal.columns, palette),
    )


def render_viewport(
    sample: Sample,
    history: Deque[Sample],
    root: Path,
    palette: Palette,
    config: RuntimeConfig,
) -> None:
    terminal = shutil.get_terminal_size((80, 24))
    fixed_body_rows = 5
    visible_history = max(1, terminal.lines - 2 - fixed_body_rows)
    content = summary_rows(
        sample,
        palette,
        config.change_window,
        terminal.columns,
    )[:2]
    content.append(clip(f"PATH {root}", terminal.columns))
    content.append(history_header(terminal.columns))
    content.append(history_separator(terminal.columns))
    content.extend(
        history_line(entry, palette, terminal.columns)
        for entry in list(history)[-visible_history:]
    )
    render_frame(
        content,
        footer_lines(config, terminal.columns, palette),
    )


def append_preamble(
    sample: Sample,
    root: Path,
    palette: Palette,
    config: RuntimeConfig,
    width: int,
) -> list[str]:
    rows = summary_rows(
        sample,
        palette,
        config.change_window,
        width,
    )[:2]
    rows.append(clip(f"PATH {root}", width))
    rows.append(history_header(width))
    rows.append(history_separator(width))
    return rows


CSV_FIELDS = (
    "timestamp",
    "folders",
    "files",
    "size_bytes",
    "last_folders",
    "last_files",
    "last_size_bytes",
    "total_folders",
    "total_files",
    "total_size_bytes",
    "elapsed_seconds",
    "files_per_second",
    "bytes_per_second",
    "changed_recently",
    "change_age_seconds",
    "scan_seconds",
    "errors",
)


def log_sample(path: Path | None, sample: Sample) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow(
            {
                "timestamp": sample.snapshot.timestamp.isoformat(timespec="seconds"),
                "folders": sample.snapshot.folders,
                "files": sample.snapshot.files,
                "size_bytes": sample.snapshot.size,
                "last_folders": sample.last.folders,
                "last_files": sample.last.files,
                "last_size_bytes": sample.last.size,
                "total_folders": sample.total.folders,
                "total_files": sample.total.files,
                "total_size_bytes": sample.total.size,
                "elapsed_seconds": f"{sample.elapsed:.6f}",
                "files_per_second": f"{sample.files_per_second:.6f}",
                "bytes_per_second": f"{sample.bytes_per_second:.6f}",
                "changed_recently": sample.changed_recently,
                "change_age_seconds": (
                    ""
                    if sample.change_age is None
                    else f"{sample.change_age:.6f}"
                ),
                "scan_seconds": f"{sample.snapshot.scan_seconds:.6f}",
                "errors": sample.snapshot.errors,
            }
        )


def prompt_float(
    label: str,
    current: float,
    keyboard: Keyboard,
    append_display: AppendDisplay,
) -> float | None:
    append_display.clear_footer()
    sys.stdout.write("\r" + CLEAR_LINE + SHOW_CURSOR)
    sys.stdout.flush()
    with keyboard.suspended():
        try:
            raw = input(f"{label} [{current:g}s]: ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        finally:
            sys.stdout.write(HIDE_CURSOR)
            sys.stdout.flush()
    if not raw:
        return current
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def confirm_quit(
    keyboard: Keyboard,
    append_display: AppendDisplay,
    palette: Palette,
) -> bool:
    append_display.clear_footer()
    sys.stdout.write("\r" + CLEAR_LINE + SHOW_CURSOR)
    sys.stdout.write(palette.paint("Quit folder monitor? [y/N] ", YELLOW))
    sys.stdout.flush()
    key = keyboard.read_key().lower()
    sys.stdout.write("\r" + CLEAR_LINE + HIDE_CURSOR)
    sys.stdout.flush()
    return key == "y"


def show_help(
    config: RuntimeConfig,
    keyboard: Keyboard,
    append_display: AppendDisplay,
    palette: Palette,
) -> None:
    terminal = shutil.get_terminal_size((80, 24))
    footer = footer_lines(config, terminal.columns, palette)
    if config.mode == "history" and config.history_display == "append":
        append_display.write_block(help_lines(terminal.columns), footer)
    else:
        render_frame(help_lines(terminal.columns), footer)
    keyboard.read_key()


def monitor(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 2

    interactive = (
        not args.no_interactive
        and sys.stdin.isatty()
        and sys.stdout.isatty()
    )
    color_enabled = (
        not args.no_color
        and sys.stdout.isatty()
        and "NO_COLOR" not in os.environ
    )
    config = RuntimeConfig(
        scan_interval=args.scan_interval,
        print_interval=args.print_interval,
        change_window=args.change_window,
        mode=args.mode,
        history_display=args.history_display,
        print_unchanged=args.print_unchanged,
        color_enabled=color_enabled,
        interactive=interactive,
    )
    keyboard = Keyboard(interactive)
    append_display = AppendDisplay(sys.stdout)
    history: Deque[Sample] = deque(maxlen=args.max_history or None)

    baseline = scan_directory(
        root,
        include_root_files=args.include_root_files,
        follow_symlinks=args.follow_symlinks,
    )
    current = baseline
    previous_scan = baseline
    previous_output = baseline
    last_change: float | None = None
    last_output_time = baseline.monotonic_time
    next_scan = baseline.monotonic_time + config.scan_interval
    pending_change = False
    scans = 1
    emitted = 0
    sample = make_sample(
        current,
        previous_output,
        baseline,
        last_change,
        config.change_window,
    )
    history.append(sample)
    log_sample(args.log_file, sample)

    def active_palette() -> Palette:
        return Palette(config.color_enabled)

    def redraw(*, append_preamble_required: bool = False) -> None:
        palette = active_palette()
        terminal = shutil.get_terminal_size((80, 24))
        if config.mode == "dashboard":
            append_display.clear_footer()
            render_dashboard(sample, root, palette, config)
            return
        if config.history_display == "viewport":
            append_display.clear_footer()
            render_viewport(sample, history, root, palette, config)
            return

        footer = footer_lines(config, terminal.columns, palette)
        if append_preamble_required or emitted == 0:
            append_display.write_block(
                append_preamble(
                    sample,
                    root,
                    palette,
                    config,
                    terminal.columns,
                ),
                footer,
            )
        else:
            append_display.clear_footer()
            append_display.draw_footer(footer)

    def emit_append_row() -> None:
        nonlocal emitted
        palette = active_palette()
        terminal = shutil.get_terminal_size((80, 24))
        footer = footer_lines(config, terminal.columns, palette)
        repeat_header = (
            bool(args.header_every)
            and emitted > 0
            and emitted % args.header_every == 0
        )
        if repeat_header:
            append_display.write_block(
                [
                    history_header(terminal.columns),
                    history_separator(terminal.columns),
                ],
                footer,
            )
        append_display.write_line(
            history_line(sample, palette, terminal.columns),
            footer,
        )
        emitted += 1

    keyboard.start()
    if interactive:
        sys.stdout.write(HIDE_CURSOR)
        sys.stdout.flush()

    try:
        redraw(append_preamble_required=True)
        if config.mode == "history" and config.history_display == "append":
            emit_append_row()

        if args.max_scans == 1:
            return 0

        while True:
            key = keyboard.poll()
            if key is not None:
                lowered = key.lower()
                if lowered == "q":
                    if confirm_quit(
                        keyboard,
                        append_display,
                        active_palette(),
                    ):
                        return 0
                    redraw(append_preamble_required=False)
                elif key == " ":
                    config.paused = not config.paused
                    if not config.paused:
                        next_scan = time.monotonic() + config.scan_interval
                    redraw(append_preamble_required=False)
                elif lowered in {"s", "p", "w"}:
                    if lowered == "s":
                        value = prompt_float(
                            "Scan interval seconds",
                            config.scan_interval,
                            keyboard,
                            append_display,
                        )
                        if value is not None:
                            config.scan_interval = value
                            if config.scan_interval > config.print_interval:
                                config.print_interval = config.scan_interval
                    elif lowered == "p":
                        value = prompt_float(
                            "Print interval seconds",
                            config.print_interval,
                            keyboard,
                            append_display,
                        )
                        if value is not None:
                            config.print_interval = value
                            (
                                config.scan_interval,
                                config.print_interval,
                            ) = normalize_intervals(
                                config.scan_interval,
                                config.print_interval,
                            )
                    else:
                        value = prompt_float(
                            "Recent-change window seconds",
                            config.change_window,
                            keyboard,
                            append_display,
                        )
                        if value is not None:
                            config.change_window = value
                    next_scan = time.monotonic() + config.scan_interval
                    redraw(append_preamble_required=False)
                elif lowered == "m":
                    config.mode = (
                        "dashboard"
                        if config.mode == "history"
                        else "history"
                    )
                    sys.stdout.write(CLEAR)
                    append_display.footer_drawn = False
                    redraw(append_preamble_required=True)
                    if (
                        config.mode == "history"
                        and config.history_display == "append"
                    ):
                        emit_append_row()
                elif lowered == "h":
                    config.history_display = (
                        "append"
                        if config.history_display == "viewport"
                        else "viewport"
                    )
                    config.mode = "history"
                    sys.stdout.write(CLEAR)
                    append_display.footer_drawn = False
                    redraw(append_preamble_required=True)
                    if config.history_display == "append":
                        emit_append_row()
                elif lowered == "u":
                    config.print_unchanged = not config.print_unchanged
                    redraw(append_preamble_required=False)
                elif lowered == "r":
                    baseline = current
                    previous_output = current
                    last_change = None
                    pending_change = False
                    emitted = 0
                    history.clear()
                    sample = make_sample(
                        current,
                        previous_output,
                        baseline,
                        last_change,
                        config.change_window,
                    )
                    history.append(sample)
                    redraw(append_preamble_required=True)
                    if (
                        config.mode == "history"
                        and config.history_display == "append"
                    ):
                        emit_append_row()
                elif lowered == "c":
                    config.color_enabled = not config.color_enabled
                    redraw(append_preamble_required=False)
                elif lowered == "?":
                    show_help(
                        config,
                        keyboard,
                        append_display,
                        active_palette(),
                    )
                    redraw(append_preamble_required=False)

            now = time.monotonic()
            if config.paused or now < next_scan:
                time.sleep(0.05)
                continue

            current = scan_directory(
                root,
                include_root_files=args.include_root_files,
                follow_symlinks=args.follow_symlinks,
            )
            scans += 1
            next_scan = current.monotonic_time + config.scan_interval

            if subtract(current, previous_scan).changed:
                last_change = current.monotonic_time
                pending_change = True
            previous_scan = current

            output_due = (
                current.monotonic_time - last_output_time
                >= config.print_interval - 1e-9
            )
            if output_due:
                sample = make_sample(
                    current,
                    previous_output,
                    baseline,
                    last_change,
                    config.change_window,
                )
                should_output = (
                    config.mode == "dashboard"
                    or pending_change
                    or config.print_unchanged
                )
                if should_output:
                    if config.mode == "history":
                        history.append(sample)
                        log_sample(args.log_file, sample)
                        if config.history_display == "viewport":
                            redraw()
                        else:
                            emit_append_row()
                    else:
                        redraw()
                    previous_output = current
                    last_output_time = current.monotonic_time
                    pending_change = False

            if args.max_scans and scans >= args.max_scans:
                return 0
    except KeyboardInterrupt:
        return 0
    finally:
        keyboard.stop()
        append_display.clear_footer()
        if interactive:
            sys.stdout.write(SHOW_CURSOR + "\n")
            sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    return monitor(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
