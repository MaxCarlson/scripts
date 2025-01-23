import os
import subprocess
import re
import glob
import ast

def get_shell_history(max_age, shell):
    """Retrieve command history up to `max_age` based on shell type."""
    try:
        if shell == "pwsh":
            cmd = "Get-Content (Get-PSReadLineOption).HistorySavePath"
            result = subprocess.run(["pwsh", "-c", cmd], capture_output=True, text=True)
            history = result.stdout.strip().split("\n")
        elif shell in ("bash", "zsh"):
            hist_file = os.path.expanduser("~/.bash_history" if shell == "bash" else "~/.zsh_history")
            if not os.path.exists(hist_file):
                return []
            with open(hist_file, "r", encoding="utf-8", errors="ignore") as f:
                history = [line.strip().split(";")[-1] for line in f.readlines()]
        else:
            raise ValueError(f"Unsupported shell: {shell}")
        return history[::-1]  # Reverse so [0] is most recent
    except Exception as e:
        raise RuntimeError(f"Error retrieving history: {e}")

def parse_run_order(run_order, history_length):
    """Parse `--run_order` into valid indices."""
    try:
        if isinstance(run_order, str) and run_order.isdigit():
            run_order = [int(run_order)]
        else:
            run_order = ast.literal_eval(run_order)
        run_order = [(history_length + idx) if idx < 0 else idx for idx in run_order]
        return [idx for idx in run_order if 0 <= idx < history_length]
    except Exception as e:
        raise ValueError(f"Invalid run_order format: {e}")

def apply_vim_substitution(command, pattern):
    """Apply Vim-style `s/pattern/replacement/g` substitution."""
    try:
        search, replace = pattern.split("/", 2)[1:3]
        return command.replace(search, replace)
    except ValueError:
        raise ValueError("Invalid Vim-style substitution format. Use 's/old/new/g'.")

def apply_glob_replacement(command, patterns, replacements):
    """Apply glob-based replacements."""
    for pattern, replacement in zip(patterns, replacements):
        matches = glob.glob(pattern)
        for match in matches:
            command = command.replace(match, replacement)
    return command

def apply_regex_replacement(command, pattern, replacement):
    """Apply regex-based replacement."""
    return re.sub(pattern, replacement, command)

def process_command(command, args, cmd_index=0):
    """Process a command using provided arguments."""
    if args.vim:
        command = apply_vim_substitution(command, args.vim[cmd_index] if isinstance(args.vim, list) else args.vim)
    if args.glob:
        patterns = args.glob[cmd_index] if isinstance(args.glob[0], list) else args.glob
        replacements = args.replace[cmd_index] if isinstance(args.replace[0], list) else args.replace
        command = apply_glob_replacement(command, patterns, replacements)
    if args.regex:
        command = apply_regex_replacement(command, args.regex[cmd_index] if isinstance(args.regex, list) else args.regex,
                                          args.replace[cmd_index] if isinstance(args.replace, list) else args.replace[0])
    return command
