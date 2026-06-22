"""Run creation, process control, restart, and duplication helpers."""

from __future__ import annotations

import json
import os
import secrets
import shlex
import shutil
import subprocess
import sys
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from runmux.constants import DEFAULT_STARTUP_TIMEOUT_SECONDS, STATUS_PENDING, TERMINAL_STATUSES
from runmux.history import mark_saved_command_run, record_run_started, save_record_command
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
    reserve_rows: int = 0,
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
    final_rows = max(1, (rows or terminal_size.lines) - max(0, reserve_rows))
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
    record_run_started(record)
    supervisor = start_supervisor(record.id, state_dir=store.state_dir)
    record = store.update_run(record.id, supervisor_pid=supervisor.pid)
    record = wait_for_supervisor_ready(
        store,
        run_id=record.id,
        supervisor=supervisor,
    )
    return StartedRun(record=record, supervisor_pid=supervisor.pid)


def save_run_command(store: RunStore, *, run_id: str) -> RunRecord:
    """Save an existing run's command for later reuse."""

    record = store.get_run(run_id)
    saved = save_record_command(record)
    mark_saved_command_run(saved.command_line)
    return record


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


def wait_for_supervisor_ready(
    store: RunStore,
    *,
    run_id: str,
    supervisor: subprocess.Popen[Any],
    timeout_seconds: float = DEFAULT_STARTUP_TIMEOUT_SECONDS,
    poll_seconds: float = 0.05,
) -> RunRecord:
    """Wait until a new supervisor publishes a responsive IPC endpoint."""

    deadline = time.monotonic() + max(0.0, timeout_seconds)
    last_ipc_error: IpcError | None = None
    while time.monotonic() < deadline:
        record = store.get_run(run_id)
        if record.status in TERMINAL_STATUSES:
            raise startup_failure(record)
        if record.port is not None:
            try:
                request_json(record, op="status", timeout=min(0.5, poll_seconds * 4))
                return store.get_run(run_id)
            except IpcError as error:
                last_ipc_error = error
        poll = getattr(supervisor, "poll", None)
        if callable(poll) and poll() is not None:
            record = store.get_run(run_id)
            if record.status in TERMINAL_STATUSES:
                raise startup_failure(record)
            raise RunnerError(
                f"Supervisor exited before run '{record.numeric_id}' became ready. "
                f"Try: runmux view -i {record.numeric_id}"
            )
        time.sleep(max(0.01, poll_seconds))

    record = store.get_run(run_id)
    detail = f" Last IPC error: {last_ipc_error}" if last_ipc_error is not None else ""
    raise RunnerError(
        f"Run '{record.numeric_id}' did not become ready within {timeout_seconds:.1f}s.{detail} "
        f"The run was left registered; inspect it with: runmux view -i {record.numeric_id}"
    )


def startup_failure(record: RunRecord) -> RunnerError:
    """Build an actionable startup failure with a short managed-log tail."""

    exit_text = "--" if record.exit_code is None else str(record.exit_code)
    tail = read_log_tail(record.log_file)
    message = f"Run '{record.numeric_id}' exited during startup " f"(status={record.status}, exit_code={exit_text})."
    if tail:
        message += f"\nLast output:\n{tail}"
    return RunnerError(message)


def read_log_tail(path: Path, *, max_bytes: int = 4096, max_lines: int = 12) -> str:
    """Return a short UTF-8-safe tail from a managed output log."""

    try:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(max(0, size - max_bytes))
            data = stream.read()
    except OSError:
        return ""
    text = data.decode("utf-8", errors="replace")
    return "\n".join(text.splitlines()[-max_lines:]).strip()


def windows_supervisor_creation_flags() -> int:
    """Return Windows process flags that keep supervisors headless."""

    return getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)


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
            f"Run '{source.id}' is not finished. Use duplicate for concurrent copies, " "or kill it before restarting."
        )
    return clone_run(store, source=source, restart_of=source.id, duplicate_of=None, force_color=force_color)


def duplicate_run(
    store: RunStore,
    *,
    run_id: str,
    force_color: bool | None = None,
) -> StartedRun:
    """Start a concurrent copy of a previous run's command metadata."""

    source = store.get_run(run_id)
    return clone_run(store, source=source, restart_of=None, duplicate_of=source.id, force_color=force_color)


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
