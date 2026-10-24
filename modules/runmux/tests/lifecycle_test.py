"""Unit tests for Runmux core lifecycle management service (Phase 4A)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from runmux.constants import STATUS_FINISHED, STATUS_KILLED, STATUS_PAUSED
from runmux.lifecycle import (
    InvalidLifecycleTransitionError,
    LifecycleManager,
    LifecyclePlatformError,
    LifecycleResult,
    RunNotFoundError,
)
from runmux.models import RunRecord
from runmux.store import RunStore


def create_test_record(
    store: RunStore,
    state_dir: Path,
    run_id: str = "20261024-010101-abcdef",
    status: str = "running",
    pid: int = 12345,
    supervisor_pid: int = 12346,
    port: int | None = 45123,
    command_line: str = "python worker.py",
    argv: list[str] | None = None,
) -> RunRecord:
    run_dir = state_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "output.ansi"
    if not log_path.exists():
        log_path.write_bytes(b"")

    argv_json = json.dumps(argv or ["python", "worker.py"])
    store.create_run(
        run_id=run_id,
        name="test-worker",
        status=status,
        program="python",
        argv_json=argv_json,
        cwd=str(state_dir),
        env_overrides_json="{}",
        auth_token="test-secret",
        log_path=log_path,
        command_line=command_line,
    )
    return store.update_run(
        run_id,
        pid=pid,
        supervisor_pid=supervisor_pid,
        port=port,
        status=status,
    )


def test_validate_exact_run_id_rejects_prefixes_and_numbers(tmp_path: Path) -> None:
    manager = LifecycleManager(tmp_path)
    with pytest.raises(RunNotFoundError):
        manager.stop_run("20261024-010101")  # prefix
    with pytest.raises(RunNotFoundError):
        manager.stop_run("0")  # numeric
    with pytest.raises(RunNotFoundError):
        manager.stop_run("invalid-id-format")


def test_stop_active_run_requests_kill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = RunStore(tmp_path)
    run_id = "20261024-010101-abcdef"
    create_test_record(store, tmp_path, run_id=run_id, status="running")

    ipc_calls: list[tuple[str, dict[str, Any] | None]] = []

    def mock_request_json(record: RunRecord, *, op: str, payload: dict[str, Any] | None = None, **kwargs: Any):
        ipc_calls.append((op, payload))
        store.update_run(record.id, status=STATUS_KILLED)
        return {"ok": True}

    monkeypatch.setattr("runmux.runner.request_json", mock_request_json)

    manager = LifecycleManager(tmp_path)
    result = manager.stop_run(run_id, force=True)

    assert isinstance(result, LifecycleResult)
    assert result.action == "stop"
    assert result.status == "ok"
    assert result.run.status == STATUS_KILLED
    assert ipc_calls == [("kill", {"force": True})]


def test_stop_terminal_run_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = RunStore(tmp_path)
    run_id = "20261024-010101-abcdef"
    create_test_record(store, tmp_path, run_id=run_id, status=STATUS_FINISHED)

    ipc_called = False

    def mock_request_json(*args: Any, **kwargs: Any):
        nonlocal ipc_called
        ipc_called = True
        return {"ok": True}

    monkeypatch.setattr("runmux.runner.request_json", mock_request_json)

    manager = LifecycleManager(tmp_path)
    result = manager.stop_run(run_id)

    assert result.action == "stop"
    assert result.status == "already_terminated"
    assert result.run.status == STATUS_FINISHED
    assert not ipc_called


def test_stop_run_falls_back_to_os_termination_when_supervisor_ipc_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from runmux.ipc import IpcError

    store = RunStore(tmp_path)
    run_id = "20261024-010101-abcdef"
    create_test_record(store, tmp_path, run_id=run_id, status="running", pid=8888, port=9999)

    terminated_pids: list[tuple[int, bool]] = []

    def mock_request_json(*args: Any, **kwargs: Any):
        raise IpcError("Supervisor connection refused")

    def mock_terminate_pid(pid: int, *, force: bool):
        terminated_pids.append((pid, force))

    monkeypatch.setattr("runmux.runner.request_json", mock_request_json)
    monkeypatch.setattr("runmux.runner.terminate_pid", mock_terminate_pid)

    manager = LifecycleManager(tmp_path)
    result = manager.stop_run(run_id, force=False)

    assert result.action == "stop"
    assert result.status == "ok"
    assert result.run.status == STATUS_KILLED
    assert terminated_pids == [(8888, False)]


def test_restart_terminal_run_preserves_identity_and_creates_new_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = RunStore(tmp_path)
    old_id = "20261024-010101-abcdef"
    create_test_record(store, tmp_path, run_id=old_id, status=STATUS_FINISHED)

    new_id = "20261024-020202-fedcba"

    def mock_create_managed_run(target_store: RunStore, **kwargs: Any):
        new_dir = tmp_path / "runs" / new_id
        new_dir.mkdir(parents=True, exist_ok=True)
        log = new_dir / "output.ansi"
        log.write_bytes(b"")
        new_rec = target_store.create_run(
            run_id=new_id,
            name=kwargs.get("name"),
            status="running",
            program="python",
            argv_json=json.dumps(kwargs.get("program_args")),
            cwd=str(kwargs.get("cwd")),
            env_overrides_json="{}",
            auth_token="new-token",
            log_path=log,
            command_line="python worker.py",
            restart_of=kwargs.get("restart_of"),
            duplicate_of=kwargs.get("duplicate_of"),
        )
        return SimpleNamespace(record=new_rec, supervisor_process=None)

    monkeypatch.setattr("runmux.runner.create_managed_run", mock_create_managed_run)

    manager = LifecycleManager(tmp_path)
    result = manager.restart_run(old_id)

    assert result.action == "restart"
    assert result.status == "ok"
    assert result.old_run_id == old_id
    assert result.new_run_id == new_id
    assert result.run.id == new_id
    assert result.run.restart_of == old_id

    # Verify old record is still in store intact
    original = store.get_run(old_id)
    assert original.status == STATUS_FINISHED
    assert original.id == old_id


def test_restart_active_run_raises_invalid_transition(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    run_id = "20261024-010101-abcdef"
    create_test_record(store, tmp_path, run_id=run_id, status="running")

    manager = LifecycleManager(tmp_path)
    with pytest.raises(InvalidLifecycleTransitionError) as exc_info:
        manager.restart_run(run_id)

    assert "Cannot restart active run" in str(exc_info.value)


def test_duplicate_run_creates_new_record_with_duplicate_of(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = RunStore(tmp_path)
    source_id = "20261024-010101-abcdef"
    create_test_record(store, tmp_path, run_id=source_id, status="running")

    dup_id = "20261024-030303-111222"

    def mock_create_managed_run(target_store: RunStore, **kwargs: Any):
        new_dir = tmp_path / "runs" / dup_id
        new_dir.mkdir(parents=True, exist_ok=True)
        log = new_dir / "output.ansi"
        log.write_bytes(b"")
        new_rec = target_store.create_run(
            run_id=dup_id,
            name=kwargs.get("name"),
            status="running",
            program="python",
            argv_json=json.dumps(kwargs.get("program_args")),
            cwd=str(kwargs.get("cwd")),
            env_overrides_json="{}",
            auth_token="dup-token",
            log_path=log,
            command_line="python worker.py",
            restart_of=kwargs.get("restart_of"),
            duplicate_of=kwargs.get("duplicate_of"),
        )
        return SimpleNamespace(record=new_rec, supervisor_process=None)

    monkeypatch.setattr("runmux.runner.create_managed_run", mock_create_managed_run)

    manager = LifecycleManager(tmp_path)
    result = manager.duplicate_run(source_id)

    assert result.action == "duplicate"
    assert result.status == "ok"
    assert result.old_run_id == source_id
    assert result.new_run_id == dup_id
    assert result.run.id == dup_id
    assert result.run.duplicate_of == source_id


def test_pause_and_resume_on_windows_raises_platform_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = RunStore(tmp_path)
    run_id = "20261024-010101-abcdef"
    create_test_record(store, tmp_path, run_id=run_id, status="running")

    monkeypatch.setattr(sys, "platform", "win32")

    manager = LifecycleManager(tmp_path)

    with pytest.raises(LifecyclePlatformError) as pause_err:
        manager.pause_run(run_id)
    assert "not supported on Windows" in str(pause_err.value)

    with pytest.raises(LifecyclePlatformError) as resume_err:
        manager.resume_run(run_id)
    assert "not supported on Windows" in str(resume_err.value)


def test_pause_and_resume_on_posix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = RunStore(tmp_path)
    run_id = "20261024-010101-abcdef"
    create_test_record(store, tmp_path, run_id=run_id, status="running")

    monkeypatch.setattr(sys, "platform", "linux")

    ipc_ops: list[str] = []

    def mock_request_json(record: RunRecord, *, op: str, **kwargs: Any):
        ipc_ops.append(op)
        if op == "pause":
            store.update_run(record.id, status=STATUS_PAUSED)
        elif op == "resume":
            store.update_run(record.id, status="running")
        return {"ok": True}

    monkeypatch.setattr("runmux.runner.request_json", mock_request_json)

    manager = LifecycleManager(tmp_path)

    # 1. Pause running run
    pause_res = manager.pause_run(run_id)
    assert pause_res.action == "pause"
    assert pause_res.status == "ok"
    assert pause_res.run.status == STATUS_PAUSED

    # 2. Pause already paused run is idempotent
    pause_again = manager.pause_run(run_id)
    assert pause_again.status == "already_paused"

    # 3. Resume paused run
    resume_res = manager.resume_run(run_id)
    assert resume_res.action == "resume"
    assert resume_res.status == "ok"
    assert resume_res.run.status == "running"

    # 4. Resume already running run is idempotent
    resume_again = manager.resume_run(run_id)
    assert resume_again.status == "already_running"

    assert ipc_ops == ["pause", "resume"]
