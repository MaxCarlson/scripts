import json
import sys
import threading
import time
from pathlib import Path

import psutil
from fastapi.testclient import TestClient

from runmux.runner import create_managed_run, kill_run
from runmux.store import RunStore
from runmux.web import create_runmux_web_app


def make_run(store: RunStore, state_dir: Path, run_id: str) -> None:
    run_dir = state_dir / "runs" / run_id
    run_dir.mkdir(parents=True)
    log_path = run_dir / "output.ansi"
    log_path.write_bytes(b"\x1b[31mline <script>alert(1)</script>\x1b[0m\n")
    store.create_run(
        run_id=run_id,
        name="sample worker",
        status="finished",
        program=r"C:\tools\worker.exe",
        argv_json=json.dumps(["worker.exe", "--token", "should-not-leak"]),
        cwd=r"C:\private\folder",
        env_overrides_json=json.dumps({"SECRET": "env-secret"}),
        auth_token="ipc-secret",
        log_path=log_path,
        command_line="worker.exe --token should-not-leak",
    )


def test_api_auth_listing_detail_and_safe_bounded_output(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    store = RunStore(state_dir)
    run_id = "20261023-123456-a1b2c3"
    make_run(store, state_dir, run_id)
    app = create_runmux_web_app(state_dir, login_code="test-login")

    with TestClient(app, base_url="http://localhost") as client:
        unauthorized = client.get("/api/runs", headers={"Origin": "http://localhost"})
        assert unauthorized.status_code == 401
        assert unauthorized.headers["cache-control"] == "no-store"

        login = client.post("/auth/login", json={"code": "test-login"}, headers={"Origin": "http://localhost"})
        assert login.status_code == 204
        assert "httponly" in login.headers["set-cookie"].lower()

        listing = client.get("/api/runs", headers={"Origin": "http://localhost"})
        assert listing.status_code == 200
        assert listing.headers["cache-control"] == "no-store"
        assert listing.json()[0]["id"] == run_id
        assert listing.json()[0]["command"] == "worker.exe"
        assert "command_line" not in listing.text
        assert "should-not-leak" not in listing.text
        assert "private\\folder" not in listing.text
        assert "ipc-secret" not in listing.text
        assert "env-secret" not in listing.text

        detail = client.get(f"/api/runs/{run_id}", headers={"Origin": "http://localhost"})
        assert detail.status_code == 200
        assert detail.json()["name"] == "sample worker"
        assert client.get("/api/runs/20261023-123", headers={"Origin": "http://localhost"}).status_code == 404

        output = client.get(f"/api/runs/{run_id}/output", headers={"Origin": "http://localhost"})
        assert output.status_code == 200
        assert output.json()["text"] == "line <script>alert(1)</script>\n"
        assert "\x1b" not in output.json()["text"]
        assert output.headers["cache-control"] == "no-store"

        assert client.get("/api/runs", headers={"Origin": "http://attacker.invalid"}).status_code == 403
        invalid_cursor = client.get(
            f"/api/runs/{run_id}/output?cursor=invalid",
            headers={"Origin": "http://localhost"},
        )
        assert invalid_cursor.status_code == 400


def test_missing_registry_stays_empty_without_creating_it(tmp_path: Path) -> None:
    state_dir = tmp_path / "missing-registry"
    app = create_runmux_web_app(state_dir, login_code="test-login")
    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "test-login"}, headers={"Origin": "http://localhost"})
        response = client.get("/api/runs", headers={"Origin": "http://localhost"})
    assert response.status_code == 200
    assert response.json() == []
    assert not state_dir.exists()


def test_web_server_shutdown_does_not_stop_supervised_child(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    store = RunStore(state_dir)
    started = create_managed_run(
        store,
        program_args=[sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=tmp_path,
        name="temporary persistence test",
        force_color=False,
        record_history=False,
    )
    process_pid = started.record.pid
    server = None
    server_thread = None
    try:
        assert process_pid is not None
        app = create_runmux_web_app(state_dir, login_code="test-login")
        from web_ui_tools import create_server

        server = create_server(app, port=0)
        server_thread = threading.Thread(target=server.run, daemon=True)
        server_thread.start()
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        server.should_exit = True
        server_thread.join(timeout=5)
        assert not server_thread.is_alive()
        assert psutil.pid_exists(process_pid)
    finally:
        if server is not None:
            server.should_exit = True
        if server_thread is not None:
            server_thread.join(timeout=5)
        if psutil.pid_exists(process_pid):
            kill_run(store, run_id=started.record.id, force=True)


def test_output_refreshes_status_and_flushes_final_incomplete_utf8(tmp_path: Path, monkeypatch) -> None:
    import runmux.web_adapter as web_adapter

    state_dir = tmp_path / "state"
    store = RunStore(state_dir)
    run_id = "20261023-123456-a1b2c3"
    make_run(store, state_dir, run_id)
    store.update_run(run_id, status="running", port=43123, supervisor_pid=9002)
    with (state_dir / "runs" / run_id / "output.ansi").open("ab") as stream:
        stream.write(b"final\xe2")
    monkeypatch.setattr(
        web_adapter,
        "request_json",
        lambda _record, *, op, timeout: {"status": "finished", "exit_code": 0, "pid": None},
    )
    app = create_runmux_web_app(state_dir, login_code="test-login")

    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "test-login"}, headers={"Origin": "http://localhost"})
        response = client.get(f"/api/runs/{run_id}/output", headers={"Origin": "http://localhost"})

    assert response.status_code == 200
    assert response.json()["text"] == "line <script>alert(1)</script>\nfinal\ufffd"
    assert response.json()["finished"] is True
    assert response.json()["at_end"] is True


def test_output_does_not_treat_unreachable_supervisor_as_finished(tmp_path: Path, monkeypatch) -> None:
    import runmux.web_adapter as web_adapter

    state_dir = tmp_path / "state"
    store = RunStore(state_dir)
    run_id = "20261023-123456-a1b2c3"
    make_run(store, state_dir, run_id)
    store.update_run(run_id, status="running", port=43123, supervisor_pid=9002)

    def unreachable(*_args, **_kwargs):
        raise web_adapter.IpcError("temporary connection failure")

    monkeypatch.setattr(web_adapter, "request_json", unreachable)
    monkeypatch.setattr(web_adapter.psutil, "pid_exists", lambda _pid: True)
    app = create_runmux_web_app(state_dir, login_code="test-login")

    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "test-login"}, headers={"Origin": "http://localhost"})
        response = client.get(f"/api/runs/{run_id}/output", headers={"Origin": "http://localhost"})

    assert response.status_code == 200
    assert response.json()["finished"] is False
