"""Runtime handlers for the task-oriented backup CLI."""

from __future__ import annotations

import copy
import json
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
from .restic import build_restic_command, execute_restic
from .wizards import run_create_wizard, run_schedule_wizard

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_OPERATION_FAILED = 3
EXIT_UNHEALTHY = 4
EXIT_SKIPPED = 10


def theme(args: Any):
    return palette(
        force=(
            False
            if getattr(args, "plain", False) or getattr(args, "no_color", False)
            else None
        )
    )


def emit(
    payload: Any,
    args: Any,
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


def inventory(args: Any) -> BackupInventory:
    result = build_inventory(getattr(args, "config_path", None))
    for record in result.records:
        profile = record.definition.profile
        if getattr(args, "repository", None):
            profile.repository = args.repository
        if getattr(args, "password_file", None):
            profile.password_file = args.password_file
        if getattr(args, "restic_executable", None):
            profile.restic_executable = args.restic_executable
    return result


def records(args: Any) -> Tuple[BackupInventory, List[BackupInventoryRecord]]:
    result = inventory(args)
    backup_name = getattr(args, "backup_name", None)
    selected = list(result.records)
    if backup_name:
        selected = [result.by_name(backup_name)]
    return result, selected


def inventory_markdown(values: Sequence[BackupInventoryRecord]) -> str:
    lines = [
        "| Backup | Health | Sources | Schedule | Next run | Missed |",
        "|---|---|---|---|---|---:|",
    ]
    for record in values:
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


def handle_create(args: Any) -> int:
    payload = run_create_wizard(
        config_path=args.config_path,
        apply=args.apply,
        colors=theme(args),
    )
    emit(payload, args, text="Creation {0}.".format(payload["mode"]))
    results = payload.get("results", [])
    return (
        EXIT_OK
        if all(result.get("succeeded", True) for result in results)
        else EXIT_OPERATION_FAILED
    )


def _select_run_records(result: BackupInventory, args: Any) -> List[BackupInventoryRecord]:
    if args.backup_name.lower() != "auto":
        return [result.by_name(args.backup_name)]
    if args.json:
        return []
    if interactive_available() and not args.plain:
        return browse_backups(
            result.records,
            title="RRBackup — Select backups to run",
            multi_select=True,
            action_key="r",
            action_label="run selected backups",
        )
    return []


def _run_one(record: BackupInventoryRecord, args: Any) -> Tuple[Dict[str, Any], int]:
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
        command = engine.build_backup_command()
        return (
            {
                "backup": record.definition.name,
                "mode": "preview",
                "executed": False,
                "command": command.render(redacted=True),
            },
            EXIT_OK,
        )

    record.definition.materialize_inputs()
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


def handle_run(args: Any) -> int:
    result = inventory(args)
    selected = _select_run_records(result, args)
    if args.backup_name.lower() == "auto" and not selected:
        text = render_backup_table(
            result.records,
            colors=theme(args),
            include_repository=True,
        )
        if not args.json:
            text += "\n\nRun one directly with: backup run <backup-name>"
        emit(
            result.to_dict(),
            args,
            text=text,
            markdown=inventory_markdown(result.records),
        )
        return EXIT_OK

    payloads: List[Dict[str, Any]] = []
    exit_codes: List[int] = []
    for selected_record in selected:
        payload, exit_code = _run_one(selected_record, args)
        payloads.append(payload)
        exit_codes.append(exit_code)
    text_lines = []
    for payload in payloads:
        if payload.get("mode") == "preview":
            text_lines.append("{0}: {1}".format(payload["backup"], payload["command"]))
        else:
            run_record = payload["record"]
            text_lines.append(
                "{0}: {1} — {2}".format(
                    payload["backup"],
                    run_record["state"],
                    run_record.get("reason") or run_record["run_id"],
                )
            )
    emit({"results": payloads}, args, text="\n".join(text_lines))
    if any(code == EXIT_OPERATION_FAILED for code in exit_codes):
        return EXIT_OPERATION_FAILED
    if any(code == EXIT_SKIPPED for code in exit_codes):
        return EXIT_SKIPPED
    return EXIT_OK


def handle_view(args: Any) -> int:
    result, selected = records(args)
    section = args.section
    if section in {"overview", "backups"}:
        if (
            not args.json
            and not args.markdown
            and not args.plain
            and interactive_available()
        ):
            browse_backups(selected, title="RRBackup — Configured Backups")
            return EXIT_OK
        text = render_backup_table(selected, colors=theme(args), include_repository=True)
        emit(
            {"section": section, "inventory": result.to_dict()},
            args,
            text=text,
            markdown=inventory_markdown(selected),
        )
        return (
            EXIT_UNHEALTHY
            if any(not record.health.healthy for record in selected)
            else EXIT_OK
        )

    if section == "history":
        emit(
            {"section": section, "backups": [record.to_dict() for record in selected]},
            args,
            text=render_history(selected, colors=theme(args)),
        )
        return EXIT_OK

    if section == "schedules":
        emit(
            {"section": section, "backups": [record.to_dict() for record in selected]},
            args,
            text=render_schedule_table(selected, colors=theme(args)),
            markdown=inventory_markdown(selected),
        )
        return EXIT_OK

    if section == "repository":
        summaries = [
            collect_repository_summary(record.definition.profile)
            for record in selected
        ]
        text = "\n\n".join(
            render_repository_summary(summary, colors=theme(args))
            for summary in summaries
        )
        emit(
            {
                "section": section,
                "repositories": [summary.to_dict() for summary in summaries],
            },
            args,
            text=text,
        )
        return (
            EXIT_OK
            if all(summary.available for summary in summaries)
            else EXIT_OPERATION_FAILED
        )

    profile = selected[0].definition.profile
    selected_sections = (
        (
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
        if section == "diagnostics"
        else tuple()
    )
    report = collect_audit(
        profile,
        selected_sections=selected_sections,
        include_legacy_evidence=args.include_legacy_evidence,
    )
    emit(
        report.to_dict(),
        args,
        text=report.to_markdown(),
        markdown=report.to_markdown(),
    )
    return EXIT_OK


def handle_schedule_list(args: Any) -> int:
    result = inventory(args)
    emit(
        result.to_dict(),
        args,
        text=render_schedule_table(result.records, colors=theme(args)),
        markdown=inventory_markdown(result.records),
    )
    return EXIT_OK


def handle_schedule_wizard(args: Any) -> int:
    result = inventory(args)
    payload = run_schedule_wizard(
        result.records,
        config_path=args.config_path,
        names=args.backup_names,
        apply=args.apply,
        colors=theme(args),
    )
    emit(payload, args, text="Schedule changes {0}.".format(payload["mode"]))
    return EXIT_OK


def handle_schedule_edit(args: Any) -> int:
    result = inventory(args)
    payload = run_schedule_wizard(
        result.records,
        config_path=args.config_path,
        names=(args.backup_name,),
        apply=args.apply,
        colors=theme(args),
    )
    emit(payload, args, text="Schedule changes {0}.".format(payload["mode"]))
    return EXIT_OK


def record_for_name(args: Any) -> BackupInventoryRecord:
    result = inventory(args)
    if getattr(args, "backup_name", None):
        return result.by_name(args.backup_name)
    if len(result.records) != 1:
        raise ValueError("Use --backup when more than one configured backup exists.")
    return result.records[0]


def handle_restore_search(args: Any) -> int:
    record = record_for_name(args)
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


def handle_restore(args: Any) -> int:
    record = record_for_name(args)
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
        emit(
            {
                "mode": "preview",
                "executed": False,
                "command": command.render(redacted=True),
            },
            args,
            text=command.render(redacted=True),
        )
        return EXIT_OK
    if not args.apply:
        raise ValueError("restore run requires --apply.")
    execution = execute_restic(command, echo=not args.json)
    emit(
        {
            "command": command.render(redacted=True),
            "return_code": execution.return_code,
            "succeeded": execution.succeeded,
        },
        args,
        text="Restore {0}.".format("completed" if execution.succeeded else "failed"),
    )
    return EXIT_OK if execution.succeeded else EXIT_OPERATION_FAILED


def loading_context(message: str):
    if not interactive_available():
        return nullcontext()
    try:
        from termdash import LoadingIndicator
    except ImportError:
        return nullcontext()
    return LoadingIndicator(message)


def handle_repo(args: Any) -> int:
    record = record_for_name(args)
    profile = record.definition.profile
    if args.repo_action == "check":
        with loading_context("Checking Restic repository"):
            operation = RepositoryClient(profile).check(read_data=args.read_data)
        payload = operation_to_dict(operation)
        lines = operation.payload.get("lines", []) if isinstance(operation.payload, dict) else []
        emit(payload, args, text="\n".join(lines) or "Repository check completed.")
        return EXIT_OK if operation.result.succeeded else EXIT_OPERATION_FAILED

    context = (
        loading_context("Calculating full repository restore size")
        if args.refresh_storage
        else nullcontext()
    )
    with context:
        summary = collect_repository_summary(
            profile,
            refresh_storage=args.refresh_storage,
        )
    emit(
        summary.to_dict(),
        args,
        text=render_repository_summary(summary, colors=theme(args)),
    )
    return EXIT_OK if summary.available else EXIT_OPERATION_FAILED


def handle_config_show(args: Any) -> int:
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
                "retention": (
                    None
                    if definition.retention is None
                    else definition.retention.to_dict()
                ),
                "profile": definition.profile.to_public_dict(),
            }
            for definition in definitions
        ],
        "warnings": warnings,
    }
    result = inventory(args)
    emit(
        payload,
        args,
        text=render_backup_table(
            result.records,
            colors=theme(args),
            include_repository=True,
        ),
        markdown=inventory_markdown(result.records),
    )
    return EXIT_OK


def handle_config_validate(args: Any) -> int:
    definitions, warnings = load_definitions(args.config_path)
    issues: List[str] = list(warnings)
    for definition in definitions:
        definition.profile.validate()
        password_path = Path(definition.profile.password_file)
        if not password_path.exists():
            issues.append(
                "{0}: missing password file: {1}".format(
                    definition.name,
                    definition.profile.password_file,
                )
            )
        if definition.source_kind != "toml":
            for label, value in (
                ("sources file", definition.profile.sources_file),
                ("excludes file", definition.profile.excludes_file),
            ):
                if value and not Path(value).exists():
                    issues.append("{0}: missing {1}: {2}".format(definition.name, label, value))
        if not definition.sources:
            issues.append("{0}: no source paths configured".format(definition.name))
    payload = {"valid": not issues, "issues": issues}
    emit(
        payload,
        args,
        text=(
            "Configuration is valid."
            if not issues
            else "\n".join("- " + value for value in issues)
        ),
    )
    return EXIT_OK if not issues else EXIT_OPERATION_FAILED


def handle_config_discover(args: Any) -> int:
    definitions, warnings = load_definitions(args.config_path)
    resolved = resolve_config_path(args.config_path)
    payload = {
        "resolved_config_path": str(resolved),
        "config_exists": resolved.exists(),
        "backups": [definition.profile.to_public_dict() for definition in definitions],
        "warnings": warnings,
    }
    lines = [
        "Config: {0} ({1})".format(
            resolved,
            "exists" if resolved.exists() else "legacy defaults",
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
    emit(payload, args, text="\n".join(lines))
    return EXIT_OK


def handle_config_migrate(args: Any) -> int:
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
    emit(
        payload,
        args,
        text="Canonical configuration {0}: {1}".format(
            "written" if args.apply else "would be written",
            target,
        ),
    )
    return EXIT_OK
