"""Shared backup execution engine for RRBackup and compatibility adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .locking import ProcessIdentity, ProcessLock, current_process_identity
from .models import ExecutionMode, RunRecord, RunState
from .policy import CpuDecision, WaitResult, wait_for_cpu_window
from .profile import BackupProfile
from .restic import (
    ExecutionResult,
    ResticCommand,
    ResticExecutionError,
    ResticInterrupted,
    build_restic_command,
    execute_restic,
)
from .snapshots import BackupSummary, parse_backup_json_lines
from .state import RunStateStore


@dataclass(frozen=True)
class BackupRunResult:
    """Combined persisted and process result for one backup attempt."""

    record: RunRecord
    execution: Optional[ExecutionResult]
    decision: Optional[CpuDecision]
    summary: Optional[BackupSummary]


class BackupEngine:
    """Execute one canonical backup profile safely."""

    def __init__(
        self,
        profile: BackupProfile,
        *,
        state_store: Optional[RunStateStore] = None,
        lock_factory: Optional[Callable[[], ProcessLock]] = None,
        command_executor: Callable[..., ExecutionResult] = execute_restic,
        identity_factory: Callable[[], ProcessIdentity] = current_process_identity,
        cpu_waiter: Callable[..., WaitResult] = wait_for_cpu_window,
    ) -> None:
        self.profile = profile
        self.state_store = state_store or RunStateStore(
            Path(profile.status_file).parent / "rrbackup-state"
        )
        self.lock_factory = lock_factory or (
            lambda: ProcessLock(profile.lock_file)
        )
        self.command_executor = command_executor
        self.identity_factory = identity_factory
        self.cpu_waiter = cpu_waiter

    def validate_backup_inputs(self) -> None:
        """Validate all local files required for a backup run."""

        self.profile.validate()
        for field_name, raw_path in (
            ("password_file", self.profile.password_file),
            ("sources_file", self.profile.sources_file),
            ("excludes_file", self.profile.excludes_file),
        ):
            if raw_path is None:
                if field_name == "sources_file":
                    raise ValueError("sources_file is required for backup.")
                continue
            path = Path(raw_path)
            if not path.exists():
                raise FileNotFoundError(
                    "{0} does not exist: {1}".format(field_name, path)
                )

    def build_backup_command(self) -> ResticCommand:
        """Build the production-compatible Restic backup command."""

        if not self.profile.sources_file:
            raise ValueError("sources_file is required for backup.")

        arguments = ["backup", "--json"]
        if self.profile.use_fs_snapshot:
            arguments.append("--use-fs-snapshot")
        arguments.extend(
            ["--files-from-verbatim", self.profile.sources_file]
        )
        if self.profile.excludes_file:
            arguments.extend(["--iexclude-file", self.profile.excludes_file])
        if self.profile.exclude_caches:
            arguments.append("--exclude-caches")
        if self.profile.tag:
            arguments.extend(["--tag", self.profile.tag])
        arguments.extend(self.profile.extra_backup_args)

        return build_restic_command(
            restic_executable=self.profile.restic_executable,
            repository=self.profile.repository,
            arguments=arguments,
            password_file=self.profile.password_file,
        )

    def preview(self) -> ExecutionResult:
        """Validate and render a backup command without writing state or acquiring a lock."""

        self.validate_backup_inputs()
        return self.command_executor(
            self.build_backup_command(),
            mode=ExecutionMode.PREVIEW,
            echo=False,
        )

    def run(
        self,
        *,
        mode: ExecutionMode = ExecutionMode.RUN,
        respect_cpu_policy: bool = True,
    ) -> BackupRunResult:
        """Run or dry-run a backup with corrected lifecycle semantics."""

        if mode == ExecutionMode.PREVIEW:
            execution = self.preview()
            record = RunRecord.create(
                profile=self.profile.name,
                backup_set=self.profile.tag or self.profile.name,
            )
            return BackupRunResult(
                record=record,
                execution=execution,
                decision=None,
                summary=None,
            )

        self.validate_backup_inputs()
        command = self.build_backup_command()
        record = RunRecord.create(
            profile=self.profile.name,
            backup_set=self.profile.tag or self.profile.name,
        )
        record.command = list(command.argv)
        record.redacted_command = command.render(redacted=True)
        self.state_store.save(record)

        decision: Optional[CpuDecision] = None
        if respect_cpu_policy:
            last_success = self.state_store.load_last_success()
            last_success_time = (
                None if last_success is None else last_success.finished_utc
            )
            record = record.transition(
                RunState.WAITING,
                reason="Waiting for an acceptable CPU window.",
            )
            self.state_store.save(record)
            wait_result = self.cpu_waiter(
                self.profile.cpu_policy,
                last_success=last_success_time,
            )
            decision = wait_result.decision
            if not decision.should_run:
                record = record.transition(
                    RunState.SKIPPED,
                    reason=decision.reason,
                    metadata={
                        "cpu_percent": decision.cpu_percent,
                        "cpu_threshold": decision.threshold,
                        "overdue": decision.overdue,
                        "wait_attempts": wait_result.attempts,
                        "deadline_reached": wait_result.deadline_reached,
                    },
                )
                self.state_store.save(record)
                return BackupRunResult(
                    record=record,
                    execution=None,
                    decision=decision,
                    summary=None,
                )

        lock = self.lock_factory()
        execution: Optional[ExecutionResult] = None
        summary: Optional[BackupSummary] = None

        lock.acquire()
        try:
            identity = lock.identity or self.identity_factory()
            record.pid = identity.pid
            record.process_start_time = identity.create_time
            record = record.transition(
                RunState.RUNNING,
                reason=None if decision is None else decision.reason,
                metadata=(
                    {}
                    if decision is None
                    else {
                        "cpu_percent": decision.cpu_percent,
                        "cpu_threshold": decision.threshold,
                        "overdue": decision.overdue,
                    }
                ),
            )
            self.state_store.save(record)

            try:
                execution = self.command_executor(
                    command,
                    mode=mode,
                    log_path=self.profile.log_file,
                )
            except ResticInterrupted as exc:
                execution = exc.result
                record = record.transition(
                    RunState.INTERRUPTED,
                    exit_code=execution.return_code,
                    reason="Backup execution was interrupted.",
                )
                self.state_store.save(record)
                return BackupRunResult(
                    record=record,
                    execution=execution,
                    decision=decision,
                    summary=None,
                )
            except ResticExecutionError as exc:
                record = record.transition(
                    RunState.FAILURE,
                    reason=str(exc),
                )
                self.state_store.save(record)
                raise

            summary = parse_backup_json_lines(execution.output)
            if execution.return_code != 0:
                record = record.transition(
                    RunState.FAILURE,
                    exit_code=execution.return_code,
                    reason="Restic exited with code {0}.".format(
                        execution.return_code
                    ),
                )
            elif mode == ExecutionMode.DRY_RUN:
                record = record.transition(
                    RunState.DRY_RUN,
                    exit_code=0,
                    reason="Restic dry-run completed; no snapshot was created.",
                    metadata=(
                        {} if summary is None else {"summary": summary.to_dict()}
                    ),
                )
            else:
                snapshot_id = None if summary is None else summary.snapshot_id
                record = record.transition(
                    RunState.SUCCESS,
                    exit_code=0,
                    snapshot_id=snapshot_id,
                    reason="Backup completed successfully.",
                    metadata=(
                        {} if summary is None else {"summary": summary.to_dict()}
                    ),
                )

            self.state_store.save(record)
            return BackupRunResult(
                record=record,
                execution=execution,
                decision=decision,
                summary=summary,
            )
        finally:
            lock.release()
