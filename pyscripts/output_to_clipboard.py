#!/usr/bin/env python3
import sys
import subprocess
import argparse

# Assume cross_platform.clipboard_utils.set_clipboard is available
# If you have issues with this import, ensure the module is correctly installed
# or in your Python path.
from cross_platform.clipboard_utils import set_clipboard

# --- Mock for testing if cross_platform.clipboard_utils is unavailable ---
# If you don't have the set_clipboard module, you can uncomment this mock
# to test the script's command execution logic.
# def set_clipboard(text):
#     print("----CLIPBOARD CONTENT----")
#     print(text)
#     print("-------------------------")
#     print("(Mock) Copied to clipboard.")
# --- End Mock ---

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
    # print(f"DEBUG: Executing command: [{command_to_run}]") # Uncomment for debugging

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
        description="Runs a given command and copies its combined standard output and standard error to the clipboard.",
        usage="%(prog)s [options] command [arg ...]",
        epilog=(
            f"Examples:\n"
            f"  %(prog)s ls -l /tmp\n"
            f"  %(prog)s echo \"Hello World\"\n"
            f"  %(prog)s -- ps aux --sort=-%%mem\n\n"  # Corrected: %mem -> %%mem
            f"Use '--' to explicitly separate script options from the command if the command itself\n"
            f"starts with a '-' or '--' and might be confused with an option for this script."
        ),
        formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument(
        'command_and_args',
        nargs=argparse.REMAINDER,
        help="The command to execute, followed by its arguments."
    )

    args = parser.parse_args()

    if not args.command_and_args:
        print("Error: No command specified to execute.", file=sys.stderr)
        parser.print_help(sys.stderr)
        sys.exit(1)
    
    run_command_and_copy(args.command_and_args)
