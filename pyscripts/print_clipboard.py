#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
print_clipboard.py

Echo the current clipboard contents to the console with optional colorization,
and (by default) emit a stats table summarizing the clipboard.

Exit codes:
  0 -> Success (clipboard printed)
  1 -> Error (clipboard unavailable, empty/whitespace-only, or unexpected error)
"""

from __future__ import annotations

import sys
import argparse

from rich.console import Console
from rich.table import Table
from rich.text import Text

# Critical dependency: clipboard utils
try:
    from cross_platform.clipboard_utils import get_clipboard
except ImportError:
    print("[CRITICAL ERROR] The 'cross_platform.clipboard_utils' module was not found.", file=sys.stderr)
    print("    Please ensure it is installed and accessible in your Python environment.", file=sys.stderr)
    sys.exit(1)

try:
    from clipboard_tools.buffers import (
        format_age,
        get_active_buffer_id,
        list_buffer_summaries,
        load_buffer,
        record_buffer_read,
        validate_buffer_id,
        buffer_file_path,
    )
except Exception:
    # fallback for non-installed module use
    from pyscripts.clipboard_buffers import (  # type: ignore
        format_age,
        get_active_buffer_id,
        list_buffer_summaries,
        load_buffer,
        record_buffer_read,
        validate_buffer_id,
        buffer_file_path,
    )

# Consoles
console_out = Console()
console_err = Console(stderr=True)


# ----------------------------
# Argument parser
# ----------------------------
def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Print the current clipboard contents with optional color and a stats table.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s                     # print clipboard and show stats table\n"
            "  %(prog)s -c green            # print clipboard colored green\n"
            "  %(prog)s -N                  # suppress stats table\n"
        ),
    )
    p.add_argument(
        "-c", "--color",
        metavar="STYLE",
        default="none",
        help=("Rich style name for colorized output (e.g., 'green', 'cyan', 'bold yellow'). "
              "Use 'none' to disable color (default: none)."),
    )
    p.add_argument(
        "-N", "--no-stats",
        action="store_true",
        help="Suppress the stats table output."
    )
    p.add_argument(
        "-b", "--buffer",
        type=int,
        default=None,
        help="Print from a stored clipboard buffer (0-99) instead of the live clipboard."
    )
    p.add_argument(
        "-S", "--buffers-summary",
        action="store_true",
        help="Show a summary of all stored clipboard buffers and exit."
    )
    p.add_argument(
        "-D", "--buffer-details",
        action="store_true",
        help="Show detailed metadata for a specific buffer (defaults to active buffer when -b is not provided)."
    )
    return p


parser = _build_arg_parser()


# ----------------------------
# Core logic
# ----------------------------
def _normalize_color(style: str) -> str:
    style = (style or "").strip()
    return style if style and style.lower() != "none" else "none"


def _gather_stats(clipboard_text: str | None, ok: bool, err_msg: str | None) -> dict:
    stats: dict[str, object] = {}
    if clipboard_text is None:
        stats["Clipboard"] = "Unavailable"
        stats["Chars"] = 0
        stats["Lines"] = 0
    else:
        stats["Chars"] = len(clipboard_text)
        stats["Lines"] = len(clipboard_text.splitlines())
        stats["Clipboard"] = "Non-empty" if clipboard_text.strip() else "Empty/Whitespace"
    stats["Outcome"] = "Success" if ok else "Failed"
    if err_msg:
        stats["Error"] = err_msg
    return stats


def _print_stats_table(stats: dict, *, to_stderr: bool = False) -> None:
    """
    Print a single-line header FIRST so tests can reliably match the exact
    'print_clipboard.py Statistics' substring (Rich may wrap table titles).
    """
    con = console_err if to_stderr else console_out
    con.print("print_clipboard.py Statistics")  # <-- stable header line

    table = Table(show_header=True, header_style="bold")   # title omitted (to avoid wrapping artifacts)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", overflow="fold")
    for k, v in stats.items():
        table.add_row(str(k), str(v))
    con.print(table)


def _render_buffer_summary() -> None:
    rows = list_buffer_summaries()
    table = Table(title="Clipboard Buffers Summary", title_style="bold green")
    table.add_column("Buffer", style="cyan", justify="right")
    table.add_column("Chars", justify="right")
    table.add_column("Words", justify="right")
    table.add_column("Lines", justify="right")
    table.add_column("Last Filled (UTC)")
    table.add_column("Age")
    table.add_column("Reads", justify="right")
    table.add_column("Present")
    if not rows:
        table.add_row("-", "0", "0", "0", "n/a", "unknown", "0", "False")
    for row in rows:
        table.add_row(
            str(row["buffer"]),
            str(row.get("chars", 0)),
            str(row.get("words", 0)),
            str(row.get("lines", 0)),
            row.get("last_filled_utc", "n/a") or "n/a",
            format_age(row.get("last_filled_utc")),
            str(row.get("read_count", 0)),
            "Yes" if row.get("present") else "No",
        )
    console_out.print(table)


def _render_buffer_detail(buffer_id: int) -> None:
    snapshot = load_buffer(buffer_id)
    table = Table(title=f"Clipboard Buffer {buffer_id} Details", title_style="bold blue")
    table.add_column("Field", style="cyan")
    table.add_column("Value", overflow="fold")
    table.add_row("Buffer", str(buffer_id))
    table.add_row("Chars", str(snapshot.meta.get("chars", 0)))
    table.add_row("Words", str(snapshot.meta.get("words", 0)))
    table.add_row("Lines", str(snapshot.meta.get("lines", 0)))
    table.add_row("Last Filled (UTC)", snapshot.meta.get("last_filled_utc", "unknown"))
    table.add_row("Age", format_age(snapshot.meta.get("last_filled_utc")))
    table.add_row("Last Read (UTC)", snapshot.meta.get("last_read_utc", "never"))
    table.add_row("Reads", str(snapshot.meta.get("read_count", 0)))
    table.add_row("Path", str(buffer_file_path(buffer_id)))
    console_out.print(table)


def print_clipboard_main(
    color_style: str,
    no_stats: bool,
    buffer_id: int | None,
    buffers_summary: bool,
    buffer_details: bool,
) -> int:
    """
    Retrieve the clipboard and print it. Returns an exit code (0 ok, 1 error).
    """
    if buffers_summary:
        _render_buffer_summary()
        return 0

    use_buffer = buffer_id is not None
    if buffer_details and not use_buffer:
        buffer_id = get_active_buffer_id()
        use_buffer = True
    if use_buffer:
        try:
            buffer_id = validate_buffer_id(buffer_id)
        except ValueError as err:
            console_err.print(f"[bold red][ERROR] {err}[/]")
            return 1

    if buffer_details:
        _render_buffer_detail(buffer_id)  # type: ignore[arg-type]
        return 0

    exit_code = 0
    err_msg = None
    text: str | None = None
    buffer_meta: dict = {}
    active_buffer_id: int | None = None

    try:
        try:
            if use_buffer:
                snapshot = load_buffer(buffer_id)  # type: ignore[arg-type]
                record_buffer_read(buffer_id)  # type: ignore[arg-type]
                text = snapshot.text
                buffer_meta = snapshot.meta
                active_buffer_id = buffer_id
            else:
                text = get_clipboard()
                active = get_active_buffer_id()
                active_buffer_id = active
                buffer_meta = load_buffer(active).meta
        except NotImplementedError:
            err_msg = "Clipboard functionality (get_clipboard) not implemented."
            console_err.print(f"[bold red][ERROR] {err_msg}[/]")
            return 1
        except Exception as e:
            err_msg = f"Failed to access clipboard: {e}"
            console_err.print(f"[bold red][ERROR] {err_msg}[/]")
            return 1

        if text is None or not text.strip():
            if text is None:
                err_msg = "Clipboard returned no data."
            else:
                err_msg = "Clipboard contains only whitespace."
            console_err.print(f"[bold red]{err_msg}[/]")
            exit_code = 1  # still print content (empty) + stats unless suppressed

        # Print clipboard content
        style = _normalize_color(color_style)
        if text is not None:
            if style == "none":
                console_out.print(Text(text))
            else:
                console_out.print(Text(text, style=style))

    except Exception as e:
        exit_code = 1
        err_msg = f"Unexpected error: {e}"
        console_err.print(f"[bold red]{err_msg}[/]")

    finally:
        if not no_stats:
            stats = _gather_stats(text, ok=(exit_code == 0), err_msg=err_msg)
            if active_buffer_id is not None:
                stats["Buffer"] = active_buffer_id
                stats["Buffer Age"] = format_age(buffer_meta.get("last_filled_utc"))
                stats["Buffer Last Filled (UTC)"] = buffer_meta.get("last_filled_utc", "unknown")
                stats["Buffer Reads"] = buffer_meta.get("read_count", 0) + (1 if use_buffer else 0)
            _print_stats_table(stats, to_stderr=False)

    return exit_code


# ----------------------------
# Entrypoint
# ----------------------------
if __name__ == "__main__":
    args = parser.parse_args()
    sys.exit(
        print_clipboard_main(
            args.color,
            args.no_stats,
            args.buffer,
            args.buffers_summary,
            args.buffer_details,
        )
    )
