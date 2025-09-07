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

import sys
import os
import json
import difflib
import argparse
from datetime import datetime
from pathlib import Path

from cross_platform.clipboard_utils import get_clipboard
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

# ------------- Core -------------

def diff_clipboard_with_file(
    file_path_str: str,
    context_lines: int,
    similarity_threshold: float,
    loc_diff_warning_threshold: int,
    no_stats: bool,
    *,
    state_dir_override: Path | None = None
) -> None:
    stats_data: dict[str, str | int | float] = {}
    operation_successful = False
    exit_code = 0

    try:
        file_path_obj = Path(file_path_str)
        stats_data["File Path"] = str(file_path_obj.resolve())

        # Read file
        try:
            with open(file_path_obj, 'r', encoding='utf-8') as f:
                file_lines = f.read().splitlines()
            stats_data["File Read"] = "Successful"
            stats_data["File LOC"] = len(file_lines)
        except Exception as e:
            stats_data["File Read"] = f"Error: {e}"
            console_stderr.print(f"[bold red][ERROR] Could not read file '{file_path_obj}': {e}[/]")
            exit_code = 1
            raise

        # Get clipboard
        try:
            clipboard_text = get_clipboard()
        except NotImplementedError:
            stats_data["Error"] = "Clipboard functionality (get_clipboard) not implemented."
            console_stderr.print("[bold red][ERROR] Clipboard functionality (get_clipboard) not implemented. Ensure clipboard utilities are installed and accessible.[/]")
            exit_code = 1
            raise
        except Exception as e_get_clip:
            stats_data["Error"] = f"Failed to get clipboard content: {e_get_clip}"
            console_stderr.print(f"[bold red][ERROR] {stats_data['Error']}[/]")
            exit_code = 1
            raise

        if clipboard_text is None or clipboard_text.strip() == "":
            stats_data["Clipboard Status"] = "Empty or whitespace"
            console_stderr.print("[bold red][CRITICAL WARNING] Clipboard is empty or contains only whitespace![/]")
            exit_code = 1
        else:
            stats_data["Clipboard Status"] = "Content retrieved"
            clipboard_lines = clipboard_text.splitlines()
            stats_data["Clipboard LOC"] = len(clipboard_lines)

            # Save snapshot for rwcp/rwc integration
            meta_path, data_path = save_last_cld_snapshot(file_path_obj, clipboard_text, state_dir_override)
            stats_data["CLD Snapshot"] = f"Saved snapshot → meta: {meta_path.name}, data: {data_path.name}"
            console_stdout.print(
                f"[cyan]CLD Snapshot:[/] Saved snapshot → meta: [bold]{meta_path.name}[/], data: [bold]{data_path.name}[/]"
            )

            # Diff (colored)
            diff_gen = difflib.unified_diff(
                file_lines,
                clipboard_lines,
                fromfile=f"file: {file_path_obj}",
                tofile="clipboard",
                lineterm="",
                n=context_lines
            )

            has_diff = False
            diff_output_lines_count = 0
            for line in diff_gen:
                has_diff = True
                diff_output_lines_count += 1
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
            if not has_diff and diff_output_lines_count == 0:
                console_stdout.print("No differences found between file and clipboard.")
                stats_data["Differences Found"] = "No"
            else:
                stats_data["Differences Found"] = "Yes"

            operation_successful = True

            loc_difference = abs(len(file_lines) - len(clipboard_lines))
            stats_data["LOC Difference"] = loc_difference
            if loc_difference > loc_diff_warning_threshold:
                warning_msg = f"Large LOC difference detected ({loc_difference} lines). The sources may be significantly different in length."
                console_stdout.print(f"[orange3]{warning_msg}[/]")
                stats_data["LOC Difference Warning"] = "Issued"

            seq = difflib.SequenceMatcher(None, "\n".join(file_lines), "\n".join(clipboard_lines))
            ratio = seq.ratio()
            stats_data["Similarity Ratio"] = f"{ratio:.2f}"
            if ratio < similarity_threshold:
                note_msg = f"The contents are very dissimilar (similarity ratio: {ratio:.2f}). They might not be the same source."
                console_stdout.print(f"[yellow]Note: {note_msg}[/]")
                stats_data["Dissimilarity Note"] = "Issued"

        if exit_code == 0 and not operation_successful:
            stats_data.setdefault("Warning", "Operation did not complete as expected but no specific error caught.")
            exit_code = 1

    except Exception:
        if exit_code == 0:
            exit_code = 1
        if ("Error" not in stats_data) and ("File Read" not in stats_data):
            stats_data["Error"] = f"An unexpected error occurred during diff: {sys.exc_info()[1]}"

    finally:
        if not no_stats:
            table = Table(title="clipboard_diff.py Statistics")
            table.add_column("Metric", style="cyan")
            table.add_column("Value", overflow="fold")
            for key, value in stats_data.items():
                table.add_row(str(key), str(value))
            console_stdout.print(table)

        sys.exit(exit_code)

# ------------- Entry -------------

if __name__ == "__main__":
    args = parser.parse_args()
    diff_clipboard_with_file(
        args.file,
        args.context_lines,
        args.similarity_threshold,
        args.loc_diff_warn,
        args.no_stats
    )
