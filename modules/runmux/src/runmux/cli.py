"""Command-line interface for runmux."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from runmux import __version__
from runmux.client import ClientError, interact_run, list_runs_live, view_run
from runmux.constants import ATTACH_RESERVED_ROWS, DEFAULT_REFRESH_SECONDS
from runmux.history import (
    HistoryError,
    command_stats,
    commands_for_base,
    history_entries,
    list_saved_commands,
    mark_saved_command_run,
    save_command,
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
        "--cwd",
        type=Path,
        default=None,
        help="Working directory for the managed program.",
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

    ls_parser = subparsers.add_parser("ls", help="Show runmux-managed programs once.")
    add_list_filters(ls_parser)
    ls_parser.set_defaults(func=handle_ls)

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

    remove_finished_parser = subparsers.add_parser(
        "remove-finished",
        help="Remove all finished runs from the registry.",
    )
    remove_finished_parser.add_argument(
        "-C",
        "--clean-only",
        action="store_true",
        help="Only remove cleanly finished runs, leaving failed, killed, and lost runs.",
    )
    remove_finished_parser.set_defaults(func=handle_remove_finished)

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
        "-p",
        "--plain",
        action="store_true",
        help="Disable ANSI color in history output.",
    )
    history_parser.add_argument("-j", "--json", action="store_true", help="Emit JSON.")
    history_parser.set_defaults(func=handle_history)

    save_parser = subparsers.add_parser("save", help="Save an existing run's command.")
    save_parser.add_argument("-i", "--id", required=True, help="Run ID or numeric ID.")
    save_parser.set_defaults(func=handle_save)

    cmd_parser = subparsers.add_parser("cmd", help="List or run saved commands.")
    cmd_parser.add_argument(
        "-S",
        "--stats",
        action="store_true",
        help="Show saved-command and command-base stats.",
    )
    cmd_parser.add_argument("-j", "--json", action="store_true", help="Emit JSON.")
    cmd_parser.set_defaults(func=handle_cmd)

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

    program_args = normalize_program_args(args.program)
    if program_args[0] == "cmd":
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
        save_command(
            argv=program_args,
            command_line=started.record.command_line,
            cwd=started.record.cwd,
        )
        mark_saved_command_run(started.record.command_line)
    print(f"Started {started.record.id}: {started.record.command_line}")
    if args.attach:
        return view_run(store, run_id=started.record.id, follow=True, from_end=False, tail_lines=None, separator=has_separator)
    if args.detach:
        return 0
    if args.interact or not args.detach:
        return interact_run(store, run_id=started.record.id, tail_lines=None, separator=has_separator)
    return 0


def handle_run_saved_command(args: argparse.Namespace, selector_args: list[str]) -> int:
    """Handle ``runmux run cmd`` saved-command selection."""

    selector = build_run_cmd_parser().parse_args(selector_args)
    selected = select_saved_command()
    if selected is None:
        return 0
    store = get_store(args)
    has_separator = getattr(args, "separator", False) or os.environ.get("RUNMUX_SEPARATOR", "").lower() in ("1", "true", "yes", "on") or os.environ.get("RUNMUX_DIVIDER", "").lower() in ("1", "true", "yes", "on")
    reserve_rows = 0 if selector.detach else (3 if has_separator else ATTACH_RESERVED_ROWS)
    started = create_managed_run(
        store,
        program_args=selected.argv,
        cwd=Path(selected.cwd),
        name=args.name,
        force_color=not args.no_force_color,
        rows=args.rows,
        columns=args.columns,
        reserve_rows=reserve_rows,
    )
    mark_saved_command_run(started.record.command_line)
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
    """Build the parser for ``runmux run cmd`` selector options."""

    parser = argparse.ArgumentParser(prog="runmux run cmd")
    parser.add_argument("-i", "--interact", action="store_true", help="Interact after launch.")
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
    )


def handle_ls(args: argparse.Namespace) -> int:
    """Handle ``runmux ls``."""

    return list_runs_live(
        get_store(args),
        once=True,
        include_all=not args.active_only,
        limit=args.limit,
        refresh_seconds=DEFAULT_REFRESH_SECONDS,
        output_json=args.json,
    )


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

    store = get_store(args)
    target = args.id or args.target
    if target is None:
        records = remove_finished_runs(store, clean_only=False)
        print(f"Removed {len(records)} run(s).")
        return 0
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

    entries = history_entries()
    if args.limit is not None:
        entries = entries[-args.limit :]
    if args.json:
        print(json.dumps(entries, indent=2))
        return 0
    if args.interactive:
        return browse_history(entries)
    color = sys.stdout.isatty() and not args.plain
    for index, entry in enumerate(entries):
        print(format_history_entry(index, entry, color=color))
    return 0


def format_history_entry(index: int, entry: dict[str, Any], *, color: bool) -> str:
    """Format one history entry for easy command copying."""

    status = entry.get("status") or ""
    started = entry.get("started_at") or ""
    runtime = format_optional_duration(entry.get("runtime_seconds"))
    command = str(entry.get("command_line") or "")
    command_text = colorize(command, "36", enabled=color)
    return f"{index:>4} {started:<25} status={status:<9} runtime={runtime:>9}\n" f"     cmd> {command_text}"


def colorize(value: str, color_code: str, *, enabled: bool) -> str:
    """Wrap text in ANSI color when enabled."""

    if not enabled:
        return value
    return f"\x1b[{color_code}m{value}\x1b[0m"


def browse_history(entries: list[dict[str, Any]]) -> int:
    """Browse command history with terminal-like Up/Down navigation."""

    if not entries:
        print("No runmux history.")
        return 0
    selected = len(entries) - 1
    print("\x1b[?25l", end="")
    try:
        while True:
            entry = entries[selected]
            screen = "\x1b[H\x1b[2J" + render_history_browser(entries, selected)
            sys.stdout.write(screen)
            sys.stdout.flush()
            key = read_history_key()
            if key in {"UP", "k", "K"}:
                selected = max(0, selected - 1)
            elif key in {"DOWN", "j", "J"}:
                selected = min(len(entries) - 1, selected + 1)
            elif key in {"ENTER", "\r", "\n"}:
                print("\x1b[?25h", end="")
                print(str(entry.get("command_line") or ""))
                return 0
            elif key in {"ESC", "q", "Q", "\x03"}:
                return 0
    finally:
        print("\x1b[?25h", end="")
        sys.stdout.flush()


def render_history_browser(entries: list[dict[str, Any]], selected: int) -> str:
    """Render the interactive history browser."""

    entry = entries[selected]
    command = str(entry.get("command_line") or "")
    lines = [
        "runmux history - Up/Down select, Enter print command, q/Esc quit",
        "",
        f"Selected: {selected + 1}/{len(entries)}",
        f"Run date: {entry.get('started_at') or '--'}",
        f"Status:   {entry.get('status') or '--'}",
        f"Runtime:  {format_optional_duration(entry.get('runtime_seconds'))}",
        "",
        f"cmd> \x1b[36m{command}\x1b[0m",
    ]
    return "\n".join(lines) + "\n"


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
        return "ESC"
    if key in {"\r", "\n"}:
        return "ENTER"
    return key


def handle_save(args: argparse.Namespace) -> int:
    """Handle ``runmux save``."""

    record = save_run_command(get_store(args), run_id=args.id)
    print(f"Saved {record.numeric_id}: {record.command_line}")
    return 0


def handle_cmd(args: argparse.Namespace) -> int:
    """Handle ``runmux cmd``."""

    if args.stats:
        return print_command_stats(output_json=args.json)
    if args.json:
        print(json.dumps([command.__dict__ for command in list_saved_commands()], indent=2))
        return 0
    selected = select_saved_command()
    if selected is not None:
        print(selected.command_line)
    return 0


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
