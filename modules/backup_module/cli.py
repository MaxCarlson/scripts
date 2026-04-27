from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backup_module.core import (
    AlreadyRunningError,
    BackupConfig,
    ProcessLock,
    build_find_command,
    build_ls_command,
    build_restore_command,
    build_restic_backup_command,
    build_snapshots_command,
    config_to_public_dict,
    default_restore_target,
    exit_with_error,
    format_command,
    get_last_success_time,
    load_config_with_overrides,
    print_json,
    read_status,
    resolve_default_config_path,
    run_command_streaming,
    update_status_for_run_end,
    update_status_for_run_start,
    update_status_for_skip,
    wait_for_backup_window,
)
from backup_module.scheduler import (
    ScheduleRequest,
    create_schedule,
    default_python_executable,
    delete_schedule,
    list_schedule,
    run_schedule,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backup_module",
        description="Manage Restic backups, snapshot listing, search, restore, and schedules.",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    add_backup_parser(subparsers)
    add_ls_parser(subparsers)
    add_search_parser(subparsers)
    add_restore_parser(subparsers)
    add_status_parser(subparsers)
    add_defaults_parser(subparsers)
    add_schedule_parser(subparsers)

    return parser


def add_common_repository_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-c",
        "--config_path",
        default=None,
        help=(
            "Path to a JSON config file. Defaults to C:\\BackupConfig\\local_backup_config.json "
            "if it exists; otherwise uses built-in local defaults."
        ),
    )
    parser.add_argument(
        "-r",
        "--repository_path",
        default=None,
        help="Override config: Restic repository path or remote repository URL.",
    )
    parser.add_argument(
        "-p",
        "--password_file",
        default=None,
        help="Override config: Restic password file.",
    )
    parser.add_argument(
        "-x",
        "--restic_executable",
        default=None,
        help="Override config: Restic executable path. Defaults to restic.",
    )
    parser.add_argument(
        "-R",
        "--default_restore_root",
        default=None,
        help="Override config: default restore root. Defaults to B:\\ResticRestore.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print additional diagnostic information.",
    )


def add_backup_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "backup",
        help="Start a Restic backup using CPU gating, locking, logging, and status tracking.",
    )
    add_common_repository_args(parser)
    parser.add_argument(
        "-S",
        "--sources_file",
        default=None,
        help="Override config: file containing source paths for --files-from-verbatim.",
    )
    parser.add_argument(
        "-E",
        "--excludes_file",
        default=None,
        help="Override config: Restic case-insensitive exclude file.",
    )
    parser.add_argument(
        "-f",
        "--force_run",
        action="store_true",
        help="Run immediately and ignore CPU gating.",
    )
    parser.add_argument(
        "-d",
        "--dry_run",
        action="store_true",
        help="Append --dry-run to the Restic backup command for this invocation only.",
    )
    parser.add_argument(
        "-n",
        "--not_backup_days",
        type=float,
        default=None,
        help="After this many days since the last success, use the max CPU cutoff.",
    )
    parser.add_argument(
        "-m",
        "--min_cpu_cutoff",
        type=float,
        default=None,
        help="Normal CPU cutoff percentage.",
    )
    parser.add_argument(
        "-M",
        "--max_cpu_cutoff",
        type=float,
        default=None,
        help="Overdue CPU cutoff percentage.",
    )
    parser.add_argument(
        "-w",
        "--max_wait_minutes",
        type=float,
        default=None,
        help="Maximum time to wait for CPU usage to fall within policy.",
    )
    parser.add_argument(
        "-s",
        "--cpu_sample_seconds",
        type=float,
        default=None,
        help="Seconds to sample CPU usage each time.",
    )
    parser.add_argument(
        "-i",
        "--cpu_check_interval_seconds",
        type=float,
        default=None,
        help="Seconds to sleep between CPU checks.",
    )
    parser.add_argument(
        "-t",
        "--tag",
        default=None,
        help="Override config: Restic snapshot tag.",
    )
    parser.add_argument(
        "-C",
        "--print_command",
        action="store_true",
        help="Print the final Restic command before running it.",
    )
    parser.add_argument(
        "-a",
        "--extra_backup_arg",
        action="append",
        default=[],
        help="Extra argument to append to the Restic backup command. Repeat as needed.",
    )
    parser.add_argument(
        "-F",
        "--no_fs_snapshot",
        action="store_true",
        help="Disable --use-fs-snapshot for this invocation.",
    )
    parser.add_argument(
        "-X",
        "--no_exclude_caches",
        action="store_true",
        help="Disable --exclude-caches for this invocation.",
    )
    parser.set_defaults(handler=handle_backup)


def add_ls_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "ls",
        aliases=["list", "snapshots"],
        help="List Restic snapshots, or list files inside a specific snapshot.",
    )
    add_common_repository_args(parser)
    parser.add_argument(
        "-s",
        "--snapshot_id",
        default=None,
        help="Snapshot ID to list. If omitted, lists snapshots instead.",
    )
    parser.add_argument(
        "-P",
        "--path",
        default=None,
        help="Path inside the snapshot to list. Windows paths are converted to Restic /D/... paths.",
    )
    parser.add_argument(
        "-t",
        "--tag",
        action="append",
        default=[],
        help="Filter snapshots by tag. Repeat as needed.",
    )
    parser.add_argument(
        "-H",
        "--host",
        default=None,
        help="Filter snapshots by host.",
    )
    parser.add_argument(
        "-j",
        "--json_output",
        action="store_true",
        help="Request JSON output from Restic.",
    )
    parser.add_argument(
        "-C",
        "--compact",
        action="store_true",
        help="Use compact snapshot listing.",
    )
    parser.set_defaults(handler=handle_ls)


def add_search_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "search",
        aliases=["find"],
        help="Search Restic snapshots for files or folders.",
    )
    add_common_repository_args(parser)
    parser.add_argument(
        "patterns",
        nargs="+",
        help="One or more Restic find patterns, filenames, or folder names.",
    )
    parser.add_argument(
        "-s",
        "--snapshot_id",
        default=None,
        help="Snapshot ID to search. If omitted, searches all snapshots.",
    )
    parser.add_argument(
        "-i",
        "--ignore_case",
        action="store_true",
        help="Use case-insensitive Restic search.",
    )
    parser.add_argument(
        "-j",
        "--json_output",
        action="store_true",
        help="Request JSON output from Restic find.",
    )
    parser.add_argument(
        "-o",
        "--output_file",
        default=None,
        help="Write search output to this file while also printing it.",
    )
    parser.set_defaults(handler=handle_search)


def add_restore_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "restore",
        help="Restore files or folders from a specific snapshot or from latest.",
    )
    add_common_repository_args(parser)
    parser.add_argument(
        "-s",
        "--snapshot_id",
        default="latest",
        help="Snapshot ID to restore from. Defaults to latest.",
    )
    parser.add_argument(
        "-T",
        "--target_path",
        default=None,
        help=(
            "Safe restore target directory. Defaults to a timestamped folder under "
            "B:\\ResticRestore."
        ),
    )
    parser.add_argument(
        "-i",
        "--include_path",
        action="append",
        default=[],
        help=(
            "File or folder to restore. Repeat as needed. Windows paths are converted to /D/...; "
            "bare names become **/name and **/name/**."
        ),
    )
    parser.add_argument(
        "-I",
        "--include_pattern",
        action="append",
        default=[],
        help="Raw Restic include pattern to pass through. Repeat as needed.",
    )
    parser.add_argument(
        "-e",
        "--exclude_pattern",
        action="append",
        default=[],
        help="Restic exclude pattern to apply during restore. Repeat as needed.",
    )
    parser.add_argument(
        "-C",
        "--case_sensitive",
        action="store_true",
        help="Use --include/--exclude instead of --iinclude/--iexclude.",
    )
    parser.add_argument(
        "-P",
        "--print_command_only",
        action="store_true",
        help="Print the Restic restore command without running it.",
    )
    parser.set_defaults(handler=handle_restore)


def add_status_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "status",
        help="Print backup status and the effective default paths being used.",
    )
    add_common_repository_args(parser)
    parser.add_argument(
        "-j",
        "--json_output",
        action="store_true",
        help="Print compact JSON output.",
    )
    parser.add_argument(
        "-q",
        "--raw_status",
        action="store_true",
        help="Print only the raw status JSON file payload.",
    )
    parser.set_defaults(handler=handle_status)


def add_defaults_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "defaults",
        help="Print the effective backup defaults/configuration.",
    )
    add_common_repository_args(parser)
    parser.add_argument(
        "-j",
        "--json_output",
        action="store_true",
        help="Print compact JSON output.",
    )
    parser.set_defaults(handler=handle_defaults)


def add_schedule_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "schedule",
        help="Create, list, delete, or run a scheduled backup task.",
    )

    schedule_subparsers = parser.add_subparsers(
        dest="schedule_command",
        required=True,
    )

    create_parser = schedule_subparsers.add_parser(
        "create",
        help="Create a scheduled backup task.",
    )
    add_common_repository_args(create_parser)
    create_parser.add_argument(
        "-n",
        "--task_name",
        default="BackupModuleLocalBackup",
        help="Scheduled task name.",
    )
    create_parser.add_argument(
        "-f",
        "--frequency",
        choices=["minute", "hourly", "daily", "weekly", "monthly", "once"],
        default="daily",
        help="Schedule frequency.",
    )
    create_parser.add_argument(
        "-m",
        "--modifier",
        type=int,
        default=1,
        help="Run every N frequency units where supported.",
    )
    create_parser.add_argument(
        "-t",
        "--start_time",
        default="02:00",
        help="Start time in HH:MM 24-hour format.",
    )
    create_parser.add_argument(
        "-D",
        "--day_of_week",
        default=None,
        help="Day of week for weekly schedules, e.g. SUN, MON, TUE.",
    )
    create_parser.add_argument(
        "-P",
        "--python_executable",
        default=default_python_executable(),
        help="Python executable used by the scheduled task.",
    )
    create_parser.add_argument(
        "-a",
        "--backup_argument",
        action="append",
        default=[],
        help=(
            "Additional argument to pass after 'backup'. Repeat as needed. "
            "Example: -a --force_run -a --print_command"
        ),
    )
    create_parser.add_argument(
        "-F",
        "--force",
        action="store_true",
        help="Overwrite an existing schedule with the same task name where supported.",
    )
    create_parser.add_argument(
        "-H",
        "--run_highest",
        action="store_true",
        help="On Windows, request highest available task privileges.",
    )
    create_parser.add_argument(
        "-N",
        "--print_only",
        action="store_true",
        help="Print the scheduler command or cron line without installing it.",
    )
    create_parser.set_defaults(handler=handle_schedule_create)

    list_parser = schedule_subparsers.add_parser(
        "list",
        help="List scheduled backup tasks.",
    )
    list_parser.add_argument(
        "-n",
        "--task_name",
        default=None,
        help="Optional task name to query.",
    )
    list_parser.set_defaults(handler=handle_schedule_list)

    delete_parser = schedule_subparsers.add_parser(
        "delete",
        help="Delete a scheduled backup task.",
    )
    delete_parser.add_argument(
        "-n",
        "--task_name",
        required=True,
        help="Task name to delete.",
    )
    delete_parser.add_argument(
        "-F",
        "--force",
        action="store_true",
        help="Force deletion without prompting where supported.",
    )
    delete_parser.set_defaults(handler=handle_schedule_delete)

    run_parser = schedule_subparsers.add_parser(
        "run",
        help="Run a scheduled backup task now.",
    )
    run_parser.add_argument(
        "-n",
        "--task_name",
        required=True,
        help="Task name to run.",
    )
    run_parser.set_defaults(handler=handle_schedule_run)


def apply_backup_overrides(config: BackupConfig, args: argparse.Namespace) -> None:
    if args.dry_run:
        config.dry_run = True
    if args.not_backup_days is not None:
        config.not_backup_days = args.not_backup_days
    if args.min_cpu_cutoff is not None:
        config.min_cpu_cutoff = args.min_cpu_cutoff
    if args.max_cpu_cutoff is not None:
        config.max_cpu_cutoff = args.max_cpu_cutoff
    if args.max_wait_minutes is not None:
        config.max_wait_minutes = args.max_wait_minutes
    if args.cpu_sample_seconds is not None:
        config.cpu_sample_seconds = args.cpu_sample_seconds
    if args.cpu_check_interval_seconds is not None:
        config.cpu_check_interval_seconds = args.cpu_check_interval_seconds
    if args.extra_backup_arg:
        config.extra_backup_args.extend(args.extra_backup_arg)
    if args.no_fs_snapshot:
        config.use_fs_snapshot = False
    if args.no_exclude_caches:
        config.exclude_caches = False

    config.validate()


def build_config_metadata(
    args: argparse.Namespace, config: BackupConfig
) -> dict[str, object]:
    effective_config_path = resolve_default_config_path(
        getattr(args, "config_path", None)
    )
    status_path = Path(config.status_file)
    log_path = Path(config.log_file)
    lock_path = Path(config.lock_file)

    return {
        "config_path": str(effective_config_path),
        "config_path_exists": effective_config_path.exists(),
        "repository": config.repository,
        "password_file": config.password_file,
        "password_file_exists": Path(config.password_file).exists(),
        "sources_file": config.sources_file,
        "sources_file_exists": (
            Path(config.sources_file).exists() if config.sources_file else False
        ),
        "excludes_file": config.excludes_file,
        "excludes_file_exists": (
            Path(config.excludes_file).exists() if config.excludes_file else False
        ),
        "status_file": config.status_file,
        "status_file_exists": status_path.exists(),
        "log_file": config.log_file,
        "log_file_exists": log_path.exists(),
        "lock_file": config.lock_file,
        "lock_file_exists": lock_path.exists(),
        "tag": config.tag,
        "restic_executable": config.restic_executable,
        "default_restore_root": config.default_restore_root,
    }


def handle_backup(args: argparse.Namespace) -> int:
    try:
        config = load_config_with_overrides(args)
        apply_backup_overrides(config, args)
        config.ensure_runtime_paths()
        config.require_backup_input_files()

        status = read_status(config.status_file)
        last_success = get_last_success_time(status)

        lock = ProcessLock(config.lock_file)
        try:
            lock.acquire()
        except AlreadyRunningError as exc:
            print(str(exc), file=sys.stderr)
            return 2

        try:
            decision = None
            if not args.force_run:
                decision = wait_for_backup_window(
                    config,
                    last_success,
                    verbose=args.verbose,
                )
                if not decision.should_run:
                    print(f"Skipping backup. {decision.reason}")
                    update_status_for_skip(config, status, decision)
                    return 0

            command = build_restic_backup_command(config)

            if args.print_command:
                print(format_command(command))

            status = update_status_for_run_start(config, status, decision, command)

            return_code = run_command_streaming(command, log_path=config.log_file)
            update_status_for_run_end(config, status, return_code)

            if return_code == 0:
                print("Backup completed successfully.")
            else:
                print(f"Backup failed with exit code {return_code}.", file=sys.stderr)

            return return_code
        finally:
            lock.release()
    except Exception as exc:
        return exit_with_error(str(exc))


def handle_ls(args: argparse.Namespace) -> int:
    try:
        config = load_config_with_overrides(args)
        config.require_repository_input_files()

        if args.snapshot_id:
            command = build_ls_command(
                config,
                snapshot_id=args.snapshot_id,
                path=args.path,
                json_output=args.json_output,
            )
        else:
            command = build_snapshots_command(
                config,
                tags=args.tag,
                host=args.host,
                json_output=args.json_output,
                compact=args.compact,
            )

        if args.verbose:
            print(format_command(command))

        return run_command_streaming(command)
    except Exception as exc:
        return exit_with_error(str(exc))


def handle_search(args: argparse.Namespace) -> int:
    try:
        config = load_config_with_overrides(args)
        config.require_repository_input_files()

        command = build_find_command(
            config,
            patterns=args.patterns,
            snapshot_id=args.snapshot_id,
            ignore_case=args.ignore_case,
            json_output=args.json_output,
        )

        if args.verbose:
            print(format_command(command))

        return run_command_streaming(command, tee_path=args.output_file)
    except Exception as exc:
        return exit_with_error(str(exc))


def handle_restore(args: argparse.Namespace) -> int:
    try:
        config = load_config_with_overrides(args)
        config.require_repository_input_files()

        target_path = args.target_path
        if not target_path:
            target_path = default_restore_target(config.default_restore_root)
            print(f"No --target_path supplied. Using restore target: {target_path}")

        command = build_restore_command(
            config,
            snapshot_id=args.snapshot_id,
            target_path=target_path,
            include_paths=args.include_path,
            include_patterns=args.include_pattern,
            exclude_patterns=args.exclude_pattern,
            ignore_case=not args.case_sensitive,
        )

        if args.print_command_only or args.verbose:
            print(format_command(command))

        if args.print_command_only:
            return 0

        Path(target_path).mkdir(parents=True, exist_ok=True)
        return run_command_streaming(command)
    except Exception as exc:
        return exit_with_error(str(exc))


def handle_status(args: argparse.Namespace) -> int:
    try:
        config = load_config_with_overrides(args)
        status_payload = read_status(config.status_file)

        if args.raw_status:
            payload = status_payload
        else:
            payload = {
                "message": (
                    "No status file exists yet. This is normal until backup_module backup "
                    "has completed at least once."
                    if not Path(config.status_file).exists()
                    else "Status file loaded."
                ),
                "effective_config": build_config_metadata(args, config),
                "status": status_payload,
            }

        if args.json_output:
            print(json.dumps(payload, separators=(",", ":"), sort_keys=True))
        else:
            print_json(payload)

        return 0
    except Exception as exc:
        return exit_with_error(str(exc))


def handle_defaults(args: argparse.Namespace) -> int:
    try:
        config = load_config_with_overrides(args)
        payload = config_to_public_dict(config)
        payload["config_path"] = str(resolve_default_config_path(args.config_path))
        payload["config_path_exists"] = Path(payload["config_path"]).exists()

        if args.json_output:
            print(json.dumps(payload, separators=(",", ":"), sort_keys=True))
        else:
            print_json(payload)

        return 0
    except Exception as exc:
        return exit_with_error(str(exc))


def handle_schedule_create(args: argparse.Namespace) -> int:
    try:
        config_path = None
        resolved_config_path = resolve_default_config_path(args.config_path)

        if args.config_path:
            if not resolved_config_path.exists():
                raise FileNotFoundError(
                    f"Config file does not exist: {resolved_config_path}"
                )
            config_path = str(resolved_config_path)
        elif resolved_config_path.exists():
            config_path = str(resolved_config_path)

        request = ScheduleRequest(
            task_name=args.task_name,
            python_executable=args.python_executable,
            config_path=config_path,
            frequency=args.frequency,
            modifier=args.modifier,
            start_time=args.start_time,
            day_of_week=args.day_of_week,
            backup_arguments=args.backup_argument,
            force=args.force,
            run_highest=args.run_highest,
            print_only=args.print_only,
        )
        return create_schedule(request)
    except Exception as exc:
        return exit_with_error(str(exc))


def handle_schedule_list(args: argparse.Namespace) -> int:
    try:
        return list_schedule(args.task_name)
    except Exception as exc:
        return exit_with_error(str(exc))


def handle_schedule_delete(args: argparse.Namespace) -> int:
    try:
        return delete_schedule(args.task_name, force=args.force)
    except Exception as exc:
        return exit_with_error(str(exc))


def handle_schedule_run(args: argparse.Namespace) -> int:
    try:
        return run_schedule(args.task_name)
    except Exception as exc:
        return exit_with_error(str(exc))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)

    if handler is None:
        parser.print_help()
        return 2

    return int(handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
