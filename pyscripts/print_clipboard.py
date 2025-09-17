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


def print_clipboard_main(color_style: str, no_stats: bool) -> int:
    """
    Retrieve the clipboard and print it. Returns an exit code (0 ok, 1 error).
    """
    exit_code = 0
    err_msg = None
    text: str | None = None

    try:
        try:
            text = get_clipboard()
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
            _print_stats_table(stats, to_stderr=False)

    return exit_code


# ----------------------------
# Entrypoint
# ----------------------------
if __name__ == "__main__":
    args = parser.parse_args()
    sys.exit(print_clipboard_main(args.color, args.no_stats))
