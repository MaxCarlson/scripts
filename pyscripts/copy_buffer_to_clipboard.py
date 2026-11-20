#!/usr/bin/env python3
__version__ = "0.2.0"

import sys
import argparse
from pathlib import Path
from rich.console import Console
from rich.table import Table

try:
    from cross_platform.system_utils import SystemUtils
    from cross_platform.tmux_utils import TmuxManager
    from cross_platform.clipboard_utils import set_clipboard
except ImportError as e:
    print(f"[CRITICAL ERROR] Failed to import a required cross_platform module: {e}", file=sys.stderr)
    print("Please ensure the cross_platform package is installed and accessible.", file=sys.stderr)
    sys.exit(1)

from clipboard_tools.terminal_capture import (
    capture_session_log,
    capture_tmux_buffer,
    resolve_session_log_path,
    unsupported_native_terminal_result,
)

console_stderr = Console(stderr=True)
console_stdout = Console()

parser = argparse.ArgumentParser(
    description=(
        "Copies the current terminal scrollback buffer to the clipboard. "
        "Primarily designed for use within a tmux session."
    ),
    formatter_class=argparse.RawTextHelpFormatter,
    epilog=(
        "Usage Examples:\n"
        "  %(prog)s           # Copies buffer content since the last 'clear' command.\n"
        "  %(prog)s --full    # Copies the entire scrollback buffer.\n"
        "  %(prog)s --no-stats # Suppress the statistics table on exit."
    )
)
parser.add_argument(
    '-f', '--full',
    action='store_true',
    help="Copy the entire scrollback buffer, ignoring the last clear command."
)
parser.add_argument(
    "-n", "--no-stats",
    action="store_true",
    help="Suppress statistics output."
)
parser.add_argument(
    "-l", "--session-log",
    default=None,
    help="Path to a recorded session log file (or set CLIPBOARD_SESSION_LOG)."
)

def copy_buffer_to_clipboard_main(full: bool, no_stats: bool, session_log: str | None = None):
    stats_data = {}
    exit_code = 0

    try:
        system_utils = SystemUtils()
        if system_utils.is_tmux():
            stats_data["Environment"] = "tmux session detected"
            tmux_manager = TmuxManager()
            cap = capture_tmux_buffer(lambda sl: tmux_manager.capture_pane(start_line=sl), full=full)
        else:
            log_path = resolve_session_log_path(session_log)
            if log_path is not None:
                stats_data["Environment"] = f"session log ({log_path})"
                cap = capture_session_log(log_path, full=full)
            else:
                stats_data["Environment"] = "Not a tmux session (no session log configured)"
                cap = unsupported_native_terminal_result()

        if not cap.ok:
            stats_data["Buffer Capture"] = "Failed"
            stats_data["Error"] = cap.error or "Capture failed."
            console_stderr.print(f"[bold red][ERROR] {stats_data['Error']}[/]")
            if cap.guidance:
                console_stderr.print(f"[yellow][HINT] {cap.guidance}[/]")
                stats_data["Guidance"] = cap.guidance
            exit_code = 1
            raise RuntimeError(stats_data["Error"])

        stats_data["Buffer Capture"] = f"Success ({cap.backend})"
        stats_data["Mode"] = "Full Buffer" if full else "Since Last Clear (Smart)"
        if not full:
            stats_data["Clear Sequence Found"] = f"Yes (at index {cap.clear_index})" if cap.clear_found else "No"
            if not cap.clear_found:
                console_stderr.print("[yellow][WARNING] Could not find a standard 'clear' sequence. Copying entire captured buffer.[/yellow]")

        final_text = cap.text
        stats_data["Final Text Chars"] = len(final_text)
        stats_data["Final Text Lines"] = len(final_text.splitlines())

        if not final_text:
            console_stderr.print("[INFO] No content to copy after processing.")
            stats_data["Clipboard Action"] = "Skipped (no content)"
        else:
            try:
                set_clipboard(final_text)
                console_stderr.print(f"[INFO] Copied {stats_data['Final Text Lines']} lines ({stats_data['Final Text Chars']} chars) to clipboard.")
                stats_data["Clipboard Action"] = "Success"
            except Exception as e:
                error_msg = f"Failed to set clipboard: {e}"
                stats_data["Error"] = error_msg
                console_stderr.print(f"[bold red][ERROR] {error_msg}[/]")
                exit_code = 1

    except (RuntimeError, Exception) as e:
        if exit_code == 0:
            exit_code = 1
        if "Error" not in stats_data:
            stats_data["Error"] = f"An unexpected error occurred: {e}"

    finally:
        if not no_stats:
            table = Table(title="copy_buffer_to_clipboard.py Statistics")
            table.add_column("Metric", style="cyan", overflow="fold")
            table.add_column("Value", overflow="fold")
            stats_data.setdefault("Outcome", "Failed" if exit_code != 0 else "Success")
            for key, value in stats_data.items():
                table.add_row(str(key), str(value))
            console_stdout.print(table)

    return exit_code

def main(argv: list[str] | None = None):
    """Entry point for the copy_buffer_to_clipboard command."""
    args = parser.parse_args(argv)
    exit_code = copy_buffer_to_clipboard_main(args.full, args.no_stats, session_log=args.session_log)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
