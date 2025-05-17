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

# Import HistoryUtils
try:
    from cross_platform.history_utils import HistoryUtils
except ImportError:
    print("[ERROR] The 'cross_platform.history_utils' module was not found.")
    print("    Please ensure it is installed and accessible in your Python environment.")
    print("    (Note: The actual package name for 'cross_platform.history_utils' might differ; please check its source.)")
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
            shell=True,  # Important to run the command string as a shell command
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
            "Re-run and copy output from the Nth most recent command from shell history. "
            "N=1 is the most recent."
        )
    )
    parser.add_argument(
        'command_and_args',
        nargs=argparse.REMAINDER,
        help="The command to execute. If omitted, uses --replay-history (defaults to N=1 if -r is not specified)."
    )
    args = parser.parse_args()

    command_to_execute_parts = []
    if args.command_and_args:
        command_to_execute_parts = args.command_and_args
    else:
        # Default to N=1 if no command is provided and -r is not explicitly set
        nth = args.replay_nth_command if args.replay_nth_command is not None else 1
        if nth <= 0:
            print("[ERROR] Value for --replay-history (-r) must be positive.", file=sys.stderr)
            parser.print_help(sys.stderr)
            sys.exit(1)
        
        print(f"[INFO] Attempting to replay history entry N={nth}...", file=sys.stderr)

        history_util = HistoryUtils()
        # Note: HistoryUtils uses its own debug logging (write_debug).
        # To see its logs, debug configuration for that module would be needed.
        
        last_cmd = history_util.get_nth_recent_command(nth)

        if not last_cmd:
            print(f"[ERROR] Failed to retrieve the {nth}{'st' if nth == 1 else 'nd' if nth == 2 else 'rd' if nth == 3 else 'th'} command from history.", file=sys.stderr)
            # HistoryUtils would have logged details via write_debug if issues like file not found occurred.
            if history_util.shell_type == "unknown":
                 print("[INFO] Shell type could not be determined by HistoryUtils. History fetching may be unreliable.", file=sys.stderr)
            sys.exit(1)
        
        print(f"[INFO] Found history command: '{last_cmd}'", file=sys.stderr)

        # Prevent looping: if the command found in history is this script itself.
        script_name = Path(sys.argv[0]).name      # e.g., "output_to_clipboard.py"
        script_name_stem = Path(sys.argv[0]).stem # e.g., "output_to_clipboard"
        
        # Check if the script name or stem is part of the command to be replayed.
        # This catches cases like `otc -r 1` or `python output_to_clipboard.py anything`
        # or `./output_to_clipboard.py`
        # Split last_cmd to check the command part, not arguments that might coincidentally match script name
        cmd_parts_from_history = last_cmd.split()
        is_self_call = False
        if cmd_parts_from_history:
            first_cmd_part = cmd_parts_from_history[0]
            # If the script is called directly (e.g. ./otc.py or otc if aliased/symlinked to the stem)
            if first_cmd_part == script_name or first_cmd_part == script_name_stem:
                is_self_call = True
            # If the script is called via python (e.g. python otc.py)
            if "python" in first_cmd_part.lower() and script_name in last_cmd:
                 is_self_call = True
            # A simpler check if the script's own name (e.g. output_to_clipboard.py) is in the command string
            if not is_self_call and script_name in last_cmd: # Generic check
                is_self_call = True


        if is_self_call:
            print(f"[WARNING] History entry N={nth} ('{last_cmd}') appears to be an invocation of this script. Aborting to prevent a loop.", file=sys.stderr)
            sys.exit(1)

        # Confirm before re-running
        try:
            resp = input(f"[CONFIRM] Re-run: '{last_cmd}'? [y/N]: ")
        except EOFError: # Handle non-interactive environments (e.g., piped input)
            print("[WARNING] No input available for confirmation (EOFError). Assuming 'No'.", file=sys.stderr)
            resp = 'n'
        except KeyboardInterrupt:
            print("\n[INFO] User cancelled confirmation (KeyboardInterrupt).", file=sys.stderr)
            sys.exit(0)


        if resp.lower() == 'y':
            print(f"[INFO] User approved. Re-running: {last_cmd}", file=sys.stderr)
            # last_cmd is a full command string. Pass it as a single item list.
            # run_command_and_copy will do " ".join([last_cmd]), which is fine.
            command_to_execute_parts = [last_cmd]
        else:
            print("[INFO] User cancelled re-run.", file=sys.stderr)
            sys.exit(0)

    if not command_to_execute_parts: 
        # This path could be reached if:
        # 1. No command_and_args, and user cancelled history replay.
        # (Should have exited with sys.exit(0) already in that case)
        # This is more of a safeguard.
        print("[INFO] No command to execute.", file=sys.stderr)
        sys.exit(0)
        
    run_command_and_copy(command_to_execute_parts)
