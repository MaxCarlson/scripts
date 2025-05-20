#!/usr/bin/env python3
import sys
import subprocess
import argparse
import os
from pathlib import Path
from rich.console import Console
from rich.table import Table

# Attempt to import clipboard utils, critical for this script
try:
    from cross_platform.clipboard_utils import set_clipboard
except ImportError:
    # Use basic print as rich Console might not be ready
    print("[CRITICAL ERROR] The 'cross_platform.clipboard_utils' module was not found.", file=sys.stderr)
    print("    Please ensure it is installed and accessible in your Python environment.", file=sys.stderr)
    sys.exit(1)

try:
    from cross_platform.history_utils import HistoryUtils
except ImportError:
    print("[CRITICAL ERROR] The 'cross_platform.history_utils' module was not found.", file=sys.stderr)
    print("    Please ensure it is installed and accessible in your Python environment.", file=sys.stderr)
    sys.exit(1)

console_stdout = Console()
console_stderr = Console(stderr=True) # For info, warnings, errors

# Define parser at module level
parser = argparse.ArgumentParser(
    description=(
        "Runs a command and copies its combined stdout/stderr to the clipboard. "
        "If no explicit command is given, replays a command from shell history."
    ),
    usage="%(prog)s [options] [--] [command [arg ...]] \n       %(prog)s [options] -r N",
    formatter_class=argparse.RawTextHelpFormatter,
    epilog= (
        "Examples:\n"
        "  %(prog)s -- ls -l /tmp\n"
        "  %(prog)s -r 1\n"
        "  %(prog)s\n"
        "  %(prog)s --no-stats -- date\n\n"
        "Note: Use '--' before a command if it might be mistaken for an option."
    )
)
parser.add_argument(
    '-r', '--replay-history', type=int, dest='replay_nth_command', metavar='N', default=None,
    help="Re-run from Nth most recent history command. Defaults to N=1 if no command given."
)
parser.add_argument(
    "--no-stats", action="store_true", help="Suppress statistics output."
)
parser.add_argument(
    'command_and_args', nargs=argparse.REMAINDER,
    help="Command to execute. If starts with '-', prefix with '--'."
)


def run_command_and_copy_main(command_parts: list[str] | None, replay_nth: int | None, no_stats: bool):
    stats_data = {}
    operation_successful = False 
    user_cancelled_operation = False
    command_to_execute_str = ""
    exit_code = 0 # Default success

    try:
        if command_parts:
            stats_data["Mode"] = "Direct Command Execution"
            command_to_execute_str = " ".join(command_parts)
            stats_data["Provided Command"] = command_to_execute_str
        elif replay_nth is not None:
            stats_data["Mode"] = f"Replay History (N={replay_nth})"
            
            if replay_nth <= 0:
                error_msg = "Value for --replay-history (-r) must be positive."
                stats_data["Error"] = error_msg
                console_stderr.print(f"[bold red][ERROR] {error_msg}[/]")
                exit_code = 1
                raise ValueError(error_msg)

            console_stderr.print(f"[INFO] Attempting to replay history entry N={replay_nth}...")
            history_util = HistoryUtils()
            
            last_cmd_from_hist = history_util.get_nth_recent_command(replay_nth)
            stats_data["History Fetch Attempted For N"] = replay_nth

            if not last_cmd_from_hist:
                error_msg = f"Failed to retrieve the {replay_nth}{'st' if replay_nth == 1 else 'nd' if replay_nth == 2 else 'rd' if replay_nth == 3 else 'th'} command from history."
                stats_data["Error"] = error_msg
                stats_data["History Command Found"] = "No"
                console_stderr.print(f"[bold red][ERROR] {error_msg}[/]")
                if history_util.shell_type == "unknown":
                     console_stderr.print("[INFO] Shell type could not be determined. History fetching may be unreliable.")
                exit_code = 1
                raise ValueError(error_msg)
            
            stats_data["History Command Found"] = last_cmd_from_hist
            console_stderr.print(f"[INFO] Found history command: '{last_cmd_from_hist}'")

            script_name = Path(sys.argv[0]).name
            script_name_stem = Path(sys.argv[0]).stem
            
            cmd_parts_from_history = last_cmd_from_hist.split()
            is_self_call = False
            if cmd_parts_from_history:
                first_cmd_part = cmd_parts_from_history[0]
                if first_cmd_part == script_name or first_cmd_part == script_name_stem: is_self_call = True
                if "python" in first_cmd_part.lower() and any(s_name in last_cmd_from_hist for s_name in [script_name, script_name_stem]): is_self_call = True
                if not is_self_call and any(s_name in last_cmd_from_hist for s_name in [script_name, script_name_stem]): is_self_call = True

            if is_self_call:
                error_msg = f"Loop detected: History entry N={replay_nth} ('{last_cmd_from_hist}') is this script. Aborting."
                stats_data["Error"] = "Loop prevention triggered"
                stats_data["Loop Prevention Detail"] = error_msg
                console_stderr.print(f"[bold red][WARNING] {error_msg}[/]")
                exit_code = 1
                raise ValueError(error_msg)

            try:
                # Use console_stderr for prompts if they are informational/control flow
                resp = console_stderr.input(f"[CONFIRM] Re-run: '{last_cmd_from_hist}'? [Y/n]: ")
            except EOFError:
                console_stderr.print("[WARNING] No input for confirmation (EOFError). Assuming 'No'.")
                resp = 'n'
            except KeyboardInterrupt:
                console_stderr.print("\n[INFO] User cancelled confirmation (KeyboardInterrupt).")
                stats_data["User Confirmation"] = "Cancelled (KeyboardInterrupt)"
                user_cancelled_operation = True
                exit_code = 0 # Clean exit for user cancel
                # Must return here to allow finally to print stats before sys.exit in __main__
                # Returning exit_code as well
                return operation_successful, user_cancelled_operation, "Error" in stats_data, exit_code


            if resp.lower() == 'y':
                console_stderr.print(f"[INFO] User approved. Re-running: {last_cmd_from_hist}")
                stats_data["User Confirmation"] = "Yes"
                command_to_execute_str = last_cmd_from_hist
            else:
                console_stderr.print("[INFO] User cancelled re-run.")
                stats_data["User Confirmation"] = "No"
                user_cancelled_operation = True
                exit_code = 0 # Clean exit
                return operation_successful, user_cancelled_operation, "Error" in stats_data, exit_code
        else:
            # This path should ideally not be reached if argparse logic in __main__ is correct
            stats_data["Error"] = "No command provided and no replay triggered."
            console_stderr.print("[bold red][ERROR] Internal Error: No command to execute.[/]")
            exit_code = 1
            raise ValueError("No command to execute.") # Should be caught by __main__

        # Execute the command if one was determined and not cancelled
        if not command_to_execute_str and not user_cancelled_operation:
            # Should not happen if logic above is correct, but as a safeguard
            stats_data.setdefault("Error", "Command to execute was empty unexpectedly.")
            exit_code = 1
            # No raise here, let finally block run, exit_code will be 1
        elif command_to_execute_str : # Only run if there is a command string
            stats_data["Command Executed"] = command_to_execute_str
            
            result = subprocess.run(
                command_to_execute_str, shell=True, capture_output=True, text=True, check=False
            )
            stats_data["Command Exit Status"] = result.returncode
            
            combined_output = result.stdout + result.stderr
            output_to_copy = combined_output.strip()

            stats_data["Stdout Length (raw)"] = len(result.stdout)
            stats_data["Stderr Length (raw)"] = len(result.stderr)

            if not output_to_copy:
                console_stdout.print(f"Command '{command_to_execute_str}' produced no output to copy.")
                stats_data["Output Status"] = "Empty"
                stats_data["Lines Copied"] = 0
                stats_data["Characters Copied"] = 0
            else:
                try:
                    set_clipboard(output_to_copy) # CRITICAL CALL
                    console_stdout.print("Copied command output to clipboard.")
                    stats_data["Output Status"] = "Copied"
                    stats_data["Lines Copied"] = len(output_to_copy.splitlines())
                    stats_data["Characters Copied"] = len(output_to_copy)
                    operation_successful = True
                except NotImplementedError as nie_set:
                    error_msg = "set_clipboard is not implemented. Cannot copy output."
                    stats_data["Error"] = error_msg
                    console_stderr.print(f"[bold red][ERROR] {error_msg}[/]")
                    exit_code = 1 # Critical failure
                    # No raise, let finally print stats
                except Exception as e_set:
                    error_msg = f"Failed to set clipboard: {e_set}"
                    stats_data["Error"] = error_msg
                    console_stderr.print(f"[bold red][ERROR] {error_msg}[/]")
                    exit_code = 1 # Critical failure
                    # No raise

            if result.returncode != 0 and exit_code == 0: # If command failed but clipboard op didn't set error
                warning_msg = f"Command '{command_to_execute_str}' exited with status {result.returncode}"
                console_stderr.print(f"[yellow][WARNING] {warning_msg}[/]")
                stats_data["Command Warning"] = warning_msg
                # Non-zero exit of command is a warning, not necessarily a script failure if output was copied.
                # If we want script to exit with command's code, set exit_code = result.returncode here.

    except ValueError as ve: # Handles known errors from this function's logic
        # Error message printed by the raiser, exit_code should be set.
        # If exit_code wasn't set by the raiser, set it here.
        if exit_code == 0: exit_code = 1
    except Exception as e: # For truly unexpected errors within this function
        if exit_code == 0: exit_code = 1
        error_detail = f"An unexpected error occurred: {e}"
        stats_data.setdefault("Error", error_detail)
        console_stderr.print(f"[bold red]{error_detail}[/]")
        # No raise, let finally handle stats. exit_code is now 1.

    finally:
        if not no_stats:
            table = Table(title="output_to_clipboard.py Statistics")
            table.add_column("Metric", style="cyan", overflow="fold")
            table.add_column("Value", overflow="fold")
            if not stats_data : # If error before stats_data populated
                stats_data["Status"] = "Operation incomplete due to early error."
            for key, value in stats_data.items():
                table.add_row(str(key), str(value))
            console_stdout.print(table) # Stats to stdout
    
    return operation_successful, user_cancelled_operation, "Error" in stats_data, exit_code


if __name__ == "__main__":
    args = parser.parse_args() # Use module-level parser

    command_to_run_parts = None
    replay_n_value = args.replay_nth_command

    if args.command_and_args:
        if not (args.command_and_args == ['--'] and len(args.command_and_args) == 1) :
            command_to_run_parts = args.command_and_args
            if replay_n_value is not None:
                console_stderr.print("[INFO] Both command and --replay-history specified. Executing provided command.")
                replay_n_value = None
    
    if not command_to_run_parts:
        if replay_n_value is None:
            replay_n_value = 1
    
    final_exit_code = 1 # Default to error
    try:
        op_ok, user_cancel, has_err, func_exit_code = run_command_and_copy_main(
            command_to_run_parts, replay_n_value, args.no_stats
        )
        final_exit_code = func_exit_code # Use exit code determined by the main logic function
            
    except ValueError: 
        # This catches ValueError re-raised from run_command_and_copy_main
        # Stats should have been printed by its finally block.
        final_exit_code = 1 
    except Exception as e_main_unexpected:
        # Fallback for truly unexpected issues not caught by run_command_and_copy_main's try/except
        if not args.no_stats: # Attempt to print a last-ditch error if stats are on
            console_stderr.print(f"[bold red][CRITICAL SCRIPT ERROR] Unhandled exception in __main__: {e_main_unexpected}[/]")
        final_exit_code = 1
    
    sys.exit(final_exit_code)
