"""Command-line interface for runmux."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runmux import __version__
from runmux.client import ClientError, interact_run, list_runs_live, view_run
from runmux.config import ConfigError, load_config, set_config_value
from runmux.constants import ATTACH_RESERVED_ROWS, DEFAULT_REFRESH_SECONDS
from runmux.history import (
    HistoryError,
    command_stats,
    commands_for_base,
    delete_saved_commands,
    filter_history_entries,
    history_entry_by_id,
    indexed_history_entries,
    list_saved_commands,
    mark_saved_command_run,
    most_common_history_entries,
    save_command,
    save_record_command,
    load_unique_commands,
    saved_bases,
)
from runmux.ipc import IpcError
from runmux.runner import (
    RunnerError,
    create_managed_run,
    duplicate_run,
    kill_run,
    normalize_program_args,
    pause_run,
    remove_finished_runs,
    remove_run,
    restart_run,
    resume_run,
    save_run_command,
)
from runmux.stats import show_stats
from runmux.store import AmbiguousRunIdError, RegistryError, RunNotFoundError, RunStore


class RunmuxArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that raises exceptions instead of exiting deep in tests."""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        raise SystemExit(f"error: {message}")


def build_parser() -> argparse.ArgumentParser:
    """Build the root CLI parser."""

    parser = RunmuxArgumentParser(
        prog="runmux",
        description="Run programs under a shared process manager with view/interact support.",
    )
    parser.add_argument("-V", "--version", action="version", version=f"runmux {__version__}")
    parser.add_argument(
        "-s",
        "--state-dir",
        type=Path,
        default=None,
        help="Override the runmux state directory for this invocation.",
    )
    parser.add_argument(
        "--separator",
        action="store_true",
        help="Draw a divider line below the top status bar.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Start a program under runmux supervision.")
    run_parser.add_argument(
        "-c",
        "-p",
        "--cwd",
        "--run-path",
        type=Path,
        default=None,
        help="Working directory for the managed program, independent of the caller's directory.",
    )
    run_parser.add_argument("-n", "--name", default=None, help="Optional friendly name.")
    run_parser.add_argument(
        "-a",
        "-w",
        "--attach",
        "--view",
        action="store_true",
        help="Immediately view output instead of interacting.",
    )
    run_parser.add_argument(
        "-I",
        "--interact",
        action="store_true",
        help="Immediately interact with the program after starting it.",
    )
    run_parser.add_argument(
        "-D",
        "--detach",
        action="store_true",
        help="Start the program and return to the shell.",
    )
    run_parser.add_argument(
        "-s",
        "--save-command",
        action="store_true",
        help="Save this command for later use.",
    )
    run_parser.add_argument(
        "-H",
        "--history",
        action="store_true",
        help="Run a command selected from runmux history.",
    )
    run_parser.add_argument(
        "-i",
        "--id",
        dest="history_id",
        type=int,
        default=None,
        help="Global newest-first history ID used with -H/--history.",
    )
    run_parser.add_argument(
        "-P",
        "--path",
        dest="history_path",
        action="store_true",
        help="Run a history command from its recorded working directory.",
    )
    run_parser.add_argument(
        "-V",
        "--verify",
        action="store_true",
        help="Show a history replay summary and require y/n confirmation before starting it.",
    )
    run_parser.add_argument(
        "-C",
        "--no-force-color",
        action="store_true",
        help="Do not set common environment variables that ask programs to emit ANSI color.",
    )
    run_parser.add_argument(
        "-r",
        "--rows",
        type=int,
        default=None,
        help="Initial terminal row count for PTY-backed programs.",
    )
    run_parser.add_argument(
        "-o",
        "--columns",
        type=int,
        default=None,
        help="Initial terminal column count for PTY-backed programs.",
    )
    run_parser.add_argument("program", nargs=argparse.REMAINDER, help="Program and arguments to run.")
    run_parser.set_defaults(func=handle_run)

    list_parser = subparsers.add_parser("list", help="Show runmux-managed programs.")
    list_parser.add_argument(
        "-1",
        "--once",
        action="store_true",
        help="Print one table and exit instead of showing a live in-place table.",
    )
    list_parser.add_argument(
        "-r",
        "--refresh",
        type=float,
        default=DEFAULT_REFRESH_SECONDS,
        help="Refresh interval in seconds for the live table.",
    )
    list_parser.add_argument(
        "-A",
        "--active-only",
        action="store_true",
        help="Only show pending, running, and paused runs.",
    )
    list_parser.add_argument(
        "-l",
        "--limit",
        type=int,
        default=None,
        help="Maximum number of runs to display.",
    )
    list_parser.add_argument("-j", "--json", action="store_true", help="Emit JSON and exit.")
    list_parser.set_defaults(func=handle_list)

    ls_parser = subparsers.add_parser("ls", help="Show active runmux-managed programs.")
    add_ls_filters(ls_parser)
    ls_parser.set_defaults(func=handle_ls)

    config_parser = subparsers.add_parser("config", help="Show or update persistent runmux settings.")
    config_group = config_parser.add_mutually_exclusive_group()
    config_group.add_argument("-g", "--get", metavar="KEY", help="Show one configuration value.")
    config_group.add_argument("-s", "--set", nargs=2, metavar=("KEY", "VALUE"), help="Persist one configuration value.")
    config_parser.add_argument("-j", "--json", action="store_true", help="Emit JSON.")
    config_parser.set_defaults(func=handle_config)

    view_parser = subparsers.add_parser("view", help="View a managed program's ANSI output.")
    view_parser.add_argument("-i", "--id", required=True, help="Run ID or unambiguous ID prefix.")
    view_parser.add_argument(
        "-F",
        "--no-follow",
        action="store_true",
        help="Print current output and exit instead of following new output.",
    )
    view_parser.add_argument(
        "-e",
        "--from-end",
        action="store_true",
        help="Start at the current end of the output log.",
    )
    view_parser.add_argument(
        "-t",
        "--tail-lines",
        type=int,
        default=None,
        help="Start by showing only the last N lines.",
    )
    view_parser.set_defaults(func=handle_view)

    interact_parser = subparsers.add_parser(
        "interact",
        help="Attach output and send keyboard input to a managed program.",
    )
    interact_parser.add_argument("-i", "--id", required=True, help="Run ID or unambiguous ID prefix.")
    interact_parser.add_argument(
        "-t",
        "--tail-lines",
        type=int,
        default=None,
        help="Start by showing only the last N lines before following live output.",
    )
    interact_parser.set_defaults(func=handle_interact)

    kill_parser = subparsers.add_parser("kill", help="Terminate a managed program.")
    kill_parser.add_argument("-i", "--id", required=True, help="Run ID or unambiguous ID prefix.")
    kill_parser.add_argument("-f", "--force", action="store_true", help="Force-kill instead of terminate.")
    kill_parser.set_defaults(func=handle_kill)

    restart_parser = subparsers.add_parser("restart", help="Restart a finished managed program.")
    restart_parser.add_argument("-i", "--id", required=True, help="Run ID or unambiguous ID prefix.")
    restart_parser.add_argument("-a", "--attach", action="store_true", help="Immediately view output.")
    restart_parser.add_argument("-I", "--interact", action="store_true", help="Immediately interact.")
    restart_parser.add_argument(
        "-C",
        "--no-force-color",
        action="store_true",
        help="Do not force color for the restarted run.",
    )
    restart_parser.set_defaults(func=handle_restart)

    duplicate_parser = subparsers.add_parser("duplicate", help="Start another copy of a managed program.")
    duplicate_parser.add_argument("-i", "--id", required=True, help="Run ID or unambiguous ID prefix.")
    duplicate_parser.add_argument("-a", "--attach", action="store_true", help="Immediately view output.")
    duplicate_parser.add_argument("-I", "--interact", action="store_true", help="Immediately interact.")
    duplicate_parser.add_argument(
        "-C",
        "--no-force-color",
        action="store_true",
        help="Do not force color for the duplicated run.",
    )
    duplicate_parser.set_defaults(func=handle_duplicate)

    pause_parser = subparsers.add_parser("pause", help="Pause a managed program where supported.")
    pause_parser.add_argument("-i", "--id", required=True, help="Run ID or unambiguous ID prefix.")
    pause_parser.set_defaults(func=handle_pause)

    resume_parser = subparsers.add_parser("resume", help="Resume a paused managed program where supported.")
    resume_parser.add_argument("-i", "--id", required=True, help="Run ID or unambiguous ID prefix.")
    resume_parser.set_defaults(func=handle_resume)

    remove_parser = subparsers.add_parser(
        "remove",
        help="Remove one terminal run, or remove all terminal runs when no ID is provided.",
    )
    add_remove_args(remove_parser)
    remove_parser.set_defaults(func=handle_remove)

    rm_parser = subparsers.add_parser(
        "rm",
        help="Alias for remove.",
    )
    add_remove_args(rm_parser)
    rm_parser.set_defaults(func=handle_remove)

    stats_parser = subparsers.add_parser(
        "stats",
        help="Show live CPU, memory, thread, and disk I/O stats for active runs.",
    )
    stats_parser.add_argument(
        "-1",
        "--once",
        action="store_true",
        help="Sample once and exit instead of showing a live in-place table.",
    )
    stats_parser.add_argument(
        "-r",
        "--refresh",
        type=float,
        default=DEFAULT_REFRESH_SECONDS,
        help="Sampling interval in seconds.",
    )
    stats_parser.add_argument("-j", "--json", action="store_true", help="Emit JSON and exit.")
    stats_parser.set_defaults(func=handle_stats)

    history_parser = subparsers.add_parser("history", help="Show runmux command history.")
    history_parser.add_argument(
        "-l",
        "--limit",
        type=int,
        default=None,
        help="Maximum history entries to show.",
    )
    history_parser.add_argument(
        "-I",
        "--interactive",
        action="store_true",
        help="Browse history with Up/Down and print the selected command with Enter.",
    )
    history_parser.add_argument(
        "-f",
        "--fzf",
        action="store_true",
        help="Browse the filtered history with fzf.",
    )
    history_parser.add_argument(
        "-b",
        "--starts-with",
        default=None,
        help="Only show commands that start with this text (case-insensitive).",
    )
    history_parser.add_argument(
        "-c",
        "--contains",
        default=None,
        help="Only show commands containing this text (case-insensitive).",
    )
    history_parser.add_argument(
        "-m",
        "--most-common",
        nargs="?",
        const=10,
        type=positive_int,
        default=None,
        metavar="COUNT",
        help="Show the most common commands (default: 10).",
    )
    history_parser.add_argument("-d", "--date", action="store_true", help="Include the run date/time.")
    history_parser.add_argument("-P", "--path", action="store_true", help="Include the recorded working directory.")
    history_parser.add_argument(
        "-S",
        "--status",
        action="store_true",
        help="Include status and exit code.",
    )
    history_parser.add_argument("-r", "--runtime", action="store_true", help="Include elapsed runtime.")
    history_parser.add_argument("-A", "--all-details", action="store_true", help="Include every cosmetic history detail.")
    history_parser.add_argument("-u", "--unique", action="store_true", help="Show unique-command ledger entries only.")
    history_parser.add_argument("-X", "--unique-paths", action="store_true", help="With --unique, show every recorded effective cwd.")
    history_parser.add_argument("-R", "--run-details", action="store_true", help="With --unique, show every recorded run time and runtime.")
    history_parser.add_argument(
        "-p",
        "--plain",
        action="store_true",
        help="Disable ANSI color in history output.",
    )
    history_parser.add_argument("-j", "--json", action="store_true", help="Emit JSON.")
    history_parser.set_defaults(func=handle_history)

    save_parser = subparsers.add_parser("save", help="Save a managed run or history command for reuse.")
    save_source = save_parser.add_mutually_exclusive_group(required=True)
    save_source.add_argument("-i", "--id", help="Managed run ID, including an active or paused run.")
    save_source.add_argument("-H", "--history", dest="history_id", type=int, metavar="HISTORY_ID", help="Global history ID to save.")
    save_parser.set_defaults(func=handle_save)

    load_parser = subparsers.add_parser("load", aliases=["cmd"], help="Browse and run saved commands.")
    load_parser.add_argument(
        "-T",
        "--stats",
        action="store_true",
        help="Show saved-command and command-base stats.",
    )
    load_parser.add_argument("-l", "--limit", type=int, default=None, help="Maximum saved commands to show.")
    load_parser.add_argument("-I", "--interactive", action="store_true", help="Browse saved commands interactively.")
    load_parser.add_argument("-f", "--fzf", action="store_true", help="Browse saved commands with fzf.")
    load_parser.add_argument("-b", "--starts-with", default=None, help="Only show commands starting with this text.")
    load_parser.add_argument("-c", "--contains", default=None, help="Only show commands containing this text.")
    load_parser.add_argument("-m", "--most-common", nargs="?", const=10, type=positive_int, default=None, metavar="COUNT")
    load_parser.add_argument("-d", "--date", action="store_true", help="Include saved date/time.")
    load_parser.add_argument("-P", "--path", action="store_true", help="Include the saved working directory.")
    load_parser.add_argument("-S", "--status", action="store_true", help="Include saved-command status.")
    load_parser.add_argument("-r", "--runtime", action="store_true", help="Include runtime when known.")
    load_parser.add_argument("-C", "--run-count", action="store_true", help="Include unique-command run count.")
    load_parser.add_argument("-A", "--all-details", action="store_true", help="Include every cosmetic saved-command detail.")
    load_parser.add_argument("-p", "--plain", action="store_true", help="Disable ANSI color.")
    load_parser.add_argument("-j", "--json", action="store_true", help="Emit JSON.")
    load_parser.add_argument("-B", "--before", default=None, metavar="DATE", help="For delete: saved before this ISO date/time.")
    load_parser.add_argument("-N", "--not-run-for", type=non_negative_int, default=None, metavar="DAYS", help="For delete: not run for at least DAYS.")
    load_parser.add_argument("-a", "--apply", action="store_true", help="For delete: carry out deletion; otherwise dry-run.")
    load_parser.add_argument("action", nargs="?", choices=["delete"], help="Optional saved-command action.")
    load_parser.set_defaults(func=handle_load)

    return parser


def add_list_filters(parser: argparse.ArgumentParser) -> None:
    """Add list filtering options shared by list and ls."""

    parser.add_argument(
        "-A",
        "--active-only",
        action="store_true",
        help="Only show pending, running, and paused runs.",
    )
    parser.add_argument(
        "-l",
        "--limit",
        type=int,
        default=None,
        help="Maximum number of runs to display.",
    )
    parser.add_argument("-j", "--json", action="store_true", help="Emit JSON and exit.")


def add_ls_filters(parser: argparse.ArgumentParser) -> None:
    """Add active-first display and interactive options for ``runmux ls``."""

    parser.add_argument("-T", "--terminal", "--all-runs", action="store_true", help="Also show terminal runs after active runs.")
    parser.add_argument("-I", "--interactive", action="store_true", help="Open the interactive run browser.")
    parser.add_argument(
        "-s",
        "--status",
        action="append",
        choices=["active", "paused", "finished", "killed", "failed", "lost", "pending", "running"],
        default=None,
        help="Filter by status; repeat to include multiple statuses.",
    )
    parser.add_argument("-l", "--limit", type=int, default=None, help="Maximum runs to display.")
    parser.add_argument("-d", "--date", action="store_true", help="Show run creation and completion timestamps.")
    parser.add_argument("-P", "--path", action="store_true", help="Show each run working directory.")
    parser.add_argument("-e", "--exit-code", action="store_true", help="Show each run exit code.")
    parser.add_argument("-A", "--all-details", action="store_true", help="Show every cosmetic per-run detail.")
    parser.add_argument("-j", "--json", action="store_true", help="Emit JSON and exit.")


def positive_int(value: str) -> int:
    """Parse a strictly positive CLI integer."""

    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def non_negative_int(value: str) -> int:
    """Parse a non-negative CLI integer."""

    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def add_remove_args(parser: argparse.ArgumentParser) -> None:
    """Add remove target arguments shared by remove and rm."""

    parser.add_argument("target", nargs="?", help="Run ID, numeric ID, or unambiguous ID prefix.")
    parser.add_argument(
        "-i",
        "--id",
        default=None,
        help="Run ID, numeric ID, or unambiguous ID prefix.",
    )


def get_store(args: argparse.Namespace) -> RunStore:
    """Create a store from parsed root args."""

    return RunStore(args.state_dir)


def handle_run(args: argparse.Namespace) -> int:
    """Handle ``runmux run``."""

    if bool(getattr(args, "history", False)):
        return handle_run_history(args)
    if getattr(args, "history_id", None) is not None or bool(getattr(args, "history_path", False)):
        raise HistoryError("-i/--id and -P/--path require -H/--history.")
    program_args = normalize_program_args(args.program)
    if program_args[0] in {"cmd", "load"}:
        return handle_run_saved_command(args, program_args[1:])

    store = get_store(args)
    has_separator = getattr(args, "separator", False) or os.environ.get("RUNMUX_SEPARATOR", "").lower() in ("1", "true", "yes", "on") or os.environ.get("RUNMUX_DIVIDER", "").lower() in ("1", "true", "yes", "on")
    reserve_rows = 0 if args.detach else (3 if has_separator else ATTACH_RESERVED_ROWS)
    started = create_managed_run(
        store,
        program_args=program_args,
        cwd=args.cwd,
        name=args.name,
        force_color=not args.no_force_color,
        rows=args.rows,
        columns=args.columns,
        reserve_rows=reserve_rows,
    )
    if args.save_command:
        saved = save_record_command(started.record)
        mark_saved_command_run(saved.command_line, cwd=saved.cwd)
        print_saved_command_confirmation(
            saved,
            ran_at=started.record.started_at or started.record.created_at,
            status=started.record.status,
            runtime_seconds=started.record.runtime_seconds,
        )
    print(f"Started {started.record.id}: {started.record.command_line}")
    if args.attach:
        return view_run(store, run_id=started.record.id, follow=True, from_end=False, tail_lines=None, separator=has_separator)
    if args.detach:
        return 0
    if args.interact or not args.detach:
        return interact_run(store, run_id=started.record.id, tail_lines=None, separator=has_separator)
    return 0


def handle_run_history(args: argparse.Namespace) -> int:
    """Launch one exact argv entry from global runmux history."""

    if args.history_id is None:
        raise HistoryError("History replay requires -i/--id ID.")
    if args.program:
        raise HistoryError("History replay cannot be combined with a positional program.")
    if args.history_path and args.cwd is not None:
        raise HistoryError("Use either -c/--cwd or -P/--path for history replay, not both.")
    entry = history_entry_by_id(args.history_id)
    return launch_history_entry(args, entry, use_original_path=args.history_path)


def launch_history_entry(
    args: argparse.Namespace,
    entry: dict[str, Any],
    *,
    use_original_path: bool,
    instance_count: int = 1,
    cwd_override: Path | None = None,
) -> int:
    """Launch a selected history entry through normal runmux supervision."""

    argv = entry.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
        raise HistoryError(f"History ID {entry.get('history_id')} has invalid argv metadata.")
    if instance_count <= 0:
        raise HistoryError("Instance count must be greater than zero.")
    cwd = cwd_override if cwd_override is not None else getattr(args, "cwd", None)
    if cwd_override is None and use_original_path:
        stored_cwd = Path(str(entry.get("cwd") or ""))
        if not stored_cwd.is_dir():
            raise HistoryError(f"Recorded working directory does not exist: {stored_cwd}")
        cwd = stored_cwd
    if bool(getattr(args, "verify", False)) and not confirm_history_replay(entry, cwd, instance_count):
        print("History replay cancelled.")
        return 0

    store = get_store(args)
    detach = bool(getattr(args, "detach", False))
    attach = bool(getattr(args, "attach", False))
    interact = bool(getattr(args, "interact", False))
    has_separator = getattr(args, "separator", False) or os.environ.get("RUNMUX_SEPARATOR", "").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    reserve_rows = 0 if detach else (3 if has_separator else ATTACH_RESERVED_ROWS)
    started_runs = []
    for _ in range(instance_count):
        started = create_managed_run(
            store,
            program_args=list(argv),
            cwd=cwd,
            name=getattr(args, "name", None),
            force_color=not bool(getattr(args, "no_force_color", False)),
            rows=getattr(args, "rows", None),
            columns=getattr(args, "columns", None),
            reserve_rows=reserve_rows,
        )
        started_runs.append(started)
        print(f"Started {started.record.id}: {started.record.command_line}")
    started = started_runs[-1]
    if bool(getattr(args, "save_command", False)):
        saved = save_record_command(started.record)
        mark_saved_command_run(saved.command_line, cwd=saved.cwd)
        print_saved_command_confirmation(
            saved,
            ran_at=started.record.started_at or started.record.created_at,
            status=started.record.status,
            runtime_seconds=started.record.runtime_seconds,
        )
    if attach:
        return view_run(
            store,
            run_id=started.record.id,
            follow=True,
            from_end=False,
            tail_lines=None,
            separator=has_separator,
        )
    if detach:
        return 0
    if interact or not detach:
        return interact_run(store, run_id=started.record.id, tail_lines=None, separator=has_separator)
    return 0


def launch_saved_history_entry(
    args: argparse.Namespace,
    entry: dict[str, Any],
    *,
    instance_count: int = 1,
    cwd_override: Path | None = None,
) -> int:
    """Launch a saved command with its saved execution context by default."""

    saved = entry.get("_saved_command")
    if saved is None:
        raise HistoryError("Saved command metadata is unavailable.")
    if instance_count <= 0:
        raise HistoryError("Instance count must be greater than zero.")
    cwd = cwd_override if cwd_override is not None else getattr(args, "cwd", None)
    if cwd is None:
        cwd = Path(saved.cwd)
    if not Path(cwd).is_dir():
        raise HistoryError(f"Saved working directory does not exist: {cwd}")
    store = get_store(args)
    detach = bool(getattr(args, "detach", False))
    attach = bool(getattr(args, "attach", False))
    interact = bool(getattr(args, "interact", False))
    has_separator = getattr(args, "separator", False) or os.environ.get("RUNMUX_SEPARATOR", "").lower() in (
        "1", "true", "yes", "on"
    )
    reserve_rows = 0 if detach else (3 if has_separator else ATTACH_RESERVED_ROWS)
    rows = getattr(args, "rows", None)
    if rows is None and saved.rows is not None:
        rows = saved.rows + reserve_rows
    name = getattr(args, "name", None) if getattr(args, "name", None) is not None else saved.name
    force_color = False if bool(getattr(args, "no_force_color", False)) else saved.force_color
    started_runs = []
    for _ in range(instance_count):
        started = create_managed_run(
            store,
            program_args=list(saved.argv),
            cwd=Path(cwd),
            name=name,
            force_color=force_color,
            rows=rows,
            columns=getattr(args, "columns", None) if getattr(args, "columns", None) is not None else saved.columns,
            reserve_rows=reserve_rows,
        )
        started_runs.append(started)
        print(f"Started {started.record.id}: {started.record.command_line}")
    started = started_runs[-1]
    mark_saved_command_run(saved.command_line, cwd=saved.cwd)
    if attach:
        return view_run(store, run_id=started.record.id, follow=True, from_end=False, tail_lines=None, separator=has_separator)
    if detach:
        return 0
    if interact or not detach:
        return interact_run(store, run_id=started.record.id, tail_lines=None, separator=has_separator)
    return 0


def launch_browser_entry(
    args: argparse.Namespace,
    entry: dict[str, Any],
    *,
    instance_count: int,
    cwd_override: Path,
) -> int:
    """Launch either a history entry or a saved-command browser entry."""

    if "_saved_command" in entry:
        return launch_saved_history_entry(args, entry, instance_count=instance_count, cwd_override=cwd_override)
    return launch_history_entry(
        args,
        entry,
        use_original_path=False,
        instance_count=instance_count,
        cwd_override=cwd_override,
    )


def confirm_history_replay(entry: dict[str, Any], cwd: Path | None, instance_count: int) -> bool:
    """Show a full replay summary and require an affirmative answer."""

    launch_path = cwd if cwd is not None else Path.cwd()
    print("History replay verification")
    print(f"ID: {entry.get('history_id')}")
    print(f"Command: {entry.get('command_line') or '--'}")
    print(f"Path: {launch_path}")
    print(f"Instances: {instance_count}")
    while True:
        try:
            answer = input("Run this command? [y/N]: ").strip().casefold()
        except (EOFError, KeyboardInterrupt):
            return False
        if answer in {"y", "yes"}:
            return True
        if answer in {"", "n", "no"}:
            return False
        print("Please enter y or n.")


def prompt_history_run(entry: dict[str, Any]) -> tuple[int, Path] | None:
    """Prompt for history instance count and launch directory."""

    original = Path(str(entry.get("cwd") or ""))
    print("\x1b[?25h\x1b[H\x1b[2J", end="")
    print("┌─ Run history command ─────────────────────────────────────────────")
    print(f"│ ID: {entry.get('history_id')}")
    print(f"│ Command: {entry.get('command_line') or ''}")
    print(f"│ Original path: {original}")
    print("└────────────────────────────────────────────────────────────────────")
    try:
        count_text = input("Instances [1]: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if count_text.casefold() in {"q", "quit", "cancel"}:
        return None
    try:
        count = int(count_text or "1")
    except ValueError:
        print("Instance count must be a positive integer.")
        return None
    if count <= 0:
        print("Instance count must be greater than zero.")
        return None
    try:
        location = input("Location [original] (o=original, c=current, m=manual): ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    normalized = location.casefold()
    if normalized in {"", "o", "original"}:
        selected_path = original
    elif normalized in {"c", "current"}:
        selected_path = Path.cwd()
    elif normalized in {"m", "manual"}:
        try:
            manual = input("Path: ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if not manual:
            return None
        selected_path = Path(manual).expanduser()
    elif normalized in {"q", "quit", "cancel"}:
        return None
    else:
        selected_path = Path(location).expanduser()
    selected_path = selected_path.resolve()
    if not selected_path.is_dir():
        print(f"Directory does not exist: {selected_path}")
        return None
    return count, selected_path


def handle_run_saved_command(args: argparse.Namespace, selector_args: list[str]) -> int:
    """Handle ``runmux run load -i ID`` saved-command replay."""

    selector = build_run_cmd_parser().parse_args(selector_args)
    if selector.saved_id is None:
        raise HistoryError("Saved-command replay requires -i/--id ID. Browse with 'runmux load -I'.")
    selected = next((command for command in list_saved_commands() if command.id == selector.saved_id), None)
    if selected is None:
        raise HistoryError(f"Saved command ID {selector.saved_id} does not exist.")
    store = get_store(args)
    has_separator = getattr(args, "separator", False) or os.environ.get("RUNMUX_SEPARATOR", "").lower() in ("1", "true", "yes", "on") or os.environ.get("RUNMUX_DIVIDER", "").lower() in ("1", "true", "yes", "on")
    reserve_rows = 0 if selector.detach else (3 if has_separator else ATTACH_RESERVED_ROWS)
    started = create_managed_run(
        store,
        program_args=selected.argv,
        cwd=args.cwd if args.cwd is not None else Path(selected.cwd),
        name=args.name if args.name is not None else selected.name,
        force_color=False if args.no_force_color else selected.force_color,
        rows=(
            args.rows
            if args.rows is not None
            else (selected.rows + reserve_rows if selected.rows is not None else None)
        ),
        columns=args.columns if args.columns is not None else selected.columns,
        reserve_rows=reserve_rows,
    )
    mark_saved_command_run(started.record.command_line, cwd=started.record.cwd)
    print(f"Started {started.record.id}: {started.record.command_line}")
    if selector.view:
        return view_run(
            store,
            run_id=started.record.id,
            follow=True,
            from_end=False,
            tail_lines=None,
            separator=has_separator,
        )
    if selector.detach:
        return 0
    if selector.interact or not selector.detach:
        return interact_run(store, run_id=started.record.id, tail_lines=None, separator=has_separator)
    return 0


def build_run_cmd_parser() -> argparse.ArgumentParser:
    """Build the parser for ``runmux run load`` selector options."""

    parser = argparse.ArgumentParser(prog="runmux run load")
    parser.add_argument("-i", "--id", dest="saved_id", type=int, default=None, help="Saved command ID.")
    parser.add_argument("-I", "--interact", action="store_true", help="Interact after launch.")
    parser.add_argument("-D", "--detach", action="store_true", help="Return after launch.")
    parser.add_argument("-w", "--view", action="store_true", help="View after launch.")
    return parser


def handle_list(args: argparse.Namespace) -> int:
    """Handle ``runmux list``."""

    return list_runs_live(
        get_store(args),
        once=args.once,
        include_all=not args.active_only,
        limit=args.limit,
        refresh_seconds=args.refresh,
        output_json=args.json,
        statuses=None,
        terminal_limit=load_config()["terminal_record_limit"],
        show_date=False,
        show_path=False,
        show_exit_code=False,
    )


def handle_ls(args: argparse.Namespace) -> int:
    """Handle ``runmux ls``."""

    return list_runs_live(
        get_store(args),
        once=not args.interactive,
        include_all=args.terminal or bool(args.status),
        limit=args.limit,
        refresh_seconds=DEFAULT_REFRESH_SECONDS,
        output_json=args.json,
        statuses=args.status,
        terminal_limit=load_config()["terminal_record_limit"],
        show_date=args.date or args.all_details,
        show_path=args.path or args.all_details,
        show_exit_code=args.exit_code or args.all_details,
    )


def handle_config(args: argparse.Namespace) -> int:
    """Handle persistent runmux configuration display and updates."""

    if args.set is not None:
        config = set_config_value(args.set[0], args.set[1])
    else:
        config = load_config()
    if args.get is not None:
        if args.get not in config:
            raise ConfigError(f"Unknown configuration key '{args.get}'.")
        config = {args.get: config[args.get]}
    if args.json:
        print(json.dumps(config, indent=2, sort_keys=True))
    else:
        for key, value in sorted(config.items()):
            print(f"{key}={value}")
    return 0


def handle_view(args: argparse.Namespace) -> int:
    """Handle ``runmux view``."""

    return view_run(
        get_store(args),
        run_id=args.id,
        follow=not args.no_follow,
        from_end=args.from_end,
        tail_lines=args.tail_lines,
        separator=getattr(args, "separator", False),
    )


def handle_interact(args: argparse.Namespace) -> int:
    """Handle ``runmux interact``."""

    return interact_run(get_store(args), run_id=args.id, tail_lines=args.tail_lines, separator=getattr(args, "separator", False))


def handle_kill(args: argparse.Namespace) -> int:
    """Handle ``runmux kill``."""

    record = kill_run(get_store(args), run_id=args.id, force=args.force)
    print(f"Kill requested for {record.id}")
    return 0


def handle_restart(args: argparse.Namespace) -> int:
    """Handle ``runmux restart``."""

    store = get_store(args)
    started = restart_run(store, run_id=args.id, force_color=not args.no_force_color)
    print(f"Restarted {args.id} as {started.record.id}: {started.record.command_line}")
    return attach_after_clone(args, store, started.record.id)


def handle_duplicate(args: argparse.Namespace) -> int:
    """Handle ``runmux duplicate``."""

    store = get_store(args)
    started = duplicate_run(store, run_id=args.id, force_color=not args.no_force_color)
    print(f"Duplicated {args.id} as {started.record.id}: {started.record.command_line}")
    return attach_after_clone(args, store, started.record.id)


def attach_after_clone(args: argparse.Namespace, store: RunStore, run_id: str) -> int:
    """Attach after restart/duplicate when requested."""

    has_separator = getattr(args, "separator", False) or os.environ.get("RUNMUX_SEPARATOR", "").lower() in ("1", "true", "yes", "on") or os.environ.get("RUNMUX_DIVIDER", "").lower() in ("1", "true", "yes", "on")
    if args.interact:
        return interact_run(store, run_id=run_id, tail_lines=None, separator=has_separator)
    if args.attach:
        return view_run(store, run_id=run_id, follow=True, from_end=False, tail_lines=None, separator=has_separator)
    return 0


def handle_pause(args: argparse.Namespace) -> int:
    """Handle ``runmux pause``."""

    record = pause_run(get_store(args), run_id=args.id)
    print(f"Paused {record.id}")
    return 0


def handle_resume(args: argparse.Namespace) -> int:
    """Handle ``runmux resume``."""

    record = resume_run(get_store(args), run_id=args.id)
    print(f"Resumed {record.id}")
    return 0


def handle_remove(args: argparse.Namespace) -> int:
    """Handle ``runmux remove``."""

    target = args.id or args.target
    if target is None:
        raise RegistryError("remove requires -i/--id or a positional run ID. Terminal retention is automatic.")
    store = get_store(args)
    record = remove_run(store, run_id=target)
    print(f"Removed {record.numeric_id}: {record.command_line}")
    return 0


def handle_remove_finished(args: argparse.Namespace) -> int:
    """Handle ``runmux remove-finished``."""

    records = remove_finished_runs(get_store(args), clean_only=args.clean_only)
    print(f"Removed {len(records)} run(s).")
    return 0


def handle_stats(args: argparse.Namespace) -> int:
    """Handle ``runmux stats``."""

    return show_stats(
        get_store(args),
        once=args.once,
        refresh_seconds=args.refresh,
        output_json=args.json,
    )


def handle_history(args: argparse.Namespace) -> int:
    """Handle ``runmux history``."""

    if args.all_details:
        args.date = args.path = args.status = args.runtime = args.unique_paths = args.run_details = True
    if args.interactive and args.fzf:
        raise HistoryError("Use either -I/--interactive or -f/--fzf, not both.")
    all_entries = unique_command_entries() if args.unique else indexed_history_entries()
    entries = filter_history_entries(
        all_entries,
        starts_with=args.starts_with,
        contains=args.contains,
    )
    if args.most_common is not None:
        entries = most_common_history_entries(entries, args.most_common)
    elif args.limit is not None:
        entries = entries[: args.limit]
    if args.json:
        print(json.dumps(entries, indent=2))
        return 0
    if args.interactive:
        return browse_history(all_entries, args)
    if args.fzf:
        return browse_history_fzf(entries, args)
    color = sys.stdout.isatty() and not args.plain
    # Recent-history text is printed oldest-to-newest so the terminal ends on
    # the most recent command. Frequency views retain their ranked ordering.
    display_entries = entries if args.most_common is not None else reversed(entries)
    for entry in display_entries:
        print(
            format_unique_history_entry(entry, args, color=color)
            if args.unique
            else format_history_entry(
                int(entry["history_id"]),
                entry,
                color=color,
                show_date=args.date,
                show_path=args.path,
                show_status=args.status,
                show_runtime=args.runtime,
            )
        )
    return 0


def unique_command_entries() -> list[dict[str, Any]]:
    """Adapt unique-command ledger rows for history filtering and display."""

    commands = sorted(load_unique_commands().get("commands", []), key=lambda item: str(item.get("last_run_at") or ""), reverse=True)
    entries = []
    for index, item in enumerate(commands):
        runs = list(item.get("runs", []))
        last = runs[-1] if runs else {}
        paths = list(item.get("paths", []))
        entries.append(
            {
                "history_id": index,
                "command_line": item.get("command_line") or "",
                "argv": item.get("argv") or [],
                "cwd": paths[-1] if paths else "--",
                "status": last.get("status") or "--",
                "exit_code": None,
                "runtime_seconds": last.get("runtime_seconds"),
                "started_at": item.get("last_run_at") or "--",
                "occurrence_count": item.get("run_count", 0),
                "unique_paths": paths,
                "unique_runs": runs,
            }
        )
    return entries


def format_unique_history_entry(entry: dict[str, Any], args: argparse.Namespace, *, color: bool) -> str:
    """Format one ledger command with optional complete path/run detail lists."""

    rendered = format_history_entry(
        int(entry["history_id"]),
        entry,
        color=color,
        show_date=args.date,
        show_path=args.path,
        show_status=args.status,
        show_runtime=args.runtime,
    )
    lines = [rendered]
    if args.unique_paths:
        lines.extend(colorize(str(path), "35", enabled=color) for path in entry.get("unique_paths", []))
    if args.run_details:
        for run in entry.get("unique_runs", []):
            status = str(run.get("status") or "--")
            lines.append(
                colorize(
                    f"date={run.get('started_at') or '--'}  runtime={format_optional_duration(run.get('runtime_seconds'))}  status={status}",
                    history_status_color({"status": status}),
                    enabled=color,
                )
            )
    return "\n".join(lines)


def format_history_entry(
    index: int,
    entry: dict[str, Any],
    *,
    color: bool,
    show_date: bool = False,
    show_path: bool = False,
    show_status: bool = False,
    show_runtime: bool = False,
) -> str:
    """Format one history entry with opt-in metadata."""

    command = str(entry.get("command_line") or "")
    command_text = colorize(command, "36", enabled=color)
    id_text = colorize(f"({index}).", "31", enabled=color)
    command_parts = [id_text, command_text]
    occurrence_count = entry.get("occurrence_count")
    if isinstance(occurrence_count, int):
        command_parts.append(f"count={occurrence_count}")
    lines = ["  ".join(command_parts)]
    if show_path:
        lines.append(colorize(str(entry.get("cwd") or "--"), "35", enabled=color))
    status_parts = []
    if show_status:
        status_parts.append(f"status={entry.get('status') or '--'}")
        status_parts.append(f"exit={entry.get('exit_code') if entry.get('exit_code') is not None else '--'}")
    if show_runtime:
        status_parts.append(f"runtime={format_optional_duration(entry.get('runtime_seconds'))}")
    if status_parts:
        lines.append(colorize("  ".join(status_parts), history_status_color(entry), enabled=color))
    if show_date:
        lines.append(
            colorize(
                f"date={entry.get('started_at') or '--'}",
                history_status_color(entry),
                enabled=color,
            )
        )
    return "\n".join(lines)


def history_status_color(entry: dict[str, Any]) -> str:
    """Return an ANSI color code appropriate for one history status."""

    status = str(entry.get("status") or "").casefold()
    if status == "finished":
        return "32"
    if status in {"failed", "lost"}:
        return "31"
    if status in {"killed", "pending"}:
        return "33"
    if status == "paused":
        return "35"
    if status == "running":
        return "36"
    return "90"


def colorize(value: str, color_code: str, *, enabled: bool) -> str:
    """Wrap text in ANSI color when enabled."""

    if not enabled:
        return value
    return f"\x1b[{color_code}m{value}\x1b[0m"


def browse_history(entries: list[dict[str, Any]], args: argparse.Namespace) -> int:
    """Browse history with run/save/search actions and persistent hotkey help."""

    if not entries:
        print("No runmux history.")
        return 0
    prefix_filter = args.starts_with
    contains_filter = args.contains
    visible_entries = apply_history_browser_filters(entries, args, prefix_filter, contains_filter)
    if not visible_entries:
        print("No runmux history matched the requested filters.")
        return 0
    selected = 0
    message = ""
    detail_mode = 3 if args.path and (args.status or args.runtime or args.date) else 0
    if detail_mode == 0 and args.path:
        detail_mode = 1
    elif detail_mode == 0 and (args.status or args.runtime or args.date):
        detail_mode = 2
    expanded = False
    action: tuple[dict[str, Any], int, Path] | None = None
    print("\x1b[?25l", end="")
    try:
        while True:
            entry = visible_entries[selected]
            screen = "\x1b[H\x1b[2J" + render_history_browser(
                visible_entries,
                selected,
                message=message,
                detail_mode=detail_mode,
                expanded=expanded,
                starts_with=prefix_filter,
                contains=contains_filter,
            )
            sys.stdout.write(screen)
            sys.stdout.flush()
            key = read_history_key()
            message = ""
            if key in {"UP", "k", "K"}:
                selected = max(0, selected - 1)
            elif key in {"DOWN", "j", "J"}:
                selected = min(len(visible_entries) - 1, selected + 1)
            elif key == "PAGE_UP":
                selected = max(0, selected - history_browser_page_size())
            elif key == "PAGE_DOWN":
                selected = min(len(visible_entries) - 1, selected + history_browser_page_size())
            elif key in {"r", "R"}:
                choice = prompt_history_run(entry)
                print("\x1b[?25l", end="")
                if choice is not None:
                    action = (entry, choice[0], choice[1])
                    break
                message = "Run cancelled."
            elif key in {"ENTER", "\r", "\n"}:
                choice = inspect_history_entry(entry)
                print("\x1b[?25l", end="")
                if choice is not None:
                    action = (entry, choice[0], choice[1])
                    break
                message = "Inspection closed."
            elif key in {"p", "P"}:
                print("\x1b[?25h", end="")
                print(render_history_inspector(entry, include_footer=False), end="")
                return 0
            elif key in {"s", "S"}:
                if "_saved_command" in entry:
                    message = "This command is already saved."
                else:
                    saved = save_command(
                        argv=list(entry.get("argv") or []),
                        command_line=str(entry.get("command_line") or ""),
                        cwd=str(entry.get("cwd") or "."),
                    )
                    message = f"Saved command {saved.id}."
            elif key in {"d", "D"}:
                if "_saved_command" not in entry:
                    message = "Only saved commands can be deleted from this browser."
                    continue
                print("\x1b[?25h", end="")
                if confirm_saved_command_delete(entry):
                    removed = delete_saved_commands({int(entry["history_id"])})
                    print(f"Deleted {len(removed)} saved command(s); history and unique-command statistics were preserved.")
                    return 0
                print("\x1b[?25l", end="")
                message = "Delete cancelled."
            elif key in {"/", "b", "B"}:
                mode = "contains" if key == "/" else "starts with"
                current = contains_filter if mode == "contains" else prefix_filter
                accepted, query = prompt_history_search(mode, current)
                if not accepted:
                    continue
                proposed_prefix = query if mode == "starts with" else prefix_filter
                proposed_contains = query if mode == "contains" else contains_filter
                proposed_entries = apply_history_browser_filters(
                    entries,
                    args,
                    proposed_prefix,
                    proposed_contains,
                )
                if not proposed_entries:
                    message = f"No commands matched {query!r}."
                else:
                    prefix_filter = proposed_prefix
                    contains_filter = proposed_contains
                    visible_entries = proposed_entries
                    selected = 0
                    message = f"Filters updated: {len(visible_entries)} command(s)."
            elif key in {"c", "C"}:
                prefix_filter = None
                contains_filter = None
                visible_entries = apply_history_browser_filters(entries, args, None, None)
                selected = 0
                message = "Filters cleared."
            elif key in {"v", "V"}:
                detail_mode = (detail_mode + 1) % 4
                message = f"Detail mode: {history_detail_mode_name(detail_mode)}."
            elif key in {"w", "W", "x", "X"}:
                expanded = not expanded
                message = "Full content enabled." if expanded else "Compact rows enabled."
            elif key in {"ESC", "q", "Q", "\x03"}:
                return 0
    finally:
        print("\x1b[?25h", end="")
        sys.stdout.flush()
    if action:
        return launch_browser_entry(args, action[0], instance_count=action[1], cwd_override=action[2])
    return 0


def apply_history_browser_filters(
    entries: list[dict[str, Any]],
    args: argparse.Namespace,
    starts_with: str | None,
    contains: str | None,
) -> list[dict[str, Any]]:
    """Apply interactive filters without changing global history IDs."""

    result = filter_history_entries(entries, starts_with=starts_with, contains=contains)
    if args.most_common is not None:
        return most_common_history_entries(result, args.most_common)
    if args.limit is not None:
        return result[: args.limit]
    return result


def render_history_browser(
    entries: list[dict[str, Any]],
    selected: int,
    *,
    message: str = "",
    detail_mode: int = 0,
    expanded: bool = False,
    starts_with: str | None = None,
    contains: str | None = None,
) -> str:
    """Render the interactive history browser."""

    try:
        columns, terminal_rows = os.get_terminal_size()
    except OSError:
        columns, terminal_rows = 100, 24
    message_lines = wrap_history_browser_text(message, columns) or [""]
    filter_lines = wrap_history_browser_text(
        f"prefix={starts_with or '--'} contains={contains or '--'}",
        columns,
    )
    help_lines = wrap_history_browser_text(
        "↑/↓ j/k | PgUp/PgDn page | r run | Enter inspect | p print | s save | d delete | b prefix | / contains | c clear | v details | w/x wrap | q",
        columns,
    )
    footer_lines = message_lines + filter_lines + help_lines
    content_rows = max(1, terminal_rows - len(footer_lines))
    page_start = max(0, selected - max(1, content_rows // 3))
    lines = [f"runmux history  {selected + 1}/{len(entries)}"]
    for absolute_index in range(page_start, len(entries)):
        block = render_history_browser_entry(
            entries[absolute_index],
            selected=absolute_index == selected,
            columns=columns,
            detail_mode=detail_mode,
            expanded=expanded,
        )
        if len(lines) + len(block) > content_rows:
            break
        lines.extend(block)
    while len(lines) < content_rows:
        lines.append("")
    lines.extend(footer_lines)
    # Raw ANSI rendering on Windows needs CRLF. Bare LF advances a row but can
    # leave the cursor in its old column, causing metadata to appear appended
    # to a clipped command line.
    return "\r\n".join(lines) + "\r\n"


def wrap_history_browser_text(value: str, columns: int) -> list[str]:
    """Wrap browser chrome so narrow terminals retain every available hotkey."""

    return textwrap.wrap(
        value,
        width=max(1, columns),
        break_long_words=True,
        break_on_hyphens=False,
    )


def history_browser_page_size() -> int:
    """Return a conservative visible-row count for Page Up/Page Down."""

    return max(1, shutil.get_terminal_size(fallback=(100, 24)).lines - 6)


def render_history_browser_entry(
    entry: dict[str, Any],
    *,
    selected: bool,
    columns: int,
    detail_mode: int,
    expanded: bool,
) -> list[str]:
    """Render one compact or expanded interactive history entry."""

    marker = "> " if selected else "  "
    prefix = f"{marker}({int(entry.get('history_id', -1))}).  "
    command = str(entry.get("command_line") or "")
    command_width = max(1, columns - len(prefix))
    command_lines = textwrap.wrap(command, width=command_width, break_long_words=expanded, break_on_hyphens=False) or [""]
    if not expanded:
        command_lines = [command[:command_width]]
    first = f"{prefix}{command_lines[0]}"[:columns]
    if selected:
        first = f"\x1b[7m{first}\x1b[0m"
    lines = [first]
    if expanded:
        lines.extend(f"{' ' * len(prefix)}{line}"[:columns] for line in command_lines[1:])
    if detail_mode in {1, 3}:
        path = str(entry.get("cwd") or "--")
        path_lines = (
            textwrap.wrap(path, width=max(1, columns), break_long_words=True, break_on_hyphens=False)
            if expanded
            else [path[:columns]]
        )
        lines.extend(colorize(line, "35", enabled=True) for line in path_lines)
    if detail_mode in {2, 3}:
        status = entry.get("status") or "--"
        exit_code = entry.get("exit_code") if entry.get("exit_code") is not None else "--"
        runtime = format_optional_duration(entry.get("runtime_seconds"))
        metadata = f"status={status}  exit={exit_code}  runtime={runtime}"
        metadata_lines = (
            textwrap.wrap(metadata, width=max(1, columns), break_long_words=True, break_on_hyphens=False)
            if expanded
            else [metadata[:columns]]
        )
        color = history_status_color(entry)
        lines.extend(colorize(line, color, enabled=True) for line in metadata_lines)
        date = f"date={entry.get('started_at') or '--'}"
        date_lines = (
            textwrap.wrap(date, width=max(1, columns), break_long_words=True, break_on_hyphens=False)
            if expanded
            else [date[:columns]]
        )
        lines.extend(colorize(line, color, enabled=True) for line in date_lines)
    return lines


def history_detail_mode_name(detail_mode: int) -> str:
    """Return a display label for an interactive metadata mode."""

    return {0: "commands", 1: "paths", 2: "status/date/runtime", 3: "all"}.get(detail_mode, "commands")


def inspect_history_entry(entry: dict[str, Any]) -> tuple[int, Path] | None:
    """Show a full history entry and optionally open its run dialog."""

    while True:
        sys.stdout.write("\x1b[H\x1b[2J" + render_history_inspector(entry))
        sys.stdout.flush()
        key = read_history_key()
        if key in {"ESC", "q", "Q", "\x03"}:
            return None
        if key in {"r", "R"}:
            choice = prompt_history_run(entry)
            if choice is not None:
                return choice


def render_history_inspector(entry: dict[str, Any], *, include_footer: bool = True) -> str:
    """Render one complete history entry for the interactive inspector."""

    try:
        columns, _ = os.get_terminal_size()
    except OSError:
        columns = 100
    raw_argv = entry.get("argv")
    argv_text = json.dumps(raw_argv) if isinstance(raw_argv, list) else "--"
    fields: list[tuple[str, object, str]] = [
        ("History ID", entry.get("history_id"), "31"),
        ("Command", entry.get("command_line"), "36"),
        ("Working path", entry.get("cwd"), "35"),
        ("argv", argv_text, "36"),
        ("Status", entry.get("status"), history_status_color(entry)),
        ("Exit code", entry.get("exit_code"), history_status_color(entry)),
        ("Runtime", format_optional_duration(entry.get("runtime_seconds")), history_status_color(entry)),
        ("Started", entry.get("started_at"), history_status_color(entry)),
        ("Ended", entry.get("ended_at"), history_status_color(entry)),
        ("Run ID", entry.get("run_id"), "33"),
        ("Run numeric ID", entry.get("numeric_id"), "33"),
        ("Base", entry.get("base"), "90"),
        ("Saved name", entry.get("name"), "90"),
        ("Terminal rows", entry.get("rows"), "90"),
        ("Terminal columns", entry.get("columns"), "90"),
        ("Forced color", entry.get("force_color"), "90"),
    ]
    lines = [colorize("runmux history inspector", "1;37", enabled=True)]
    for label, value, color_code in fields:
        rendered = f"{label}: {value if value not in (None, '') else '--'}"
        lines.extend(colorize(line, color_code, enabled=True) for line in wrap_history_browser_text(rendered, columns))
    if include_footer:
        lines.extend(colorize(line, "1;33", enabled=True) for line in wrap_history_browser_text("r run | Esc/q back", columns))
    return "\r\n".join(lines) + "\r\n"


def prompt_history_search(mode: str, current: str | None) -> tuple[bool, str | None]:
    """Prompt for an interactive history search query."""

    print("\x1b[?25h", end="")
    try:
        value = input(f"{mode} [{current or '--'}] (empty clears)> ").strip()
    except (EOFError, KeyboardInterrupt):
        return False, current
    finally:
        print("\x1b[?25l", end="")
    return True, value or None


def confirm_saved_command_delete(entry: dict[str, Any]) -> bool:
    """Require explicit confirmation before deleting a saved command."""

    print("Delete saved command?")
    print(str(entry.get("command_line") or "--"))
    print(str(entry.get("cwd") or "--"))
    try:
        answer = input("Delete? [y/N]: ").strip().casefold()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in {"y", "yes"}


def browse_history_fzf(entries: list[dict[str, Any]], args: argparse.Namespace) -> int:
    """Select a history entry with fzf while retaining its global ID."""

    if not entries:
        print("No runmux history.")
        return 0
    executable = shutil.which("fzf")
    if executable is None:
        raise HistoryError("fzf mode requires 'fzf' on PATH.")
    rows = "\n".join(f"{int(entry['history_id'])}\t{entry.get('command_line') or ''}" for entry in entries)
    completed = subprocess.run(
        [executable, "--delimiter=\t", "--with-nth=1,2", "--expect=enter,r,s", "--prompt=runmux history> "],
        input=rows,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode not in {0, 1, 130}:
        raise HistoryError(f"fzf failed with exit code {completed.returncode}: {completed.stderr.strip()}")
    output_lines = completed.stdout.splitlines()
    if not output_lines:
        return 0
    key = output_lines[0]
    selected_line = output_lines[-1]
    try:
        history_id = int(selected_line.split("\t", 1)[0])
    except (ValueError, IndexError) as error:
        raise HistoryError("fzf returned an invalid history selection.") from error
    entry = next((item for item in entries if int(item["history_id"]) == history_id), None)
    if entry is None:
        raise HistoryError(f"fzf selected unavailable history ID {history_id}.")
    if key == "r":
        if "_saved_command" in entry:
            return launch_saved_history_entry(args, entry)
        return launch_history_entry(args, entry, use_original_path=True)
    if key == "s":
        saved = save_command(
            argv=list(entry.get("argv") or []),
            command_line=str(entry.get("command_line") or ""),
            cwd=str(entry.get("cwd") or "."),
        )
        print(f"Saved command {saved.id}: {saved.command_line}")
        return 0
    print(str(entry.get("command_line") or ""))
    return 0


def read_history_key() -> str:
    """Read one key for the history browser."""

    if sys.platform == "win32":
        import msvcrt

        key = msvcrt.getwch()
        if key in {"\x00", "\xe0"}:
            code = msvcrt.getwch()
            if code == "H":
                return "UP"
            if code == "P":
                return "DOWN"
            if code == "I":
                return "PAGE_UP"
            if code == "Q":
                return "PAGE_DOWN"
            return code
        if key == "\r":
            return "ENTER"
        if key == "\x1b":
            return "ESC"
        return key
    key = sys.stdin.read(1)
    if key == "\x1b":
        tail = sys.stdin.read(2)
        if tail == "[A":
            return "UP"
        if tail == "[B":
            return "DOWN"
        if tail in {"[5", "[6"}:
            sys.stdin.read(1)
            return "PAGE_UP" if tail == "[5" else "PAGE_DOWN"
        return "ESC"
    if key in {"\r", "\n"}:
        return "ENTER"
    return key


def handle_save(args: argparse.Namespace) -> int:
    """Handle ``runmux save``."""

    if args.history_id is not None:
        entry = history_entry_by_id(args.history_id)
        saved = save_command(
            argv=list(entry.get("argv") or []),
            command_line=str(entry.get("command_line") or ""),
            cwd=str(entry.get("cwd") or "."),
        )
        print_saved_command_confirmation(
            saved,
            ran_at=str(entry.get("started_at") or "--"),
            status=str(entry.get("status") or "--"),
            runtime_seconds=entry.get("runtime_seconds"),
            prefix=f"Saved history {entry['history_id']} as command {saved.id}",
        )
        return 0
    record = save_run_command(get_store(args), run_id=args.id)
    saved = save_record_command(record)
    print_saved_command_confirmation(
        saved,
        ran_at=record.started_at or record.created_at,
        status=record.status,
        runtime_seconds=record.runtime_seconds,
        prefix=f"Saved run {record.numeric_id} as command {saved.id}",
    )
    return 0


def print_saved_command_confirmation(
    saved: Any,
    *,
    ran_at: str,
    status: str,
    runtime_seconds: object,
    prefix: str | None = None,
) -> None:
    """Print a complete, copyable saved-command confirmation."""

    color = sys.stdout.isatty()
    if prefix:
        print(colorize(prefix, "1;37", enabled=color))
    print(colorize(saved.command_line, "36", enabled=color))
    print(colorize(f"date={ran_at or '--'}", history_status_color({"status": status}), enabled=color))
    print(
        colorize(
            f"status={status or '--'}  runtime={format_optional_duration(runtime_seconds)}",
            history_status_color({"status": status}),
            enabled=color,
        )
    )
    print(colorize(saved.cwd, "35", enabled=color))


def handle_load(args: argparse.Namespace) -> int:
    """Handle non-interactive and interactive saved-command browsing."""

    if args.all_details:
        args.date = args.path = args.status = args.runtime = args.run_count = True
    if args.stats:
        return print_command_stats(output_json=args.json)
    if args.action == "delete":
        return handle_load_delete(args)
    if args.interactive and args.fzf:
        raise HistoryError("Use either -I/--interactive or -f/--fzf, not both.")
    all_entries = saved_command_entries()
    entries = filter_history_entries(all_entries, starts_with=args.starts_with, contains=args.contains)
    if args.most_common is not None:
        entries = most_common_history_entries(entries, args.most_common)
    elif args.limit is not None:
        entries = entries[: args.limit]
    if args.json:
        print(json.dumps([public_saved_entry(entry) for entry in entries], indent=2))
        return 0
    if args.interactive:
        return browse_history(all_entries, args)
    if args.fzf:
        return browse_history_fzf(entries, args)
    color = sys.stdout.isatty() and not args.plain
    display_entries = entries if args.most_common is not None else reversed(entries)
    for entry in display_entries:
        rendered = format_history_entry(
                int(entry["history_id"]),
                entry,
                color=color,
                show_date=args.date,
                show_path=args.path,
                show_status=args.status,
                show_runtime=args.runtime,
            )
        if args.run_count:
            count_text = colorize(f"runs={entry.get('run_count', 0)}", "90", enabled=color)
            rendered = f"{rendered}\n{count_text}"
        print(rendered)
    return 0


def handle_load_delete(args: argparse.Namespace) -> int:
    """Dry-run or apply a composable saved-command deletion filter."""

    before = parse_filter_datetime(args.before) if args.before else None
    now = datetime.now(timezone.utc)
    entries = filter_history_entries(saved_command_entries(), starts_with=args.starts_with, contains=args.contains)
    matches = []
    for entry in entries:
        saved_at = parse_filter_datetime(str(entry.get("started_at") or ""))
        ledger_last_run = entry.get("ledger_last_run_at")
        saved_last_run = entry.get("_saved_command").last_run_at
        last_run_at = parse_filter_datetime(str(ledger_last_run or saved_last_run or "")) if (ledger_last_run or saved_last_run) else None
        if before is not None and (saved_at is None or saved_at >= before):
            continue
        if args.not_run_for is not None:
            reference = last_run_at or saved_at
            if reference is not None and (now - reference).total_seconds() < args.not_run_for * 86400:
                continue
        matches.append(entry)
    if not matches:
        print("No saved commands matched the deletion filters.")
        return 0
    color = sys.stdout.isatty() and not args.plain
    print("Applying deletion:" if args.apply else "Dry run; matching saved commands:")
    for entry in matches:
        print(
            format_history_entry(
                int(entry["history_id"]),
                entry,
                color=color,
                show_date=args.date,
                show_path=args.path,
                show_status=args.status,
                show_runtime=args.runtime,
            )
        )
    if not args.apply:
        print("Re-run with -a/--apply to delete these saved commands only.")
        return 0
    removed = delete_saved_commands({int(entry["history_id"]) for entry in matches})
    print(f"Deleted {len(removed)} saved command(s); history and unique-command statistics were preserved.")
    return 0


def parse_filter_datetime(value: str) -> datetime | None:
    """Parse an ISO date/time filter as a timezone-aware timestamp."""

    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise HistoryError(f"Invalid ISO date/time: {value}") from error
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def saved_command_entries() -> list[dict[str, Any]]:
    """Convert saved commands into history-browser-compatible entries."""

    commands = sorted(list_saved_commands(), key=lambda item: item.saved_at, reverse=True)
    ledger = {str(item.get("key") or ""): item for item in load_unique_commands().get("commands", [])}
    return [
        {
            "history_id": command.id,
            "run_id": None,
            "numeric_id": None,
            "base": command.base,
            "argv": command.argv,
            "command_line": command.command_line,
            "cwd": command.cwd,
            "name": command.name,
            "rows": command.rows,
            "columns": command.columns,
            "force_color": command.force_color,
            "status": (ledger.get(command.command_line.casefold(), {}).get("runs") or [{}])[-1].get("status") or "saved",
            "started_at": command.saved_at,
            "ended_at": None,
            "runtime_seconds": (ledger.get(command.command_line.casefold(), {}).get("runs") or [{}])[-1].get("runtime_seconds"),
            "exit_code": None,
            "run_count": int(ledger.get(command.command_line.casefold(), {}).get("run_count", 0)),
            "ledger_last_run_at": ledger.get(command.command_line.casefold(), {}).get("last_run_at"),
            "_saved_command": command,
        }
        for command in commands
    ]


def public_saved_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Remove browser-only objects before JSON serialization."""

    return {key: value for key, value in entry.items() if not key.startswith("_")}


def print_command_stats(*, output_json: bool) -> int:
    """Print saved-command stats."""

    stats = command_stats()
    if output_json:
        payload = {
            "base_counts": stats["base_counts"],
            "saved": [
                {
                    "id": item["command"].id,
                    "base": item["command"].base,
                    "command_line": item["command"].command_line,
                    "run_count": item["run_count"],
                    "average_runtime_seconds": item["average_runtime_seconds"],
                    "last_runtime_seconds": item["last_runtime_seconds"],
                    "last_run_age_seconds": item["last_run_age_seconds"],
                }
                for item in stats["saved"]
            ],
        }
        print(json.dumps(payload, indent=2))
        return 0

    color = sys.stdout.isatty()
    print(colorize("Command bases", "1;37", enabled=color))
    for index, (base, count) in enumerate(sorted(stats["base_counts"].items())):
        rendered_base = colorize(f"{base:<24}", "36", enabled=color)
        rendered_count = colorize(f"runs={count}", "32", enabled=color)
        print(f"{index:>4} {rendered_base} {rendered_count}")
    print("")
    print(colorize("Saved commands", "1;37", enabled=color))
    header = f"{'ID':>4} {'BASE':<18} {'RUNS':<9} {'AVG':>9} {'LAST':>9} {'AGE':>9} COMMAND"
    print(colorize(header, "2", enabled=color))
    for item in stats["saved"]:
        command = item["command"]
        avg = format_optional_duration(item["average_runtime_seconds"])
        last = format_optional_duration(item["last_runtime_seconds"])
        age = format_optional_duration(item["last_run_age_seconds"])
        command_text = colorize(command.command_line, "36", enabled=color)
        base_text = colorize(f"{command.base:<18}", "35", enabled=color)
        runs_text = colorize(f"runs={item['run_count']:<4}", "32", enabled=color)
        avg_text = colorize(f"{avg:>9}", "33", enabled=color)
        last_text = colorize(f"{last:>9}", "33", enabled=color)
        age_text = colorize(f"{age:>9}", "90", enabled=color)
        print(f"{command.id:>4} {base_text} {runs_text} " f"{avg_text} {last_text} {age_text} {command_text}")
    return 0


def select_saved_command():
    """Prompt for a saved command by base and command number."""

    bases = saved_bases()
    if not bases:
        print("No saved commands.")
        return None
    print_saved_bases(bases)
    if not sys.stdin.isatty():
        return None
    base_index = read_number("base")
    if base_index is None:
        return None
    if base_index < 0 or base_index >= len(bases):
        print("Invalid base selection.", file=sys.stderr)
        return None
    commands = commands_for_base(bases[base_index])
    print_saved_commands(commands)
    command_index = read_number("command")
    if command_index is None:
        return None
    if command_index < 0 or command_index >= len(commands):
        print("Invalid command selection.", file=sys.stderr)
        return None
    return commands[command_index]


def print_saved_bases(bases: list[str]) -> None:
    """Print saved command bases."""

    for index, base in enumerate(bases):
        print(f"{index}: {base}")


def print_saved_commands(commands: list[Any]) -> None:
    """Print saved commands for one base."""

    for index, command in enumerate(commands):
        print(f"{index}: {command.command_line}")
        print(f"   {command.cwd}")


def read_number(label: str) -> int | None:
    """Read a numeric selector from stdin."""

    try:
        value = input(f"{label}> ").strip()
    except (EOFError, KeyboardInterrupt):
        print("")
        return None
    if value in {"", "\x1b"}:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def format_optional_duration(value: object) -> str:
    """Format an optional duration-like value."""

    if not isinstance(value, int | float):
        return "--"
    seconds = int(max(0, value))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    if days:
        return f"{days}d{hours:02}h"
    if hours:
        return f"{hours}h{minutes:02}m"
    if minutes:
        return f"{minutes}m{seconds:02}s"
    return f"{seconds}s"


def main(argv: list[str] | None = None) -> int:
    """Run the CLI."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (
        AmbiguousRunIdError,
        ClientError,
        ConfigError,
        HistoryError,
        IpcError,
        RegistryError,
        RunNotFoundError,
        RunnerError,
    ) as error:
        print(f"runmux: error: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
