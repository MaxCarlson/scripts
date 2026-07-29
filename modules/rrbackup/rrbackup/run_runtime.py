"""Runtime wrapper for configured-backup operations and monitored execution."""

from __future__ import annotations

import copy
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import cli_runtime
from .engine import BackupEngine
from .inventory import BackupInventoryRecord
from .models import ExecutionMode, RunState
from .monitored_restic import ResticExecutionControl, execute_restic_monitored
from .operations_dashboard import run_operations_dashboard
from .presentation import interactive_available, render_backup_table
from .run_progress import BackupProgress, parse_progress_line
from .state import RunStateStore

ProgressCallback = Callable[[BackupProgress], None]


def _available_records(args: Any) -> tuple[object, List[BackupInventoryRecord]]:
    result = cli_runtime.inventory(args)
    if args.backup_name.lower() == "auto":
        return result, list(result.records)
    return result, [result.by_name(args.backup_name)]


def _configured_profile(record: BackupInventoryRecord, args: Any):
    profile = copy.deepcopy(record.definition.profile)
    extra = list(profile.extra_backup_args)
    for value in args.tag:
        extra.extend(["--tag", value])
    for value in args.exclude:
        extra.extend(["--exclude", value])
    extra.extend(args.restic_arg)
    profile.extra_backup_args = extra
    return profile


class _ProgressPersistence:
    """Persist throttled progress while forwarding every update to the dashboard."""

    def __init__(
        self,
        state_store: RunStateStore,
        profile_name: str,
        callback: ProgressCallback,
        *,
        interval_seconds: float = 1.0,
    ) -> None:
        self.state_store = state_store
        self.profile_name = profile_name
        self.callback = callback
        self.interval_seconds = interval_seconds
        self.last_saved = 0.0
        self.latest: Optional[BackupProgress] = None

    def handle_line(self, line: str) -> None:
        progress = parse_progress_line(line)
        if progress is None:
            return
        self.latest = progress
        self.callback(progress)
        current = time.monotonic()
        if current - self.last_saved < self.interval_seconds:
            return
        latest_run = self.state_store.load_latest()
        if (
            latest_run is not None
            and latest_run.profile == self.profile_name
            and latest_run.state == RunState.RUNNING
        ):
            latest_run.metadata["progress"] = progress.to_dict()
            self.state_store.save(latest_run)
            self.last_saved = current

    def preserve_terminal_progress(self, record: Any) -> None:
        if self.latest is None:
            return
        record.metadata["progress"] = self.latest.to_dict()
        self.state_store.save(record)


def _run_one_monitored(
    record: BackupInventoryRecord,
    args: Any,
    progress_callback: ProgressCallback,
    control: ResticExecutionControl,
) -> Tuple[Dict[str, Any], int]:
    profile = _configured_profile(record, args)
    record.definition.materialize_inputs()
    state_store = RunStateStore(Path(profile.status_file).parent / "rrbackup-state")
    persistence = _ProgressPersistence(
        state_store,
        profile.name,
        progress_callback,
    )

    def executor(command: Any, **kwargs: Any):
        return execute_restic_monitored(
            command,
            mode=kwargs.get("mode", ExecutionMode.RUN),
            log_path=kwargs.get("log_path"),
            line_handler=persistence.handle_line,
            control=control,
        )

    engine = BackupEngine(
        profile,
        state_store=state_store,
        command_executor=executor,
    )
    mode = ExecutionMode.DRY_RUN if args.dry_run else ExecutionMode.RUN
    result = engine.run(
        mode=mode,
        respect_cpu_policy=not args.ignore_cpu_policy,
    )
    persistence.preserve_terminal_progress(result.record)
    payload = {
        "backup": record.definition.name,
        "record": result.record.to_dict(),
        "summary": None if result.summary is None else result.summary.to_dict(),
        "executed": None if result.execution is None else result.execution.executed,
    }
    if result.record.state == RunState.SKIPPED:
        return payload, cli_runtime.EXIT_SKIPPED
    if result.record.state in {RunState.SUCCESS, RunState.DRY_RUN}:
        return payload, cli_runtime.EXIT_OK
    return payload, cli_runtime.EXIT_OPERATION_FAILED


def _exit_code(values: List[int]) -> int:
    if any(value == cli_runtime.EXIT_OPERATION_FAILED for value in values):
        return cli_runtime.EXIT_OPERATION_FAILED
    if any(value == cli_runtime.EXIT_SKIPPED for value in values):
        return cli_runtime.EXIT_SKIPPED
    return cli_runtime.EXIT_OK


def _interactive_dashboard(args: Any) -> bool:
    return (
        interactive_available()
        and not args.json
        and not args.plain
        and not args.markdown
        and not args.print_command_only
    )


def handle_run(args: Any) -> int:
    """List or execute configured backups through the appropriate surface."""

    result, available = _available_records(args)
    if _interactive_dashboard(args):
        outcome = run_operations_dashboard(
            available,
            lambda selected_record, progress_callback, control: _run_one_monitored(
                selected_record,
                args,
                progress_callback,
                control,
            ),
            dry_run=args.dry_run,
        )
        return _exit_code(list(outcome.exit_codes))

    if args.backup_name.lower() == "auto":
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
    for selected_record in available:
        payload, code = cli_runtime._run_one(selected_record, args)
        payloads.append(payload)
        exit_codes.append(code)

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
    return _exit_code(exit_codes)
