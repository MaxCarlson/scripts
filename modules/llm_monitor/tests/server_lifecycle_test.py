"""Tests for LLM Monitor server lifecycle, process identity, and security."""

from __future__ import annotations

import os
from pathlib import Path
import socket
import time
import pytest
import psutil
from fastapi import FastAPI
from fastapi.testclient import TestClient
import asyncio

from llm_monitor.server_lifecycle import (
    ServerDescriptor,
    ServerSecurityError,
    compute_challenge_hmac,
    compute_shutdown_hmac,
    default_runtime_dir,
    descriptor_path,
    enforce_owner_permissions,
    force_terminate_process,
    is_process_alive,
    is_reparse_point_or_symlink,
    list_descriptors,
    mount_control_routes,
    read_descriptor,
    remove_descriptor,
    request_instance_shutdown,
    status_server,
    stop_server,
    verify_owner_permissions,
    verify_process_identity,
    verify_running_instance,
    write_descriptor,
)


def test_default_runtime_dir_permissions(tmp_path: Path):
    runtime_dir = default_runtime_dir(state_dir=tmp_path / "custom_runtime")
    assert runtime_dir.is_dir()
    enforce_owner_permissions(runtime_dir, is_dir=True)
    assert verify_owner_permissions(runtime_dir)


def _sample_descriptor(port: int = 8788) -> ServerDescriptor:
    proc = psutil.Process()
    return ServerDescriptor(
        instance_id="inst-test-1234",
        version=1,
        protocol="llm_monitor_web_v1",
        host="127.0.0.1",
        port=port,
        pid=os.getpid(),
        process_create_time=proc.create_time(),
        started_at="2026-11-02T10:00:00Z",
        control_token="secret-token-xyz",
        gateway_enabled=True,
        recording_mode="content",
        database_path="C:/tmp/test.sqlite3",
    )


def test_descriptor_round_trip(tmp_path: Path):
    desc = _sample_descriptor(8788)
    data = desc.to_dict()
    restored = ServerDescriptor.from_dict(data)
    assert restored.instance_id == desc.instance_id
    assert restored.port == 8788
    assert restored.gateway_enabled is True
    assert restored.recording_mode == "content"
    assert restored.database_path == "C:/tmp/test.sqlite3"
    assert restored.pid == os.getpid()
    assert restored.process_create_time == desc.process_create_time


def test_write_and_read_descriptor(tmp_path: Path):
    desc = _sample_descriptor(8788)
    path = descriptor_path(8788, "127.0.0.1", state_dir=tmp_path)
    write_descriptor(path, desc)

    assert path.exists()
    assert verify_owner_permissions(path)

    loaded = read_descriptor(path)
    assert loaded is not None
    assert loaded.instance_id == desc.instance_id
    assert loaded.control_token == desc.control_token

    # Listing descriptors finds it
    all_descs = list_descriptors(state_dir=tmp_path)
    assert len(all_descs) == 1
    assert all_descs[0].port == 8788

    # Safe removal
    assert remove_descriptor(path) is True
    assert not path.exists()
    assert remove_descriptor(path) is False


def test_multiple_descriptors_independent(tmp_path: Path):
    desc1 = _sample_descriptor(8788)
    desc2 = _sample_descriptor(8789)
    p1 = descriptor_path(8788, state_dir=tmp_path)
    p2 = descriptor_path(8789, state_dir=tmp_path)

    write_descriptor(p1, desc1)
    write_descriptor(p2, desc2)

    found = list_descriptors(state_dir=tmp_path)
    assert len(found) == 2
    ports = {d.port for d in found}
    assert ports == {8788, 8789}


def test_stale_pid_and_pid_reuse_detection():
    current_pid = os.getpid()
    proc = psutil.Process(current_pid)
    real_time = proc.create_time()

    # Living current process
    assert is_process_alive(current_pid, real_time) is True

    # PID 0 is never a valid user server process
    assert is_process_alive(0) is False

    # Negative PID
    assert is_process_alive(-1) is False

    # Dead PID (find an unused PID)
    dead_pid = 999999
    while psutil.pid_exists(dead_pid):
        dead_pid += 1
    assert is_process_alive(dead_pid) is False

    # PID reuse: matching PID but mismatched create_time
    assert is_process_alive(current_pid, real_time - 100.0) is False
    assert is_process_alive(current_pid, real_time + 100.0) is False

    # Process identity verification
    valid_desc = _sample_descriptor()
    assert verify_process_identity(valid_desc) is True

    mismatched_desc = _sample_descriptor()
    mismatched_desc.process_create_time = real_time - 50.0
    assert verify_process_identity(mismatched_desc) is False


def test_symlink_rejection(tmp_path: Path):
    target_file = tmp_path / "real_file.txt"
    target_file.write_text("hello", encoding="utf-8")
    symlink_file = tmp_path / "link.json"

    try:
        symlink_file.symlink_to(target_file)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not supported in this environment")

    assert is_reparse_point_or_symlink(symlink_file) is True

    # Writing descriptor refuses symlink
    desc = _sample_descriptor(8788)
    with pytest.raises(ServerSecurityError):
        write_descriptor(symlink_file, desc)

    with pytest.raises(ServerSecurityError):
        read_descriptor(symlink_file)

    with pytest.raises(ServerSecurityError):
        remove_descriptor(symlink_file)


def test_hmac_domain_separation():
    token = "secret-token-123"
    inst = "inst-001"
    sig1 = compute_challenge_hmac(token, inst, "challenge-abc")
    sig2 = compute_shutdown_hmac(token, inst, 1000.0, "challenge-abc")
    assert sig1 != sig2
    # Deterministic
    assert sig1 == compute_challenge_hmac(token, inst, "challenge-abc")


def test_control_routes_health_and_verification():
    app = FastAPI()
    desc = _sample_descriptor(8788)
    event = asyncio.Event()
    mount_control_routes(app, desc, event)

    client = TestClient(app)

    # Simple health check
    res = client.get("/_llm_monitor/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["instance_id"] == desc.instance_id

    # Challenge-response
    challenge = "test-challenge-123"
    res_ch = client.get(f"/_llm_monitor/health?challenge={challenge}")
    assert res_ch.status_code == 200
    ch_data = res_ch.json()
    expected_sig = compute_challenge_hmac(desc.control_token, desc.instance_id, challenge)
    assert ch_data["signature"] == expected_sig
    assert ch_data["pid"] == desc.pid


def test_control_routes_shutdown_security():
    app = FastAPI()
    desc = _sample_descriptor(8788)
    event = asyncio.Event()
    mount_control_routes(app, desc, event)

    client = TestClient(app)

    # 1. Invalid signature
    res = client.post(
        "/_llm_monitor/control/shutdown",
        json={"timestamp": time.time(), "nonce": "nonce-1", "signature": "bad-sig"},
    )
    assert res.status_code == 403

    # 2. Expired timestamp (>30s)
    old_time = time.time() - 60.0
    sig_old = compute_shutdown_hmac(desc.control_token, desc.instance_id, old_time, "nonce-2")
    res_old = client.post(
        "/_llm_monitor/control/shutdown",
        json={"timestamp": old_time, "nonce": "nonce-2", "signature": sig_old},
    )
    assert res_old.status_code == 403

    # 3. Cross-origin request rejected
    now = time.time()
    sig = compute_shutdown_hmac(desc.control_token, desc.instance_id, now, "nonce-3")
    res_cors = client.post(
        "/_llm_monitor/control/shutdown",
        json={"timestamp": now, "nonce": "nonce-3", "signature": sig},
        headers={"Origin": "https://malicious-website.com"},
    )
    assert res_cors.status_code == 403

    # 4. Valid shutdown request
    sig_valid = compute_shutdown_hmac(desc.control_token, desc.instance_id, now, "nonce-valid")
    res_valid = client.post(
        "/_llm_monitor/control/shutdown",
        json={"timestamp": now, "nonce": "nonce-valid", "signature": sig_valid},
        headers={"Origin": "http://127.0.0.1:8788"},
    )
    assert res_valid.status_code == 200
    assert res_valid.json()["status"] == "shutting_down"
    assert event.is_set()

    # 5. Replay rejected (same nonce)
    res_replay = client.post(
        "/_llm_monitor/control/shutdown",
        json={"timestamp": now, "nonce": "nonce-valid", "signature": sig_valid},
    )
    assert res_replay.status_code == 403


def test_status_server_not_running(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    rc = status_server(port=8788, state_dir=tmp_path)
    assert rc == 0
    out = capsys.readouterr().out
    assert "Status: Not running" in out


def test_status_server_stale_descriptor(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    desc = _sample_descriptor(8788)
    desc.pid = 999999  # Non-existent PID
    p = descriptor_path(8788, state_dir=tmp_path)
    write_descriptor(p, desc)

    rc = status_server(port=8788, state_dir=tmp_path)
    assert rc == 0
    out = capsys.readouterr().out
    assert "Status: Not running" in out
    assert "Stale descriptor" in out


def test_stop_server_dry_run_preview(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    desc = _sample_descriptor(8788)
    p = descriptor_path(8788, state_dir=tmp_path)
    write_descriptor(p, desc)

    # Mock verify_running_instance so the process appears genuinely running
    import llm_monitor.server_lifecycle as slc
    orig_verify = slc.verify_running_instance
    try:
        slc.verify_running_instance = lambda d, timeout=2.0: {"status": "ok", "recorder_healthy": True}
        # Run stop without execute (-x)
        rc = stop_server(port=8788, execute=False, state_dir=tmp_path)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Running (dry-run preview)" in out
        assert "No action taken. Pass -x/--execute to stop this server." in out
        # Descriptor was NOT removed
        assert p.exists()
    finally:
        slc.verify_running_instance = orig_verify


def test_stop_server_recorder_flush_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    desc = _sample_descriptor(8788)
    p = descriptor_path(8788, state_dir=tmp_path)
    write_descriptor(p, desc)

    import llm_monitor.server_lifecycle as slc
    orig_verify = slc.verify_running_instance
    orig_shutdown = slc.request_instance_shutdown
    try:
        slc.verify_running_instance = lambda d, timeout=2.0: {"status": "ok", "recorder_healthy": False}
        slc.request_instance_shutdown = lambda d, timeout=5.0: (
            False,
            "Recorder shutdown flush timed out or failed; pending writes remain",
        )

        # Without force, stop MUST fail and report the recorder failure explicitly
        rc = stop_server(port=8788, execute=True, force=False, state_dir=tmp_path)
        assert rc == 1
        err = capsys.readouterr().err
        assert "Recorder shutdown flush timed out or failed" in err
        # Descriptor is preserved so caller can retry or inspect
        assert p.exists()
    finally:
        slc.verify_running_instance = orig_verify
        slc.request_instance_shutdown = orig_shutdown


def test_stop_server_graceful_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    desc = _sample_descriptor(8788)
    p = descriptor_path(8788, state_dir=tmp_path)
    write_descriptor(p, desc)

    import llm_monitor.server_lifecycle as slc
    orig_verify = slc.verify_running_instance
    orig_shutdown = slc.request_instance_shutdown
    orig_alive = slc.is_process_alive
    try:
        slc.verify_running_instance = lambda d, timeout=2.0: {"status": "ok", "recorder_healthy": True}
        is_alive = [True]

        def fake_shutdown(d, timeout=5.0):
            is_alive[0] = False
            return (True, None)

        slc.request_instance_shutdown = fake_shutdown
        slc.is_process_alive = lambda pid, t=None: is_alive[0]

        rc = stop_server(port=8788, execute=True, force=False, state_dir=tmp_path)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Server stopped successfully." in out
        # Descriptor was cleaned up
        assert not p.exists()
    finally:
        slc.verify_running_instance = orig_verify
        slc.request_instance_shutdown = orig_shutdown
        slc.is_process_alive = orig_alive


def test_stop_server_force_termination(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    desc = _sample_descriptor(8788)
    p = descriptor_path(8788, state_dir=tmp_path)
    write_descriptor(p, desc)

    import llm_monitor.server_lifecycle as slc
    orig_verify = slc.verify_running_instance
    orig_shutdown = slc.request_instance_shutdown
    orig_force = slc.force_terminate_process
    try:
        slc.verify_running_instance = lambda d, timeout=2.0: {"status": "ok", "recorder_healthy": True}
        # Shutdown request fails / times out
        slc.request_instance_shutdown = lambda d, timeout=5.0: (False, "Timeout")
        # Force terminate succeeds
        slc.force_terminate_process = lambda d, timeout=3.0: True

        rc = stop_server(port=8788, execute=True, force=True, state_dir=tmp_path, timeout=0.2)
        assert rc == 0
        out = capsys.readouterr().out
        assert "forcefully terminated" in out
        # Descriptor was cleaned up
        assert not p.exists()
    finally:
        slc.verify_running_instance = orig_verify
        slc.request_instance_shutdown = orig_shutdown
        slc.force_terminate_process = orig_force


def test_port_occupied_by_unrelated_application(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    # Bind a temporary alien socket
    import socket
    alien_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    alien_sock.bind(("127.0.0.1", 0))
    alien_sock.listen(5)
    alien_port = alien_sock.getsockname()[1]

    try:
        # status_server reports unmanaged listener detected without crashing
        rc_status = status_server(port=alien_port, state_dir=tmp_path)
        assert rc_status == 0
        out_status = capsys.readouterr().out
        assert "Unmanaged or unrelated listener detected" in out_status

        # stop_server refuses to stop unmanaged listener
        rc_stop = stop_server(port=alien_port, execute=True, state_dir=tmp_path)
        assert rc_stop == 1
        err_stop = capsys.readouterr().err
        assert "unmanaged or legacy server" in err_stop

        # Alien socket is still open!
        assert alien_sock.fileno() != -1
    finally:
        alien_sock.close()


def test_verify_running_instance_and_shutdown_live():
    app = FastAPI()
    shutdown_event = asyncio.Event()
    # Find free port
    free_sock = socket.socket()
    free_sock.bind(("127.0.0.1", 0))
    port = free_sock.getsockname()[1]
    free_sock.close()

    desc = _sample_descriptor(port)
    mount_control_routes(app, desc, shutdown_event)

    import uvicorn
    import threading

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    app.state.server = server

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    # Wait for server to listen
    deadline = time.time() + 3.0
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)

    try:
        # Verify running instance over HTTP
        info = verify_running_instance(desc, timeout=2.0)
        assert info is not None
        assert info["status"] == "ok"
        assert info["instance_id"] == desc.instance_id

        # Mismatched control token fails verification
        bad_desc = _sample_descriptor(port)
        bad_desc.control_token = "wrong-token"
        assert verify_running_instance(bad_desc, timeout=2.0) is None

        # Request shutdown over HTTP
        ok, err = request_instance_shutdown(desc, timeout=5.0)
        assert ok is True
        assert err is None
        assert shutdown_event.is_set()

        thread.join(timeout=3.0)
        assert not thread.is_alive()
    finally:
        server.should_exit = True


def test_run_web_detects_already_running_instance(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    desc = _sample_descriptor(8788)
    p = descriptor_path(8788, state_dir=tmp_path)
    write_descriptor(p, desc)

    import llm_monitor.web as web_mod

    orig_verify = web_mod.verify_running_instance
    try:
        web_mod.verify_running_instance = lambda d, timeout=2.0: {"status": "ok"}
        rc = web_mod.run_web(port=8788, state_dir=tmp_path, no_browser=True)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Status: Already running" in out
        assert "The existing server was left running." in out
    finally:
        web_mod.verify_running_instance = orig_verify


def test_gateway_rejects_new_requests_during_shutdown():
    from llm_monitor.gateway import OpenAIInferenceGateway, RequestEventHub
    from llm_monitor.live_store import LiveInferenceStore

    store = LiveInferenceStore()
    hub = RequestEventHub()
    gw = OpenAIInferenceGateway("http://127.0.0.1:1234", store, hub, server_instance_id="test-srv")

    app = FastAPI()
    app.include_router(gw.router())
    app.state.shutting_down = True

    client = TestClient(app)
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "m1", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 503
    assert "shutting down" in resp.json()["detail"].lower()


def test_process_identity_requires_create_time_and_positive_pid():
    desc = _sample_descriptor(8788)
    assert verify_process_identity(desc) is True

    # Missing create time must fail verification
    desc_no_time = _sample_descriptor(8788)
    desc_no_time.process_create_time = None
    assert verify_process_identity(desc_no_time) is False

    # Negative or zero PID must fail verification
    desc_bad_pid = _sample_descriptor(8788)
    desc_bad_pid.pid = 0
    assert verify_process_identity(desc_bad_pid) is False

    desc_neg_pid = _sample_descriptor(8788)
    desc_neg_pid.pid = -1
    assert verify_process_identity(desc_neg_pid) is False


def test_remove_descriptor_protects_other_instance_id(tmp_path: Path):
    desc = _sample_descriptor(8788)
    desc.instance_id = "inst-primary"
    path = descriptor_path(8788, state_dir=tmp_path)
    write_descriptor(path, desc)
    assert path.exists()

    # Mismatched instance ID does not remove descriptor
    removed = remove_descriptor(path, expected_instance_id="inst-different")
    assert removed is False
    assert path.exists()

    # Matching instance ID removes successfully
    removed = remove_descriptor(path, expected_instance_id="inst-primary")
    assert removed is True
    assert not path.exists()


def test_shutdown_unauthenticated_nonce_does_not_pollute():
    app = FastAPI()
    desc = _sample_descriptor(8788)
    shutdown_event = asyncio.Event()
    mount_control_routes(app, desc, shutdown_event)

    client = TestClient(app)
    # Send forged signature
    resp = client.post(
        "/_llm_monitor/control/shutdown",
        json={
            "timestamp": time.time(),
            "nonce": "nonce-unauthorized-123",
            "signature": "bad-signature-hex",
        },
    )
    assert resp.status_code == 403
    assert "Invalid shutdown authorization signature" in resp.json()["detail"]
    # Verify nonce was NOT cached in app.state
    assert "nonce-unauthorized-123" not in app.state.seen_shutdown_nonces


def test_force_terminate_protects_against_missing_create_time():
    desc = _sample_descriptor(8788)
    desc.process_create_time = None
    # Even if PID is our own process, missing create time must refuse force termination
    assert force_terminate_process(desc) is False






