"""Task-oriented command-line application for unified backup management."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .audit import collect_audit
from .config import resolve_config_path, save_config
from .engine import BackupEngine
from .inventory import (
    BackupInventory,
    BackupInventoryRecord,
    build_inventory,
    load_definitions,
    settings_from_definitions,
)
from .locking import LockError
from .models import ExecutionMode, RunState
from .presentation import (
    browse_backups,
    interactive_available,
    palette,
    render_backup_table,
    render_history,
    render_repository_summary,
    render_schedule_table,
    strip_ansi,
)
from .repository_ops import RepositoryClient, operation_to_dict
from .repository_summary import collect_repository_summary
from .restic import ResticCommandError, build_restic_command, execute_restic
from .version import __version__
from .wizards import run_create_wizard, run_schedule_wizard

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_OPERATION_FAILED = 3
EXIT_UNHEALTHY = 4
EXIT_SKIPPED = 10

ROOT_AREAS = ("create", "run", "view", "schedule", "restore", "repo", "config")
VIEW_SECTIONS = (
    "overview",
    "backups",
    "history",
    "repository",
    "schedules",
    "diagnostics",
    "audit",
)


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
        metavar="{" + ",".join(ROOT_AREAS) + "}",
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
    parser.set_defaults(handler=_handle_create)


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
    parser.set_defaults(handler=_handle_run)


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
    parser.set_defaults(handler=_handle_view)


def _add_schedule_parser(areas: argparse._SubParsersAction) -> None:
    parser = areas.add_parser(
        "schedule",
        help="List backup schedules or open the schedule/retention editor.",
    )
    _add_output_options(parser)
    operations = parser.add_subparsers(dest="schedule_command")
    parser.set_defaults(handler=_handle_schedule_list, schedule_command="list")

    wizard = operations.add_parser("wizard", help="Select one or more backups and edit their schedule.")
    wizard.add_argument("backup_names", nargs="*")
    wizard.add_argument("-y", "--apply", action="store_true")
    _add_output_options(wizard)
    wizard.set_defaults(handler=_handle_schedule_wizard)

    edit = operations.add_parser("edit", help="Edit one configured backup schedule.")
    edit.add_argument("backup_name")
    edit.add_argument("-y", "--apply", action="store_true")
    _add_output_options(edit)
    edit.set_defaults(handler=_handle_schedule_edit)


def _add_restore_parser(areas: argparse._SubParsersAction) -> None:
    parser = areas.add_parser("restore", help="Search, preview, and explicitly run restores.")
    operations = parser.add_subparsers(dest="restore_command", required=True)

    search = operations.add_parser("search", help="Search repository snapshots.")
    search.add_argument("patterns", nargs="+")
    search.add_argument("-b", "--backup", dest="backup_name")
    search.add_argument("-s", "--snapshot-id", "--snapshot_id")
    search.add_argument("-i", "--ignore-case", "--ignore_case", action="store_true")
    _add_output_options(search)
    search.set_defaults(handler=_handle_restore_search)

    preview = operations.add_parser("preview", help="Preview a restore command without executing it.")
    _add_restore_arguments(preview, include_apply=False)
    preview.set_defaults(handler=_handle_restore, restore_apply=False)

    run = operations.add_parser("run", help="Run a restore only with --apply.")
    _add_restore_arguments(run, include_apply=True)
    run.set_defaults(handler=_handle_restore, restore_apply=True)


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
    parser.set_defaults(handler=_handle_repo)


def _add_config_parser(areas: argparse._SubParsersAction) -> None:
    parser = areas.add_parser("config", help="Inspect, validate, or migrate backup configuration.")
    operations = parser.add_subparsers(dest="config_command", required=True)
    for name, help_text, handler in (
        ("show", "Show all configured backup definitions.", _handle_config_show),
        ("validate", "Validate configured paths and definitions.", _handle_config_validate),
        ("discover", "Show configuration and input-file discovery.", _handle_config_discover),
    ):
        child = operations.add_parser(name, help=help_text)
        _add_output_options(child)
        child.set_defaults(handler=handler)

    migrate = operations.add_parser("migrate", help="Preview or write canonical TOML from legacy defaults.")
    migrate.add_argument("-o", "--output")
    migrate.add_argument("-y", "--apply", action="store_true")
    _add_output_options(migrate)
    migrate.set_defaults(handler=_handle_config_migrate)


def _translate_hidden_aliases(argv: Sequence[str]) -> List[str]:
    """Accept selected old spellings without advertising them in help."""

    values = list(argv)
    if not values:
        return values
    try:
        area_index = next(index for index, value in enumerate(values) if not value.startswith("-"))
    except StopIteration:
        return values
    area = values[area_index]
    if area == "repository":
        values[area_index] = "repo"
        area = "repo"
    if area == "edit":
        values[area_index] = "config"
        return values
    if area == "view" and len(values) > area_index + 1:
        operation = values[area_index + 1]
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
            values = values[: area_index + 1] + ["--section", section_map[operation]] + values[area_index + 2 :]
    if area == "schedule" and len(values) > area_index + 1 and values[area_index + 1] in {"list", "discover"}:
        values.pop(area_index + 1)
    return values


def _theme(args: argparse.Namespace):
    return palette(force=False if getattr(args, "plain", False) or getattr(args, "no_color", False) else None)


def _emit(
    payload: Any,
    args: argparse.Namespace,
    *,
    text: Optional[str] = None,
    markdown: Optional[str] = None,
) -> None:
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    if getattr(args, "markdown", False):
        if markdown is not None:
            print(strip_ansi(markdown))
        elif text is not None:
            print("```text\n{0}\n```".format(strip_ansi(text)))
        else:
            print("```json\n{0}\n```".format(json.dumps(payload, indent=2, default=str)))
        return
    if text is not None:
        print(strip_ansi(text) if getattr(args, "plain", False) else text)
    else:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def _inventory(args: argparse.Namespace) -> BackupInventory:
    inventory = build_inventory(getattr(args, "config_path", None))
    for record in inventory.records:
        profile = record.definition.profile
        if getattr(args, "repository", None):
            profile.repository = args.repository
        if getattr(args, "password_file", None):
            profile.password_file = args.password_file
        if getattr(args, "restic_executable", None):
            profile.restic_executable = args.restic_executable
    return inventory


def _records(args: argparse.Namespace) -> Tuple[BackupInventory, List[BackupInventoryRecord]]:
    inventory = _inventory(args)
    backup_name = getattr(args, "backup_name", None)
    records = list(inventory.records)
    if backup_name:
        records = [inventory.by_name(backup_name)]
    return inventory, records


def _inventory_markdown(records: Sequence[BackupInventoryRecord]) -> str:
    lines = [
        "| Backup | Health | Sources | Schedule | Next run | Missed |",
        "|---|---|---|---|---|---:|",
    ]
    for record in records:
        lines.append(
            "| {0} | {1} | {2} | {3} | {4} | {5} |".format(
                record.definition.name,
                record.health.severity.value,
                record.definition.source_summary.replace("|", "\\|"),
                record.definition.schedule_text.replace("|", "\\|"),
                "-" if record.next_run is None else record.next_run.isoformat(),
                "-" if record.missed_runs is None else record.missed_runs,
            )
        )
    return "\n".join(lines)


def _handle_create(args: argparse.Namespace) -> int:
    payload = run_create_wizard(
        config_path=args.config_path,
        apply=args.apply,
        colors=_theme(args),
    )
    _emit(payload, args, text="Creation {0}.".format(payload["mode"]))
    results = payload.get("results", [])
    return EXIT_OK if all(result.get("succeeded", True) for result in results) else EXIT_OPERATION_FAILED


def _select_run_records(
    inventory: BackupInventory,
    args: argparse.Namespace,
) -> List[BackupInventoryRecord]:
    if args.backup_name.lower() != "auto":
        return [inventory.by_name(args.backup_name)]
    if args.json:
        return []
    if interactive_available() and not args.plain:
        return browse_backups(
            inventory.records,
            title="RRBackup — Select backups to run",
            multi_select=True,
            action_key="r",
            action_label="run selected backups",
        )
    return []


def _run_one(record: BackupInventoryRecord, args: argparse.Namespace) -> Tuple[Dict[str, Any], int]:
    record.definition.materialize_inputs()
    profile = copy.deepcopy(record.definition.profile)
    extra = list(profile.extra_backup_args)
    for value in args.tag:
        extra.extend(["--tag", value])
    for value in args.exclude:
        extra.extend(["--exclude", value])
    extra.extend(args.restic_arg)
    profile.extra_backup_args = extra
    engine = BackupEngine(profile)

    if args.print_command_only:
        preview = engine.preview()
        return (
            {
                "backup": record.definition.name,
                "mode": "preview",
                "executed": preview.executed,
                "command": preview.command.render(redacted=True),
            },
            EXIT_OK,
        )

    mode = ExecutionMode.DRY_RUN if args.dry_run else ExecutionMode.RUN
    result = engine.run(mode=mode, respect_cpu_policy=not args.ignore_cpu_policy)
    payload = {
        "backup": record.definition.name,
        "record": result.record.to_dict(),
        "summary": None if result.summary is None else result.summary.to_dict(),
        "executed": None if result.execution is None else result.execution.executed,
    }
    if result.record.state == RunState.SKIPPED:
        return payload, EXIT_SKIPPED
    if result.record.state in {RunState.SUCCESS, RunState.DRY_RUN}:
        return payload, EXIT_OK
    return payload, EXIT_OPERATION_FAILED


def _handle_run(args: argparse.Namespace) -> int:
    inventory = _inventory(args)
    selected = _select_run_records(inventory, args)
    if args.backup_name.lower() == "auto" and not selected:
        text = render_backup_table(
            inventory.records,
            colors=_theme(args),
            include_repository=True,
        )
        if not args.json:
            text += "\n\nRun one directly with: backup run <backup-name>"
        _emit(inventory.to_dict(), args, text=text, markdown=_inventory_markdown(inventory.records))
        return EXIT_OK

    results: List[Dict[str, Any]] = []
    exit_codes: List[int] = []
    for record in selected:
        payload, exit_code = _run_one(record, args)
        results.append(payload)
        exit_codes.append(exit_code)
    text_lines = []
    for result in results:
        if result.get("mode") == "preview":
            text_lines.append("{0}: {1}".format(result["backup"], result["command"]))
        else:
            run_record = result["record"]
            text_lines.append(
                "{0}: {1} — {2}".format(
                    result["backup"],
                    run_record["state"],
                    run_record.get("reason") or run_record["run_id"],
                )
            )
    _emit({"results": results}, args, text="\n".join(text_lines))
    if any(code == EXIT_OPERATION_FAILED for code in exit_codes):
        return EXIT_OPERATION_FAILED
    if any(code == EXIT_SKIPPED for code in exit_codes):
        return EXIT_SKIPPED
    return EXIT_OK


def _handle_view(args: argparse.Namespace) -> int:
    inventory, records = _records(args)
    section = args.section
    if section in {"overview", "backups"}:
        if not args.json and not args.markdown and not args.plain and interactive_available():
            browse_backups(records, title="RRBackup — Configured Backups")
            return EXIT_OK
        text = render_backup_table(records, colors=_theme(args), include_repository=True)
        _emit(
            {"section": section, "inventory": inventory.to_dict()},
            args,
            text=text,
            markdown=_inventory_markdown(records),
        )
        return EXIT_UNHEALTHY if any(not record.health.healthy for record in records) else EXIT_OK

    if section == "history":
        _emit(
            {"section": section, "backups": [record.to_dict() for record in records]},
            args,
            text=render_history(records, colors=_theme(args)),
        )
        return EXIT_OK

    if section == "schedules":
        _emit(
            {"section": section, "backups": [record.to_dict() for record in records]},
            args,
            text=render_schedule_table(records, colors=_theme(args)),
            markdown=_inventory_markdown(records),
        )
        return EXIT_OK

    if section == "repository":
        summaries = [collect_repository_summary(record.definition.profile) for record in records]
        text = "\n\n".join(
            render_repository_summary(summary, colors=_theme(args))
            for summary in summaries
        )
        _emit(
            {"section": section, "repositories": [summary.to_dict() for summary in summaries]},
            args,
            text=text,
        )
        return EXIT_OK if all(summary.available for summary in summaries) else EXIT_OPERATION_FAILED

    profile = records[0].definition.profile
    if section == "diagnostics":
        selected_sections = (
            "configuration",
            "config-files",
            "paths",
            "inputs",
            "commands",
            "runtime",
            "environment",
            "provenance",
            "recommendations",
        )
    else:
        selected_sections = tuple()
    report = collect_audit(
        profile,
        selected_sections=selected_sections,
        include_legacy_evidence=args.include_legacy_evidence,
    )
    _emit(report.to_dict(), args, text=report.to_markdown(), markdown=report.to_markdown())
    return EXIT_OK


def _handle_schedule_list(args: argparse.Namespace) -> int:
    inventory = _inventory(args)
    _emit(
        inventory.to_dict(),
        args,
        text=render_schedule_table(inventory.records, colors=_theme(args)),
        markdown=_inventory_markdown(inventory.records),
    )
    return EXIT_OK


def _handle_schedule_wizard(args: argparse.Namespace) -> int:
    inventory = _inventory(args)
    payload = run_schedule_wizard(
        inventory.records,
        config_path=args.config_path,
        names=args.backup_names,
        apply=args.apply,
        colors=_theme(args),
    )
    _emit(payload, args, text="Schedule changes {0}.".format(payload["mode"]))
    return EXIT_OK


def _handle_schedule_edit(args: argparse.Namespace) -> int:
    inventory = _inventory(args)
    payload = run_schedule_wizard(
        inventory.records,
        config_path=args.config_path,
        names=(args.backup_name,),
        apply=args.apply,
        colors=_theme(args),
    )
    _emit(payload, args, text="Schedule changes {0}.".format(payload["mode"]))
    return EXIT_OK


def _record_for_name(args: argparse.Namespace) -> BackupInventoryRecord:
    inventory = _inventory(args)
    if getattr(args, "backup_name", None):
        return inventory.by_name(args.backup_name)
    if len(inventory.records) != 1:
        raise ValueError("Use --backup when more than one configured backup exists.")
    return inventory.records[0]


def _handle_restore_search(args: argparse.Namespace) -> int:
    record = _record_for_name(args)
    arguments = ["find"]
    if args.snapshot_id:
        arguments.extend(["-s", args.snapshot_id])
    if args.ignore_case:
        arguments.append("-i")
    if args.json:
        arguments.append("--json")
    arguments.extend(args.patterns)
    result = RepositoryClient(record.definition.profile).execute(arguments)
    text = "".join(result.output).strip()
    if args.json:
        print(text or "[]")
    else:
        print(text or "No matching files were found.")
    return EXIT_OK if result.return_code == 0 else EXIT_OPERATION_FAILED


def _handle_restore(args: argparse.Namespace) -> int:
    record = _record_for_name(args)
    profile = record.definition.profile
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
        _emit(
            {"mode": "preview", "executed": False, "command": command.render(redacted=True)},
            args,
            text=command.render(redacted=True),
        )
        return EXIT_OK
    if not args.apply:
        raise ValueError("restore run requires --apply.")
    result = execute_restic(command, echo=not args.json)
    _emit(
        {
            "command": command.render(redacted=True),
            "return_code": result.return_code,
            "succeeded": result.succeeded,
        },
        args,
        text="Restore {0}.".format("completed" if result.succeeded else "failed"),
    )
    return EXIT_OK if result.succeeded else EXIT_OPERATION_FAILED


def _loading_context(message: str):
    if not interactive_available():
        return nullcontext()
    try:
        from termdash import LoadingIndicator
    except ImportError:
        return nullcontext()
    return LoadingIndicator(message)


def _handle_repo(args: argparse.Namespace) -> int:
    record = _record_for_name(args)
    profile = record.definition.profile
    if args.repo_action == "check":
        with _loading_context("Checking Restic repository"):
            operation = RepositoryClient(profile).check(read_data=args.read_data)
        payload = operation_to_dict(operation)
        lines = operation.payload.get("lines", []) if isinstance(operation.payload, dict) else []
        _emit(payload, args, text="\n".join(lines) or "Repository check completed.")
        return EXIT_OK if operation.result.succeeded else EXIT_OPERATION_FAILED

    with _loading_context("Calculating full repository restore size") if args.refresh_storage else nullcontext():
        summary = collect_repository_summary(
            profile,
            refresh_storage=args.refresh_storage,
        )
    _emit(
        summary.to_dict(),
        args,
        text=render_repository_summary(summary, colors=_theme(args)),
    )
    return EXIT_OK if summary.available else EXIT_OPERATION_FAILED


def _handle_config_show(args: argparse.Namespace) -> int:
    definitions, warnings = load_definitions(args.config_path)
    payload = {
        "config_path": str(resolve_config_path(args.config_path)),
        "backups": [
            {
                "name": definition.name,
                "source_kind": definition.source_kind,
                "sources": list(definition.sources),
                "excludes": list(definition.excludes),
                "tags": list(definition.tags),
                "schedule": definition.schedule.to_dict(),
                "retention": None if definition.retention is None else definition.retention.to_dict(),
                "profile": definition.profile.to_public_dict(),
            }
            for definition in definitions
        ],
        "warnings": warnings,
    }
    inventory = _inventory(args)
    _emit(
        payload,
        args,
        text=render_backup_table(inventory.records, colors=_theme(args), include_repository=True),
        markdown=_inventory_markdown(inventory.records),
    )
    return EXIT_OK


def _handle_config_validate(args: argparse.Namespace) -> int:
    definitions, warnings = load_definitions(args.config_path)
    issues: List[str] = list(warnings)
    for definition in definitions:
        definition.profile.validate()
        for label, value in (
            ("password file", definition.profile.password_file),
            ("sources file", definition.profile.sources_file),
        ):
            if value and not Path(value).exists() and definition.source_kind != "toml":
                issues.append("{0}: missing {1}: {2}".format(definition.name, label, value))
        if not definition.sources:
            issues.append("{0}: no source paths configured".format(definition.name))
    payload = {"valid": not issues, "issues": issues}
    _emit(
        payload,
        args,
        text="Configuration is valid." if not issues else "\n".join("- " + value for value in issues),
    )
    return EXIT_OK if not issues else EXIT_OPERATION_FAILED


def _handle_config_discover(args: argparse.Namespace) -> int:
    definitions, warnings = load_definitions(args.config_path)
    payload = {
        "resolved_config_path": str(resolve_config_path(args.config_path)),
        "config_exists": resolve_config_path(args.config_path).exists(),
        "backups": [definition.profile.to_public_dict() for definition in definitions],
        "warnings": warnings,
    }
    lines = [
        "Config: {0} ({1})".format(
            payload["resolved_config_path"],
            "exists" if payload["config_exists"] else "legacy defaults",
        )
    ]
    for definition in definitions:
        lines.extend(
            [
                "{0}:".format(definition.name),
                "  repository: {0}".format(definition.profile.repository),
                "  password:   {0}".format(definition.profile.password_file),
                "  sources:    {0}".format(definition.profile.sources_file),
                "  excludes:   {0}".format(definition.profile.excludes_file),
                "  state:      {0}".format(definition.profile.status_file),
            ]
        )
    _emit(payload, args, text="\n".join(lines))
    return EXIT_OK


def _handle_config_migrate(args: argparse.Namespace) -> int:
    definitions, warnings = load_definitions(args.config_path)
    target = Path(args.output) if args.output else resolve_config_path(None)
    settings = settings_from_definitions(definitions)
    payload = {
        "mode": "apply" if args.apply else "preview",
        "target": str(target),
        "backups": [definition.name for definition in definitions],
        "warnings": warnings,
    }
    if args.apply:
        save_config(settings, target, overwrite=True)
    _emit(
        payload,
        args,
        text="Canonical configuration {0}: {1}".format(
            "written" if args.apply else "would be written",
            target,
        ),
    )
    return EXIT_OK


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    program_name: str = "backup",
) -> int:
    """Parse and dispatch the canonical CLI."""

    raw = list(sys.argv[1:] if argv is None else argv)
    translated = _translate_hidden_aliases(raw)
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
