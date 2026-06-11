"""Run creation, process control, restart, and duplication helpers."""

from __future__ import annotations

import json
import os
import secrets
import shlex
import shutil
import subprocess
import sys
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from runmux.constants import STATUS_PENDING, TERMINAL_STATUSES
from runmux.ipc import IpcError, request_json
from runmux.models import RunRecord
from runmux.store import RunStore


class RunnerError(RuntimeError):
    """Raised for managed-run lifecycle errors."""


@dataclass(frozen=True)
class StartedRun:
    """Result returned after starting a managed run."""

    record: RunRecord
    supervisor_pid: int | None


def generate_run_id(existing_ids: set[str] | None = None) -> str:
    """Generate a collision-resistant readable run ID."""

    existing = existing_ids or set()
    for _ in range(20):
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        suffix = secrets.token_hex(3)
        candidate = f"{timestamp}-{suffix}"
        if candidate not in existing:
            return candidate
    raise RunnerError("Could not generate a unique run ID.")


def normalize_program_args(program_args: list[str]) -> list[str]:
    """Normalize argparse REMAINDER program arguments."""

    if program_args and program_args[0] == "--":
        program_args = program_args[1:]
    if not program_args:
        raise RunnerError("No program was provided. Use: runmux run -- <program> [args...]")
    return program_args


def command_line_for_display(argv: list[str]) -> str:
    """Return a display command line for a vector of arguments."""

    if sys.platform == "win32":
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)


def build_env_overrides(*, force_color: bool) -> dict[str, str]:
    """Build deterministic environment overrides for managed programs."""

    overrides = {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
        "RUNMUX": "1",
    }
    if force_color:
        overrides.update(
            {
                "TERM": os.environ.get("TERM", "xterm-256color"),
                "COLORTERM": os.environ.get("COLORTERM", "truecolor"),
                "CLICOLOR_FORCE": "1",
                "FORCE_COLOR": "1",
            }
        )
    return overrides


def create_managed_run(
    store: RunStore,
    *,
    program_args: list[str],
    cwd: Path | None,
    name: str | None,
    force_color: bool,
    restart_of: str | None = None,
    duplicate_of: str | None = None,
    rows: int | None = None,
    columns: int | None = None,
) -> StartedRun:
    """Create a registry record and start a detached supervisor."""

    argv = normalize_program_args(program_args)
    run_id = generate_run_id(store.ids_exist([]))
    run_dir = store.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    log_path = run_dir / "output.ansi"
    log_path.touch(mode=0o600, exist_ok=False)

    resolved_cwd = (cwd or Path.cwd()).expanduser().resolve()
    if not resolved_cwd.exists() or not resolved_cwd.is_dir():
        raise RunnerError(f"Working directory does not exist or is not a directory: {resolved_cwd}")

    env_overrides = build_env_overrides(force_color=force_color)
    terminal_size = shutil.get_terminal_size(fallback=(80, 24))
    final_rows = rows or terminal_size.lines
    final_columns = columns or terminal_size.columns

    record = store.create_run(
        run_id=run_id,
        name=name,
        status=STATUS_PENDING,
        program=argv[0],
        argv_json=json.dumps(argv),
        cwd=str(resolved_cwd),
        env_overrides_json=json.dumps(env_overrides, sort_keys=True),
        auth_token=secrets.token_urlsafe(32),
        log_path=log_path,
        command_line=command_line_for_display(argv),
        restart_of=restart_of,
        duplicate_of=duplicate_of,
        rows=final_rows,
        columns=final_columns,
    )
    supervisor = start_supervisor(record.id, state_dir=store.state_dir)
    record = store.update_run(record.id, supervisor_pid=supervisor.pid)
    return StartedRun(record=record, supervisor_pid=supervisor.pid)


def start_supervisor(run_id: str, *, state_dir: Path | None = None) -> subprocess.Popen[Any]:
    """Start a detached supervisor process for a run ID."""

    command = [sys.executable, "-m", "runmux.supervisor", "--run-id", run_id]
    if state_dir is not None:
        command.extend(["--state-dir", str(state_dir)])
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": sys.platform != "win32",
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = windows_supervisor_creation_flags()
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(command, **kwargs)


def windows_supervisor_creation_flags() -> int:
    """Return Windows process flags that keep supervisors headless."""

    return getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
        subprocess, "CREATE_NO_WINDOW", 0
    )


def kill_run(store: RunStore, *, run_id: str, force: bool) -> RunRecord:
    """Request termination of a managed run."""

    record = store.get_run(run_id)
    if record.status in TERMINAL_STATUSES:
        return record
    if record.port is not None:
        try:
            request_json(record, op="kill", payload={"force": force})
            return store.get_run(record.id)
        except IpcError:
            pass
    if record.pid is None:
        raise RunnerError(f"Run '{record.id}' has no process ID to kill.")
    try:
        terminate_pid(record.pid, force=force)
    except OSError as error:
        raise RunnerError(f"Could not kill run '{record.id}' PID {record.pid}: {error}") from error
    return store.update_run(record.id, status="killed")


def terminate_pid(pid: int, *, force: bool) -> None:
    """Terminate a local process by PID."""

    if sys.platform == "win32":
        command = ["taskkill", "/PID", str(pid), "/T"]
        if force:
            command.append("/F")
        subprocess.run(
            command,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return
    import signal

    os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)


def remove_run(store: RunStore, *, run_id: str) -> RunRecord:
    """Remove a terminal run and clean up any leftover supervisor process."""

    record = store.remove_run(run_id)
    cleanup_supervisor_process(record)
    return record


def remove_finished_runs(store: RunStore, *, clean_only: bool = False) -> list[RunRecord]:
    """Remove terminal runs and clean up any leftover supervisor processes."""

    records = store.remove_finished_runs(clean_only=clean_only)
    for record in records:
        cleanup_supervisor_process(record)
    return records


def cleanup_supervisor_process(record: RunRecord) -> None:
    """Best-effort cleanup for a supervisor process that survived a terminal run."""

    if record.supervisor_pid is None:
        return
    with suppress(OSError, RunnerError):
        terminate_pid(record.supervisor_pid, force=True)


def restart_run(
    store: RunStore,
    *,
    run_id: str,
    force_color: bool | None = None,
) -> StartedRun:
    """Start a new run using a previous run's command metadata."""

    source = store.get_run(run_id)
    if source.status not in TERMINAL_STATUSES:
        raise RunnerError(
            f"Run '{source.id}' is not finished. Use duplicate for concurrent copies, "
            "or kill it before restarting."
        )
    return clone_run(
        store, source=source, restart_of=source.id, duplicate_of=None, force_color=force_color
    )


def duplicate_run(
    store: RunStore,
    *,
    run_id: str,
    force_color: bool | None = None,
) -> StartedRun:
    """Start a concurrent copy of a previous run's command metadata."""

    source = store.get_run(run_id)
    return clone_run(
        store, source=source, restart_of=None, duplicate_of=source.id, force_color=force_color
    )


def clone_run(
    store: RunStore,
    *,
    source: RunRecord,
    restart_of: str | None,
    duplicate_of: str | None,
    force_color: bool | None,
) -> StartedRun:
    """Create a new run from an existing run record."""

    argv = json.loads(source.argv_json)
    if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
        raise RunnerError(f"Run '{source.id}' has invalid argv metadata.")
    existing_overrides = json.loads(source.env_overrides_json)
    if not isinstance(existing_overrides, dict):
        existing_overrides = {}
    resolved_force_color = force_color
    if resolved_force_color is None:
        resolved_force_color = bool(existing_overrides.get("FORCE_COLOR"))
    return create_managed_run(
        store,
        program_args=argv,
        cwd=Path(source.cwd),
        name=source.name,
        force_color=resolved_force_color,
        restart_of=restart_of,
        duplicate_of=duplicate_of,
        rows=source.rows,
        columns=source.columns,
    )


def pause_run(store: RunStore, *, run_id: str) -> RunRecord:
    """Pause a managed run using the supervisor."""

    record = store.get_run(run_id)
    request_json(record, op="pause")
    return store.get_run(record.id)


def resume_run(store: RunStore, *, run_id: str) -> RunRecord:
    """Resume a managed run using the supervisor."""

    record = store.get_run(run_id)
    request_json(record, op="resume")
    return store.get_run(record.id)
