#!/usr/bin/env python3
import sys
import subprocess
import argparse
import os
from pathlib import Path

# Assume cross_platform.clipboard_utils.set_clipboard is available
try:
    from cross_platform.clipboard_utils import set_clipboard
except ImportError:
    print("[ERROR] The 'cross_platform.clipboard_utils' module was not found.")
    print("    Please ensure it is installed and accessible in your Python environment.")
    print("    (Note: The actual package name for 'cross_platform.clipboard_utils' might differ; please check its source.)")
    sys.exit(1)

def run_command_and_copy(command_parts):
    """
    Runs the command constructed from command_parts, captures its output
    (stdout and stderr), and copies the combined output to the clipboard.
    command_parts is expected to be a list of strings.
    """
    if not command_parts:
        print("Error: No command provided to run_command_and_copy function.", file=sys.stderr)
        sys.exit(1)

    command_to_run = " ".join(command_parts)
    try:
        result = subprocess.run(
            command_to_run,
            shell=True,
            capture_output=True,
            text=True,
            check=False
        )
        output = result.stdout + result.stderr
        output_to_copy = output.strip()

        set_clipboard(output_to_copy)
        print("Copied command output to clipboard.")

        if result.returncode != 0:
            print(f"Warning: Command '{command_to_run}' exited with status {result.returncode}", file=sys.stderr)
    except Exception as e:
        print(f"An error occurred while running '{command_to_run}' or setting clipboard: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Runs a command and copies its combined stdout/stderr to the clipboard. "
            "If no explicit command is given, replays a command from shell history."
        ),
        usage="%(prog)s [options] [command [arg ...]]",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        '-r', '--replay-history',
        type=int,
        dest='replay_nth_command',
        metavar='N',
        default=None,
        help=(
            "Re-run and copy output from the Nth most recent command from shell history."
        )
    )
    parser.add_argument(
        'command_and_args',
        nargs=argparse.REMAINDER,
        help="The command to execute. If omitted, uses --replay-history or defaults to 1."
    )
    args = parser.parse_args()

    command_to_execute_parts = []
    if args.command_and_args:
        command_to_execute_parts = args.command_and_args
    else:
        nth = args.replay_nth_command or 1
        if nth <= 0:
            print("[ERROR] Value for --replay-history (-r) must be positive.", file=sys.stderr)
            parser.print_help(sys.stderr)
            sys.exit(1)
        print(f"[INFO] Replaying history entry N={nth}...", file=sys.stderr)

        # Retrieve history
        current_shell = os.environ.get('SHELL', '/bin/sh')
        shell_name = Path(current_shell).name
        history_cmd = [shell_name, '-i', '-c', 'history']
        hist = subprocess.run(history_cmd, capture_output=True, text=True)
        if hist.returncode != 0:
            print(f"[ERROR] Failed to retrieve history: {hist.stderr.strip()}", file=sys.stderr)
            sys.exit(1)
        lines = [l for l in hist.stdout.splitlines() if l.strip()]
        if len(lines) < nth:
            print(f"[ERROR] Only {len(lines)} history entries; cannot replay N={nth}.", file=sys.stderr)
            sys.exit(1)

        entry = lines[-nth].strip()
        parts = entry.split(None, 1)
        last_cmd = parts[1] if len(parts) == 2 else parts[0]

        # Prevent looping
        script = Path(sys.argv[0]).name
        if script in last_cmd:
            print(f"[WARNING] History entry '{last_cmd}' looks like this script; aborting.", file=sys.stderr)
            sys.exit(1)

        # Confirm
        resp = input(f"[CONFIRM] Re-run: '{last_cmd}'? [y/N]: ")
        if resp.lower() == 'y':
            print(f"[INFO] User approved. Re-running: {last_cmd}", file=sys.stderr)
            command_to_execute_parts = [last_cmd]
        else:
            print("[INFO] Cancelled.", file=sys.stderr)
            sys.exit(0)

    run_command_and_copy(command_to_execute_parts)
