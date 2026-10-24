"""Unit tests for Runmux core lifecycle management service (Phase 4A)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psutil
import pytest

from runmux.constants import STATUS_FINISHED, STATUS_KILLED, STATUS_PAUSED
from runmux.lifecycle import (
    InvalidLifecycleTransitionError,
    LifecycleError,
    LifecycleManager,
    LifecyclePlatformError,
    LifecycleResult,
    RunNotFoundError,
)
from runmux.models import RunRecord
from runmux.runner import RunnerError, kill_run
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
    env_overrides: dict[str, str] | None = None,
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
        env_overrides_json=json.dumps(env_overrides or {}),
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


def test_kill_run_method_defaults_to_forced_termination(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    result = manager.kill_run(run_id)

    assert result.action == "kill"
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
    pid_alive = True

    def mock_request_json(*args: Any, **kwargs: Any):
        raise IpcError("Supervisor connection refused")

    def mock_terminate_pid(pid: int, *, force: bool):
        nonlocal pid_alive
        terminated_pids.append((pid, force))
        pid_alive = False

    def mock_verify_run_process(psutil_mod: Any, record: RunRecord):
        if pid_alive:
            return SimpleNamespace(is_running=lambda: True), None
        return None, "process exited"

    monkeypatch.setattr("runmux.runner.request_json", mock_request_json)
    monkeypatch.setattr("runmux.runner.terminate_pid", mock_terminate_pid)
    monkeypatch.setattr("runmux.runner.verify_run_process", mock_verify_run_process)
    monkeypatch.setattr(psutil, "pid_exists", lambda pid: pid_alive)

    manager = LifecycleManager(tmp_path)
    result = manager.stop_run(run_id, force=False)

    assert result.action == "stop"
    assert result.status == "ok"
    assert result.run.status == STATUS_KILLED
    assert (8888, False) in terminated_pids
    assert (12346, True) in terminated_pids


def test_termination_failure_preserves_state_and_raises_lifecycle_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that when termination fails, status is NOT marked killed and an error is raised."""
    store = RunStore(tmp_path)
    run_id = "20261024-010101-abcdef"
    create_test_record(store, tmp_path, run_id=run_id, status="running", pid=8888, port=9999)

    def mock_kill_run(*args: Any, **kwargs: Any):
        raise RunnerError("Process could not be terminated: Access is denied")

    monkeypatch.setattr("runmux.lifecycle.kill_run", mock_kill_run)

    manager = LifecycleManager(tmp_path)
    with pytest.raises(LifecycleError) as exc_info:
        manager.stop_run(run_id)

    assert "Could not terminate run" in str(exc_info.value)
    # State MUST be preserved as running, NOT killed!
    record = store.get_run(run_id)
    assert record.status == "running"


def test_kill_run_protects_reused_pid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that if supervisor IPC fails and PID reuse is detected, the reused PID is NOT killed."""
    from runmux.ipc import IpcError

    store = RunStore(tmp_path)
    run_id = "20261024-010101-abcdef"
    create_test_record(store, tmp_path, run_id=run_id, status="running", pid=9999, port=8888)

    terminated_pids: list[int] = []

    def mock_request_json(*args: Any, **kwargs: Any):
        raise IpcError("Supervisor connection refused")

    def mock_verify_run_process(psutil_mod: Any, record: RunRecord):
        # Simulate PID reuse detection
        return None, "pid reused by another process"

    def mock_terminate_pid(pid: int, *, force: bool):
        terminated_pids.append(pid)

    monkeypatch.setattr("runmux.runner.request_json", mock_request_json)
    monkeypatch.setattr("runmux.runner.verify_run_process", mock_verify_run_process)
    monkeypatch.setattr("runmux.runner.terminate_pid", mock_terminate_pid)

    updated = kill_run(store, run_id=run_id, force=True)

    # The recycled PID must NOT have been terminated!
    assert 9999 not in terminated_pids
    assert updated.status == STATUS_KILLED


def test_windows_taskkill_failure_raises_runner_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that when taskkill fails on Windows with non-zero exit code, RunnerError is raised."""
    from runmux.ipc import IpcError

    store = RunStore(tmp_path)
    run_id = "20261024-010101-abcdef"
    create_test_record(store, tmp_path, run_id=run_id, status="running", pid=7777, port=8888)

    def mock_request_json(*args: Any, **kwargs: Any):
        raise IpcError("Supervisor connection refused")

    def mock_verify_run_process(psutil_mod: Any, record: RunRecord):
        return SimpleNamespace(is_running=lambda: True), None

    def mock_subprocess_run(*args: Any, **kwargs: Any):
        # Simulate taskkill access denied
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="ERROR: Access is denied.")

    monkeypatch.setattr("runmux.runner.request_json", mock_request_json)
    monkeypatch.setattr("runmux.runner.verify_run_process", mock_verify_run_process)
    monkeypatch.setattr(subprocess, "run", mock_subprocess_run)
    monkeypatch.setattr(psutil, "pid_exists", lambda pid: True)
    monkeypatch.setattr(sys, "platform", "win32")

    with pytest.raises(RunnerError) as exc_info:
        kill_run(store, run_id=run_id, force=True)

    assert "Access is denied" in str(exc_info.value) or "could not be terminated" in str(exc_info.value)
    # The record was NOT marked killed because termination failed
    assert store.get_run(run_id).status == "running"


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


def test_repeated_restart_rejected_while_active_restart_exists(tmp_path: Path) -> None:
    """Verify that restarting a run while an active restart already exists is rejected."""
    store = RunStore(tmp_path)
    old_id = "20261024-010101-abcdef"
    active_restart_id = "20261024-020202-123456"

    create_test_record(store, tmp_path, run_id=old_id, status=STATUS_FINISHED)
    # Create an active restart of old_id
    run_dir = tmp_path / "runs" / active_restart_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log = run_dir / "output.ansi"
    log.write_bytes(b"")
    store.create_run(
        run_id=active_restart_id,
        name="test-worker",
        status="running",
        program="python",
        argv_json=json.dumps(["python", "worker.py"]),
        cwd=str(tmp_path),
        env_overrides_json="{}",
        auth_token="tok",
        log_path=log,
        command_line="python worker.py",
        restart_of=old_id,
    )

    manager = LifecycleManager(tmp_path)
    with pytest.raises(InvalidLifecycleTransitionError) as exc_info:
        manager.restart_run(old_id)

    assert "already running" in str(exc_info.value)
    assert active_restart_id in str(exc_info.value)


def test_concurrent_in_flight_restart_and_duplicate_rejected(tmp_path: Path) -> None:
    """Verify in-flight operation guards reject concurrent duplicate launches."""
    store = RunStore(tmp_path)
    run_id = "20261024-010101-abcdef"
    create_test_record(store, tmp_path, run_id=run_id, status=STATUS_FINISHED)

    manager = LifecycleManager(tmp_path)
    # Simulate an in-flight restart already registered
    manager._in_flight_restarts.add(run_id)

    with pytest.raises(InvalidLifecycleTransitionError) as exc_info:
        manager.restart_run(run_id)
    assert "already in progress" in str(exc_info.value)

    # Simulate an in-flight duplicate already registered
    manager._in_flight_duplicates.add(run_id)
    with pytest.raises(InvalidLifecycleTransitionError) as dup_exc:
        manager.duplicate_run(run_id)
    assert "already in progress" in str(dup_exc.value)


def test_environment_overrides_preserved_across_restart_and_duplicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify custom environment overrides in source run are preserved across restart and duplicate."""
    store = RunStore(tmp_path)
    source_id = "20261024-010101-abcdef"
    custom_env = {"MY_CUSTOM_VAR": "foo_bar", "BATCH_MODE": "1"}
    create_test_record(store, tmp_path, run_id=source_id, status=STATUS_FINISHED, env_overrides=custom_env)

    passed_extra_envs: list[dict[str, str]] = []

    def mock_create_managed_run(target_store: RunStore, **kwargs: Any):
        extra = kwargs.get("extra_env") or {}
        passed_extra_envs.append(extra)
        new_id = f"20261024-999999-{len(passed_extra_envs):06d}"
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
            env_overrides_json=json.dumps(extra),
            auth_token="token",
            log_path=log,
            command_line="python worker.py",
            restart_of=kwargs.get("restart_of"),
            duplicate_of=kwargs.get("duplicate_of"),
        )
        return SimpleNamespace(record=new_rec, supervisor_process=None)

    monkeypatch.setattr("runmux.runner.create_managed_run", mock_create_managed_run)

    manager = LifecycleManager(tmp_path)

    # 1. Restart preserves custom env
    manager.restart_run(source_id)
    assert len(passed_extra_envs) == 1
    assert passed_extra_envs[0].get("MY_CUSTOM_VAR") == "foo_bar"
    assert passed_extra_envs[0].get("BATCH_MODE") == "1"

    # 2. Duplicate preserves custom env
    manager.duplicate_run(source_id)
    assert len(passed_extra_envs) == 2
    assert passed_extra_envs[1].get("MY_CUSTOM_VAR") == "foo_bar"
    assert passed_extra_envs[1].get("BATCH_MODE") == "1"


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
