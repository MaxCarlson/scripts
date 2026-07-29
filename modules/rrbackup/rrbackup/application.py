"""Task-oriented parser and dispatcher for the unified ``backup`` command."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from . import cli_runtime
from .command_contract import MAJOR_COMMANDS, VIEW_SECTIONS
from .locking import LockError
from .restic import ResticCommandError
from .version import __version__

EXIT_OK = cli_runtime.EXIT_OK
EXIT_USAGE = cli_runtime.EXIT_USAGE
EXIT_OPERATION_FAILED = cli_runtime.EXIT_OPERATION_FAILED
EXIT_UNHEALTHY = cli_runtime.EXIT_UNHEALTHY
EXIT_SKIPPED = cli_runtime.EXIT_SKIPPED

_GLOBAL_VALUE_OPTIONS = {
    "-c",
    "--config",
    "--config-path",
    "--config_path",
    "-R",
    "--repository",
    "--repository-path",
    "-p",
    "--password-file",
    "--password_file",
    "-x",
    "--restic-executable",
    "--restic_executable",
}


def _add_output_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-j", "--json", action="store_true", help="Emit machine-readable JSON only.")
    parser.add_argument("-M", "--markdown", action="store_true", help="Emit Markdown without ANSI color.")
    parser.add_argument("-P", "--plain", action="store_true", help="Disable the interactive UI and ANSI color.")


def _add_global_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-c",
        "--config",
        "--config-path",
        "--config_path",
        dest="config_path",
        help="Canonical TOML or legacy JSON configuration path.",
    )
    parser.add_argument("-R", "--repository", "--repository-path", dest="repository")
    parser.add_argument("-p", "--password-file", "--password_file", dest="password_file")
    parser.add_argument(
        "-x",
        "--restic-executable",
        "--restic_executable",
        dest="restic_executable",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI color.")


def build_parser(program_name: str = "backup") -> argparse.ArgumentParser:
    """Build the seven-area task-oriented parser."""

    parser = argparse.ArgumentParser(
        prog=program_name,
        description="Create, run, inspect, schedule, restore, and maintain Restic backups.",
        epilog=(
            "Start with 'backup view' to inspect configured backups or 'backup create' "
            "to define a new one. Human output is formatted by default; use --json for automation."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("-V", "--version", action="version", version="%(prog)s {0}".format(__version__))
    _add_global_options(parser)
    areas = parser.add_subparsers(
        dest="area",
        required=True,
        metavar="{" + ",".join(MAJOR_COMMANDS) + "}",
    )
    _add_create_parser(areas)
    _add_run_parser(areas)
    _add_view_parser(areas)
    _add_schedule_parser(areas)
    _add_restore_parser(areas)
    _add_repo_parser(areas)
    _add_config_parser(areas)
    return parser


def _add_create_parser(areas: argparse._SubParsersAction) -> None:
    parser = areas.add_parser("create", help="Create a complete backup through a preview-first wizard.")
    parser.add_argument("-y", "--apply", action="store_true", help="Write configuration and install the schedule.")
    _add_output_options(parser)
    parser.set_defaults(handler=cli_runtime.handle_create)


def _add_run_parser(areas: argparse._SubParsersAction) -> None:
    parser = areas.add_parser("run", help="Choose configured backups or run one by name.")
    parser.add_argument(
        "backup_name",
        nargs="?",
        default="auto",
        help="Configured backup name. Omit it or use 'auto' for the chooser.",
    )
    parser.add_argument("-C", "--print-command-only", "--print_command_only", action="store_true")
    parser.add_argument("-n", "--dry-run", "--dry_run", action="store_true")
    parser.add_argument(
        "-f",
        "--force",
        "--ignore-cpu-policy",
        "--force-run",
        "--force_run",
        dest="ignore_cpu_policy",
        action="store_true",
    )
    parser.add_argument("-t", "--tag", action="append", default=[])
    parser.add_argument("-e", "--exclude", action="append", default=[])
    parser.add_argument(
        "-a",
        "--restic-arg",
        "--extra-backup-arg",
        "--extra_backup_arg",
        action="append",
        default=[],
    )
    _add_output_options(parser)
    parser.set_defaults(handler=cli_runtime.handle_run)


def _add_view_parser(areas: argparse._SubParsersAction) -> None:
    parser = areas.add_parser(
        "view",
        help="Open the backup dashboard or render one combined section.",
        description=(
            "Interactive sections: Overview, Backups, History, Repository, Schedules, "
            "and Diagnostics. Use --section for noninteractive output."
        ),
    )
    parser.add_argument("-s", "--section", choices=VIEW_SECTIONS, default="overview")
    parser.add_argument("-b", "--backup", dest="backup_name", help="Limit output to one configured backup.")
    parser.add_argument("-L", "--include-legacy-evidence", action="store_true")
    parser.add_argument("-r", "--redact-paths", action="store_true")
    _add_output_options(parser)
    parser.set_defaults(handler=cli_runtime.handle_view)


def _add_schedule_parser(areas: argparse._SubParsersAction) -> None:
    parser = areas.add_parser(
        "schedule",
        help="List backup schedules or open the schedule/retention editor.",
    )
    _add_output_options(parser)
    operations = parser.add_subparsers(dest="schedule_command")
    parser.set_defaults(handler=cli_runtime.handle_schedule_list, schedule_command="list")

    wizard = operations.add_parser("wizard", help="Select one or more backups and edit their schedule.")
    wizard.add_argument("backup_names", nargs="*")
    wizard.add_argument("-y", "--apply", action="store_true")
    _add_output_options(wizard)
    wizard.set_defaults(handler=cli_runtime.handle_schedule_wizard)

    edit = operations.add_parser("edit", help="Edit one configured backup schedule.")
    edit.add_argument("backup_name")
    edit.add_argument("-y", "--apply", action="store_true")
    _add_output_options(edit)
    edit.set_defaults(handler=cli_runtime.handle_schedule_edit)


def _add_restore_parser(areas: argparse._SubParsersAction) -> None:
    parser = areas.add_parser("restore", help="Search, preview, and explicitly run restores.")
    operations = parser.add_subparsers(dest="restore_command", required=True)

    search = operations.add_parser("search", help="Search repository snapshots.")
    search.add_argument("patterns", nargs="+")
    search.add_argument("-b", "--backup", dest="backup_name")
    search.add_argument("-s", "--snapshot-id", "--snapshot_id")
    search.add_argument("-i", "--ignore-case", "--ignore_case", action="store_true")
    _add_output_options(search)
    search.set_defaults(handler=cli_runtime.handle_restore_search)

    preview = operations.add_parser("preview", help="Preview a restore command without executing it.")
    _add_restore_arguments(preview, include_apply=False)
    preview.set_defaults(handler=cli_runtime.handle_restore, restore_apply=False)

    run = operations.add_parser("run", help="Run a restore only with --apply.")
    _add_restore_arguments(run, include_apply=True)
    run.set_defaults(handler=cli_runtime.handle_restore, restore_apply=True)


def _add_restore_arguments(parser: argparse.ArgumentParser, *, include_apply: bool) -> None:
    parser.add_argument("snapshot_id", nargs="?", default="latest")
    parser.add_argument("-b", "--backup", dest="backup_name")
    parser.add_argument("-T", "--target", required=True)
    parser.add_argument("-i", "--include", action="append", default=[])
    parser.add_argument("-e", "--exclude", action="append", default=[])
    if include_apply:
        parser.add_argument("-y", "--apply", action="store_true")
    _add_output_options(parser)


def _add_repo_parser(areas: argparse._SubParsersAction) -> None:
    parser = areas.add_parser(
        "repo",
        help="Show one combined repository summary or run an explicit check.",
    )
    parser.add_argument(
        "repo_action",
        nargs="?",
        choices=("summary", "check"),
        default="summary",
    )
    parser.add_argument("-b", "--backup", dest="backup_name")
    parser.add_argument(
        "-S",
        "--refresh-storage",
        action="store_true",
        help="Run the expensive full restore-size calculation and cache it.",
    )
    parser.add_argument("-d", "--read-data", action="store_true", help="Read all data during repo check.")
    _add_output_options(parser)
    parser.set_defaults(handler=cli_runtime.handle_repo)


def _add_config_parser(areas: argparse._SubParsersAction) -> None:
    parser = areas.add_parser("config", help="Inspect, validate, or migrate backup configuration.")
    operations = parser.add_subparsers(dest="config_command", required=True)
    for name, help_text, handler in (
        ("show", "Show all configured backup definitions.", cli_runtime.handle_config_show),
        ("validate", "Validate configured paths and definitions.", cli_runtime.handle_config_validate),
        ("discover", "Show configuration and input-file discovery.", cli_runtime.handle_config_discover),
    ):
        child = operations.add_parser(name, help=help_text)
        _add_output_options(child)
        child.set_defaults(handler=handler)

    migrate = operations.add_parser("migrate", help="Preview or write canonical TOML from legacy defaults.")
    migrate.add_argument("-o", "--output")
    migrate.add_argument("-y", "--apply", action="store_true")
    _add_output_options(migrate)
    migrate.set_defaults(handler=cli_runtime.handle_config_migrate)


def _split_global_prefix(argv: Sequence[str]) -> Tuple[List[str], List[str]]:
    prefix: List[str] = []
    values = list(argv)
    index = 0
    while index < len(values) and values[index].startswith("-"):
        option = values[index]
        prefix.append(option)
        index += 1
        if option in _GLOBAL_VALUE_OPTIONS and index < len(values):
            prefix.append(values[index])
            index += 1
    return prefix, values[index:]


def _translate_hidden_aliases(argv: Sequence[str]) -> List[str]:
    """Accept selected old spellings without advertising them in help."""

    prefix, remainder = _split_global_prefix(argv)
    if not remainder:
        return list(argv)
    area = remainder[0]
    tail = remainder[1:]
    if area == "repository":
        area = "repo"
    elif area == "edit":
        area = "config"

    if area == "view" and tail:
        operation = tail[0]
        section_map = {
            "dashboard": "overview",
            "health": "overview",
            "gaps": "overview",
            "alerts": "overview",
            "timeline": "history",
            "runs": "history",
            "logs": "history",
            "schedules": "schedules",
            "setup": "diagnostics",
            "system": "diagnostics",
            "provenance": "diagnostics",
            "audit": "audit",
        }
        if operation in section_map:
            return prefix + ["view", "--section", section_map[operation]] + tail[1:]
    if area == "schedule" and tail and tail[0] in {"list", "discover"}:
        return prefix + ["schedule"] + tail[1:]
    return prefix + [area] + tail


def _explicit_config_must_exist(args: argparse.Namespace) -> bool:
    """Return whether an explicitly supplied config is an input, not an output target."""

    if not args.config_path:
        return False
    if args.area == "create":
        return False
    return not (args.area == "config" and args.config_command == "migrate")


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    program_name: str = "backup",
) -> int:
    """Parse and dispatch the canonical CLI."""

    raw = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser(program_name=program_name)
    try:
        args = parser.parse_args(_translate_hidden_aliases(raw))
        if _explicit_config_must_exist(args) and not Path(args.config_path).exists():
            raise FileNotFoundError("Config file not found: {0}".format(args.config_path))
        return int(args.handler(args))
    except (OSError, ValueError, json.JSONDecodeError, ResticCommandError, LockError) as exc:
        print("{0}: {1}".format(parser.prog, exc), file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:
        print("{0}: interrupted".format(parser.prog), file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
