"""Runtime wrapper for configured-backup selection and execution."""

from __future__ import annotations

from typing import Any, Dict, List

from . import cli_runtime
from .inventory import BackupInventoryRecord
from .presentation import interactive_available, render_backup_table
from .viewer import select_backups


def _selected_records(args: Any) -> tuple[object, List[BackupInventoryRecord]]:
    result = cli_runtime.inventory(args)
    if args.backup_name.lower() != "auto":
        return result, [result.by_name(args.backup_name)]
    if args.json:
        return result, []
    if interactive_available() and not args.plain:
        return result, select_backups(
            result.records,
            title="RRBackup — Select backups to run",
            multi_select=True,
            action_key="r",
            action_label="run selected backups",
        )
    return result, []


def handle_run(args: Any) -> int:
    """Choose configured backups and delegate execution to the shared engine."""

    result, selected = _selected_records(args)
    if args.backup_name.lower() == "auto" and not selected:
        text = render_backup_table(
            result.records,
            colors=cli_runtime.theme(args),
            include_repository=True,
        )
        if not args.json:
            text += "\n\nRun one directly with: backup run <backup-name>"
        cli_runtime.emit(
            result.to_dict(),
            args,
            text=text,
            markdown=cli_runtime.inventory_markdown(result.records),
        )
        return cli_runtime.EXIT_OK

    payloads: List[Dict[str, Any]] = []
    exit_codes: List[int] = []
    for selected_record in selected:
        payload, exit_code = cli_runtime._run_one(selected_record, args)
        payloads.append(payload)
        exit_codes.append(exit_code)

    text_lines: List[str] = []
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
    cli_runtime.emit({"results": payloads}, args, text="\n".join(text_lines))
    if any(code == cli_runtime.EXIT_OPERATION_FAILED for code in exit_codes):
        return cli_runtime.EXIT_OPERATION_FAILED
    if any(code == cli_runtime.EXIT_SKIPPED for code in exit_codes):
        return cli_runtime.EXIT_SKIPPED
    return cli_runtime.EXIT_OK
