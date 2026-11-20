#!/usr/bin/env python3
"""
Diff the current clipboard against a file, show a colored unified diff, and emit stats.
Also snapshots the last cld (clipboard diff) so that other tools (e.g., rwcp) can reuse it.

State directory resolution (in order):
  - If environment variable CLIPBOARD_TOOLS_STATE_DIR is set, use it.
  - Linux/Unix: $XDG_STATE_HOME/clipboard_tools or ~/.local/state/clipboard_tools
  - macOS: ~/Library/Application Support/clipboard_tools
  - Windows: %LOCALAPPDATA%\\clipboard_tools
"""
from __future__ import annotations

__version__ = "0.2.0"

import sys
import os
import json
import difflib
import argparse
from datetime import datetime
from pathlib import Path

from cross_platform.clipboard_utils import get_clipboard
from clipboard_tools.compare import compare_clipboard_to_file, EXIT_EQUAL, EXIT_DIFFERENT, EXIT_ERROR
from rich.console import Console
from rich.table import Table
from rich.text import Text

console_stdout = Console()
console_stderr = Console(stderr=True)

# ------------- State dir helpers -------------

def _is_windows() -> bool:
    return os.name == "nt" or sys.platform.startswith("win")

def _is_macos() -> bool:
    return sys.platform == "darwin"

def get_state_dir() -> Path:
    # Allow tests or callers to override via env var
    override = os.environ.get("CLIPBOARD_TOOLS_STATE_DIR")
    if override:
        return Path(override).expanduser().resolve()

    if _is_windows():
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "clipboard_tools"
        # Fallback to userprofile if LOCALAPPDATA not found
        return Path.home() / "AppData" / "Local" / "clipboard_tools"

    if _is_macos():
        return Path.home() / "Library" / "Application Support" / "clipboard_tools"

    # Linux/Unix: XDG_STATE_HOME or ~/.local/state/clipboard_tools
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg) / "clipboard_tools"
    return Path.home() / ".local" / "state" / "clipboard_tools"

def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def save_last_cld_snapshot(file_path: Path, clipboard_text: str, state_dir: Path | None = None) -> tuple[Path, Path]:
    sd = state_dir or get_state_dir()
    _ensure_dir(sd)

    meta_path = sd / "last_cld.json"
    data_path = sd / "last_cld_clipboard.txt"

    # Save clipboard contents
    data_path.write_text(clipboard_text, encoding="utf-8")

    # Save metadata
    meta = {
        "file_path": str(file_path.resolve()),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "clipboard_file": str(data_path.resolve())
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    return meta_path, data_path

# ------------- CLI -------------

parser = argparse.ArgumentParser(
    description="Diff clipboard contents with a file, providing stats and warnings.",
    formatter_class=argparse.RawTextHelpFormatter
)
parser.add_argument(
    "file",
    help="File path to compare against clipboard contents"
)
parser.add_argument(
    "-c", "-C", "--context-lines",
    type=int,
    default=3,
    help="Number of context lines to display (default: 3)"
)
parser.add_argument(
    "-t", "-T", "--similarity-threshold",
    type=float,
    default=0.75,
    help="Similarity threshold for dissimilarity note (range 0.0-1.0, default: 0.75)"
)
parser.add_argument(
    "-l", "-L", "--loc-diff-warn",
    type=int,
    default=50,
    help="Absolute LOC difference above which a warning is shown (default: 50)"
)
parser.add_argument(
    "-n", "-N", "--no-stats",
    action="store_true",
    help="Suppress statistics output."
)
parser.add_argument(
    "-s", "-S", "--strict",
    action="store_true",
    help="Compare strictly without normalizing LF/CRLF or trailing newlines."
)
parser.add_argument(
    "-z", "--trim-trailing-newline",
    action="store_true",
    help="Ignore trailing newline differences in normalized comparison mode."
)
parser.add_argument(
    "-k", "-K", "--check",
    action="store_true",
    help="Equality check mode: exit 0 if equal, 1 if different, 2 on error/empty clipboard."
)
parser.add_argument(
    "-E", "--encoding",
    default="utf-8",
    help="File encoding to use when reading target file (default: utf-8)."
)

# ------------- Core -------------

def diff_clipboard_with_file(
    file_path_str: str,
    context_lines: int,
    similarity_threshold: float,
    loc_diff_warning_threshold: int,
    no_stats: bool,
    *,
    strict: bool = False,
    ignore_trailing_newline: bool = False,
    check: bool = False,
    encoding: str = "utf-8",
    state_dir_override: Path | None = None
) -> int:
    stats_data: dict[str, str | int | float] = {}
    exit_code = 0

    try:
        file_path_obj = Path(file_path_str)
        stats_data["File Path"] = str(file_path_obj.resolve())
        stats_data["Mode"] = "Strict" if strict else "Normalized"
        stats_data["Encoding"] = encoding

        result = compare_clipboard_to_file(
            file_path_obj,
            get_clipboard,
            strict=strict,
            ignore_trailing_newline=ignore_trailing_newline,
            encoding=encoding,
            context_lines=context_lines,
        )

        if result.error:
            stats_data["Error"] = result.error
            console_stderr.print(f"[bold red][ERROR] {result.error}[/]")
            exit_code = EXIT_ERROR if check else 1
            return exit_code

        stats_data["File Read"] = "Successful"
        stats_data["File LOC"] = result.file_lines
        stats_data["Clipboard Status"] = "Content retrieved"
        stats_data["Clipboard LOC"] = result.clipboard_lines
        stats_data["Line Ending Mismatch"] = "Yes" if result.line_ending_mismatch else "No"
        stats_data["Trailing Newline Mismatch"] = "Yes" if result.trailing_newline_mismatch else "No"

        clipboard_text = get_clipboard()
        meta_path, data_path = save_last_cld_snapshot(file_path_obj, clipboard_text, state_dir_override)
        stats_data["CLD Snapshot"] = f"Saved snapshot → meta: {meta_path.name}, data: {data_path.name}"
        console_stdout.print(
            f"[cyan]CLD Snapshot:[/] Saved snapshot → meta: [bold]{meta_path.name}[/], data: [bold]{data_path.name}[/]"
        )

        for diag in result.diagnostics:
            console_stderr.print(f"[yellow][NOTE] {diag}[/]")

        diff_output_lines_count = len(result.diff_lines)
        for line in result.diff_lines:
            if line.startswith('---') or line.startswith('+++'):
                console_stdout.print(line)
            elif line.startswith('@@'):
                console_stdout.print(Text(line, style="cyan"))
            elif line.startswith('-'):
                console_stdout.print(Text(line, style="red"))
            elif line.startswith('+'):
                console_stdout.print(Text(line, style="green"))
            else:
                console_stdout.print(line)

        stats_data["Diff Lines Generated"] = diff_output_lines_count
        if result.equal:
            console_stdout.print("No differences found between file and clipboard.")
            stats_data["Differences Found"] = "No"
        else:
            stats_data["Differences Found"] = "Yes"

        loc_difference = abs(result.file_lines - result.clipboard_lines)
        stats_data["LOC Difference"] = loc_difference
        if loc_difference > loc_diff_warning_threshold:
            warning_msg = f"Large LOC difference detected ({loc_difference} lines). The sources may be significantly different in length."
            console_stdout.print(f"[orange3]{warning_msg}[/]")
            stats_data["LOC Difference Warning"] = "Issued"

        stats_data["Similarity Ratio"] = f"{result.similarity_ratio:.2f}"
        if result.similarity_ratio < similarity_threshold:
            note_msg = f"The contents are very dissimilar (similarity ratio: {result.similarity_ratio:.2f}). They might not be the same source."
            console_stdout.print(f"[yellow]Note: {note_msg}[/]")
            stats_data["Dissimilarity Note"] = "Issued"

        if check:
            exit_code = EXIT_EQUAL if result.equal else EXIT_DIFFERENT
        else:
            exit_code = 0

    except Exception as exc:
        exit_code = EXIT_ERROR if check else 1
        stats_data.setdefault("Error", f"An unexpected error occurred during diff: {exc}")

    finally:
        if not no_stats:
            table = Table(title="clipboard_diff.py Statistics")
            table.add_column("Metric", style="cyan")
            table.add_column("Value", overflow="fold")
            for key, value in stats_data.items():
                table.add_row(str(key), str(value))
            console_stdout.print(table)

    return exit_code

# ------------- Entry -------------

def main(argv: list[str] | None = None) -> int:
    args = parser.parse_args(argv)
    return diff_clipboard_with_file(
        args.file,
        args.context_lines,
        args.similarity_threshold,
        args.loc_diff_warn,
        args.no_stats,
        strict=args.strict,
        ignore_trailing_newline=args.trim_trailing_newline,
        check=args.check,
        encoding=args.encoding,
    )

if __name__ == "__main__":
    sys.exit(main())
