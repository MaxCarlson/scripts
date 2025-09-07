#!/usr/bin/env python3
import sys
import os
import json
import difflib
import argparse
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple

from cross_platform.clipboard_utils import get_clipboard
from rich.console import Console
from rich.table import Table
from rich.text import Text

console_stdout = Console()
console_stderr = Console(stderr=True)

# ------------------------------ State helpers (for rwcp) ------------------------------

def _state_root() -> Path:
    r"""
    Cross-platform state directory for saving the last CLD run:
      - Windows: %LOCALAPPDATA%\clipboard_tools
      - POSIX:   $XDG_STATE_HOME/clipboard_tools or ~/.local/state/clipboard_tools
      - Override with env var CLIPBOARD_STATE_DIR
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

def _sha256_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def _save_cld_snapshot(target_file: Path, clipboard_text: str) -> tuple[bool, str]:
    """
    Save the last cld run (file path + clipboard content) for rwc --from-last-cld / rwcp.
    Returns (ok, message_for_stats).
    """
    meta_path, clip_path = _snapshot_paths()
    try:
        clip_path.write_text(clipboard_text, encoding="utf-8")
        payload = {
            "file_path": str(target_file),
            "clipboard_file": str(clip_path),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "clipboard_len": len(clipboard_text),
            "clipboard_sha256": _sha256_str(clipboard_text),
        }
        meta_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return True, f"Saved snapshot → meta: {meta_path.name}, data: {clip_path.name}"
    except Exception as e:
        return False, f"Snapshot save failed: {e}"

# ------------------------------ CLI ------------------------------

parser = argparse.ArgumentParser(
    description="Diff clipboard contents with a file, providing stats and warnings.",
    formatter_class=argparse.RawTextHelpFormatter
)
parser.add_argument(
    "file",
    help="File path to compare against clipboard contents"
)
# Dual short flags (lower+upper) for every long option.
parser.add_argument(
    "-c", "--context-lines", "-C",
    dest="context_lines",
    type=int,
    default=3,
    help="Number of context lines to display (default: 3)"
)
parser.add_argument(
    "-t", "--similarity-threshold", "-T",
    dest="similarity_threshold",
    type=float,
    default=0.75,
    help="Similarity threshold for dissimilarity note (0.0-1.0, default: 0.75)"
)
parser.add_argument(
    "-l", "--loc-diff-warn", "-L",
    dest="loc_diff_warn",
    type=int,
    default=50,
    help="Absolute LOC difference above which a warning is shown (default: 50)"
)
parser.add_argument(
    "-n", "--no-stats", "-N",
    dest="no_stats",
    action="store_true",
    help="Suppress statistics output."
)

def diff_clipboard_with_file(
    file_path_str: str,
    context_lines: int,
    similarity_threshold: float,
    loc_diff_warning_threshold: int,
    no_stats: bool
) -> None:
    stats_data = {}
    operation_successful = False
    exit_code = 0

    try:
        file_path_obj = Path(file_path_str)
        stats_data["File Path"] = str(file_path_obj.resolve())

        # Read file (utf-8)
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

        # Clipboard
        try:
            clipboard_text = get_clipboard()
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

        if clipboard_text is None or clipboard_text == "" or clipboard_text.isspace():
            stats_data["Clipboard Status"] = "Empty or whitespace"
            console_stderr.print("[bold red][CRITICAL WARNING] Clipboard is empty or contains only whitespace! Snapshot skipped.[/]")
            exit_code = 1
        else:
            stats_data["Clipboard Status"] = "Content retrieved"
            clipboard_lines = clipboard_text.splitlines()
            stats_data["Clipboard LOC"] = len(clipboard_lines)

            # Save snapshot for rwc --from-last-cld / rwcp
            ok, msg = _save_cld_snapshot(file_path_obj.resolve(), clipboard_text)
            stats_data["CLD Snapshot"] = msg
            if not ok:
                console_stderr.print(f"[yellow][WARNING][/yellow] {msg}")

            # Diff (file -> clipboard)
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

            # LOC warning & similarity stats
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
        if "Error" not in stats_data and "File Read" not in stats_data:
            stats_data["Error"] = f"An unexpected error occurred during diff: {sys.exc_info()[1]}"

    finally:
        if not no_stats:
            table = Table(title="clipboard_diff.py Statistics")
            table.add_column("Metric", style="cyan")
            table.add_column("Value", overflow="fold")
            for key, value in stats_data.items():
                table.add_row(str(key), str(value))
            console_stdout.print(table)  # Diff output and stats go to stdout

        sys.exit(exit_code)

if __name__ == "__main__":
    args = parser.parse_args()
    diff_clipboard_with_file(
        args.file,
        args.context_lines,
        args.similarity_threshold,
        args.loc_diff_warn,
        args.no_stats
    )
