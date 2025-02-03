#!/usr/bin/env python3
import sys
import subprocess
from cross_platform.clipboard_utils import set_clipboard

def run_command_and_copy(command_args):
    """
    Runs the given command, captures its output (stdout and stderr),
    and copies the combined output to the clipboard.
    """
    try:
        result = subprocess.run(command_args, capture_output=True, text=True, check=False)
        output = result.stdout + result.stderr
        set_clipboard(output)
        print("Copied command output to clipboard.")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: copy_output_to_clipboard.py <command> [arguments...]")
        sys.exit(1)
    run_command_and_copy(sys.argv[1:])

