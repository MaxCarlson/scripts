#!/usr/bin/env python3
"""
# `run_pattern.py`
A cross-platform script for executing an arbitrary command over all files matching a given pattern, preserving command-line syntax across Bash, Zsh, PowerShell, and Termux.

---

## **📌 Features**
- Runs an arbitrary command across multiple files that match a pattern.
- Keeps all flags **before and after** the pattern intact.
- Works on **Linux, macOS, WSL, Windows (PowerShell), and Termux**.
- Uses `fd` if available for fast searching; falls back to `find`.
- Supports any shell-compatible command.

---

## **🛠️ Installation**
### **Linux/macOS/WSL/Termux**
1. Ensure Python is installed:
   ```bash
   python3 --version
"""
import sys
import subprocess
import shutil
import os

def run_command_on_pattern(command, pre_flags, pattern, post_flags):
    """Runs the specified command on all files matching a pattern."""
    
    # Determine shell type
    is_windows = os.name == "nt"
    
    # Use 'fd' if available, otherwise fallback to 'find'
    fd_path = shutil.which("fd")
    find_command = ["fd", "--type", "f", pattern] if fd_path else ["find", ".", "-type", "f", "-name", pattern]
    
    # Execute the file search
    try:
        result = subprocess.run(find_command, capture_output=True, text=True, check=True)
        files = result.stdout.strip().split("\n")
    except subprocess.CalledProcessError:
        print(f"Error: No files matching pattern '{pattern}' found.")
        sys.exit(1)

    # Run command on each file
    for file in files:
        full_cmd = [command] + pre_flags + [file] + post_flags
        print(f"Executing: {' '.join(full_cmd)}")
        subprocess.run(full_cmd)

def parse_arguments():
    """Parses the arguments to extract command, flags, and pattern."""
    
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} command -<pre-flags> pattern -<post-flags>")
        sys.exit(1)

    cmd = sys.argv[1]  # First argument is the command
    args = sys.argv[2:]

    pre_flags = []
    post_flags = []
    pattern = None

    # Parse arguments
    i = 0
    while i < len(args):
        arg = args[i]
        
        if arg.startswith("-"):
            if pattern is None:
                pre_flags.append(arg)
            else:
                post_flags.append(arg)
        else:
            if pattern is None:
                pattern = arg  # First non-flag argument is the pattern
            else:
                print(f"Error: Multiple patterns provided ({pattern} and {arg}).")
                sys.exit(1)
        i += 1

    if not pattern:
        print("Error: No pattern provided.")
        sys.exit(1)

    return cmd, pre_flags, pattern, post_flags

if __name__ == "__main__":
    cmd, pre_flags, pattern, post_flags = parse_arguments()
    run_command_on_pattern(cmd, pre_flags, pattern, post_flags)


