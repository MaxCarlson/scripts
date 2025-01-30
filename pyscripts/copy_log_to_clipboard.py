#!/usr/bin/env python3

import sys
import subprocess
import os
import argparse

from clipboard_utils import set_clipboard  # Assuming clipboard_utils.py is in same directory or PYTHONPATH

def get_current_session_log_file():
    """Determines the log file path for the current shell session based on SHLVL."""
    session_id = os.environ.get("SHLVL", "1") # Get SHLVL from environment, default to "1"
    log_file = os.path.expanduser(f"~/.term_log.session_shlvl_{session_id}")
    return log_file

def copy_terminal_log_to_clipboard(num_lines=10):
    """Copies last num_lines from current session's log file (SHLVL-based)."""
    log_file = get_current_session_log_file()

    try:
        if not os.path.exists(log_file):
            print(f"Error: Log file '{log_file}' not found for this session (SHLVL={os.environ.get('SHLVL', 'N/A')}). Make sure logging is set up and you've used this terminal session.")
            sys.exit(1)

        # Get the last num_lines from the log file
        tail_command = ["tail", "-n", str(num_lines), log_file]
        log_output = subprocess.run(tail_command, capture_output=True, text=True, check=True).stdout.strip()

        text_to_copy = log_output
        set_clipboard(text_to_copy)
        print(f"Last {num_lines} lines from current session's log (SHLVL={os.environ.get('SHLVL', 'N/A')}) copied to clipboard.")

    except FileNotFoundError:
        print("Error: 'tail' command not found.")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {e}")
        print(f"Stderr: {e.stderr.decode()}")
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Copy terminal log history from current session (SHLVL-based).")
    parser.add_argument("-n", "--lines", type=int, default=10, help="Number of lines to copy from log (default: 10).")
    args = parser.parse_args()

    copy_terminal_log_to_clipboard(args.lines)
