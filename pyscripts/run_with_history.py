# run_with_history.py
#!/usr/bin/env python3
"""
run_with_history.py

Run a command with the Nth most recent file/dir path from shell history.
With no command, lists the 10 most recent paths.
"""
import argparse
import subprocess
import sys
from pathlib import Path

from cross_platform.history_utils import HistoryUtils
from cross_platform.debug_utils import set_console_verbosity

# Silence debug/info messages
set_console_verbosity("Warning")

def main():
    parser = argparse.ArgumentParser(
        description="Run a command with the Nth most recent file/dir path from shell history.\n"
                    "With no command, lists the 10 most recent paths.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "-n", "--number",
        type=int,
        default=1,
        help="The Nth recent path to use (1-indexed; default: 1)."
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Command to run with the path, e.g. rwc"
    )
    args = parser.parse_args()

    # Initialize history utils
    history = HistoryUtils()

    # If running under Zsh, warn if key history options aren't enabled
    if history.shell_type == "zsh":
        try:
            result = subprocess.run(
                ["zsh", "-lic", "setopt"], capture_output=True, text=True
            )
            zsh_opts = set(result.stdout.split())
        except Exception:
            zsh_opts = set()
        required = {"share_history", "inc_append_history", "inc_append_history_time"}
        missing = required - zsh_opts
        if missing:
            sys.stderr.write(
                f"Warning: Zsh options not set: {', '.join(sorted(missing))}. "
                "For accurate history, enable: share_history, inc_append_history, inc_append_history_time.\n"
            )

    # Locate and read history file
    hist_file = history._get_history_file_path()
    if not hist_file:
        sys.stderr.write("Error: Could not locate history file.\n")
        sys.exit(1)

    try:
        with open(hist_file, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.read().splitlines()
    except Exception as e:
        sys.stderr.write(f"Error reading history file: {e}\n")
        sys.exit(1)

    all_paths = history._extract_paths_from_history_lines(lines)
    cwd = str(Path.cwd().resolve())
    filtered = [p for p in all_paths if p != cwd]

    # No command: list top 10 recent paths
    if not args.command:
        for idx, path in enumerate(filtered[:10], start=1):
            print(f"{idx}: {path}")
        sys.exit(0)

    # Validate requested index
    n = args.number
    if n <= 0 or n > len(filtered):
        sys.stderr.write(f"Error: Cannot retrieve path #{n}. Only {len(filtered)} available.\n")
        sys.exit(1)

    # Execute command against selected path
    selected = filtered[n-1]
    cmd = args.command + [selected]
    try:
        result = subprocess.run(cmd)
        sys.exit(result.returncode)
    except FileNotFoundError:
        sys.stderr.write(f"Error: Command not found: {args.command[0]}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
