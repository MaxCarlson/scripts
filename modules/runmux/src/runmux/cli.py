"""Command-line interface for runmux."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from runmux import __version__
from runmux.client import ClientError, interact_run, list_runs_live, view_run
from runmux.constants import DEFAULT_REFRESH_SECONDS
from runmux.ipc import IpcError
from runmux.runner import (
    RunnerError,
    create_managed_run,
    duplicate_run,
    kill_run,
    pause_run,
    remove_finished_runs,
    remove_run,
    restart_run,
    resume_run,
)
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
        "--attach",
        action="store_true",
        help="Immediately view the output after starting the program.",
    )
    run_parser.add_argument(
        "-I",
        "--interact",
        action="store_true",
        help="Immediately interact with the program after starting it.",
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
    run_parser.add_argument(
        "program", nargs=argparse.REMAINDER, help="Program and arguments to run."
    )
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
    interact_parser.add_argument(
        "-i", "--id", required=True, help="Run ID or unambiguous ID prefix."
    )
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
    kill_parser.add_argument(
        "-f", "--force", action="store_true", help="Force-kill instead of terminate."
    )
    kill_parser.set_defaults(func=handle_kill)

    restart_parser = subparsers.add_parser("restart", help="Restart a finished managed program.")
    restart_parser.add_argument(
        "-i", "--id", required=True, help="Run ID or unambiguous ID prefix."
    )
    restart_parser.add_argument(
        "-a", "--attach", action="store_true", help="Immediately view output."
    )
    restart_parser.add_argument(
        "-I", "--interact", action="store_true", help="Immediately interact."
    )
    restart_parser.add_argument(
        "-C",
        "--no-force-color",
        action="store_true",
        help="Do not force color for the restarted run.",
    )
    restart_parser.set_defaults(func=handle_restart)

    duplicate_parser = subparsers.add_parser(
        "duplicate", help="Start another copy of a managed program."
    )
    duplicate_parser.add_argument(
        "-i", "--id", required=True, help="Run ID or unambiguous ID prefix."
    )
    duplicate_parser.add_argument(
        "-a", "--attach", action="store_true", help="Immediately view output."
    )
    duplicate_parser.add_argument(
        "-I", "--interact", action="store_true", help="Immediately interact."
    )
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

    resume_parser = subparsers.add_parser(
        "resume", help="Resume a paused managed program where supported."
    )
    resume_parser.add_argument("-i", "--id", required=True, help="Run ID or unambiguous ID prefix.")
    resume_parser.set_defaults(func=handle_resume)

    remove_parser = subparsers.add_parser("remove", help="Remove a terminal run from the registry.")
    remove_parser.add_argument("-i", "--id", required=True, help="Run ID or unambiguous ID prefix.")
    remove_parser.set_defaults(func=handle_remove)

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


def get_store(args: argparse.Namespace) -> RunStore:
    """Create a store from parsed root args."""

    return RunStore(args.state_dir)


def handle_run(args: argparse.Namespace) -> int:
    """Handle ``runmux run``."""

    store = get_store(args)
    started = create_managed_run(
        store,
        program_args=args.program,
        cwd=args.cwd,
        name=args.name,
        force_color=not args.no_force_color,
        rows=args.rows,
        columns=args.columns,
    )
    print(f"Started {started.record.id}: {started.record.command_line}")
    if args.interact:
        return interact_run(store, run_id=started.record.id, tail_lines=None)
    if args.attach:
        return view_run(
            store, run_id=started.record.id, follow=True, from_end=False, tail_lines=None
        )
    return 0


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
    )


def handle_interact(args: argparse.Namespace) -> int:
    """Handle ``runmux interact``."""

    return interact_run(get_store(args), run_id=args.id, tail_lines=args.tail_lines)


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

    if args.interact:
        return interact_run(store, run_id=run_id, tail_lines=None)
    if args.attach:
        return view_run(store, run_id=run_id, follow=True, from_end=False, tail_lines=None)
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

    record = remove_run(get_store(args), run_id=args.id)
    print(f"Removed {record.numeric_id}: {record.command_line}")
    return 0


def handle_remove_finished(args: argparse.Namespace) -> int:
    """Handle ``runmux remove-finished``."""

    records = remove_finished_runs(get_store(args), clean_only=args.clean_only)
    print(f"Removed {len(records)} run(s).")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the CLI."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (
        AmbiguousRunIdError,
        ClientError,
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
