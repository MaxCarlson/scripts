"""Read-only Runmux records and transient status for the TUI."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from runmux.client import is_pid_alive
from runmux.constants import STATUS_LOST, TERMINAL_STATUSES
from runmux.history import (
    SavedCommand,
    delete_saved_commands,
    indexed_history_entries,
    list_saved_commands,
    mark_saved_command_run,
    save_record_command,
)
from runmux.ipc import IpcError, request_json
from runmux.models import RunRecord
from runmux.runner import (
    create_managed_run,
    duplicate_run,
    kill_run,
    pause_run,
    remove_run,
    restart_run,
    resume_run,
)
from runmux.store import RunStore


class RunmuxTuiAdapter:
    """Expose registry data to a UI without pruning or persisting status refreshes."""

    def __init__(self, store: RunStore, history_path: Path) -> None:
        self.store = store
        self.history_path = Path(history_path)

    def list_runs(self) -> list[RunRecord]:
        """Return active and historical runs without mutating the registry."""

        return self.store.list_runs(include_all=True)

    def get_run(self, run_id: str) -> RunRecord:
        """Get a record by its immutable full ID, never by its reusable numeric ID."""

        return self.store.get_run(run_id)

    def refresh_display_status(self, record: RunRecord) -> RunRecord:
        """Project current supervisor status onto a record without writing SQLite."""

        if record.status in TERMINAL_STATUSES or record.port is None:
            return record
        try:
            response = request_json(record, op="status", timeout=0.2)
        except IpcError:
            if record.supervisor_pid is not None and not is_pid_alive(record.supervisor_pid):
                return replace(record, status=STATUS_LOST, exit_code=None)
            return record

        values: dict[str, object] = {}
        status = response.get("status")
        if isinstance(status, str) and status:
            values["status"] = status
        for field in ("exit_code", "pid"):
            if field in response:
                values[field] = response[field]
        return replace(record, **values) if values else record

    def launch(self, argv: list[str], *, cwd: Path, name: str | None = None) -> RunRecord:
        """Launch the exact argv and cwd under Runmux supervision."""

        if not argv or not all(isinstance(argument, str) for argument in argv):
            raise ValueError("argv must contain at least one string argument")
        started = create_managed_run(
            self.store,
            program_args=list(argv),
            cwd=Path(cwd),
            name=name,
            force_color=True,
        )
        return started.record

    def kill(self, run_id: str, *, force: bool = False) -> RunRecord:
        return kill_run(self.store, run_id=run_id, force=force)

    def pause(self, run_id: str) -> RunRecord:
        return pause_run(self.store, run_id=run_id)

    def resume(self, run_id: str) -> RunRecord:
        return resume_run(self.store, run_id=run_id)

    def restart(self, run_id: str) -> RunRecord:
        return restart_run(self.store, run_id=run_id).record

    def duplicate(self, run_id: str) -> RunRecord:
        return duplicate_run(self.store, run_id=run_id).record

    def remove_terminal(self, run_id: str) -> RunRecord:
        record = self.get_run(run_id)
        if record.status not in TERMINAL_STATUSES:
            raise ValueError(f"Run {record.id} is not terminal and cannot be removed")
        return remove_run(self.store, run_id=run_id)

    def history_entries(self) -> list[dict[str, object]]:
        return indexed_history_entries(path=self.history_path)

    def saved_commands(self) -> list[SavedCommand]:
        return list_saved_commands(path=self.history_path)

    def save_command(self, run_id: str) -> SavedCommand:
        return save_record_command(self.get_run(run_id), path=self.history_path)

    def delete_saved_commands(self, ids: set[int]) -> list[SavedCommand]:
        return delete_saved_commands(ids, path=self.history_path)

    def launch_saved(self, command: SavedCommand) -> RunRecord:
        record = self.launch(command.argv, cwd=Path(command.cwd), name=command.name)
        mark_saved_command_run(command.command_line, cwd=command.cwd, path=self.history_path)
        return record
