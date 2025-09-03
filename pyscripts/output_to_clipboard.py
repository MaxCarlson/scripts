# File: output_to_clipboard.py
#!/usr/bin/env python3
from __future__ import annotations

import sys
import subprocess
import argparse
import os
import shlex
import shutil
from pathlib import Path
from typing import Tuple

from rich.console import Console
from rich.table import Table

# Attempt to import clipboard utils, critical for this script
try:
    from cross_platform.clipboard_utils import set_clipboard, get_clipboard
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
console_stderr = Console(stderr=True)  # For info, warnings, errors, AND STATS TABLE

# ----------------------------
# Shell wrapper for aliases/functions
# ----------------------------

def _shell_from_env() -> str:
    """Best-effort detection of user's shell ('zsh', 'bash', 'fish', 'pwsh', 'powershell', 'cmd', 'sh')."""
    if os.name == "nt":
        if shutil.which("pwsh"):
            return "pwsh"
        if shutil.which("powershell"):
            return "powershell"
        return "cmd"
    # POSIX
    shell_path = os.environ.get("SHELL", "").strip()
    shell = Path(shell_path).name.lower() if shell_path else ""
    if "zsh" in shell:
        return "zsh"
    if "bash" in shell:
        return "bash"
    if "fish" in shell:
        return "fish"
    if "sh" in shell:
        return "sh"
    return "sh"


def _quote_ps_command(cmd: str) -> str:
    """
    Quote a PowerShell command to pass after -Command safely.
    We wrap in double quotes and escape internal double quotes by doubling them.
    """
    return '"' + cmd.replace('"', '""') + '"'


def build_shell_wrapped_command(user_command: str, shell_choice: str | None = None) -> Tuple[str, dict]:
    """
    Return a command string that executes `user_command` in a way that supports aliases/functions.
    Also returns small metadata dict describing the selection for stats.

    The returned string is suitable for subprocess.run(..., shell=True).
    """
    meta: dict[str, str] = {}

    shell = (shell_choice or "auto").lower()
    if shell == "auto":
        shell = _shell_from_env()
        meta["Shell Detection"] = "auto"
    else:
        meta["Shell Detection"] = "forced"

    meta["Shell"] = shell

    # POSIX shells
    if shell in {"zsh"}:
        wrapped = f'zsh -i -c {shlex.quote(user_command)}'
        meta["Alias/Function Support"] = "interactive"
        return wrapped, meta

    if shell in {"bash"}:
        # Non-interactive bash doesn't expand aliases unless expand_aliases is set.
        # Source ~/.bashrc quietly to pick up user aliases/functions.
        bootstrap = 'shopt -s expand_aliases; [ -f ~/.bashrc ] && source ~/.bashrc; '
        wrapped = f'bash -lc {shlex.quote(bootstrap + user_command)}'
        meta["Alias/Function Support"] = "expand_aliases + rc"
        return wrapped, meta

    if shell in {"fish"}:
        # interactive to pick up abbreviations and functions, but fish -c loads functions from ~/.config
        wrapped = f'fish -i -c {shlex.quote(user_command)}'
        meta["Alias/Function Support"] = "interactive"
        return wrapped, meta

    if shell in {"sh"}:
        # No alias support, but still run through sh for consistency
        wrapped = f'sh -c {shlex.quote(user_command)}'
        meta["Alias/Function Support"] = "none (sh)"
        return wrapped, meta

    # Windows shells
    if shell in {"pwsh", "powershell"}:
        exe = "pwsh" if shell == "pwsh" else "powershell"
        # Load profile so aliases/functions exist; avoid logo noise.
        # Use -NoProfile if explicitly requested by user via --shell, but by default we DO load profile.
        wrapped = f'{exe} -NoLogo -Command {_quote_ps_command(user_command)}'
        meta["Alias/Function Support"] = "profile-loaded"
        return wrapped, meta

    if shell == "cmd":
        # cmd has no aliases; still run for compatibility
        wrapped = f'cmd /S /C {shlex.quote(user_command)}'
        meta["Alias/Function Support"] = "none (cmd)"
        return wrapped, meta

    # Fallback – execute raw
    meta["Alias/Function Support"] = "unknown"
    return user_command, meta


# ----------------------------
# Argument parser
# ----------------------------

parser = argparse.ArgumentParser(
    description=(
        "Runs a command and copies its combined stdout/stderr to the clipboard. "
        "If no explicit command is given, replays a command from shell history."
    ),
    usage="%(prog)s [options] [--] [command [arg ...]] \n       %(prog)s [options] -r N",
    formatter_class=argparse.RawTextHelpFormatter,
    epilog=(
        "Examples:\n"
        "  %(prog)s -- ls -l /tmp\n"
        "  %(prog)s -r 1\n"
        "  %(prog)s\n"
        "  %(prog)s -w -- git status\n"
        "  %(prog)s --no-stats -- date\n"
        "  %(prog)s -a -- echo part2  # append to existing clipboard\n\n"
        "Note: Use '--' before a command if it might be mistaken for an option."
    ),
)
parser.add_argument(
    "-r",
    "--replay-history",
    type=int,
    dest="replay_nth_command",
    metavar="N",
    default=None,
    help="Re-run from Nth most recent history command. Defaults to N=1 if no command given.",
)
parser.add_argument(
    "-w",
    "--wrap",
    action="store_true",
    help="Wrap the command output in a code block with the command string as a header.",
)
parser.add_argument("--no-stats", action="store_true", help="Suppress statistics output.")
parser.add_argument(
    "-a",
    "--append",
    action="store_true",
    help="Append new capture to current clipboard with ONE space separator.",
)
parser.add_argument(
    "-s",
    "--shell",
    default="auto",
    choices=["auto", "zsh", "bash", "fish", "pwsh", "powershell", "cmd", "sh"],
    help="Shell to use for alias/function support (default: auto).",
)
parser.add_argument(
    "command_and_args",
    nargs=argparse.REMAINDER,
    help="Command to execute. If starts with '-', prefix with '--'.",
)


def _append_to_clipboard(current: str, new: str) -> str:
    """Append new text to current clipboard with exactly one space separating."""
    if not current:
        return new
    # Normalize ends to guarantee single space boundary.
    return current.rstrip("\r\n ") + " " + new.lstrip("\r\n ")


def run_command_and_copy_main(
    command_parts: list[str] | None,
    replay_nth: int | None,
    no_stats: bool,
    wrap: bool,
    append: bool = False,
    shell_choice: str = "auto",
):
    """
    Execute the requested command (or replay from history), capture stdout+stderr,
    and copy to clipboard (optionally wrapping, optionally appending).

    Returns: (operation_successful, user_cancelled_operation, has_error, exit_code)
    """
    stats_data: dict[str, object] = {}
    operation_successful = False
    user_cancelled_operation = False
    user_command_display = ""  # The command string the user intended (shown in headers/warnings)
    exit_code = 0  # Default success

    try:
        # ----------------------------
        # Determine command to execute
        # ----------------------------
        if command_parts:
            stats_data["Mode"] = "Direct Command Execution"
            user_command_display = " ".join(command_parts)
            stats_data["Provided Command"] = user_command_display

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
                ord_map = {1: "st", 2: "nd", 3: "rd"}
                suffix = ord_map.get(replay_nth if replay_nth < 20 else replay_nth % 10, "th")
                error_msg = f"Failed to retrieve the {replay_nth}{suffix} command from history."
                stats_data["Error"] = error_msg
                stats_data["History Command Found"] = "No"
                console_stderr.print(f"[bold red][ERROR] {error_msg}[/]")
                if getattr(history_util, "shell_type", "unknown") == "unknown":
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
                if first_cmd_part == script_name or first_cmd_part == script_name_stem:
                    is_self_call = True
                if "python" in first_cmd_part.lower() and any(
                    s_name in last_cmd_from_hist for s_name in [script_name, script_name_stem]
                ):
                    is_self_call = True
                if not is_self_call and any(s_name in last_cmd_from_hist for s_name in [script_name, script_name_stem]):
                    is_self_call = True

            if is_self_call:
                error_msg = (
                    f"Loop detected: History entry N={replay_nth} ('{last_cmd_from_hist}') is this script. Aborting."
                )
                stats_data["Error"] = "Loop prevention triggered"
                stats_data["Loop Prevention Detail"] = error_msg
                console_stderr.print(f"[bold red][WARNING] {error_msg}[/]")
                exit_code = 1
                raise ValueError(error_msg)

            try:
                resp = console_stderr.input(f"[CONFIRM] Re-run: '{last_cmd_from_hist}'? [Y/n]: ")
            except EOFError:
                console_stderr.print("[WARNING] No input for confirmation (EOFError). Assuming 'No'.")
                resp = "n"
            except KeyboardInterrupt:
                console_stderr.print("\n[INFO] User cancelled confirmation (KeyboardInterrupt).")
                stats_data["User Confirmation"] = "Cancelled (KeyboardInterrupt)"
                user_cancelled_operation = True
                exit_code = 0  # Clean exit for user cancel
                return operation_successful, user_cancelled_operation, "Error" in stats_data, exit_code

            if resp.lower() == "y":
                console_stderr.print(f"[INFO] User approved. Re-running: {last_cmd_from_hist}")
                stats_data["User Confirmation"] = "Yes"
                user_command_display = last_cmd_from_hist
            else:
                console_stderr.print("[INFO] User cancelled re-run.")
                stats_data["User Confirmation"] = "No"
                user_cancelled_operation = True
                exit_code = 0  # Clean exit
                return operation_successful, user_cancelled_operation, "Error" in stats_data, exit_code
        else:
            stats_data["Error"] = "No command provided and no replay triggered."
            console_stderr.print("[bold red][ERROR] Internal Error: No command to execute.[/]")
            exit_code = 1
            raise ValueError("No command to execute.")

        # ----------------------------
        # Build shell-wrapped command for alias/function support
        # ----------------------------
        wrapped_command, shell_meta = build_shell_wrapped_command(user_command_display, shell_choice=shell_choice)
        stats_data.update({f"Shell {k}": v for k, v in shell_meta.items()})
        stats_data["Command (display)"] = user_command_display
        stats_data["Command (executed)"] = wrapped_command

        # ----------------------------
        # Execute
        # ----------------------------
        result = subprocess.run(wrapped_command, shell=True, capture_output=True, text=True, check=False)

        combined_output = (result.stdout or "") + (result.stderr or "")
        output_to_copy = combined_output.strip()

        stats_data["Stdout Length (raw)"] = len(result.stdout or "")
        stats_data["Stderr Length (raw)"] = len(result.stderr or "")
        stats_data["Command Exit Status"] = result.returncode

        if not output_to_copy:
            console_stdout.print(f"Command '{user_command_display}' produced no output to copy.")
            stats_data["Output Status"] = "Empty"
            stats_data["Lines Copied"] = 0
            stats_data["Characters Copied"] = 0
        else:
            if wrap:
                header = f"$ {user_command_display}"
                output_to_copy = f"{header}\n```\n{output_to_copy}\n```"
                stats_data["Wrapping Mode"] = "Wrapped (command + code block)"
            else:
                stats_data["Wrapping Mode"] = "Raw"

            # Append logic
            if append:
                try:
                    current_clip = get_clipboard() or ""
                except Exception:
                    current_clip = ""
                output_to_copy = _append_to_clipboard(current_clip, output_to_copy)
                stats_data["Clipboard Mode"] = "Append"
            else:
                stats_data["Clipboard Mode"] = "Replace"

            try:
                set_clipboard(output_to_copy)
                console_stdout.print("Copied command output to clipboard.")
                stats_data["Output Status"] = "Copied"
                stats_data["Lines Copied"] = len(output_to_copy.splitlines())
                stats_data["Characters Copied"] = len(output_to_copy)
                operation_successful = True
            except NotImplementedError:
                error_msg = "set_clipboard is not implemented. Cannot copy output."
                stats_data["Error"] = error_msg
                console_stderr.print(f"[bold red][ERROR] {error_msg}[/]")
                exit_code = 1
            except Exception as e_set:
                error_msg = f"Failed to set clipboard: {e_set}"
                stats_data["Error"] = error_msg
                console_stderr.print(f"[bold red][ERROR] {error_msg}[/]")
                exit_code = 1

        if result.returncode != 0 and exit_code == 0:
            warning_msg = f"Command '{user_command_display}' exited with status {result.returncode}"
            console_stderr.print(f"[yellow][WARNING] {warning_msg}[/]")
            stats_data["Command Warning"] = warning_msg

    except ValueError:
        if exit_code == 0:
            exit_code = 1
    except Exception as e:
        if exit_code == 0:
            exit_code = 1
        error_detail = f"An unexpected error occurred: {e}"
        stats_data.setdefault("Error", error_detail)
        console_stderr.print(f"[bold red]{error_detail}[/]")

    finally:
        if not no_stats:
            table = Table(title="output_to_clipboard.py Statistics")
            table.add_column("Metric", style="cyan", overflow="fold")
            table.add_column("Value", overflow="fold")
            if not stats_data:
                stats_data["Status"] = "Operation incomplete due to early error."
            for key, value in stats_data.items():
                table.add_row(str(key), str(value))
            # Direct stats output to console_stderr
            console_stderr.print(table)

    return operation_successful, user_cancelled_operation, "Error" in stats_data, exit_code


if __name__ == "__main__":
    args = parser.parse_args()

    command_to_run_parts = None
    replay_n_value = args.replay_nth_command

    if args.command_and_args:
        if not (len(args.command_and_args) == 1 and args.command_and_args[0] == "--"):
            command_to_run_parts = args.command_and_args
            if replay_n_value is not None:
                console_stderr.print("[INFO] Both command and --replay-history specified. Executing provided command.")
                replay_n_value = None

    if not command_to_run_parts:
        if replay_n_value is None:
            replay_n_value = 1

    final_exit_code = 1
    try:
        _op_ok, _user_cancel, _has_err, func_exit_code = run_command_and_copy_main(
            command_to_run_parts,
            replay_n_value,
            args.no_stats,
            args.wrap,
            append=args.append,
            shell_choice=args.shell,
        )
        final_exit_code = func_exit_code

    except ValueError:
        final_exit_code = 1
    except Exception as e_main_unexpected:
        if not args.no_stats:
            console_stderr.print(f"[bold red][CRITICAL SCRIPT ERROR] Unhandled exception in __main__: {e_main_unexpected}[/]")
        final_exit_code = 1

    sys.exit(final_exit_code)
