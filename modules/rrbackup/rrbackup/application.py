"""Canonical hierarchical command-line application for merged backup management."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .audit import collect_audit
from .command_contract import AUDIT_SECTION_NAMES, MAJOR_COMMANDS
from .engine import BackupEngine
from .health import HealthReport, evaluate_health
from .locking import LockError, ProcessLock
from .models import ExecutionMode, RunRecord, RunState
from .profile import BackupProfile, discover_legacy_config, load_legacy_profile
from .repository_ops import RepositoryClient, RepositoryOperation, operation_to_dict
from .restic import ResticCommandError, build_restic_command, execute_restic
from .schedule_discovery import ScheduleDiscovery, discover_schedules
from .snapshots import SnapshotRecord
from .state import RunStateStore
from .version import __version__

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_OPERATION_FAILED = 3
EXIT_UNHEALTHY = 4
EXIT_SKIPPED = 10

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


def _program_name() -> str:
    name = Path(sys.argv[0]).stem.lower()
    return name if name in {"backup", "rrb", "rrbackup"} else "backup"


def _add_output_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-j", "--json", action="store_true", help="Emit JSON only on stdout.")
    parser.add_argument("-M", "--markdown", action="store_true", help="Emit Markdown output.")


def _add_global_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-c",
        "--config",
        "--config-path",
        "--config_path",
        dest="config_path",
        help="Legacy JSON configuration path.",
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


def build_parser(program_name: Optional[str] = None) -> argparse.ArgumentParser:
    """Build the canonical six-area parser."""

    parser = argparse.ArgumentParser(
        prog=program_name or _program_name(),
        description=(
            "Unified Restic backup management, viewer, scheduling, restore, and repository CLI."
        ),
        epilog=(
            "Areas: run, view, config, schedule, restore, repository.\n"
            "Alias: edit -> config. Compatibility commands: rrb, rrbackup, backup_module.\n"
            "Inspection is read-only by default; mutation requires an explicit action flag."
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
    _add_run_parser(areas)
    _add_view_parser(areas)
    _add_config_parser(areas)
    _add_schedule_parser(areas)
    _add_restore_parser(areas)
    _add_repository_parser(areas)
    return parser


def _add_run_parser(areas: argparse._SubParsersAction) -> None:
    parser = areas.add_parser("run", help="Execute, dry-run, or preview a backup.")
    parser.add_argument("set_name", nargs="?", default="local-main")
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
    parser.add_argument("-S", "--sources-file", "--sources_file", dest="sources_file")
    parser.add_argument("-E", "--excludes-file", "--excludes_file", dest="excludes_file")
    _add_output_options(parser)
    parser.set_defaults(handler=_handle_run)


def _add_view_parser(areas: argparse._SubParsersAction) -> None:
    parser = areas.add_parser("view", help="View dashboard, history, health, and diagnostics.")
    _add_output_options(parser)
    operations = parser.add_subparsers(dest="view_command")
    parser.set_defaults(handler=_handle_view_dashboard, view_command="dashboard")

    simple = {
        "dashboard": ("Show the health dashboard.", _handle_view_dashboard),
        "timeline": ("Show snapshot and run history.", _handle_view_timeline),
        "snapshots": ("List snapshots.", _handle_view_snapshots),
        "runs": ("List merged-engine run records.", _handle_view_runs),
        "logs": ("Show recent backup log lines.", _handle_view_logs),
        "storage": ("Show repository restore-size statistics.", _handle_view_storage),
        "gaps": ("Show overdue and missing-backup findings.", _handle_view_health),
        "health": ("Evaluate backup health.", _handle_view_health),
        "schedules": ("Show discovered schedules.", _handle_view_schedules),
        "setup": ("Show configured paths and inputs.", _handle_view_setup),
        "system": ("Show runtime and executable diagnostics.", _handle_view_system),
        "provenance": ("Show evidence-backed lineage.", _handle_view_provenance),
        "alerts": ("Show alert-relevant health findings.", _handle_view_health),
    }
    for name, (help_text, handler) in simple.items():
        child = operations.add_parser(name, help=help_text)
        _add_output_options(child)
        child.set_defaults(handler=handler)

    snapshot = operations.add_parser("snapshot", help="Show one snapshot by ID or prefix.")
    snapshot.add_argument("snapshot_id")
    _add_output_options(snapshot)
    snapshot.set_defaults(handler=_handle_view_snapshot)

    run = operations.add_parser("run", help="Show one run record by ID or prefix.")
    run.add_argument("run_id")
    _add_output_options(run)
    run.set_defaults(handler=_handle_view_run)

    search = operations.add_parser("search", help="Search snapshots with Restic find.")
    search.add_argument("patterns", nargs="+")
    search.add_argument("-s", "--snapshot-id", "--snapshot_id")
    search.add_argument("-i", "--ignore-case", "--ignore_case", action="store_true")
    _add_output_options(search)
    search.set_defaults(handler=_handle_view_search)

    audit = operations.add_parser("audit", help="Collect the complete read-only backup audit.")
    audit.add_argument("-s", "--section", action="append", choices=AUDIT_SECTION_NAMES, default=[])
    audit.add_argument("-L", "--include-legacy-evidence", action="store_true")
    audit.add_argument("-r", "--redact-paths", action="store_true")
    _add_output_options(audit)
    audit.set_defaults(handler=_handle_view_audit)

    export = operations.add_parser("export", help="Export the complete audit.")
    export.add_argument("-o", "--output", required=True)
    export.add_argument("-F", "--format", choices=("json", "markdown"), default="json")
    export.add_argument("-L", "--include-legacy-evidence", action="store_true")
    export.set_defaults(handler=_handle_view_export)


def _add_config_parser(areas: argparse._SubParsersAction) -> None:
    parser = areas.add_parser("config", help="Discover, inspect, validate, and migrate configuration.")
    operations = parser.add_subparsers(dest="config_command", required=True)
    commands = {
        "show": ("Show effective configuration.", _handle_config_effective),
        "effective": ("Show values and source attribution.", _handle_config_effective),
        "path": ("Show the discovered legacy config path.", _handle_config_path),
        "validate": ("Validate profile and input paths.", _handle_config_validate),
        "discover": ("Discover backup artifacts.", _handle_config_discover),
        "import-legacy": ("Preview legacy configuration import.", _handle_config_import),
        "profiles": ("List profiles.", _handle_config_profiles),
        "sets": ("List backup sets.", _handle_config_profiles),
    }
    for name, (help_text, handler) in commands.items():
        child = operations.add_parser(name, help=help_text)
        _add_output_options(child)
        child.set_defaults(handler=handler)


def _add_schedule_parser(areas: argparse._SubParsersAction) -> None:
    parser = areas.add_parser("schedule", help="Discover and diagnose schedules.")
    operations = parser.add_subparsers(dest="schedule_command", required=True)
    commands = {
        "list": ("List discovered schedules.", _handle_schedule_list),
        "discover": ("Discover scheduler definitions.", _handle_schedule_list),
        "health": ("Evaluate schedule and backup health.", _handle_view_health),
        "history": ("Show available scheduler history.", _handle_schedule_history),
    }
    for name, (help_text, handler) in commands.items():
        child = operations.add_parser(name, help=help_text)
        _add_output_options(child)
        child.set_defaults(handler=handler)
    show = operations.add_parser("show", help="Show one discovered schedule.")
    show.add_argument("name")
    _add_output_options(show)
    show.set_defaults(handler=_handle_schedule_show)


def _add_restore_parser(areas: argparse._SubParsersAction) -> None:
    parser = areas.add_parser("restore", help="Search, preview, and explicitly run safe restores.")
    operations = parser.add_subparsers(dest="restore_command", required=True)

    search = operations.add_parser("search", help="Search snapshots.")
    search.add_argument("patterns", nargs="+")
    search.add_argument("-s", "--snapshot-id", "--snapshot_id")
    search.add_argument("-i", "--ignore-case", "--ignore_case", action="store_true")
    _add_output_options(search)
    search.set_defaults(handler=_handle_view_search)

    preview = operations.add_parser("preview", help="Preview a restore command.")
    _add_restore_arguments(preview, include_apply=False)
    preview.set_defaults(handler=_handle_restore, restore_apply=False)

    run = operations.add_parser("run", help="Run a restore only with --apply.")
    _add_restore_arguments(run, include_apply=True)
    run.set_defaults(handler=_handle_restore, restore_apply=True)

    for name in ("verify", "history"):
        child = operations.add_parser(name, help="Show {0} availability.".format(name))
        _add_output_options(child)
        child.set_defaults(handler=_handle_restore_unavailable)


def _add_restore_arguments(parser: argparse.ArgumentParser, *, include_apply: bool) -> None:
    parser.add_argument("snapshot_id", nargs="?", default="latest")
    parser.add_argument("-T", "--target", required=True)
    parser.add_argument("-i", "--include", action="append", default=[])
    parser.add_argument("-e", "--exclude", action="append", default=[])
    if include_apply:
        parser.add_argument("-y", "--apply", action="store_true")
    _add_output_options(parser)


def _add_repository_parser(areas: argparse._SubParsersAction) -> None:
    parser = areas.add_parser("repository", help="Inspect and explicitly maintain the repository.")
    operations = parser.add_subparsers(dest="repository_command", required=True)

    status = operations.add_parser("status", help="Show repository format and availability.")
    _add_output_options(status)
    status.set_defaults(handler=_handle_repository_status)

    keys = operations.add_parser("keys", help="List key metadata without key material.")
    _add_output_options(keys)
    keys.set_defaults(handler=_handle_repository_keys)

    locks = operations.add_parser("locks", help="List repository locks.")
    _add_output_options(locks)
    locks.set_defaults(handler=_handle_repository_locks)

    stats = operations.add_parser("stats", help="Show repository statistics.")
    stats.add_argument("-m", "--mode", default="restore-size")
    _add_output_options(stats)
    stats.set_defaults(handler=_handle_repository_stats)

    check = operations.add_parser("check", help="Run repository integrity checks.")
    check.add_argument("-d", "--read-data", action="store_true")
    _add_output_options(check)
    check.set_defaults(handler=_handle_repository_check)

    cache = operations.add_parser("cache", help="Inspect cache status.")
    cache_operations = cache.add_subparsers(dest="cache_command", required=True)
    cache_status = cache_operations.add_parser("status", help="Show cache status without cleanup.")
    _add_output_options(cache_status)
    cache_status.set_defaults(handler=_handle_repository_cache)

    init = operations.add_parser("init", help="Initialize only with --apply.")
    init.add_argument("-y", "--apply", action="store_true")
    _add_output_options(init)
    init.set_defaults(handler=_handle_repository_init)

    retention = operations.add_parser("retention", help="Preview scoped retention policy.")
    retention_operations = retention.add_subparsers(dest="retention_command", required=True)
    for name in ("show", "preview"):
        child = retention_operations.add_parser(name)
        _add_output_options(child)
        child.set_defaults(handler=_handle_repository_retention)


def _split_global_prefix(argv: Sequence[str]) -> Tuple[List[str], List[str]]:
    prefix: List[str] = []
    index = 0
    values = list(argv)
    while index < len(values) and values[index].startswith("-"):
        option = values[index]
        prefix.append(option)
        index += 1
        if option in _GLOBAL_VALUE_OPTIONS and index < len(values):
            prefix.append(values[index])
            index += 1
    return prefix, values[index:]


def _translate_legacy(argv: Sequence[str]) -> Tuple[List[str], bool]:
    prefix, remainder = _split_global_prefix(argv)
    if not remainder:
        return list(argv), False
    command = remainder[0]
    tail = remainder[1:]
    if command == "edit":
        return prefix + ["config"] + tail, False
    if command in {"list", "ls", "snapshots"}:
        return prefix + ["view", "snapshots"] + tail, False
    if command == "stats":
        return prefix + ["repository", "stats"] + tail, False
    if command == "check":
        return prefix + ["repository", "check"] + tail, False
    if command == "progress":
        return prefix + ["view", "health"] + tail, False
    if command == "backup":
        set_name = "local-main"
        translated: List[str] = ["run"]
        index = 0
        while index < len(tail):
            value = tail[index]
            if value in {"--set", "-s"} and index + 1 < len(tail):
                set_name = tail[index + 1]
                index += 2
                continue
            if value in {"--extra", "-x"} and index + 1 < len(tail):
                translated.extend(["--restic-arg", tail[index + 1]])
                index += 2
                continue
            translated.append(value)
            index += 1
        translated.insert(1, set_name)
        return prefix + translated, False
    legacy_config_commands = {"init", "wizard", "list-sets", "add-set", "remove-set", "set", "retention"}
    if command in {"setup", "prune"} or (
        command == "config" and tail and tail[0] in legacy_config_commands
    ):
        return list(argv), True
    return list(argv), False


def _profile_overrides(args: argparse.Namespace) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for attribute in (
        "repository",
        "password_file",
        "restic_executable",
        "sources_file",
        "excludes_file",
    ):
        value = getattr(args, attribute, None)
        if value:
            result[attribute] = value
    return result


def _load_profile(args: argparse.Namespace) -> BackupProfile:
    profile, _ = load_legacy_profile(
        getattr(args, "config_path", None),
        overrides=_profile_overrides(args),
    )
    set_name = getattr(args, "set_name", None)
    if set_name:
        profile.name = set_name
    return profile


def _state_store(profile: BackupProfile) -> RunStateStore:
    return RunStateStore(Path(profile.status_file).parent / "rrbackup-state")


def _emit(
    payload: Any,
    args: argparse.Namespace,
    *,
    text: Optional[str] = None,
    markdown: Optional[str] = None,
) -> None:
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    elif getattr(args, "markdown", False):
        print(
            markdown
            if markdown is not None
            else "```json\n{0}\n```".format(json.dumps(payload, indent=2, default=str))
        )
    else:
        print(text if text is not None else json.dumps(payload, indent=2, sort_keys=True, default=str))


def _snapshots(profile: BackupProfile) -> Tuple[List[SnapshotRecord], int]:
    records, result = RepositoryClient(profile).snapshots(
        tags=(() if not profile.tag else (profile.tag,))
    )
    return records, int(result.return_code or 0)


def _health(profile: BackupProfile) -> Tuple[HealthReport, List[SnapshotRecord]]:
    snapshots, _ = _snapshots(profile)
    return (
        evaluate_health(
            profile,
            snapshots=snapshots,
            latest_run=_state_store(profile).load_latest(),
            lock=ProcessLock(profile.lock_file).inspect(),
        ),
        snapshots,
    )


def _handle_run(args: argparse.Namespace) -> int:
    profile = _load_profile(args)
    extra = list(profile.extra_backup_args)
    for value in args.tag:
        extra.extend(["--tag", value])
    for value in args.exclude:
        extra.extend(["--exclude", value])
    extra.extend(args.restic_arg)
    profile.extra_backup_args = extra
    engine = BackupEngine(profile)

    if args.print_command_only:
        result = engine.preview()
        payload = {
            "mode": "preview",
            "executed": result.executed,
            "command": result.command.render(redacted=True),
        }
        _emit(payload, args, text=payload["command"])
        return EXIT_OK

    mode = ExecutionMode.DRY_RUN if args.dry_run else ExecutionMode.RUN
    result = engine.run(mode=mode, respect_cpu_policy=not args.ignore_cpu_policy)
    payload = {
        "record": result.record.to_dict(),
        "summary": None if result.summary is None else result.summary.to_dict(),
        "executed": None if result.execution is None else result.execution.executed,
    }
    _emit(
        payload,
        args,
        text="{0}: {1}".format(
            result.record.state.value,
            result.record.reason or result.record.run_id,
        ),
    )
    if result.record.state == RunState.SKIPPED:
        return EXIT_SKIPPED
    if result.record.state in {RunState.SUCCESS, RunState.DRY_RUN}:
        return EXIT_OK
    return EXIT_OPERATION_FAILED


def _handle_view_snapshots(args: argparse.Namespace) -> int:
    snapshots, return_code = _snapshots(_load_profile(args))
    payload = [snapshot.to_dict() for snapshot in snapshots]
    text = "\n".join(
        "{0}  {1}  {2}  {3}".format(
            snapshot.short_id,
            snapshot.time.astimezone().isoformat(timespec="seconds"),
            snapshot.hostname or "-",
            ",".join(snapshot.tags) or "-",
        )
        for snapshot in snapshots
    )
    _emit(payload, args, text=text or "No snapshots found.")
    return EXIT_OK if return_code == 0 else EXIT_OPERATION_FAILED


def _handle_view_snapshot(args: argparse.Namespace) -> int:
    snapshots, return_code = _snapshots(_load_profile(args))
    matches = [
        value
        for value in snapshots
        if value.snapshot_id.startswith(args.snapshot_id)
        or value.short_id.startswith(args.snapshot_id)
    ]
    if len(matches) != 1:
        raise ValueError("Snapshot ID matched {0} snapshots; exactly one is required.".format(len(matches)))
    _emit(matches[0].to_dict(), args)
    return EXIT_OK if return_code == 0 else EXIT_OPERATION_FAILED


def _read_runs(profile: BackupProfile) -> List[RunRecord]:
    store = _state_store(profile)
    result: List[RunRecord] = []
    if store.runs_root.exists():
        for path in store.runs_root.glob("*.json"):
            record = store.load_run(path.stem)
            if record is not None:
                result.append(record)
    return sorted(result, key=lambda value: value.created_utc, reverse=True)


def _handle_view_runs(args: argparse.Namespace) -> int:
    records = _read_runs(_load_profile(args))
    payload = [record.to_dict() for record in records]
    text = "\n".join(
        "{0}  {1}  {2}".format(
            record.created_utc.astimezone().isoformat(timespec="seconds"),
            record.state.value,
            record.run_id,
        )
        for record in records
    )
    _emit(payload, args, text=text or "No structured run records found.")
    return EXIT_OK


def _handle_view_run(args: argparse.Namespace) -> int:
    matches = [record for record in _read_runs(_load_profile(args)) if record.run_id.startswith(args.run_id)]
    if len(matches) != 1:
        raise ValueError("Run ID matched {0} runs; exactly one is required.".format(len(matches)))
    _emit(matches[0].to_dict(), args)
    return EXIT_OK


def _handle_view_timeline(args: argparse.Namespace) -> int:
    profile = _load_profile(args)
    snapshots, return_code = _snapshots(profile)
    events: List[Tuple[datetime, str, Dict[str, Any]]] = []
    events.extend((value.time, "snapshot", value.to_dict()) for value in snapshots)
    events.extend((value.created_utc, "run", value.to_dict()) for value in _read_runs(profile))
    events.sort(key=lambda value: value[0], reverse=True)
    payload = [
        {"time": time.isoformat(), "type": kind, "data": data}
        for time, kind, data in events
    ]
    lines = []
    for time, kind, data in events:
        if kind == "snapshot":
            lines.append(
                "● {0}  SNAPSHOT {1}  {2}".format(
                    time.astimezone().isoformat(timespec="seconds"),
                    data["short_id"],
                    ",".join(data["tags"]) or "-",
                )
            )
        else:
            lines.append(
                "○ {0}  RUN {1}  {2}".format(
                    time.astimezone().isoformat(timespec="seconds"),
                    data["state"].upper(),
                    data["run_id"][:8],
                )
            )
    _emit(payload, args, text="\n│\n".join(lines) or "No history found.")
    return EXIT_OK if return_code == 0 else EXIT_OPERATION_FAILED


def _handle_view_dashboard(args: argparse.Namespace) -> int:
    profile = _load_profile(args)
    report, snapshots = _health(profile)
    lines = [
        "Backup profile: {0}".format(profile.name),
        "Health: {0}".format(report.severity.value.upper()),
        "Snapshots: {0}".format(len(snapshots)),
        "Latest snapshot: {0}".format(
            "none"
            if report.latest_snapshot is None
            else "{0} at {1}".format(
                report.latest_snapshot.short_id,
                report.latest_snapshot.time.astimezone().isoformat(timespec="seconds"),
            )
        ),
        "Latest run: {0}".format(
            "none"
            if report.latest_run is None
            else "{0} ({1})".format(
                report.latest_run.state.value,
                report.latest_run.run_id[:8],
            )
        ),
    ]
    lines.extend(
        "- [{0}] {1}".format(issue.severity.value.upper(), issue.message)
        for issue in report.issues
    )
    _emit(report.to_dict(), args, text="\n".join(lines))
    return EXIT_OK if report.healthy else EXIT_UNHEALTHY


def _handle_view_health(args: argparse.Namespace) -> int:
    return _handle_view_dashboard(args)


def _handle_view_logs(args: argparse.Namespace) -> int:
    path = Path(_load_profile(args).log_file)
    lines = (
        []
        if not path.exists()
        else path.read_text(encoding="utf-8", errors="replace").splitlines()[-100:]
    )
    payload = {"path": str(path), "exists": path.exists(), "lines": lines}
    _emit(payload, args, text="\n".join(lines) or "No log file found.")
    return EXIT_OK


def _handle_view_storage(args: argparse.Namespace) -> int:
    return _emit_repository_operation(RepositoryClient(_load_profile(args)).stats(), args)


def _handle_view_schedules(args: argparse.Namespace) -> int:
    discovery = discover_schedules()
    _emit(discovery.to_dict(), args, text=_schedule_text(discovery))
    return EXIT_OK


def _handle_view_setup(args: argparse.Namespace) -> int:
    return _emit_audit(
        collect_audit(
            _load_profile(args),
            selected_sections=("configuration", "config-files", "paths", "inputs"),
        ),
        args,
    )


def _handle_view_system(args: argparse.Namespace) -> int:
    return _emit_audit(
        collect_audit(
            _load_profile(args),
            selected_sections=("commands", "runtime", "environment"),
        ),
        args,
    )


def _handle_view_provenance(args: argparse.Namespace) -> int:
    return _emit_audit(
        collect_audit(
            _load_profile(args),
            selected_sections=("snapshots", "runs", "provenance", "recommendations"),
        ),
        args,
    )


def _handle_view_audit(args: argparse.Namespace) -> int:
    return _emit_audit(
        collect_audit(
            _load_profile(args),
            selected_sections=args.section,
            include_legacy_evidence=args.include_legacy_evidence,
        ),
        args,
    )


def _emit_audit(report: Any, args: argparse.Namespace) -> int:
    _emit(report.to_dict(), args, markdown=report.to_markdown())
    return EXIT_OK


def _handle_view_export(args: argparse.Namespace) -> int:
    report = collect_audit(
        _load_profile(args),
        include_legacy_evidence=args.include_legacy_evidence,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    content = (
        report.to_markdown()
        if args.format == "markdown"
        else json.dumps(report.to_dict(), indent=2, sort_keys=True, default=str) + "\n"
    )
    output.write_text(content, encoding="utf-8")
    print(str(output))
    return EXIT_OK


def _handle_view_search(args: argparse.Namespace) -> int:
    profile = _load_profile(args)
    arguments = ["find"]
    if getattr(args, "snapshot_id", None):
        arguments.extend(["-s", args.snapshot_id])
    if getattr(args, "ignore_case", False):
        arguments.append("-i")
    if getattr(args, "json", False):
        arguments.append("--json")
    arguments.extend(args.patterns)
    result = RepositoryClient(profile).execute(arguments)
    text = "".join(result.output)
    print(text.strip() or "[]" if getattr(args, "json", False) else text, end="\n" if not text.endswith("\n") else "")
    return EXIT_OK if result.return_code == 0 else EXIT_OPERATION_FAILED


def _handle_config_effective(args: argparse.Namespace) -> int:
    _emit(_load_profile(args).to_public_dict(), args)
    return EXIT_OK


def _handle_config_path(args: argparse.Namespace) -> int:
    path = discover_legacy_config(getattr(args, "config_path", None))
    payload = {"path": None if path is None else str(path), "exists": bool(path and path.exists())}
    _emit(payload, args, text=payload["path"] or "No legacy config file found; built-in defaults apply.")
    return EXIT_OK


def _handle_config_validate(args: argparse.Namespace) -> int:
    profile = _load_profile(args)
    profile.validate()
    missing = [
        raw
        for raw in (profile.password_file, profile.sources_file)
        if raw and not Path(raw).exists()
    ]
    payload = {
        "valid": not missing,
        "missing_required_files": missing,
        "profile": profile.to_public_dict(),
    }
    _emit(
        payload,
        args,
        text="Configuration is valid."
        if not missing
        else "Missing: {0}".format(", ".join(missing)),
    )
    return EXIT_OK if not missing else EXIT_OPERATION_FAILED


def _handle_config_discover(args: argparse.Namespace) -> int:
    return _handle_view_setup(args)


def _handle_config_import(args: argparse.Namespace) -> int:
    payload = {
        "mode": "preview",
        "write_performed": False,
        "profile": _load_profile(args).to_public_dict(),
        "next_step": "Explicit TOML output and --apply are required before import can write.",
    }
    _emit(payload, args)
    return EXIT_OK


def _handle_config_profiles(args: argparse.Namespace) -> int:
    profile = _load_profile(args)
    payload = [
        {
            "name": profile.name,
            "tag": profile.tag,
            "source": "legacy/default-compatible",
        }
    ]
    _emit(payload, args, text="{0}\t{1}".format(profile.name, profile.tag or "-"))
    return EXIT_OK


def _schedule_text(discovery: ScheduleDiscovery) -> str:
    if not discovery.records:
        return "\n".join(discovery.warnings) or "No backup-related schedules discovered."
    return "\n".join(
        "{0}  {1}  {2}".format(
            record.state or "-",
            record.identifier,
            record.next_run or "-",
        )
        for record in discovery.records
    )


def _handle_schedule_list(args: argparse.Namespace) -> int:
    discovery = discover_schedules()
    _emit(discovery.to_dict(), args, text=_schedule_text(discovery))
    return EXIT_OK


def _handle_schedule_show(args: argparse.Namespace) -> int:
    discovery = discover_schedules()
    matches = [
        value
        for value in discovery.records
        if args.name.lower() in value.identifier.lower()
    ]
    if len(matches) != 1:
        raise ValueError("Schedule name matched {0} records; exactly one is required.".format(len(matches)))
    _emit(matches[0].to_dict(), args)
    return EXIT_OK


def _handle_schedule_history(args: argparse.Namespace) -> int:
    payload = {
        "available": False,
        "reason": "Detailed scheduler event history is planned for Stage 3.",
        "discovery": discover_schedules().to_dict(),
    }
    _emit(payload, args)
    return EXIT_OK


def _handle_restore(args: argparse.Namespace) -> int:
    profile = _load_profile(args)
    arguments = ["restore", args.snapshot_id, "--target", args.target]
    for value in args.include:
        arguments.extend(["--iinclude", value])
    for value in args.exclude:
        arguments.extend(["--iexclude", value])
    command = build_restic_command(
        restic_executable=profile.restic_executable,
        repository=profile.repository,
        arguments=arguments,
        password_file=profile.password_file,
    )
    if not args.restore_apply:
        payload = {
            "mode": "preview",
            "executed": False,
            "command": command.render(redacted=True),
        }
        _emit(payload, args, text=payload["command"])
        return EXIT_OK
    if not args.apply:
        raise ValueError("restore run requires --apply.")
    result = execute_restic(command, echo=not getattr(args, "json", False))
    payload = {
        "command": command.render(redacted=True),
        "return_code": result.return_code,
        "succeeded": result.succeeded,
    }
    _emit(payload, args)
    return EXIT_OK if result.succeeded else EXIT_OPERATION_FAILED


def _handle_restore_unavailable(args: argparse.Namespace) -> int:
    _emit(
        {
            "available": False,
            "reason": "Structured restore history and hash verification follow compatibility merge.",
        },
        args,
    )
    return EXIT_OK


def _emit_repository_operation(operation: RepositoryOperation, args: argparse.Namespace) -> int:
    _emit(operation_to_dict(operation), args)
    return EXIT_OK if operation.result.succeeded else EXIT_OPERATION_FAILED


def _handle_repository_status(args: argparse.Namespace) -> int:
    return _emit_repository_operation(RepositoryClient(_load_profile(args)).status(), args)


def _handle_repository_keys(args: argparse.Namespace) -> int:
    return _emit_repository_operation(RepositoryClient(_load_profile(args)).keys(), args)


def _handle_repository_locks(args: argparse.Namespace) -> int:
    return _emit_repository_operation(RepositoryClient(_load_profile(args)).locks(), args)


def _handle_repository_stats(args: argparse.Namespace) -> int:
    return _emit_repository_operation(
        RepositoryClient(_load_profile(args)).stats(mode=args.mode),
        args,
    )


def _handle_repository_check(args: argparse.Namespace) -> int:
    return _emit_repository_operation(
        RepositoryClient(_load_profile(args)).check(read_data=args.read_data),
        args,
    )


def _handle_repository_cache(args: argparse.Namespace) -> int:
    return _emit_repository_operation(RepositoryClient(_load_profile(args)).cache_status(), args)


def _handle_repository_init(args: argparse.Namespace) -> int:
    if not args.apply:
        raise ValueError("repository init requires --apply.")
    profile = _load_profile(args)
    result = RepositoryClient(profile).execute(["init"], echo=not args.json)
    _emit(
        {"return_code": result.return_code, "succeeded": result.succeeded},
        args,
    )
    return EXIT_OK if result.succeeded else EXIT_OPERATION_FAILED


def _handle_repository_retention(args: argparse.Namespace) -> int:
    _emit(
        {
            "mode": args.retention_command,
            "mutation_allowed": False,
            "reason": "Scoped ownership tags and isolation are required before retention application.",
        },
        args,
    )
    return EXIT_OK


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    program_name: Optional[str] = None,
) -> int:
    """Parse and dispatch the canonical CLI with compatibility translation."""

    raw = list(sys.argv[1:] if argv is None else argv)
    translated, use_legacy = _translate_legacy(raw)
    if use_legacy:
        from .cli import main as legacy_main

        return int(legacy_main(raw))

    parser = build_parser(program_name=program_name)
    try:
        args = parser.parse_args(translated)
        return int(args.handler(args))
    except (OSError, ValueError, json.JSONDecodeError, ResticCommandError, LockError) as exc:
        print("{0}: {1}".format(parser.prog, exc), file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:
        print("{0}: interrupted".format(parser.prog), file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
