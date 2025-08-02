#!/usr/bin/env python3

import sys
import os
import argparse
from pathlib import Path
from cross_platform.clipboard_utils import set_clipboard
from rich.console import Console
from rich.table import Table

console_stdout = Console()
console_stderr = Console(stderr=True)

parser = argparse.ArgumentParser(
    description="Copies the last N lines from the current shell session's log file (SHLVL-based) to the clipboard.",
    formatter_class=argparse.RawTextHelpFormatter
)
parser.add_argument(
    "-n", "--lines",
    type=int,
    default=10,
    help="Number of lines to copy from the end of the log file (default: 10)."
)
parser.add_argument(
    "--no-stats",
    action="store_true",
    help="Suppress statistics output."
)

def get_current_session_log_file():
    session_id = os.environ.get("SHLVL", "1")
    log_file = os.path.expanduser(f"~/.term_log.session_shlvl_{session_id}")
    return Path(log_file)

def copy_terminal_log_to_clipboard_main(num_lines: int, no_stats: bool):
    stats_data = {}
    operation_successful = False # Only true if set_clipboard is successful
    exit_code = 0
    
    shlvl = os.environ.get("SHLVL", "N/A")
    stats_data["SHLVL"] = shlvl
    stats_data["Lines Requested"] = num_lines

    log_file_path = get_current_session_log_file()
    stats_data["Log File Path"] = str(log_file_path)

    try:
        if not log_file_path.exists():
            error_msg = f"Log file '{log_file_path}' not found for this session (SHLVL={shlvl})."
            stats_data["Error"] = error_msg
            console_stderr.print(f"[bold red][ERROR] {error_msg} Make sure logging is set up and you've used this terminal session.[/]")
            exit_code = 1
        else:
            all_log_lines = log_file_path.read_text(encoding="utf-8").splitlines()
            
            if num_lines >= len(all_log_lines):
                log_output_lines = all_log_lines
            else:
                log_output_lines = all_log_lines[-num_lines:]
            
            text_to_copy = "\n".join(log_output_lines).strip()

            if not text_to_copy:
                stats_data["Content Status"] = "Log file yielded no content to copy."
                stats_data["Lines Copied"] = 0
                stats_data["Characters Copied"] = 0
                console_stdout.print(f"Log file '{log_file_path}' yielded no content for the last {num_lines} lines.")
                # This is not a script error, but no clipboard action taken.
            else:
                try:
                    set_clipboard(text_to_copy)
                    operation_successful = True
                    success_msg = f"Last {len(log_output_lines)} lines from SHLVL={shlvl} log copied to clipboard."
                    console_stdout.print(success_msg)
                    stats_data["Lines Copied"] = len(log_output_lines)
                    stats_data["Characters Copied"] = len(text_to_copy)
                    stats_data["Content Status"] = "Copied successfully"
                except NotImplementedError as nie:
                    stats_data["Error"] = "Clipboard functionality (set_clipboard) not implemented."
                    console_stderr.print(f"[bold red][ERROR] {stats_data['Error']} Ensure clipboard utilities are installed and accessible.[/]")
                    exit_code = 1
                except Exception as e_set_clip:
                    stats_data["Error"] = f"Failed to set clipboard: {e_set_clip}"
                    console_stderr.print(f"[bold red][ERROR] {stats_data['Error']}[/]")
                    exit_code = 1
        
        if exit_code == 0 and not operation_successful and text_to_copy : # If there was text but copy failed
             stats_data.setdefault("Warning", "Copy to clipboard did not complete successfully.")
             exit_code = 1


    except Exception as e: # Catch other unexpected errors
        if exit_code == 0: exit_code = 1 # Ensure error code if not already set
        if "Error" not in stats_data:
            stats_data["Error"] = f"An unexpected error occurred: {e}"
            console_stderr.print(f"[bold red][ERROR] {stats_data['Error']}[/]")
    
    finally:
        if not no_stats:
            table = Table(title="copy_log_to_clipboard.py Statistics")
            table.add_column("Metric", style="cyan")
            table.add_column("Value", overflow="fold")
            for key, value in stats_data.items():
                table.add_row(str(key), str(value))
            console_stdout.print(table)
        
        sys.exit(exit_code)

if __name__ == "__main__":
    args = parser.parse_args()
    copy_terminal_log_to_clipboard_main(args.lines, args.no_stats)
