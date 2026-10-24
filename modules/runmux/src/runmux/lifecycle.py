"""Core process lifecycle management for Runmux browser and API controls (Phase 4A)."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from runmux.constants import STATUS_KILLED, STATUS_PAUSED, TERMINAL_STATUSES
from runmux.ipc import IpcError
from runmux.models import RunRecord
from runmux.runner import (
    RunnerError,
    duplicate_run,
    kill_run,
    pause_run,
    restart_run,
    resume_run,
)
from runmux.store import RunNotFoundError as StoreRunNotFoundError
from runmux.store import RunStore
from runmux.web_adapter import RUN_ID_PATTERN, ReadOnlyRunmux


class LifecycleError(RuntimeError):
    """Base exception for lifecycle operations."""


class RunNotFoundError(LifecycleError):
    """Raised when a run ID does not exist or does not match full immutable format."""


class InvalidLifecycleTransitionError(LifecycleError):
    """Raised when requesting an invalid lifecycle transition (e.g. restarting an active run)."""


class LifecyclePlatformError(LifecycleError):
    """Raised when an operation is unsupported on the current host operating system."""


class LifecycleSupervisorUnavailableError(LifecycleError):
    """Raised when a live supervisor is required but unreachable."""


@dataclass(frozen=True)
class LifecycleResult:
    """Outcome of an authorized process lifecycle action."""

    action: str
    status: str
    message: str
    run: RunRecord
    new_run: RunRecord | None = None
    new_run_id: str | None = None
    old_run_id: str | None = None


class LifecycleManager:
    """Manages process lifecycle actions with state validation, idempotency, and platform guards."""

    def __init__(self, state_dir: Path | str) -> None:
        self.state_dir = Path(state_dir).expanduser().resolve()
        self.db_path = self.state_dir / "registry.sqlite3"
        self._store: RunStore | None = None
        self.read_only = ReadOnlyRunmux(self.state_dir)

    @property
    def store(self) -> RunStore:
        if self._store is None:
            self._store = RunStore(self.state_dir)
        return self._store

    def _validate_run_id(self, run_id: str) -> str:
        if not isinstance(run_id, str) or not RUN_ID_PATTERN.fullmatch(run_id):
            raise RunNotFoundError(f"Run ID '{run_id}' must be a full immutable Runmux ID.")
        return run_id

    def _get_run(self, run_id: str) -> RunRecord:
        valid_id = self._validate_run_id(run_id)
        if not self.db_path.is_file():
            raise RunNotFoundError(f"Run '{run_id}' not found.")
        try:
            return self.store.get_run(valid_id)
        except StoreRunNotFoundError as error:
            raise RunNotFoundError(f"Run '{run_id}' not found.") from error

    def stop_run(self, run_id: str, *, force: bool = False) -> LifecycleResult:
        """Stop or terminate a managed run idempotently."""

        record = self._get_run(run_id)

        # Idempotency check: if run is already in terminal state, return without error
        if record.status in TERMINAL_STATUSES:
            return LifecycleResult(
                action="stop",
                status="already_terminated",
                message=f"Run '{run_id}' is already {record.status}.",
                run=record,
            )

        try:
            # kill_run contacts supervisor via IPC, falling back to PID termination on error
            updated = kill_run(self.store, run_id=run_id, force=force)
            refreshed, _ = self.read_only.refresh_display_status(updated)
            return LifecycleResult(
                action="stop",
                status="ok",
                message=f"Run '{run_id}' stopped successfully.",
                run=refreshed,
            )
        except RunnerError as error:
            # If kill_run encountered an error but the run could not be stopped normally,
            # mark it as killed in the store to maintain consistent terminal status
            updated = self.store.update_run(record.id, status=STATUS_KILLED)
            return LifecycleResult(
                action="stop",
                status="ok",
                message=f"Run '{run_id}' marked killed ({error}).",
                run=updated,
            )

    def restart_run(self, run_id: str, *, force_color: bool | None = None) -> LifecycleResult:
        """Restart a terminated run, creating a new run record while preserving historical identity."""

        record = self._get_run(run_id)

        # Invariant check: only terminal runs may be restarted
        if record.status not in TERMINAL_STATUSES:
            raise InvalidLifecycleTransitionError(
                f"Cannot restart active run '{run_id}' (status: {record.status}). "
                "Stop the run first before restarting, or duplicate it."
            )

        try:
            started = restart_run(self.store, run_id=run_id, force_color=force_color)
            new_record, _ = self.read_only.refresh_display_status(started.record)
            return LifecycleResult(
                action="restart",
                status="ok",
                message=f"Run '{run_id}' restarted as '{new_record.id}'.",
                run=new_record,
                new_run=new_record,
                new_run_id=new_record.id,
                old_run_id=record.id,
            )
        except RunnerError as error:
            raise InvalidLifecycleTransitionError(str(error)) from error

    def duplicate_run(self, run_id: str, *, force_color: bool | None = None) -> LifecycleResult:
        """Duplicate an existing run (active or terminal) into a new parallel managed run."""

        record = self._get_run(run_id)

        try:
            started = duplicate_run(self.store, run_id=run_id, force_color=force_color)
            new_record, _ = self.read_only.refresh_display_status(started.record)
            return LifecycleResult(
                action="duplicate",
                status="ok",
                message=f"Run '{run_id}' duplicated as '{new_record.id}'.",
                run=new_record,
                new_run=new_record,
                new_run_id=new_record.id,
                old_run_id=record.id,
            )
        except RunnerError as error:
            raise LifecycleError(str(error)) from error

    def pause_run(self, run_id: str) -> LifecycleResult:
        """Pause a running process when supported by host platform."""

        record = self._get_run(run_id)

        if sys.platform == "win32":
            raise LifecyclePlatformError("Pause is not supported on Windows without an external process API.")

        if record.status in TERMINAL_STATUSES:
            raise InvalidLifecycleTransitionError(
                f"Cannot pause terminal run '{run_id}' (status: {record.status})."
            )

        if record.status == STATUS_PAUSED:
            return LifecycleResult(
                action="pause",
                status="already_paused",
                message=f"Run '{run_id}' is already paused.",
                run=record,
            )

        try:
            updated = pause_run(self.store, run_id=run_id)
            return LifecycleResult(
                action="pause",
                status="ok",
                message=f"Run '{run_id}' paused successfully.",
                run=updated,
            )
        except IpcError as error:
            raise LifecycleSupervisorUnavailableError(
                f"Supervisor for run '{run_id}' is unavailable: {error}"
            ) from error
        except RuntimeError as error:
            if "not supported" in str(error).lower():
                raise LifecyclePlatformError(str(error)) from error
            raise InvalidLifecycleTransitionError(str(error)) from error

    def resume_run(self, run_id: str) -> LifecycleResult:
        """Resume a paused process when supported by host platform."""

        record = self._get_run(run_id)

        if sys.platform == "win32":
            raise LifecyclePlatformError("Resume is not supported on Windows without an external process API.")

        if record.status in TERMINAL_STATUSES:
            raise InvalidLifecycleTransitionError(
                f"Cannot resume terminal run '{run_id}' (status: {record.status})."
            )

        if record.status == "running":
            return LifecycleResult(
                action="resume",
                status="already_running",
                message=f"Run '{run_id}' is already running.",
                run=record,
            )

        try:
            updated = resume_run(self.store, run_id=run_id)
            return LifecycleResult(
                action="resume",
                status="ok",
                message=f"Run '{run_id}' resumed successfully.",
                run=updated,
            )
        except IpcError as error:
            raise LifecycleSupervisorUnavailableError(
                f"Supervisor for run '{run_id}' is unavailable: {error}"
            ) from error
        except RuntimeError as error:
            if "not supported" in str(error).lower():
                raise LifecyclePlatformError(str(error)) from error
            raise InvalidLifecycleTransitionError(str(error)) from error
