#!/usr/bin/env python3
import sys
import argparse
import re
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
    "--no-stats",
    action="store_true",
    help="Suppress statistics output."
)

def copy_buffer_to_clipboard_main(full: bool, no_stats: bool):
    stats_data = {}
    exit_code = 0

    try:
        system_utils = SystemUtils()
        if not system_utils.is_tmux():
            stats_data["Environment"] = "Not a tmux session"
            error_msg = "This script is designed to run inside a tmux session to capture the scrollback buffer."
            console_stderr.print(f"[bold red][ERROR] {error_msg}[/]")
            stats_data["Error"] = error_msg
            exit_code = 1
            raise RuntimeError(error_msg)

        stats_data["Environment"] = "tmux session detected"
        tmux_manager = TmuxManager()
        
        # Capture a large amount of history. tmux default is 2000 lines.
        # Capturing with '-' can be slow if history is massive. '-5000' is a good balance.
        full_buffer = tmux_manager.capture_pane(start_line='-10000')

        if full_buffer is None:
            error_msg = "Failed to capture tmux pane buffer."
            stats_data["Buffer Capture"] = "Failed"
            stats_data["Error"] = error_msg
            console_stderr.print(f"[bold red][ERROR] {error_msg}[/]")
            exit_code = 1
            raise RuntimeError(error_msg)

        stats_data["Buffer Capture"] = "Success"
        stats_data["Raw Buffer Chars"] = len(full_buffer)
        stats_data["Raw Buffer Lines"] = len(full_buffer.splitlines())

        text_to_copy = ""
        if full:
            stats_data["Mode"] = "Full Buffer"
            text_to_copy = full_buffer
        else:
            stats_data["Mode"] = "Since Last Clear (Smart)"
            # The `clear` command typically sends an escape sequence to clear the visible
            # screen (CSI 2 J) and move the cursor to the home position (CSI H).
            # We search for the last occurrence of this combined sequence.
            clear_sequence = "\x1b[H\x1b[2J"
            last_clear_pos = full_buffer.rfind(clear_sequence)

            if last_clear_pos != -1:
                # Take everything after the sequence.
                text_to_copy = full_buffer[last_clear_pos + len(clear_sequence):]
                stats_data["Clear Sequence Found"] = f"Yes (at index {last_clear_pos})"
            else:
                text_to_copy = full_buffer
                stats_data["Clear Sequence Found"] = "No"
                console_stderr.print("[yellow][WARNING] Could not find a standard 'clear' sequence. Copying entire captured buffer.[/yellow]")

        final_text = text_to_copy.strip()
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

if __name__ == "__main__":
    args = parser.parse_args()
    final_exit_code = copy_buffer_to_clipboard_main(args.full, args.no_stats)
    sys.exit(final_exit_code)
