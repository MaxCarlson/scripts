#!/usr/bin/env python3
import sys
import subprocess
import argparse
import os # Needed for os.environ.get
from pathlib import Path # For robust script name checking in loop prevention

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
    # print(f"DEBUG: Executing command: [{command_to_run}]")

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
            "If no explicit command is given, it can re-run a command from shell history."
        ),
        usage="%(prog)s [options] [command [arg ...]]",
        epilog=(
            f"Examples:\n"
            f"  %(prog)s ls -l /tmp                   # Run 'ls -l /tmp' and copy its output.\n"
            f"  %(prog)s echo \"Hello World\"             # Run 'echo \"Hello World\"' and copy its output.\n"
            f"  %(prog)s                             # Re-run the PREVIOUS (N=1) shell command and copy output (with confirmation).\n"
            f"  %(prog)s -r 3                         # Re-run the 3rd most recent shell command and copy output (with confirmation).\n"
            f"  %(prog)s --replay-history 1           # Same as providing no command (N=1 default for history).\n"
            f"  %(prog)s -r 2 -- ps aux --sort=-%%mem  # The '-r 2' is IGNORED because an explicit command 'ps aux ...' is given.\n\n"
            f"Use '--' to explicitly separate script options from an explicit command if the command itself\n"
            f"starts with a '-' or '--'."
        ),
        formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument(
        '-r', '--replay-history',
        type=int,
        dest='replay_nth_command',
        metavar='N',
        default=None,
        help=(
            "Re-run and copy output from the Nth most recent command from shell history "
            "(e.g., 1 for the last, 2 for second to last). "
            "This option is only effective if no explicit [command] is provided. "
            "If no command and no -r/--replay-history option is given, defaults to N=1."
        )
    )

    parser.add_argument(
        'command_and_args',
        nargs=argparse.REMAINDER,
        help=(
            "The command to execute, followed by its arguments. "
            "If omitted, the script will use the --replay-history option (or default to N=1) "
            "to pick a command from shell history."
        )
    )

    args = parser.parse_args()
    command_to_execute_parts = [] 

    if args.command_and_args:
        command_to_execute_parts = args.command_and_args
    else: 
        nth_to_replay = 1 
        if args.replay_nth_command is not None:
            if args.replay_nth_command <= 0:
                print("[ERROR] Value for --replay-history (-r) must be a positive integer.", file=sys.stderr)
                parser.print_help(sys.stderr)
                sys.exit(1)
            nth_to_replay = args.replay_nth_command
            print(f"[INFO] No explicit command. Using --replay-history to target N={nth_to_replay} from shell history...")
        else:
            print(f"[INFO] No explicit command and no --replay-history option. Defaulting to replay N=1 (last command)...")
        
        last_command_str = None
        try:
            current_shell_path = os.environ.get('SHELL', '/bin/sh')
            current_shell_name = Path(current_shell_path).name
            
            history_fc_event_specifier = f"-{nth_to_replay}" # e.g., -1, -3
            
            history_retrieval_cmd_parts = []
            history_retrieval_sub_command = ""

            if current_shell_name == 'bash':
                # For bash, fc -ln -N -N (list, no numbers, Nth event to Nth event)
                history_retrieval_sub_command = f"fc -ln {history_fc_event_specifier} {history_fc_event_specifier}"
                history_retrieval_cmd_parts = ['bash', '-ic', history_retrieval_sub_command] # -i for interactive-like behavior
            elif current_shell_name == 'zsh':
                # For zsh, set options to ensure history is accessible and then use fc.
                # Using `fc -ln -N` (single -N) might be more robust for just getting the Nth last command if `-N -N` is tricky.
                # `fc -ln -1` gets the last command. `fc -ln -N -N` should get the Nth last.
                # The setopts are to help the non-interactive subshell access history.
                zsh_opts = "setopt EXTENDED_HISTORY; setopt INC_APPEND_HISTORY; setopt SHARE_HISTORY; setopt HIST_NO_FUNCTIONS;"
                if nth_to_replay == 1:
                    # For N=1, `fc -ln -1` is simpler and standard.
                    history_retrieval_sub_command = f"{zsh_opts} fc -ln -1"
                else:
                    history_retrieval_sub_command = f"{zsh_opts} fc -ln {history_fc_event_specifier} {history_fc_event_specifier}"
                history_retrieval_cmd_parts = ['zsh', '-ic', history_retrieval_sub_command] # -i for interactive-like behavior
            else:
                print(f"[WARNING] Automatic history retrieval for shell '{current_shell_name}' is not explicitly supported. "
                      f"Trying generic `fc -ln {history_fc_event_specifier} {history_fc_event_specifier}` via '/bin/sh'. This may not work.", file=sys.stderr)
                history_retrieval_sub_command = f"fc -ln {history_fc_event_specifier} {history_fc_event_specifier}"
                history_retrieval_cmd_parts = ['sh', '-c', history_retrieval_sub_command]
            
            if history_retrieval_cmd_parts:
                # print(f"[DEBUG] Attempting to retrieve history with: {' '.join(history_retrieval_cmd_parts)}")
                result = subprocess.run(history_retrieval_cmd_parts, capture_output=True, text=True, check=False)
                
                if result.returncode == 0 and result.stdout.strip():
                    last_command_str = result.stdout.strip()
                else:
                    print(f"[ERROR] Could not retrieve N={nth_to_replay} command. `{' '.join(history_retrieval_cmd_parts)}` failed or returned empty.", file=sys.stderr)
                    if result.stderr:
                        print(f"Stderr from history command: {result.stderr.strip()}", file=sys.stderr)
                    last_command_str = None
            
            if not last_command_str:
                print(f"[INFO] No command (N={nth_to_replay}) retrieved from history or retrieval failed. Please provide a command explicitly.", file=sys.stderr)
                # parser.print_help(sys.stderr) # Already printed by a previous error or will be if no command.
                sys.exit(1)

            current_script_path_str = str(Path(sys.argv[0]).resolve())
            script_name_itself = Path(sys.argv[0]).name
            # Check if the retrieved command is an invocation of this script.
            # This check is heuristic.
            if script_name_itself in last_command_str or \
               (os.path.isabs(sys.argv[0]) and current_script_path_str in last_command_str) or \
               ("output_to_clipboard.py" in last_command_str and "output_to_clipboard.py" in script_name_itself) : # Be more specific if needed
                 print(f"[WARNING] The N={nth_to_replay} command from history ('{last_command_str}') appears to be an invocation of this script itself. Aborting to prevent a loop.", file=sys.stderr)
                 sys.exit(1)

            try:
                confirm_prompt = f"[CONFIRM] Re-run command (N={nth_to_replay} from history): '{last_command_str}'? [y/N]: "
                confirm = input(confirm_prompt)
                if confirm.lower() == 'y':
                    print(f"[INFO] User approved. Re-running: {last_command_str}")
                    command_to_execute_parts = [last_command_str]
                else:
                    print("[INFO] Re-run cancelled by user.")
                    sys.exit(0)
            except EOFError:
                print("[ERROR] Could not get confirmation (EOF). Aborting re-run. Please run interactively or provide a command.", file=sys.stderr)
                sys.exit(1)
            except Exception as e_confirm:
                 print(f"[ERROR] Error during confirmation: {e_confirm}", file=sys.stderr)
                 sys.exit(1)
                
        except Exception as e_hist:
            print(f"[ERROR] An unexpected error occurred while processing history: {e_hist}", file=sys.stderr)
            # parser.print_help(sys.stderr) # Avoid double printing if an error occurred above.
            sys.exit(1)
            
    if command_to_execute_parts:
        run_command_and_copy(command_to_execute_parts)
    else:
        # This means no explicit command, and history retrieval failed AND didn't exit, which shouldn't happen.
        # Or if user cancelled and we didn't sys.exit(0) properly.
        print("[ERROR] No command determined for execution. If you intended to use history, it might have failed.", file=sys.stderr)
        parser.print_help(sys.stderr)
        sys.exit(1)
