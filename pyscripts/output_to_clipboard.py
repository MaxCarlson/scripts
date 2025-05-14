#!/usr/bin/env python3
import sys
import subprocess
import argparse # Import the argparse module

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
        # This should ideally be caught by the argparse logic before calling this function
        print("Error: No command provided to run_command_and_copy function.", file=sys.stderr)
        sys.exit(1)

    # Join the parts into a single command string for execution with shell=True
    command_to_run = " ".join(command_parts)

    # print(f"DEBUG: Executing command: [{command_to_run}]") # Uncomment for debugging

    try:
        result = subprocess.run(
            command_to_run,
            shell=True, # Allows shell to parse the command string
            capture_output=True,
            text=True,
            check=False # Do not raise an exception for non-zero exit codes from the command
        )
        
        output = result.stdout + result.stderr
        output_to_copy = output.strip() # Remove leading/trailing whitespace
        
        set_clipboard(output_to_copy)
        print("Copied command output to clipboard.")

        if result.returncode != 0:
            # Inform user if the executed command itself had an error
            print(f"Warning: Command '{command_to_run}' exited with status {result.returncode}", file=sys.stderr)

    except Exception as e:
        # Catch other potential errors during subprocess execution or clipboard operation
        print(f"An error occurred while running '{command_to_run}' or setting clipboard: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    # Initialize ArgumentParser
    # The `prog` variable will be automatically set to your script's name.
    parser = argparse.ArgumentParser(
        description="Runs a given command and copies its combined standard output and standard error to the clipboard.",
        usage="%(prog)s [options] command [arg ...]", # Custom usage string
        epilog=(
            f"Examples:\n"
            f"  %(prog)s ls -l /tmp\n"
            f"  %(prog)s echo \"Hello World\"\n"
            f"  %(prog)s -- ps aux --sort=-%mem\n\n"
            f"Use '--' to explicitly separate script options from the command if the command itself\n"
            f"starts with a '-' or '--' and might be confused with an option for this script."
        ),
        formatter_class=argparse.RawTextHelpFormatter # Allows for newlines in epilog
    )

    # `add_help=True` is the default, so -h/--help for this script is automatically handled.

    # This argument will collect all remaining command-line arguments AFTER any options
    # defined for this script (like -h/--help) have been processed.
    # These collected arguments are treated as the command and its arguments to be executed.
    parser.add_argument(
        'command_and_args',
        nargs=argparse.REMAINDER, # Collect all remaining arguments into a list
        help="The command to execute, followed by its arguments."
    )

    # Parse the arguments provided on the command line.
    # If -h or --help is present (and it's meant for this script),
    # argparse will print the help message and exit automatically.
    args = parser.parse_args()

    # Check if any command was actually provided.
    # args.command_and_args will be an empty list if no command was given
    # (e.g., if the script was called as `python your_script.py` or `python your_script.py --help`).
    # The `--help` case is handled by argparse exiting, so this check is mainly for "no command given".
    if not args.command_and_args:
        print("Error: No command specified to execute.", file=sys.stderr)
        parser.print_help(sys.stderr) # Show this script's help message
        sys.exit(1)
    
    # If command_and_args contains ['--'], it's often used to signify end of options.
    # We can filter it out if it's the first element and there are other arguments.
    # However, " ".join() and shell=True will typically handle it fine,
    # as an initial '--' often doesn't affect shell command parsing unless specific commands treat it specially.
    # For simplicity, we'll pass it as is; most shells/commands will ignore a leading '--' if it's not their own.
    # If the first actual command part is '--', that's fine for " ".join()

    # Proceed to run the collected command and its arguments
    run_command_and_copy(args.command_and_args)
