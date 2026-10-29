"""Tests for Runmux Web server lifecycle management and security."""

from __future__ import annotations

import asyncio
import http.client
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from runmux.runner import create_managed_run, kill_run
from runmux.server_lifecycle import (
    ServerDescriptor,
    ServerSecurityError,
    compute_challenge_hmac,
    compute_shutdown_hmac,
    descriptor_path,
    find_target_descriptor,
    is_reparse_point_or_symlink,
    mount_control_routes,
    read_descriptor,
    remove_descriptor,
    run_web_server,
    status_server,
    stop_server,
    write_descriptor,
)
from runmux.store import RunStore


def test_descriptor_serialization_roundtrip(tmp_path: Path) -> None:
    desc = ServerDescriptor(
        instance_id="inst-1234",
        version=1,
        protocol="runmux_web_v1",
        host="127.0.0.1",
        port=8787,
        state_dir=str(tmp_path.resolve()),
        pid=12345,
        process_create_time=1730000000.0,
        started_at="2026-10-29T00:00:00Z",
        access_code="secret-access-code",
        control_token="secret-control-token",
    )
    data = desc.to_dict()
    assert data["instance_id"] == "inst-1234"
    assert data["port"] == 8787
    assert data["access_code"] == "secret-access-code"

    restored = ServerDescriptor.from_dict(data)
    assert restored == desc


def test_reparse_point_and_symlink_detection(tmp_path: Path) -> None:
    regular_file = tmp_path / "regular.txt"
    regular_file.write_text("hello", encoding="utf-8")
    assert not is_reparse_point_or_symlink(regular_file)
    assert not is_reparse_point_or_symlink(tmp_path)


def test_write_and_read_descriptor_securely(tmp_path: Path) -> None:
    path = descriptor_path(tmp_path, "127.0.0.1", 8787)
    assert path.name == "server_127.0.0.1_8787.json"

    desc = ServerDescriptor(
        instance_id="inst-5678",
        version=1,
        protocol="runmux_web_v1",
        host="127.0.0.1",
        port=8787,
        state_dir=str(tmp_path.resolve()),
        pid=os.getpid(),
        process_create_time=None,
        started_at="2026-10-29T00:00:00Z",
        access_code="code-abc",
        control_token="token-xyz",
    )

    write_descriptor(path, desc)
    assert path.is_file()

    loaded = read_descriptor(path)
    assert loaded is not None
    assert loaded.instance_id == "inst-5678"
    assert loaded.access_code == "code-abc"
    assert loaded.control_token == "token-xyz"


def test_read_descriptor_rejects_symlink(tmp_path: Path) -> None:
    real_file = tmp_path / "target.json"
    real_file.write_text(
        json.dumps(
            {
                "instance_id": "fake",
                "version": 1,
                "protocol": "runmux_web_v1",
                "host": "127.0.0.1",
                "port": 8787,
                "state_dir": str(tmp_path),
                "pid": 99999,
                "started_at": "2026-10-29T00:00:00Z",
                "access_code": "malicious",
                "control_token": "malicious",
            }
        ),
        encoding="utf-8",
    )
    symlink_path = tmp_path / "web" / "server_127.0.0.1_8787.json"
    symlink_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        symlink_path.symlink_to(real_file)
    except OSError:
        pytest.skip("Symlink creation requires elevation or developer mode on Windows")

    with pytest.raises(ServerSecurityError, match="Symbolic link or reparse point"):
        read_descriptor(symlink_path)


def test_read_descriptor_returns_none_for_missing_file(tmp_path: Path) -> None:
    path = descriptor_path(tmp_path, 9999)
    assert read_descriptor(path) is None


def test_remove_descriptor_is_idempotent(tmp_path: Path) -> None:
    path = descriptor_path(tmp_path, 8787)
    assert remove_descriptor(path) is False

    desc = ServerDescriptor(
        instance_id="inst-temp",
        version=1,
        protocol="runmux_web_v1",
        host="127.0.0.1",
        port=8787,
        state_dir=str(tmp_path.resolve()),
        pid=os.getpid(),
        process_create_time=None,
        started_at="2026-10-29T00:00:00Z",
        access_code="code",
        control_token="token",
    )
    write_descriptor(path, desc)
    assert path.is_file()

    assert remove_descriptor(path) is True
    assert not path.exists()
    assert remove_descriptor(path) is False


def test_control_routes_health_and_hmac_challenge(tmp_path: Path) -> None:
    app = FastAPI()
    shutdown_event = asyncio.Event()
    desc = ServerDescriptor(
        instance_id="inst-test-ctrl",
        version=1,
        protocol="runmux_web_v1",
        host="127.0.0.1",
        port=8787,
        state_dir=str(tmp_path.resolve()),
        pid=os.getpid(),
        process_create_time=None,
        started_at="2026-10-29T00:00:00Z",
        access_code="login-code-secret",
        control_token="control-token-secret",
    )
    mount_control_routes(app, desc, shutdown_event)

    with TestClient(app) as client:
        # Basic health check without challenge
        resp = client.get("/_runmux/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["instance_id"] == "inst-test-ctrl"
        assert "login-code-secret" not in resp.text
        assert "control-token-secret" not in resp.text

        # Challenge-response check
        challenge = "a1b2c3d4"
        resp_chal = client.get(f"/_runmux/health?challenge={challenge}")
        assert resp_chal.status_code == 200
        chal_data = resp_chal.json()
        assert chal_data["status"] == "ok"
        expected_sig = compute_challenge_hmac("control-token-secret", "inst-test-ctrl", challenge)
        assert chal_data["signature"] == expected_sig
        assert chal_data["pid"] == os.getpid()


def test_control_routes_shutdown_authorization(tmp_path: Path) -> None:
    app = FastAPI()
    shutdown_event = asyncio.Event()
    desc = ServerDescriptor(
        instance_id="inst-test-shut",
        version=1,
        protocol="runmux_web_v1",
        host="127.0.0.1",
        port=8787,
        state_dir=str(tmp_path.resolve()),
        pid=os.getpid(),
        process_create_time=None,
        started_at="2026-10-29T00:00:00Z",
        access_code="login-code-secret",
        control_token="control-token-secret",
    )
    mount_control_routes(app, desc, shutdown_event)

    with TestClient(app) as client:
        # Invalid signature
        bad_resp = client.post(
            "/_runmux/control/shutdown",
            json={"timestamp": time.time(), "nonce": "abc", "signature": "wrong-signature"},
        )
        assert bad_resp.status_code == 403
        assert not shutdown_event.is_set()

        # Expired timestamp (older than 30s)
        old_time = time.time() - 60.0
        old_sig = compute_shutdown_hmac("control-token-secret", "inst-test-shut", old_time, "nonce123")
        expired_resp = client.post(
            "/_runmux/control/shutdown",
            json={"timestamp": old_time, "nonce": "nonce123", "signature": old_sig},
        )
        assert expired_resp.status_code == 403
        assert not shutdown_event.is_set()

        # Valid signed shutdown
        valid_time = time.time()
        valid_sig = compute_shutdown_hmac("control-token-secret", "inst-test-shut", valid_time, "nonce456")
        ok_resp = client.post(
            "/_runmux/control/shutdown",
            json={"timestamp": valid_time, "nonce": "nonce456", "signature": valid_sig},
        )
        assert ok_resp.status_code == 200
        assert ok_resp.json()["status"] == "shutting_down"
        assert shutdown_event.is_set()


def test_health_to_shutdown_hmac_cross_protocol_misuse_fails(tmp_path: Path) -> None:
    """Verify that the health challenge endpoint cannot act as a signing oracle for shutdown."""
    app = FastAPI()
    shutdown_event = asyncio.Event()
    desc = ServerDescriptor(
        instance_id="inst-oracle-test",
        version=1,
        protocol="runmux_web_v1",
        host="127.0.0.1",
        port=8787,
        state_dir=str(tmp_path.resolve()),
        pid=os.getpid(),
        process_create_time=None,
        started_at="2026-10-29T00:00:00Z",
        access_code="login-code-secret",
        control_token="control-token-secret",
    )
    mount_control_routes(app, desc, shutdown_event)

    with TestClient(app) as client:
        valid_time = time.time()
        target_nonce = "malicious-nonce-777"
        # Attacker crafts the challenge string hoping to forge a shutdown signature
        crafted_challenge = f"POST:/_runmux/control/shutdown:{valid_time:.3f}:{target_nonce}"

        # Attacker queries health endpoint
        health_resp = client.get(f"/_runmux/health?challenge={crafted_challenge}")
        assert health_resp.status_code == 200
        oracle_sig = health_resp.json()["signature"]

        # Attacker tries to use oracle_sig for shutdown
        shutdown_attempt = client.post(
            "/_runmux/control/shutdown",
            json={"timestamp": valid_time, "nonce": target_nonce, "signature": oracle_sig},
        )
        # MUST BE REJECTED!
        assert shutdown_attempt.status_code == 403
        assert not shutdown_event.is_set()


def test_shutdown_nonce_replay_rejected(tmp_path: Path) -> None:
    """Verify that replaying a previously accepted shutdown nonce is rejected."""
    app = FastAPI()
    shutdown_event = asyncio.Event()
    desc = ServerDescriptor(
        instance_id="inst-replay-test",
        version=1,
        protocol="runmux_web_v1",
        host="127.0.0.1",
        port=8787,
        state_dir=str(tmp_path.resolve()),
        pid=os.getpid(),
        process_create_time=None,
        started_at="2026-10-29T00:00:00Z",
        access_code="login-code-secret",
        control_token="control-token-secret",
    )
    mount_control_routes(app, desc, shutdown_event)

    with TestClient(app) as client:
        valid_time = time.time()
        nonce = "replay-nonce-001"
        valid_sig = compute_shutdown_hmac("control-token-secret", "inst-replay-test", valid_time, nonce)

        # First request succeeds
        resp1 = client.post(
            "/_runmux/control/shutdown",
            json={"timestamp": valid_time, "nonce": nonce, "signature": valid_sig},
        )
        assert resp1.status_code == 200

        # Second request with SAME nonce MUST fail
        resp2 = client.post(
            "/_runmux/control/shutdown",
            json={"timestamp": valid_time, "nonce": nonce, "signature": valid_sig},
        )
        assert resp2.status_code == 403
        assert "replay" in resp2.text.lower()


def test_find_target_descriptor_single_and_ambiguous(tmp_path: Path) -> None:
    # No descriptors
    desc, err = find_target_descriptor(tmp_path)
    assert desc is None
    assert err is None

    # One descriptor on 8787
    d1 = ServerDescriptor(
        instance_id="inst-1",
        version=1,
        protocol="runmux_web_v1",
        host="127.0.0.1",
        port=8787,
        state_dir=str(tmp_path.resolve()),
        pid=1001,
        process_create_time=None,
        started_at="2026-10-29T00:00:00Z",
        access_code="code1",
        control_token="tok1",
    )
    write_descriptor(descriptor_path(tmp_path, "127.0.0.1", 8787), d1)

    desc, err = find_target_descriptor(tmp_path)
    assert desc is not None
    assert desc.port == 8787
    assert err is None

    # Two descriptors (8787 and 8788)
    d2 = ServerDescriptor(
        instance_id="inst-2",
        version=1,
        protocol="runmux_web_v1",
        host="127.0.0.1",
        port=8788,
        state_dir=str(tmp_path.resolve()),
        pid=1002,
        process_create_time=None,
        started_at="2026-10-29T00:00:00Z",
        access_code="code2",
        control_token="tok2",
    )
    write_descriptor(descriptor_path(tmp_path, "127.0.0.1", 8788), d2)

    # Ambiguous when port is None
    desc, err = find_target_descriptor(tmp_path)
    assert desc is None
    assert err is not None
    assert "Multiple" in err

    # Specific port works
    desc, err = find_target_descriptor(tmp_path, port=8788)
    assert desc is not None
    assert desc.port == 8788
    assert err is None


def test_stop_when_not_running(tmp_path: Path, capsys) -> None:
    code = stop_server(tmp_path, 8787)
    assert code == 0
    out = capsys.readouterr().out
    assert "Status: Not running" in out
    assert "No matching server needs to be stopped." in out


def test_status_when_not_running(tmp_path: Path, capsys) -> None:
    code = status_server(tmp_path, 8787)
    assert code == 0
    out = capsys.readouterr().out
    assert "Status: Not running" in out


def test_status_stale_descriptor(tmp_path: Path, capsys) -> None:
    stale = ServerDescriptor(
        instance_id="inst-stale",
        version=1,
        protocol="runmux_web_v1",
        host="127.0.0.1",
        port=8787,
        state_dir=str(tmp_path.resolve()),
        pid=99999999,
        process_create_time=None,
        started_at="2026-10-29T00:00:00Z",
        access_code="code-stale",
        control_token="tok-stale",
    )
    write_descriptor(descriptor_path(tmp_path, "127.0.0.1", 8787), stale)

    code = status_server(tmp_path, 8787)
    assert code == 0
    out = capsys.readouterr().out
    assert "Status: Not running" in out
    assert "Stale descriptor" in out


def test_unrelated_listener_rejection(tmp_path: Path, capsys) -> None:
    # Bind an alien socket that does NOT speak Runmux
    alien_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    alien_sock.bind(("127.0.0.1", 0))
    alien_sock.listen(1)
    alien_port = alien_sock.getsockname()[1]

    try:
        # run_web_server should fail closed without starting or leaking secrets
        rc = run_web_server(tmp_path, host="127.0.0.1", port=alien_port)
        assert rc == 1
        err = capsys.readouterr().err
        assert f"Port {alien_port} is already in use by an unrelated service" in err

        # status_server reports Not running
        rc_status = status_server(tmp_path, port=alien_port)
        assert rc_status == 0
        out_status = capsys.readouterr().out
        assert "Status: Not running" in out_status

        # stop_server reports Not running and does NOT kill the alien socket
        rc_stop = stop_server(tmp_path, port=alien_port)
        assert rc_stop == 0
        out_stop = capsys.readouterr().out
        assert "Status: Not running" in out_stop
    finally:
        alien_sock.close()


def test_pid_reuse_rejected_by_create_time(tmp_path: Path, capsys) -> None:
    future_time = time.time() + 100000.0
    reused = ServerDescriptor(
        instance_id="inst-reused",
        version=1,
        protocol="runmux_web_v1",
        host="127.0.0.1",
        port=8787,
        state_dir=str(tmp_path.resolve()),
        pid=os.getpid(),
        process_create_time=future_time,
        started_at="2026-10-29T00:00:00Z",
        access_code="code-reused",
        control_token="tok-reused",
    )
    write_descriptor(descriptor_path(tmp_path, "127.0.0.1", 8787), reused)

    rc = status_server(tmp_path, 8787)
    assert rc == 0
    out = capsys.readouterr().out
    assert "Status: Not running" in out
    assert "Stale descriptor" in out


def test_end_to_end_server_lifecycle_and_discovery(tmp_path: Path, capsys) -> None:
    temp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    temp_sock.bind(("127.0.0.1", 0))
    free_port = temp_sock.getsockname()[1]
    temp_sock.close()

    src_dir = str(Path(__file__).resolve().parents[1] / "src")
    server_proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                f"import sys; sys.path.insert(0, {repr(src_dir)}); "
                f"from runmux.server_lifecycle import run_web_server; "
                f"sys.exit(run_web_server({repr(str(tmp_path))}, '127.0.0.1', {free_port}, True))"
            ),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        desc_p = descriptor_path(tmp_path, "127.0.0.1", free_port)
        deadline = time.time() + 5.0
        desc = None
        while time.time() < deadline:
            desc = read_descriptor(desc_p)
            if desc is not None:
                break
            time.sleep(0.05)

        assert desc is not None
        original_code = desc.access_code
        original_pid = desc.pid
        assert psutil.pid_exists(original_pid)

        # 1. Test status_server reports running with exact access code and URL
        rc_status = status_server(tmp_path, free_port)
        assert rc_status == 0
        out_status = capsys.readouterr().out
        assert "Status: Running" in out_status
        assert f"URL:    http://127.0.0.1:{free_port}/" in out_status
        assert f"Access code: {original_code}" in out_status
        assert f"PID:    {original_pid}" in out_status

        # 2. Test duplicate invocation discovers existing server, preserves original code, returns 0
        rc_dup = run_web_server(tmp_path, "127.0.0.1", free_port, True)
        assert rc_dup == 0
        out_dup = capsys.readouterr().out
        assert "Status: Already running" in out_dup
        assert f"Access code: {original_code}" in out_dup
        assert "The existing server was left running." in out_dup

        # 3. Test connection readiness: HTTP request immediately succeeds
        conn = http.client.HTTPConnection("127.0.0.1", free_port, timeout=2.0)
        conn.request("GET", "/_runmux/health")
        resp = conn.getresponse()
        assert resp.status == 200
        conn.close()

        # 4. Test stop_server stops the server gracefully
        rc_stop = stop_server(tmp_path, free_port)
        assert rc_stop == 0
        out_stop = capsys.readouterr().out
        assert "Status: Stopping" in out_stop
        assert "Server stopped successfully." in out_stop
        assert "Managed processes remain running." in out_stop

        # Subprocess should finish promptly
        server_proc.wait(timeout=5.0)
        assert not desc_p.exists()

        # 5. Test repeated stop is idempotent
        rc_stop2 = stop_server(tmp_path, free_port)
        assert rc_stop2 == 0
        out_stop2 = capsys.readouterr().out
        assert "Status: Not running" in out_stop2
        assert "No matching server needs to be stopped." in out_stop2
    finally:
        if server_proc.poll() is None:
            server_proc.kill()
            server_proc.wait()


def test_immediate_restart_after_stop_on_same_port(tmp_path: Path) -> None:
    """Verify that stopping a server allows immediately starting a new server on the same port."""
    temp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    temp_sock.bind(("127.0.0.1", 0))
    free_port = temp_sock.getsockname()[1]
    temp_sock.close()

    src_dir = str(Path(__file__).resolve().parents[1] / "src")

    def spawn_server():
        return subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    f"import sys; sys.path.insert(0, {repr(src_dir)}); "
                    f"from runmux.server_lifecycle import run_web_server; "
                    f"sys.exit(run_web_server({repr(str(tmp_path))}, '127.0.0.1', {free_port}, True))"
                ),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    # Start first instance
    proc1 = spawn_server()
    desc_p = descriptor_path(tmp_path, "127.0.0.1", free_port)
    try:
        deadline = time.time() + 5.0
        while time.time() < deadline and read_descriptor(desc_p) is None:
            time.sleep(0.05)
        assert read_descriptor(desc_p) is not None

        # Stop first instance
        rc = stop_server(tmp_path, free_port)
        assert rc == 0
        proc1.wait(timeout=5.0)
        assert not desc_p.exists()

        # Immediately start second instance on the exact same port
        proc2 = spawn_server()
        try:
            deadline = time.time() + 5.0
            desc2 = None
            while time.time() < deadline:
                desc2 = read_descriptor(desc_p)
                if desc2 is not None:
                    break
                time.sleep(0.05)
            assert desc2 is not None
            # Stop second instance
            rc2 = stop_server(tmp_path, free_port)
            assert rc2 == 0
            proc2.wait(timeout=5.0)
        finally:
            if proc2.poll() is None:
                proc2.kill()
                proc2.wait()
    finally:
        if proc1.poll() is None:
            proc1.kill()
            proc1.wait()


def test_managed_processes_remain_running_when_web_stops(tmp_path: Path, capsys) -> None:
    store = RunStore(tmp_path)
    started = create_managed_run(
        store,
        program_args=[sys.executable, "-c", "import time; time.sleep(15)"],
        cwd=tmp_path,
        name="supervised-test-task",
        force_color=False,
    )
    run_id = started.record.id
    try:
        assert started.record.pid is not None
        supervisor_pid = started.record.pid
        assert psutil.pid_exists(supervisor_pid)

        temp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        temp_sock.bind(("127.0.0.1", 0))
        free_port = temp_sock.getsockname()[1]
        temp_sock.close()

        src_dir = str(Path(__file__).resolve().parents[1] / "src")
        server_proc = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    f"import sys; sys.path.insert(0, {repr(src_dir)}); "
                    f"from runmux.server_lifecycle import run_web_server; "
                    f"sys.exit(run_web_server({repr(str(tmp_path))}, '127.0.0.1', {free_port}, True))"
                ),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        try:
            # Wait for web descriptor
            desc_p = descriptor_path(tmp_path, "127.0.0.1", free_port)
            deadline = time.time() + 5.0
            while time.time() < deadline:
                if read_descriptor(desc_p) is not None:
                    break
                time.sleep(0.05)

            assert read_descriptor(desc_p) is not None

            # Stop Web UI server
            rc_stop = stop_server(tmp_path, free_port)
            assert rc_stop == 0
            server_proc.wait(timeout=5.0)

            # Invariant check: Managed process supervisor is STILL running!
            assert psutil.pid_exists(supervisor_pid)
            current_record = store.get_run(run_id)
            assert current_record.status in {"running", "pending"}
        finally:
            if server_proc.poll() is None:
                server_proc.kill()
                server_proc.wait()
    finally:
        kill_run(store, run_id=run_id, force=True)
