#!/usr/bin/env python3

import os
import sys
import subprocess
import argparse
import re
import glob
import ast
import threading
from colorama import Fore, Style, init

# Initialize color support (cross-platform)
init(autoreset=True)

# Color-coded messages
def print_status(message, color=Style.RESET_ALL):
    print(f"{color}{message}{Style.RESET_ALL}")

def get_shell_history(max_age, shell):
    """Retrieves the command history up to `max_age` based on shell type."""
    try:
        if shell == "pwsh":
            cmd = "Get-Content (Get-PSReadLineOption).HistorySavePath"
            result = subprocess.run(["pwsh", "-c", cmd], capture_output=True, text=True)
            history = result.stdout.strip().split("\n")
        elif shell in ("bash", "zsh"):
            hist_file = os.path.expanduser("~/.bash_history" if shell == "bash" else "~/.zsh_history")
            if not os.path.exists(hist_file):
                print_status("Warning: History file not found.", Fore.YELLOW)
                return []
            with open(hist_file, "r", encoding="utf-8", errors="ignore") as f:
                lines = [line.strip().split(";")[-1] for line in f.readlines()]
            history = lines[-max_age:]
        else:
            print_status(f"Error: Unsupported shell {shell}.", Fore.RED)
            sys.exit(1)

        return history[::-1]  # Reverse so [0] is most recent
    except Exception as e:
        print_status(f"Error retrieving history: {e}", Fore.RED)
        sys.exit(1)

def parse_run_order(run_order, history_length):
    """Parses `--run_order` argument into valid indices."""
    try:
        if isinstance(run_order, str) and run_order.isdigit():
            run_order = [int(run_order)]
        else:
            run_order = ast.literal_eval(run_order)

        run_order = [(history_length + idx) if idx < 0 else idx for idx in run_order]
        return [idx for idx in run_order if 0 <= idx < history_length]
    except Exception as e:
        print_status(f"Invalid run_order format: {e}", Fore.RED)
        sys.exit(1)

def apply_vim_substitution(command, pattern):
    """Apply Vim-style `s/pattern/replacement/g` substitution."""
    try:
        search, replace = pattern.split("/", 2)[1:3]
        return command.replace(search, replace)
    except ValueError:
        print_status("Invalid Vim-style substitution format. Use 's/old/new/g'.", Fore.RED)
        sys.exit(1)

def apply_glob_replacement(command, patterns, replacements):
    """Applies glob-based replacements in order."""
    for pattern, replacement in zip(patterns, replacements):
        matches = glob.glob(pattern)
        for match in matches:
            command = command.replace(match, replacement)
    return command

def apply_regex_replacement(command, pattern, replacement):
    """Applies regex-based replacement."""
    return re.sub(pattern, replacement, command)

def process_command(command, args, cmd_index=0):
    """Processes a command using provided arguments for modifications."""
    if args.debug:
        print_status(f"[DEBUG] Original command: {command}", Fore.CYAN)

    if args.vim:
        pattern = args.vim[cmd_index] if isinstance(args.vim, list) else args.vim
        command = apply_vim_substitution(command, pattern)

    if args.glob:
        patterns = args.glob[cmd_index] if isinstance(args.glob[0], list) else args.glob
        replacements = args.replace[cmd_index] if isinstance(args.replace[0], list) else args.replace
        command = apply_glob_replacement(command, patterns, replacements)

    if args.regex:
        pattern = args.regex[cmd_index] if isinstance(args.regex, list) else args.regex
        replacement = args.replace[cmd_index] if isinstance(args.replace, list) else args.replace[0]
        command = apply_regex_replacement(command, pattern, replacement)

    if args.debug:
        print_status(f"[DEBUG] Modified command: {command}", Fore.CYAN)

    return command

def execute_command(command, args):
    """Executes a command with error handling."""
    print_status(f"Running: {command}", Fore.BLUE)
    if not args.dry_run:
        result = os.system(command)
        if result != 0:
            if args.force:
                print_status(f"Warning: Command failed but continuing (--force enabled).", Fore.YELLOW)
            else:
                print_status(f"Error: Command failed.", Fore.RED)
                sys.exit(1)
    else:
        print_status(f"Dry-run: {command}", Fore.GREEN)

def main():
    parser = argparse.ArgumentParser(description="Modify and re-run previous shell commands with pattern matching.")
    parser.add_argument("-m", "--max-age", type=int, default=100, help="Max number of historical commands to retrieve.")
    parser.add_argument("-o", "--run-order", type=str, default="[0]", help="Order of commands to execute (Python slicing syntax allowed).")
    parser.add_argument("-p", "--parallel", action="store_true", help="Run all specified commands in parallel.")
    parser.add_argument("-f", "--force", action="store_true", help="Continue execution even if a command fails.")
    parser.add_argument("-d", "--debug", action="store_true", help="Enable detailed debugging output.")
    parser.add_argument("-n", "--dry-run", action="store_true", help="Print modified commands instead of executing them.")

    parser.add_argument("-v", "--vim", nargs="+", help="Vim-style substitution (e.g., 's/old/new/g').")
    parser.add_argument("-g", "--glob", nargs="+", help="Glob patterns to replace (must be used with --replace).")
    parser.add_argument("-r", "--regex", nargs="+", help="Regex pattern to replace (must be used with --replace).")
    parser.add_argument("--replace", nargs="+", help="Replacement values for --glob or --regex.")

    args = parser.parse_args()

    shell = os.getenv("SHELL", "pwsh").split("/")[-1]

    history = get_shell_history(args.max_age, shell)
    if not history:
        print_status("No command history available.", Fore.RED)
        sys.exit(1)

    run_indices = parse_run_order(args.run_order, len(history))

    commands = [process_command(history[idx], args, i) for i, idx in enumerate(run_indices)]

    if args.parallel:
        threads = []
        for cmd in commands:
            t = threading.Thread(target=lambda: execute_command(cmd, args))
            t.start()
            threads.append(t)
        for t in threads:
            t.join()
    else:
        for cmd in commands:
            execute_command(cmd, args)

if __name__ == "__main__":
    main()
