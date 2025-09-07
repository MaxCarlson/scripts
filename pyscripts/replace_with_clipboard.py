#!/usr/bin/env python3

import sys
import os
import json
import argparse
from pathlib import Path
from typing import Optional, Tuple

from cross_platform.clipboard_utils import get_clipboard
from rich.console import Console
from rich.table import Table

# Global console instances
console_stdout = Console()
console_stderr = Console(stderr=True)  # Dedicated console for stderr messages

# ------------------------------ State helpers (from CLD) ------------------------------

def _state_root() -> Path:
    """
    Location used by clipboard_diff.py to store the last CLD snapshot.
    Override with CLIPBOARD_STATE_DIR.
    """
    override = os.environ.get("CLIPBOARD_STATE_DIR")
    if override:
        p = Path(override).expanduser()
    elif os.name == "nt":
        p = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "clipboard_tools"
    else:
        p = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))) / "clipboard_tools"
    p.mkdir(parents=True, exist_ok=True)
    return p

def _snapshot_paths() -> Tuple[Path, Path]:
    root = _state_root()
    return root / "last_cld.json", root / "last_cld_clipboard.txt"

def _load_last_cld() -> Tuple[Optional[Path], Optional[str], Optional[str]]:
    """
    Returns (file_path, clipboard_text, timestamp_str) or components as None if unavailable.
    """
    meta_path, clip_path = _snapshot_paths()
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        file_path = Path(meta.get("file_path")) if meta.get("file_path") else None
        ts = meta.get("timestamp_utc")
    except Exception:
        return None, None, None
    try:
        clip_text = clip_path.read_text(encoding="utf-8")
    except Exception:
        clip_text = None
    return file_path, clip_text, ts

# ------------------------------ CLI ------------------------------

# Dual short flags (lower+upper) for every long option.
parser = argparse.ArgumentParser(
    description=(
        "Replaces file contents with clipboard data, or prints clipboard to stdout if no file is specified.\n"
        "New: --from-last-cld uses the clipboard snapshot and file path captured by the last `cld` run."
    ),
    formatter_class=argparse.RawTextHelpFormatter
)
parser.add_argument(
    "file",
    nargs="?",
    default=None,
    help="Path to the file whose contents will be replaced. If omitted, clipboard contents are printed to stdout (unless --from-last-cld is used)."
)
parser.add_argument(
    "-n", "--no-stats", "-N",
    dest="no_stats",
    action="store_true",
    help="Suppress statistics output."
)
parser.add_argument(
    "-f", "--from-last-cld", "-F",
    dest="from_last_cld",
    action="store_true",
    help="Use the last `cld` snapshot (saved clipboard & file path). If FILE is omitted, overwrites the saved file."
)

def replace_or_print_clipboard(file_path_str: str | None, no_stats: bool, from_last_cld: bool = False):
    """
    NOTE: `from_last_cld` has a default to preserve back-compat with tests that call
    replace_or_print_clipboard(file, no_stats) with two arguments.
    """
    stats_data = {}
    operation_successful = False
    exit_code = 0  # Default to success

    # Decide which console prints the stats:
    # - When printing clipboard to stdout (no file & not from_last_cld), put stats on stderr to avoid mixing.
    printing_mode = (file_path_str is None and not from_last_cld)
    stats_console = console_stderr if printing_mode else console_stdout

    try:
        target_path: Optional[Path] = Path(file_path_str).expanduser().resolve() if file_path_str else None

        source_text: Optional[str] = None
        source_desc = "Current clipboard"

        if from_last_cld:
            last_file, last_clip, last_ts = _load_last_cld()
            if last_clip is None:
                stats_data["Error"] = "No saved clipboard snapshot from a previous `cld` run was found (or it is unreadable)."
                console_stderr.print(f"[bold red][ERROR] {stats_data['Error']}[/]")
                exit_code = 1
                raise Exception(stats_data["Error"])
            source_text = last_clip
            source_desc = f"Saved CLD snapshot ({last_ts})" if last_ts else "Saved CLD snapshot"
            if target_path is None:
                if last_file is None:
                    stats_data["Error"] = "No saved file path from the last `cld` run was found."
                    console_stderr.print(f"[bold red][ERROR] {stats_data['Error']}[/]")
                    exit_code = 1
                    raise Exception(stats_data["Error"])
                target_path = last_file.resolve()
                stats_data["Inferred Target"] = str(target_path)

        else:
            # Standard behavior: use CURRENT clipboard (print to stdout if no file is provided)
            try:
                source_text = get_clipboard()
            except NotImplementedError:
                stats_data["Error"] = "Clipboard functionality (get_clipboard) not implemented."
                console_stderr.print(f"[bold red][ERROR] {stats_data['Error']} Ensure clipboard utilities are installed and accessible.[/]")
                exit_code = 1
                raise
            except Exception as e_get_clip:
                stats_data["Error"] = f"Failed to get clipboard content: {e_get_clip}"
                console_stderr.print(f"[bold red][ERROR] {stats_data['Error']}[/]")
                exit_code = 1
                raise

        if source_text is None or source_text == "":
            # Revert to your original wording so existing tests pass.
            stats_data["Status"] = "Clipboard is empty. Aborting."
            console_stderr.print(stats_data["Status"], style="bold red")
            exit_code = 1

        else:
            stats_data["Clipboard Source"] = source_desc
            stats_data["Clipboard Content"] = f"{len(source_text)} chars, {len(source_text.splitlines())} lines"

            if printing_mode:
                # Print clipboard to stdout (no file, not from_last_cld)
                stats_data["Operation Mode"] = "Print to stdout"
                try:
                    sys.stdout.write(source_text)
                    sys.stdout.flush()
                    operation_successful = True
                    stats_data["Chars Printed"] = len(source_text)
                    stats_data["Lines Printed"] = len(source_text.splitlines())
                except Exception as e_print:
                    stats_data["Error"] = f"Error printing to stdout: {e_print}"
                    console_stderr.print(f"[bold red][ERROR] {stats_data['Error']}[/]")
                    exit_code = 1

            else:
                # Replace file content
                stats_data["Operation Mode"] = "Replace file content"

                if target_path is None:
                    stats_data["Error"] = "Target file is required unless --from-last-cld is used to infer it."
                    console_stderr.print(f"[bold red][ERROR] {stats_data['Error']}[/]")
                    exit_code = 1
                    raise Exception(stats_data["Error"])

                stats_data["File Path"] = str(target_path)

                created_new_file = False
                original_content_desc = "File did not exist"

                if not target_path.exists():
                    message = f"File '{target_path}' does not exist. Creating new file."
                    console_stdout.print(message)
                    stats_data["File Action"] = "Created new file"
                    created_new_file = True
                else:
                    try:
                        original_text = target_path.read_text(encoding="utf-8")
                        original_content_desc = f"{len(original_text)} chars, {len(original_text.splitlines())} lines"
                        stats_data["File Action"] = "Overwritten existing file"
                    except Exception as e_read_orig:
                        original_content_desc = f"Could not read original for stats: {e_read_orig}"
                    stats_data["Original Content (approx)"] = original_content_desc

                # Normalize to end with a single newline (keeps your prior behavior)
                content_to_write = source_text.rstrip("\n") + "\n"

                try:
                    with open(target_path, "w", encoding="utf-8") as f:
                        chars_written = f.write(content_to_write)
                    operation_successful = True
                    console_stdout.print(f"Replaced contents of '{target_path}' with clipboard data.")
                    stats_data["Chars Written"] = chars_written
                    stats_data["Lines Written"] = len(content_to_write.splitlines())
                    if created_new_file:
                        stats_data["Note"] = "File was newly created."
                except Exception as e_write:
                    stats_data["Error"] = f"Error writing to file '{target_path}': {e_write}"
                    console_stderr.print(f"[bold red][ERROR] {stats_data['Error']}[/]")
                    exit_code = 1

        if exit_code == 0 and not operation_successful and not printing_mode:
            # If not print mode and operation failed without a specific error captured
            stats_data.setdefault("Warning", "Operation did not complete as expected but no specific error caught.")
            exit_code = 1

    except Exception:
        if exit_code == 0:
            exit_code = 1
        if "Error" not in stats_data and "Status" not in stats_data:
            stats_data["Error"] = f"An unexpected error occurred: {sys.exc_info()[1]}"

    finally:
        if not no_stats:
            if not stats_data:
                stats_data["Status"] = "No operation performed or stats collected due to early error."

            table = Table(title="replace_with_clipboard.py Statistics")
            table.add_column("Metric", style="cyan")
            table.add_column("Value", overflow="fold")

            for key, value in stats_data.items():
                table.add_row(str(key), str(value))

            stats_console.print(table)

        sys.exit(exit_code)


if __name__ == "__main__":
    args = parser.parse_args()
    replace_or_print_clipboard(args.file, args.no_stats, args.from_last_cld)
