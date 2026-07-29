"""Canonical hierarchical command-line application for merged backup management."""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .audit import AuditReport, collect_audit
from .command_contract import AUDIT_SECTION_NAMES, MAJOR_COMMANDS
from .engine import BackupEngine
from .health import HealthReport, evaluate_health
from .locking import ProcessLock
from .models import ExecutionMode, RunRecord, RunState
from .profile import BackupProfile, discover_legacy_config, load_legacy_profile, read_path_list
from .repository_ops import RepositoryClient, RepositoryOperation, operation_to_dict
from .restic import build_restic_command, execute_restic
from .schedule_discovery import ScheduleDiscovery, discover_schedules
from .snapshots import SnapshotRecord
from .state import RunStateStore
from .version import __version__


EXIT_OK = 0
EXIT_USAGE = 2
EXIT_OPERATION_FAILED = 3
EXIT_UNHEALTHY = 4


def _program_name() -> str:
    raw = Path(sys.argv[0]).stem.lower()
    return raw if raw in {"backup", "rrb", "rrbackup"} else "backup"


def _add_output_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-j", "--json", action="store_true", help="Emit JSON only on stdout.")
    parser.add_argument("-m", "--markdown", action="store_true", help="Emit Markdown output.")


def _add_global_profile_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-c",
        "--config",
        "--config-path",
        "--config_path",
        dest="config_path",
        help="Legacy JSON config path. Defaults and environment discovery remain supported.",
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
            "Unified Restic backup management, diagnostics, scheduling, restore, and repository CLI."
        ),
        epilog=(
            "Major areas: run, view, config, schedule, restore, repository.\n"
            "Alias: 'edit' resolves to 'config'. Compatibility commands: rrb, rrbackup, backup_module.\n"
            "Read-only inspection is the default; mutation requires an explicit action option."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("-V", "--version", action="version", version="%(prog)s {0}".format(__version__))
    _add_global_profile_options(parser)

    areas = parser.add_subparsers(dest="area", required=True, metavar="{" + ",".join(MAJOR_COMMANDS) + "}")
    _add_run_parser(areas)
    _add_view_parser(areas)
    _add_config_parser(areas)
    _add_schedule_parser(areas)
    _add_restore_parser(areas)
    _add_repository_parser(areas)
    return parser


def _add_run_parser(areas: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = areas.add_parser("run", help="Execute, dry-run, or preview a backup.")
    parser.add_argument("set_name", nargs="?", default="local-main", help="Backup set/profile name.")
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


def _add_view_parser(areas: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = areas.add_parser("view", help="View dashboard, timeline, snapshots, runs, health, and audits.")
    operations = parser.add_subparsers(dest="view_command")
    parser.set_defaults(handler=_handle_view_dashboard, view_command="dashboard")

    for name, help_text, handler in (
        ("dashboard", "Show the backup health dashboard.", _handle_view_dashboard),
        ("timeline", "Show snapshot and run history as a timeline.", _handle_view_timeline),
        ("snapshots", "List available snapshots.", _handle_view_snapshots),
        ("runs", "List structured merged-engine run records.", _handle_view_runs),
        ("logs", "Show recent backup log lines.", _handle_view_logs),
        ("storage", "Show repository restore-size statistics.", _handle_view_storage),
        ("gaps", "Show overdue and missing-backup findings.", _handle_view_health),
        ("health", "Evaluate backup health and return stable status.", _handle_view_health),
        ("schedules", "Show discovered backup schedules.", _handle_view_schedules),
        ("setup", "Show configured paths and source/exclusion inputs.", _handle_view_setup),
        ("system", "Show executable, runtime, and environment diagnostics.", _handle_view_system),
        ("provenance", "Show evidence-backed backup lineage.", _handle_view_provenance),
        ("alerts", "Show alert-relevant health findings.", _handle_view_health),
    ):
        child = operations.add_parser(name, help=help_text)
        _add_output_options(child)
        child.set_defaults(handler=handler)

    snapshot = operations.add_parser("snapshot", help="Show one snapshot by ID or prefix.")
    snapshot.add_argument("snapshot_id")
    _add_output_options(snapshot)
    snapshot.set_defaults(handler=_handle_view_snapshot)

    run = operations.add_parser("run", help="Show one structured run record.")
    run.add_argument("run_id")
    _add_output_options(run)
    run.set_defaults(handler=_handle_view_run)

    search = operations.add_parser("search", help="Search snapshots using Restic find.")
    search.add_argument("patterns", nargs="+")
    search.add_argument("-s", "--snapshot-id", "--snapshot_id", default=None)
    search.add_argument("-i", "--ignore-case", "--ignore_case", action="store_true")
    _add_output_options(search)
    search.set_defaults(handler=_handle_view_search)

    audit = operations.add_parser("audit", help="Collect the comprehensive read-only backup audit.")
    audit.add_argument("-s", "--section", action="append", choices=AUDIT_SECTION_NAMES, default=[])
    audit.add_argument("-L", "--include-legacy-evidence", action="store_true")
    audit.add_argument("-r", "--redact-paths", action="store_true")
    _add_output_options(audit)
    audit.set_defaults(handler=_handle_view_audit)

    export = operations.add_parser("export", help="Export the comprehensive audit.")
    export.add_argument("-o", "--output", required=True)
    export.add_argument("-F", "--format", choices=("json", "markdown"), default="json")
    export.add_argument("-L", "--include-legacy-evidence", action="store_true")
    export.set_defaults(handler=_handle_view_export)


def _add_config_parser(areas: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = areas.add_parser("config", help="Discover, inspect, validate, and migrate configuration.")
    operations = parser.add_subparsers(dest="config_command", required=True)
    for name, help_text, handler in (
        ("show", "Show effective configuration.", _handle_config_effective),
        ("effective", "Show values and source attribution.", _handle_config_effective),
        ("path", "Show the discovered legacy config path.", _handle_config_path),
        ("validate", "Validate the effective profile and input paths.", _handle_config_validate),
        ("discover", "Discover canonical and legacy backup artifacts.", _handle_config_discover),
        ("import-legacy", "Preview legacy-to-canonical configuration import.", _handle_config_import),
        ("profiles", "List available profiles.", _handle_config_profiles),
        ("sets", "List available backup sets.", _handle_config_profiles),
    ):
        child = operations.add_parser(name, help=help_text)
        _add_output_options(child)
        child.set_defaults(handler=handler)


def _add_schedule_parser(areas: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = areas.add_parser("schedule", help="Discover and diagnose backup schedules.")
    operations = parser.add_subparsers(dest="schedule_command", required=True)
    for name, help_text, handler in (
        ("list", "List discovered backup schedules.", _handle_schedule_list),
        ("discover", "Discover scheduler and launcher definitions.", _handle_schedule_list),
        ("health", "Evaluate schedule and backup health.", _handle_view_health),
        ("history", "Show available scheduler history metadata.", _handle_schedule_history),
    ):
        child = operations.add_parser(name, help=help_text)
        _add_output_options(child)
        child.set_defaults(handler=handler)

    show = operations.add_parser("show", help="Show one discovered schedule.")
    show.add_argument("name")
    _add_output_options(show)
    show.set_defaults(handler=_handle_schedule_show)


def _add_restore_parser(areas: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = areas.add_parser("restore", help="Search, preview, and explicitly run safe restores.")
    operations = parser.add_subparsers(dest="restore_command", required=True)

    search = operations.add_parser("search", help="Search snapshots for files or folders.")
    search.add_argument("patterns", nargs="+")
    search.add_argument("-s", "--snapshot-id", default=None)
    search.add_argument("-i", "--ignore-case", action="store_true")
    _add_output_options(search)
    search.set_defaults(handler=_handle_view_search)

    for name, apply in (("preview", False), ("run", True)):
        child = operations.add_parser(name, help="{0} a restore operation.".format(name.title()))
        child.add_argument("snapshot_id", nargs="?", default="latest")
        child.add_argument("-T", "--target", required=True)
        child.add_argument("-i", "--include", action="append", default=[])
        child.add_argument("-e", "--exclude", action="append", default=[])
        if apply:
            child.add_argument("-y", "--apply", action="store_true", help="Required to execute restore.")
        _add_output_options(child)
        child.set_defaults(handler=_handle_restore, restore_apply=apply)

    verify = operations.add_parser("verify", help="Report restore verification availability.")
    _add_output_options(verify)
    verify.set_defaults(handler=_handle_restore_verify)

    history = operations.add_parser("history", help="Show restore history availability.")
    _add_output_options(history)
    history.set_defaults(handler=_handle_restore_verify)


def _add_repository_parser(areas: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = areas.add_parser("repository", help="Inspect and explicitly maintain the Restic repository.")
    operations = parser.add_subparsers(dest="repository_command", required=True)

    for name, help_text, handler in (
        ("status", "Show repository format and availability.", _handle_repository_status),
        ("keys", "List key metadata without key material.", _handle_repository_keys),
        ("locks", "List Restic repository locks.", _handle_repository_locks),
        ("stats", "Show repository statistics.", _handle_repository_stats),
        ("check", "Run Restic repository integrity checks.", _handle_repository_check),
    ):
        child = operations.add_parser(name, help=help_text)
        if name == "stats":
            child.add_argument("-m", "--mode", default="restore-size")
        if name == "check":
            child.add_argument("-d", "--read-data", action="store_true")
        _add_output_options(child)
        child.set_defaults(handler=handler)

    cache = operations.add_parser("cache", help="Inspect Restic cache status.")
    cache_ops = cache.add_subparsers(dest="cache_command", required=True)
    cache_status = cache_ops.add_parser("status", help="Show cache status without cleanup.")
    _add_output_options(cache_status)
    cache_status.set_defaults(handler=_handle_repository_cache)

    init = operations.add_parser("init", help="Initialize a repository only with explicit --apply.")
    init.add_argument("-y", "--apply", action="store_true")
    _add_output_options(init)
    init.set_defaults(handler=_handle_repository_init)

    retention = operations.add_parser("retention", help="Retention remains preview-only in this stage.")
    retention_ops = retention.add_subparsers(dest="retention_command", required=True)
    for name in ("show", "preview"):
        child = retention_ops.add_parser(name)
        _add_output_options(child)
        child.set_defaults(handler=_handle_repository_retention)


def _legacy_translation(argv: Sequence[str]) -> Tuple[List[str], bool]:
    values = list(argv)
    if not values:
        return values, False
    if values[0] == "edit":
        values[0] = "config"
        return values, False
    if values[0] in {"list", "ls", "snapshots"}:
        return ["view", "snapshots"] + values[1:], False
    if values[0] == "stats":
        return ["repository", "stats"] + values[1:], False
    if values[0] == "check":
        return ["repository", "check"] + values[1:], False
    if values[0] == "progress":
        return ["view", "health"] + values[1:], False
    if values[0] == "backup":
        set_name = "local-main"
        translated: List[str] = ["run"]
        index = 1
        while index < len(values):
            value = values[index]
            if value in {"--set", "-s"} and index + 1 < len(values):
                set_name = values[index + 1]
                index += 2
                continue
            if value in {"--extra", "-x"} and index + 1 < len(values):
                translated.extend(["--restic-arg", values[index + 1]])
                index += 2
                continue
            translated.append(value)
            index += 1
        translated.insert(1, set_name)
        return translated, False
    if values[0] in {"setup", "prune"}:
        return values, True
    return values, False


def _profile_overrides(args: argparse.Namespace) -> Dict[str, Any]:
    overrides: Dict[str, Any] = {}
    for attribute, field_name in (
        ("repository", "repository"),
        ("password_file", "password_file"),
        ("restic_executable", "restic_executable"),
        ("sources_file", "sources_file"),
        ("excludes_file", "excludes_file"),
    ):
        value = getattr(args, attribute, None)
        if value:
            overrides[field_name] = value
    return overrides


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


def _emit(payload: Any, args: argparse.Namespace, *, text: Optional[str] = None, markdown: Optional[str] = None) -> None:
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    if getattr(args, "markdown", False):
        print(markdown if markdown is not None else "```json\n{0}\n```".format(json.dumps(payload, indent=2, default=str)))
        return
    print(text if text is not None else json.dumps(payload, indent=2, sort_keys=True, default=str))


def _snapshot_lines(snapshots: Sequence[SnapshotRecord]) -> List[str]:
    lines = []
    for snapshot in snapshots:
        lines.append(
            "{0}  {1}  {2}  {3}".format(
                snapshot.short_id,
                snapshot.time.astimezone().isoformat(timespec="seconds"),
                snapshot.hostname or "-",
                ",".join(snapshot.tags) or "-",
            )
        )
    return lines


def _health_context(profile: BackupProfile) -> Tuple[HealthReport, List[SnapshotRecord]]:
    client = RepositoryClient(profile)
    snapshots, _ = client.snapshots(tags=(() if not profile.tag else (profile.tag,)))
    store = _state_store(profile)
    lock = ProcessLock(profile.lock_file).inspect()
    return evaluate_health(
        profile,
        snapshots=snapshots,
        latest_run=store.load_latest(),
        lock=lock,
    ), snapshots


def _handle_run(args: argparse.Namespace) -> int:
    profile = _load_profile(args)
    extra_arguments = list(profile.extra_backup_args)
    for tag in args.tag:
        extra_arguments.extend(["--tag", tag])
    for exclude in args.exclude:
        extra_arguments.extend(["--exclude", exclude])
    extra_arguments.extend(args.restic_arg)
    profile.extra_backup_args = extra_arguments

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
    _emit(payload, args, text="{0}: {1}".format(result.record.state.value, result.record.reason or result.record.run_id))
    return EXIT_OK if result.record.state in {RunState.SUCCESS, RunState.DRY_RUN, RunState.SKIPPED} else EXIT_OPERATION_FAILED


def _handle_view_snapshots(args: argparse.Namespace) -> int:
    profile = _load_profile(args)
    snapshots, result = RepositoryClient(profile).snapshots(tags=(() if not profile.tag else (profile.tag,)))
    payload = [snapshot.to_dict() for snapshot in snapshots]
    _emit(payload, args, text="\n".join(_snapshot_lines(snapshots)) or "No snapshots found.")
    return EXIT_OK if result.return_code == 0 else EXIT_OPERATION_FAILED


def _handle_view_snapshot(args: argparse.Namespace) -> int:
    profile = _load_profile(args)
    snapshots, result = RepositoryClient(profile).snapshots()
    matches = [snapshot for snapshot in snapshots if snapshot.snapshot_id.startswith(args.snapshot_id) or snapshot.short_id.startswith(args.snapshot_id)]
    if len(matches) != 1:
        raise ValueError("Snapshot ID must match exactly one snapshot; found {0}.".format(len(matches)))
    payload = matches[0].to_dict()
    _emit(payload, args)
    return EXIT_OK if result.return_code == 0 else EXIT_OPERATION_FAILED


def _handle_view_timeline(args: argparse.Namespace) -> int:
    profile = _load_profile(args)
    snapshots, result = RepositoryClient(profile).snapshots(tags=(() if not profile.tag else (profile.tag,)))
    store = _state_store(profile)
    run_records: List[RunRecord] = []
    if store.runs_root.exists():
        for path in store.runs_root.glob("*.json"):
            record = store.load_run(path.stem)
            if record is not None:
                run_records.append(record)
    events: List[Tuple[datetime, str, Dict[str, Any]]] = []
    for snapshot in snapshots:
        events.append((snapshot.time, "snapshot", snapshot.to_dict()))
    for record in run_records:
        events.append((record.created_utc, "run", record.to_dict()))
    events.sort(key=lambda item: item[0], reverse=True)
    payload = [{"time": time.isoformat(), "type": kind, "data": data} for time, kind, data in events]
    lines = []
    for time, kind, data in events:
        if kind == "snapshot":
            lines.append("● {0}  SNAPSHOT {1}  {2}".format(time.astimezone().isoformat(timespec="seconds"), data["short_id"], ",".join(data["tags"]) or "-"))
        else:
            lines.append("○ {0}  RUN {1}  {2}".format(time.astimezone().isoformat(timespec="seconds"), data["state"].upper(), data["run_id"][:8]))
    _emit(payload, args, text="\n│\n".join(lines) or "No snapshot or run history found.")
    return EXIT_OK if result.return_code == 0 else EXIT_OPERATION_FAILED


def _handle_view_runs(args: argparse.Namespace) -> int:
    profile = _load_profile(args)
    store = _state_store(profile)
    records: List[RunRecord] = []
    if store.runs_root.exists():
        for path in store.runs_root.glob("*.json"):
            record = store.load_run(path.stem)
            if record is not None:
                records.append(record)
    records.sort(key=lambda value: value.created_utc, reverse=True)
    payload = [record.to_dict() for record in records]
    text = "\n".join("{0}  {1}  {2}".format(record.created_utc.astimezone().isoformat(timespec="seconds"), record.state.value, record.run_id) for record in records)
    _emit(payload, args, text=text or "No structured run records found.")
    return EXIT_OK


def _handle_view_run(args: argparse.Namespace) -> int:
    profile = _load_profile(args)
    store = _state_store(profile)
    matches = []
    if store.runs_root.exists():
        for path in store.runs_root.glob("*.json"):
            if path.stem.startswith(args.run_id):
                record = store.load_run(path.stem)
                if record is not None:
                    matches.append(record)
    if len(matches) != 1:
        raise ValueError("Run ID must match exactly one run; found {0}.".format(len(matches)))
    _emit(matches[0].to_dict(), args)
    return EXIT_OK


def _handle_view_dashboard(args: argparse.Namespace) -> int:
    profile = _load_profile(args)
    report, snapshots = _health_context(profile)
    payload = report.to_dict()
    lines = [
        "Backup profile: {0}".format(profile.name),
        "Health: {0}".format(report.severity.value.upper()),
        "Snapshots: {0}".format(len(snapshots)),
        "Latest snapshot: {0}".format("none" if report.latest_snapshot is None else "{0} at {1}".format(report.latest_snapshot.short_id, report.latest_snapshot.time.astimezone().isoformat(timespec="seconds"))),
        "Latest run: {0}".format("none" if report.latest_run is None else "{0} ({1})".format(report.latest_run.state.value, report.latest_run.run_id[:8])),
    ]
    lines.extend("- [{0}] {1}".format(issue.severity.value.upper(), issue.message) for issue in report.issues)
    _emit(payload, args, text="\n".join(lines))
    return EXIT_OK if report.healthy else EXIT_UNHEALTHY


def _handle_view_health(args: argparse.Namespace) -> int:
    return _handle_view_dashboard(args)


def _handle_view_logs(args: argparse.Namespace) -> int:
    profile = _load_profile(args)
    path = Path(profile.log_file)
    lines = [] if not path.exists() else path.read_text(encoding="utf-8", errors="replace").splitlines()[-100:]
    payload = {"path": str(path), "exists": path.exists(), "lines": lines}
    _emit(payload, args, text="\n".join(lines) or "No log file found.")
    return EXIT_OK


def _handle_view_storage(args: argparse.Namespace) -> int:
    operation = RepositoryClient(_load_profile(args)).stats()
    payload = operation_to_dict(operation)
    _emit(payload, args)
    return EXIT_OK if operation.result.succeeded else EXIT_OPERATION_FAILED


def _handle_view_schedules(args: argparse.Namespace) -> int:
    discovery = discover_schedules()
    _emit(discovery.to_dict(), args, text=_schedule_text(discovery))
    return EXIT_OK


def _handle_view_setup(args: argparse.Namespace) -> int:
    report = collect_audit(_load_profile(args), selected_sections=("configuration", "config-files", "paths", "inputs"))
    _emit(report.to_dict(), args, markdown=report.to_markdown())
    return EXIT_OK


def _handle_view_system(args: argparse.Namespace) -> int:
    report = collect_audit(_load_profile(args), selected_sections=("commands", "runtime", "environment"))
    _emit(report.to_dict(), args, markdown=report.to_markdown())
    return EXIT_OK


def _handle_view_provenance(args: argparse.Namespace) -> int:
    report = collect_audit(_load_profile(args), selected_sections=("snapshots", "runs", "provenance", "recommendations"))
    _emit(report.to_dict(), args, markdown=report.to_markdown())
    return EXIT_OK


def _handle_view_audit(args: argparse.Namespace) -> int:
    report = collect_audit(
        _load_profile(args),
        selected_sections=args.section,
        include_legacy_evidence=args.include_legacy_evidence,
    )
    _emit(report.to_dict(), args, markdown=report.to_markdown())
    return EXIT_OK


def _handle_view_export(args: argparse.Namespace) -> int:
    report = collect_audit(_load_profile(args), include_legacy_evidence=args.include_legacy_evidence)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.format == "markdown":
        output.write_text(report.to_markdown(), encoding="utf-8")
    else:
        output.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(str(output))
    return EXIT_OK


def _handle_view_search(args: argparse.Namespace) -> int:
    profile = _load_profile(args)
    arguments = ["find"]
    snapshot_id = getattr(args, "snapshot_id", None)
    if snapshot_id:
        arguments.extend(["-s", snapshot_id])
    if getattr(args, "ignore_case", False):
        arguments.append("-i")
    if getattr(args, "json", False):
        arguments.append("--json")
    arguments.extend(args.patterns)
    result = RepositoryClient(profile).execute(arguments)
    text = "".join(result.output)
    if getattr(args, "json", False):
        print(text.strip() or "[]")
    else:
        print(text, end="" if text.endswith("\n") else "\n")
    return EXIT_OK if result.return_code == 0 else EXIT_OPERATION_FAILED


def _handle_config_effective(args: argparse.Namespace) -> int:
    profile = _load_profile(args)
    _emit(profile.to_public_dict(), args)
    return EXIT_OK


def _handle_config_path(args: argparse.Namespace) -> int:
    path = discover_legacy_config(getattr(args, "config_path", None))
    payload = {"path": None if path is None else str(path), "exists": bool(path and path.exists())}
    _emit(payload, args, text=payload["path"] or "No legacy config file found; built-in defaults apply.")
    return EXIT_OK


def _handle_config_validate(args: argparse.Namespace) -> int:
    profile = _load_profile(args)
    profile.validate()
    missing = []
    for raw_path in (profile.password_file, profile.sources_file):
        if raw_path and not Path(raw_path).exists():
            missing.append(raw_path)
    payload = {"valid": not missing, "missing_required_files": missing, "profile": profile.to_public_dict()}
    _emit(payload, args, text="Configuration is valid." if not missing else "Missing: {0}".format(", ".join(missing)))
    return EXIT_OK if not missing else EXIT_OPERATION_FAILED


def _handle_config_discover(args: argparse.Namespace) -> int:
    profile = _load_profile(args)
    report = collect_audit(profile, selected_sections=("configuration", "config-files", "paths", "inputs"))
    _emit(report.to_dict(), args, markdown=report.to_markdown())
    return EXIT_OK


def _handle_config_import(args: argparse.Namespace) -> int:
    profile = _load_profile(args)
    payload = {"mode": "preview", "write_performed": False, "profile": profile.to_public_dict(), "next_step": "A TOML writer and explicit --apply gate will be added before legacy import can mutate files."}
    _emit(payload, args)
    return EXIT_OK


def _handle_config_profiles(args: argparse.Namespace) -> int:
    profile = _load_profile(args)
    payload = [{"name": profile.name, "tag": profile.tag, "source": "legacy/default-compatible"}]
    _emit(payload, args, text="{0}\t{1}".format(profile.name, profile.tag or "-"))
    return EXIT_OK


def _schedule_text(discovery: ScheduleDiscovery) -> str:
    if not discovery.records:
        warning_text = "\n".join(discovery.warnings)
        return warning_text or "No backup-related schedules were discovered."
    return "\n".join("{0}  {1}  {2}".format(record.state or "-", record.identifier, record.next_run or "-") for record in discovery.records)


def _handle_schedule_list(args: argparse.Namespace) -> int:
    discovery = discover_schedules()
    _emit(discovery.to_dict(), args, text=_schedule_text(discovery))
    return EXIT_OK


def _handle_schedule_show(args: argparse.Namespace) -> int:
    discovery = discover_schedules()
    matches = [record for record in discovery.records if args.name.lower() in record.identifier.lower()]
    if len(matches) != 1:
        raise ValueError("Schedule name must match exactly one record; found {0}.".format(len(matches)))
    _emit(matches[0].to_dict(), args)
    return EXIT_OK


def _handle_schedule_history(args: argparse.Namespace) -> int:
    payload = {"available": False, "reason": "Detailed scheduler event history is scheduled for Stage 3.", "discovery": discover_schedules().to_dict()}
    _emit(payload, args)
    return EXIT_OK


def _handle_restore(args: argparse.Namespace) -> int:
    profile = _load_profile(args)
    command_arguments = ["restore", args.snapshot_id, "--target", args.target]
    for value in args.include:
        command_arguments.extend(["--iinclude", value])
    for value in args.exclude:
        command_arguments.extend(["--iexclude", value])
    command = build_restic_command(restic_executable=profile.restic_executable, repository=profile.repository, arguments=command_arguments, password_file=profile.password_file)
    if not args.restore_apply:
        payload = {"mode": "preview", "executed": False, "command": command.render(redacted=True)}
        _emit(payload, args, text=payload["command"])
        return EXIT_OK
    if not args.apply:
        raise ValueError("restore run requires --apply.")
    result = execute_restic(command, echo=not getattr(args, "json", False))
    payload = {"command": command.render(redacted=True), "return_code": result.return_code, "succeeded": result.succeeded}
    _emit(payload, args)
    return EXIT_OK if result.succeeded else EXIT_OPERATION_FAILED


def _handle_restore_verify(args: argparse.Namespace) -> int:
    payload = {"available": False, "reason": "Structured restore history and hash verification are planned after compatibility merge."}
    _emit(payload, args)
    return EXIT_OK


def _emit_repository_operation(operation: RepositoryOperation, args: argparse.Namespace) -> int:
    payload = operation_to_dict(operation)
    _emit(payload, args)
    return EXIT_OK if operation.result.succeeded else EXIT_OPERATION_FAILED


def _handle_repository_status(args: argparse.Namespace) -> int:
    return _emit_repository_operation(RepositoryClient(_load_profile(args)).status(), args)


def _handle_repository_keys(args: argparse.Namespace) -> int:
    return _emit_repository_operation(RepositoryClient(_load_profile(args)).keys(), args)


def _handle_repository_locks(args: argparse.Namespace) -> int:
    return _emit_repository_operation(RepositoryClient(_load_profile(args)).locks(), args)


def _handle_repository_stats(args: argparse.Namespace) -> int:
    return _emit_repository_operation(RepositoryClient(_load_profile(args)).stats(mode=args.mode), args)


def _handle_repository_check(args: argparse.Namespace) -> int:
    return _emit_repository_operation(RepositoryClient(_load_profile(args)).check(read_data=args.read_data), args)


def _handle_repository_cache(args: argparse.Namespace) -> int:
    return _emit_repository_operation(RepositoryClient(_load_profile(args)).cache_status(), args)


def _handle_repository_init(args: argparse.Namespace) -> int:
    if not args.apply:
        raise ValueError("repository init requires --apply.")
    profile = _load_profile(args)
    result = RepositoryClient(profile).execute(["init"], echo=not args.json)
    payload = {"return_code": result.return_code, "succeeded": result.succeeded}
    _emit(payload, args)
    return EXIT_OK if result.succeeded else EXIT_OPERATION_FAILED


def _handle_repository_retention(args: argparse.Namespace) -> int:
    payload = {"mode": args.retention_command, "mutation_allowed": False, "reason": "Scoped ownership tags and retention isolation are required before retention application."}
    _emit(payload, args)
    return EXIT_OK


def main(argv: Optional[Sequence[str]] = None, *, program_name: Optional[str] = None) -> int:
    """Parse and dispatch the canonical CLI with compatibility translation."""

    raw = list(sys.argv[1:] if argv is None else argv)
    translated, use_legacy = _legacy_translation(raw)
    if use_legacy:
        from .cli import main as legacy_main

        return int(legacy_main(raw))

    parser = build_parser(program_name=program_name)
    try:
        args = parser.parse_args(translated)
        return int(args.handler(args))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("{0}: {1}".format(parser.prog, exc), file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:
        print("{0}: interrupted".format(parser.prog), file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
