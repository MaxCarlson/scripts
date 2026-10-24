"""Integration tests for authenticated browser lifecycle API endpoints (Phase 4A)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from runmux.constants import STATUS_FINISHED, STATUS_KILLED
from runmux.models import RunRecord
from runmux.store import RunStore
from runmux.web import create_runmux_web_app


def create_test_run(
    store: RunStore,
    state_dir: Path,
    run_id: str = "20261024-010101-abcdef",
    status: str = "running",
    pid: int = 12345,
    supervisor_pid: int = 12346,
    port: int | None = 45123,
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
        command_line="python worker.py",
    )
    return store.update_run(
        run_id,
        pid=pid,
        supervisor_pid=supervisor_pid,
        port=port,
        status=status,
    )


def test_unauthenticated_lifecycle_requests_rejected(tmp_path: Path) -> None:
    app = create_runmux_web_app(tmp_path, login_code="secret123")
    run_id = "20261024-010101-abcdef"

    with TestClient(app, base_url="http://localhost") as client:
        for action in ("stop", "kill", "restart", "duplicate", "pause", "resume"):
            res = client.post(f"/api/runs/{run_id}/{action}", headers={"Origin": "http://localhost"})
            assert res.status_code in {401, 403}


def test_wrong_origin_lifecycle_requests_rejected(tmp_path: Path) -> None:
    app = create_runmux_web_app(tmp_path, login_code="secret123")
    run_id = "20261024-010101-abcdef"

    with TestClient(app, base_url="http://localhost") as client:
        # Login with legitimate origin
        login_res = client.post("/auth/login", json={"code": "secret123"}, headers={"Origin": "http://localhost"})
        assert login_res.status_code == 204

        # Mutation request from evil origin must be rejected with 403
        for action in ("stop", "restart", "duplicate", "pause", "resume"):
            res = client.post(f"/api/runs/{run_id}/{action}", headers={"Origin": "http://evil.com"})
            assert res.status_code == 403


def test_non_existent_and_invalid_run_ids_return_404(tmp_path: Path) -> None:
    app = create_runmux_web_app(tmp_path, login_code="secret123")

    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "secret123"}, headers={"Origin": "http://localhost"})

        # Valid format but non-existent run
        res = client.post("/api/runs/20261024-999999-000000/stop", headers={"Origin": "http://localhost"})
        assert res.status_code == 404

        # Invalid format (numeric ID or prefix)
        res_numeric = client.post("/api/runs/0/stop", headers={"Origin": "http://localhost"})
        assert res_numeric.status_code == 404

        res_prefix = client.post("/api/runs/20261024-010101/stop", headers={"Origin": "http://localhost"})
        assert res_prefix.status_code == 404


def test_api_stop_active_run_returns_200_and_killed_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = RunStore(tmp_path)
    run_id = "20261024-010101-abcdef"
    create_test_run(store, tmp_path, run_id=run_id, status="running")

    ipc_calls: list[tuple[str, dict[str, Any] | None]] = []

    def mock_request_json(record: RunRecord, *, op: str, payload: dict[str, Any] | None = None, **kwargs: Any):
        ipc_calls.append((op, payload))
        store.update_run(record.id, status=STATUS_KILLED)
        return {"ok": True}

    monkeypatch.setattr("runmux.runner.request_json", mock_request_json)

    app = create_runmux_web_app(tmp_path, login_code="secret123")
    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "secret123"}, headers={"Origin": "http://localhost"})

        # Stop defaults to graceful (force=False)
        res = client.post(f"/api/runs/{run_id}/stop", headers={"Origin": "http://localhost"})
        assert res.status_code == 200
        data = res.json()
        assert data["action"] == "stop"
        assert data["status"] == "ok"
        assert data["run"]["id"] == run_id
        assert data["run"]["status"] == STATUS_KILLED
        assert ipc_calls == [("kill", {"force": False})]


def test_api_kill_active_run_returns_200_with_action_kill_and_forced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = RunStore(tmp_path)
    run_id = "20261024-010101-abcdef"
    create_test_run(store, tmp_path, run_id=run_id, status="running")

    ipc_calls: list[tuple[str, dict[str, Any] | None]] = []

    def mock_request_json(record: RunRecord, *, op: str, payload: dict[str, Any] | None = None, **kwargs: Any):
        ipc_calls.append((op, payload))
        store.update_run(record.id, status=STATUS_KILLED)
        return {"ok": True}

    monkeypatch.setattr("runmux.runner.request_json", mock_request_json)

    app = create_runmux_web_app(tmp_path, login_code="secret123")
    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "secret123"}, headers={"Origin": "http://localhost"})

        # Kill defaults to forced (force=True)
        res = client.post(f"/api/runs/{run_id}/kill", headers={"Origin": "http://localhost"})
        assert res.status_code == 200
        data = res.json()
        assert data["action"] == "kill"
        assert data["status"] == "ok"
        assert data["run"]["id"] == run_id
        assert data["run"]["status"] == STATUS_KILLED
        assert ipc_calls == [("kill", {"force": True})]


def test_api_termination_failure_returns_500_and_leaves_run_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from runmux.runner import RunnerError

    store = RunStore(tmp_path)
    run_id = "20261024-010101-abcdef"
    create_test_run(store, tmp_path, run_id=run_id, status="running")

    def mock_kill_run(*args: Any, **kwargs: Any):
        raise RunnerError("Process could not be terminated: Access is denied")

    monkeypatch.setattr("runmux.lifecycle.kill_run", mock_kill_run)

    app = create_runmux_web_app(tmp_path, login_code="secret123")
    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "secret123"}, headers={"Origin": "http://localhost"})

        res = client.post(f"/api/runs/{run_id}/stop", headers={"Origin": "http://localhost"})
        assert res.status_code == 500
        assert "Could not terminate run" in res.json()["detail"]

    # Verify run remains running in the store
    assert store.get_run(run_id).status == "running"


def test_api_stop_terminal_run_is_idempotent(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    run_id = "20261024-010101-abcdef"
    create_test_run(store, tmp_path, run_id=run_id, status=STATUS_FINISHED)

    app = create_runmux_web_app(tmp_path, login_code="secret123")
    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "secret123"}, headers={"Origin": "http://localhost"})

        res = client.post(f"/api/runs/{run_id}/stop", headers={"Origin": "http://localhost"})
        assert res.status_code == 200
        data = res.json()
        assert data["action"] == "stop"
        assert data["status"] == "already_terminated"
        assert data["run"]["status"] == STATUS_FINISHED


def test_api_restart_terminal_run_creates_new_record_and_returns_201(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = RunStore(tmp_path)
    old_id = "20261024-010101-abcdef"
    create_test_run(store, tmp_path, run_id=old_id, status=STATUS_FINISHED)

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

    app = create_runmux_web_app(tmp_path, login_code="secret123")
    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "secret123"}, headers={"Origin": "http://localhost"})

        res = client.post(f"/api/runs/{old_id}/restart", headers={"Origin": "http://localhost"})
        assert res.status_code == 201
        data = res.json()
        assert data["action"] == "restart"
        assert data["status"] == "ok"
        assert data["old_run_id"] == old_id
        assert data["new_run_id"] == new_id
        assert data["run"]["id"] == new_id
        assert data["run"]["restart_of"] == old_id


def test_api_restart_active_run_returns_409_conflict(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    run_id = "20261024-010101-abcdef"
    create_test_run(store, tmp_path, run_id=run_id, status="running")

    app = create_runmux_web_app(tmp_path, login_code="secret123")
    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "secret123"}, headers={"Origin": "http://localhost"})

        res = client.post(f"/api/runs/{run_id}/restart", headers={"Origin": "http://localhost"})
        assert res.status_code == 409
        assert "Cannot restart active run" in res.json()["detail"]


def test_api_repeated_restart_with_active_restart_returns_409(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    old_id = "20261024-010101-abcdef"
    create_test_run(store, tmp_path, run_id=old_id, status=STATUS_FINISHED)

    # Active restart already running
    active_id = "20261024-020202-123456"
    run_dir = tmp_path / "runs" / active_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "output.ansi").write_bytes(b"")
    store.create_run(
        run_id=active_id,
        name="test-worker",
        status="running",
        program="python",
        argv_json=json.dumps(["python", "worker.py"]),
        cwd=str(tmp_path),
        env_overrides_json="{}",
        auth_token="tok",
        log_path=run_dir / "output.ansi",
        command_line="python worker.py",
        restart_of=old_id,
    )

    app = create_runmux_web_app(tmp_path, login_code="secret123")
    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "secret123"}, headers={"Origin": "http://localhost"})

        res = client.post(f"/api/runs/{old_id}/restart", headers={"Origin": "http://localhost"})
        assert res.status_code == 409
        assert "already running" in res.json()["detail"]


def test_api_duplicate_run_returns_201_with_duplicate_of(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = RunStore(tmp_path)
    source_id = "20261024-010101-abcdef"
    create_test_run(store, tmp_path, run_id=source_id, status="running")

    dup_id = "20261024-030303-112233"

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

    app = create_runmux_web_app(tmp_path, login_code="secret123")
    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "secret123"}, headers={"Origin": "http://localhost"})

        res = client.post(f"/api/runs/{source_id}/duplicate", headers={"Origin": "http://localhost"})
        assert res.status_code == 201
        data = res.json()
        assert data["action"] == "duplicate"
        assert data["status"] == "ok"
        assert data["new_run_id"] == dup_id
        assert data["run"]["id"] == dup_id
        assert data["run"]["duplicate_of"] == source_id


def test_api_pause_and_resume_on_windows_returns_501(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = RunStore(tmp_path)
    run_id = "20261024-010101-abcdef"
    create_test_run(store, tmp_path, run_id=run_id, status="running")

    monkeypatch.setattr(sys, "platform", "win32")

    app = create_runmux_web_app(tmp_path, login_code="secret123")
    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "secret123"}, headers={"Origin": "http://localhost"})

        res_pause = client.post(f"/api/runs/{run_id}/pause", headers={"Origin": "http://localhost"})
        assert res_pause.status_code == 501
        assert "not supported on Windows" in res_pause.json()["detail"]

        res_resume = client.post(f"/api/runs/{run_id}/resume", headers={"Origin": "http://localhost"})
        assert res_resume.status_code == 501
        assert "not supported on Windows" in res_resume.json()["detail"]


def test_websocket_disconnect_leaves_managed_process_running(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = RunStore(tmp_path)
    run_id = "20261024-010101-abcdef"
    create_test_run(store, tmp_path, run_id=run_id, status="running")

    operations: list[str] = []

    def mock_request_json(record: RunRecord, *, op: str, payload: dict[str, Any] | None = None, **kwargs: Any):
        operations.append(op)
        if op == "attach":
            return {"session_holds_lock": False, "lock_queue_count": 0}
        if op == "detach":
            return {"ok": True}
        return {"ok": True}

    monkeypatch.setattr("runmux.web.request_json", mock_request_json)

    app = create_runmux_web_app(tmp_path, login_code="secret123")
    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "secret123"}, headers={"Origin": "http://localhost"})
        session_cookie = f"web_ui_session={client.cookies.get('web_ui_session')}"

        with client.websocket_connect(
            f"/api/runs/{run_id}/terminal",
            headers={"Host": "localhost", "Origin": "http://localhost", "Cookie": session_cookie},
        ) as ws:
            status = ws.receive_json()
            assert status["type"] == "status"
            msg = ws.receive_json()
            assert msg["type"] == "output_reset"

    deadline = time.monotonic() + 1.0
    while not any(op == "detach" for op in operations) and time.monotonic() < deadline:
        time.sleep(0.01)

    # Invariant: process status remains "running" in store!
    record = store.get_run(run_id)
    assert record.status == "running"
    # And detach was requested for the view session
    assert "attach" in operations
    assert "detach" in operations


def test_api_kill_endpoint_consistently_defaults_to_forced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = RunStore(tmp_path)
    run_id = "20261024-010101-abcdef"
    create_test_run(store, tmp_path, run_id=run_id, status="running")

    ipc_calls: list[tuple[str, dict[str, Any] | None]] = []

    def mock_request_json(record: RunRecord, *, op: str, payload: dict[str, Any] | None = None, **kwargs: Any):
        ipc_calls.append((op, payload))
        return {"ok": True}

    monkeypatch.setattr("runmux.runner.request_json", mock_request_json)

    app = create_runmux_web_app(tmp_path, login_code="secret123")
    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "secret123"}, headers={"Origin": "http://localhost"})

        # 1. No body -> force=True
        res_no_body = client.post(f"/api/runs/{run_id}/kill", headers={"Origin": "http://localhost"})
        assert res_no_body.status_code == 200
        assert ipc_calls[-1] == ("kill", {"force": True})

        # 2. Empty JSON body {} -> force=True
        res_empty_dict = client.post(f"/api/runs/{run_id}/kill", json={}, headers={"Origin": "http://localhost"})
        assert res_empty_dict.status_code == 200
        assert ipc_calls[-1] == ("kill", {"force": True})

        # 3. Explicit force=False
        res_graceful = client.post(
            f"/api/runs/{run_id}/kill", json={"force": False}, headers={"Origin": "http://localhost"}
        )
        assert res_graceful.status_code == 200
        assert ipc_calls[-1] == ("kill", {"force": False})


def test_api_stop_endpoint_consistently_defaults_to_graceful(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = RunStore(tmp_path)
    run_id = "20261024-010101-abcdef"
    create_test_run(store, tmp_path, run_id=run_id, status="running")

    ipc_calls: list[tuple[str, dict[str, Any] | None]] = []

    def mock_request_json(record: RunRecord, *, op: str, payload: dict[str, Any] | None = None, **kwargs: Any):
        ipc_calls.append((op, payload))
        return {"ok": True}

    monkeypatch.setattr("runmux.runner.request_json", mock_request_json)

    app = create_runmux_web_app(tmp_path, login_code="secret123")
    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "secret123"}, headers={"Origin": "http://localhost"})

        # 1. No body -> force=False
        res_no_body = client.post(f"/api/runs/{run_id}/stop", headers={"Origin": "http://localhost"})
        assert res_no_body.status_code == 200
        assert ipc_calls[-1] == ("kill", {"force": False})

        # 2. Empty JSON body {} -> force=False
        res_empty_dict = client.post(f"/api/runs/{run_id}/stop", json={}, headers={"Origin": "http://localhost"})
        assert res_empty_dict.status_code == 200
        assert ipc_calls[-1] == ("kill", {"force": False})

        # 3. Explicit force=True
        res_forced = client.post(
            f"/api/runs/{run_id}/stop", json={"force": True}, headers={"Origin": "http://localhost"}
        )
        assert res_forced.status_code == 200
        assert ipc_calls[-1] == ("kill", {"force": True})


def test_api_stop_reports_terminating_when_process_remains_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = RunStore(tmp_path)
    run_id = "20261024-010101-abcdef"
    create_test_run(store, tmp_path, run_id=run_id, status="running")

    def mock_kill_run(*args: Any, **kwargs: Any):
        return store.get_run(run_id)

    monkeypatch.setattr("runmux.lifecycle.kill_run", mock_kill_run)
    monkeypatch.setattr("runmux.web_adapter.request_json", lambda record, **kwargs: {"ok": True, "status": "running"})

    app = create_runmux_web_app(tmp_path, login_code="secret123")
    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "secret123"}, headers={"Origin": "http://localhost"})

        res = client.post(f"/api/runs/{run_id}/stop", headers={"Origin": "http://localhost"})
        assert res.status_code == 200
        data = res.json()
        assert data["action"] == "stop"
        assert data["status"] == "terminating"
        assert "shutdown is in progress" in data["message"]
        assert data["run"]["status"] == "running"
