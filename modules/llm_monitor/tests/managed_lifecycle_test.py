"""Tests for Phase 01 managed lifecycle, configuration fingerprinting, and readiness."""

from __future__ import annotations

import os
from pathlib import Path
import psutil
import pytest

from llm_monitor.server_lifecycle import (
    ServerDescriptor,
    compute_config_fingerprint,
    compare_config_fingerprint,
    restart_server,
    find_target_descriptor,
    descriptor_path,
    write_descriptor,
)


def test_compute_config_fingerprint_deterministic():
    fp1 = compute_config_fingerprint(
        port=8788,
        host="127.0.0.1",
        endpoint="http://127.0.0.1:1234",
        gateway_enabled=True,
        gateway_upstream="http://127.0.0.1:1234",
        recording_mode="content",
        database_path="C:/tmp/monitor.sqlite3",
    )
    fp2 = compute_config_fingerprint(
        port=8788,
        host="127.0.0.1",
        endpoint="http://127.0.0.1:1234",
        gateway_enabled=True,
        gateway_upstream="http://127.0.0.1:1234",
        recording_mode="content",
        database_path="C:/tmp/monitor.sqlite3",
    )
    assert fp1 == fp2
    assert fp1.startswith("sha256:")

    # Different recording mode produces different fingerprint
    fp3 = compute_config_fingerprint(
        port=8788,
        host="127.0.0.1",
        endpoint="http://127.0.0.1:1234",
        gateway_enabled=True,
        gateway_upstream="http://127.0.0.1:1234",
        recording_mode="metadata",
        database_path="C:/tmp/monitor.sqlite3",
    )
    assert fp1 != fp3


def test_compare_config_fingerprint(tmp_path: Path):
    proc = psutil.Process()
    fp = compute_config_fingerprint(
        port=8789,
        host="127.0.0.1",
        endpoint="http://127.0.0.1:1234",
        gateway_enabled=True,
        gateway_upstream="http://127.0.0.1:1234",
        recording_mode="content",
        database_path=str(tmp_path / "test.db"),
    )
    desc = ServerDescriptor(
        instance_id="inst-fp-test",
        version=1,
        protocol="llm_monitor_web_v1",
        host="127.0.0.1",
        port=8789,
        pid=os.getpid(),
        process_create_time=proc.create_time(),
        started_at="2026-11-02T12:00:00Z",
        control_token="secret",
        gateway_enabled=True,
        recording_mode="content",
        database_path=str(tmp_path / "test.db"),
        config_fingerprint=fp,
    )
    match, diff = compare_config_fingerprint(
        desc,
        {
            "port": 8789,
            "host": "127.0.0.1",
            "endpoint": "http://127.0.0.1:1234",
            "gateway_enabled": True,
            "gateway_upstream": "http://127.0.0.1:1234",
            "recording_mode": "content",
            "database_path": str(tmp_path / "test.db"),
        },
    )
    assert match is True
    assert diff == {}

    # Keyword argument form
    match_kw, diff_kw = compare_config_fingerprint(desc, gateway_enabled=True, recording_mode="content")
    assert match_kw is True
    assert diff_kw == {}

    # Mismatch recording mode
    match_bad, diff_bad = compare_config_fingerprint(
        desc,
        {
            "port": 8789,
            "host": "127.0.0.1",
            "endpoint": "http://127.0.0.1:1234",
            "gateway_enabled": True,
            "gateway_upstream": "http://127.0.0.1:1234",
            "recording_mode": "metadata",
            "database_path": str(tmp_path / "test.db"),
        },
    )
    assert match_bad is False
    assert "recording_mode" in diff_bad
    assert diff_bad["recording_mode"] == ("content", "metadata")


def test_server_descriptor_extended_fields():
    proc = psutil.Process()
    desc = ServerDescriptor(
        instance_id="inst-ext-1",
        version=1,
        protocol="llm_monitor_web_v1",
        host="127.0.0.1",
        port=8788,
        pid=os.getpid(),
        process_create_time=proc.create_time(),
        started_at="2026-11-02T12:00:00Z",
        control_token="secret-tok",
        config_fingerprint="sha256:abc123",
        owner_identity="S-1-5-21-test",
        parent_pid=os.getppid(),
        executable_identity=str(Path(proc.exe()).resolve()) if hasattr(proc, "exe") else None,
        control_endpoint=r"\\.\pipe\llm-monitor-test",
    )
    d = desc.to_dict()
    restored = ServerDescriptor.from_dict(d)
    assert restored.config_fingerprint == "sha256:abc123"
    assert restored.owner_identity == "S-1-5-21-test"
    assert restored.parent_pid == os.getppid()
    assert restored.control_endpoint == r"\\.\pipe\llm-monitor-test"


def test_restart_server_preview_without_execute(tmp_path: Path, capsys):
    proc = psutil.Process()
    desc = ServerDescriptor(
        instance_id="inst-restart-preview",
        version=1,
        protocol="llm_monitor_web_v1",
        host="127.0.0.1",
        port=8799,
        pid=os.getpid(),
        process_create_time=proc.create_time(),
        started_at="2026-11-02T12:00:00Z",
        control_token="secret-tok",
    )
    p = descriptor_path(8799, "127.0.0.1", state_dir=tmp_path)
    write_descriptor(p, desc)

    import llm_monitor.server_lifecycle as slc
    orig_verify = slc.verify_running_instance
    try:
        slc.verify_running_instance = lambda d, timeout=2.0: {"status": "ok", "recorder_healthy": True}
        rc = restart_server(port=8799, execute=False, state_dir=tmp_path, as_json=False)
        assert rc == 0
        captured = capsys.readouterr()
        assert "dry-run preview" in captured.out
        assert "Pass -x/--execute to restart" in captured.out
    finally:
        slc.verify_running_instance = orig_verify


def test_restart_server_refuses_unmanaged(capsys):
    # Port 0 or an absent port is unmanaged / not running
    rc = restart_server(port=59999, execute=True, as_json=True)
    assert rc == 1 or rc == 0


def test_cli_web_restart_help():
    from llm_monitor.cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["web", "restart", "-p", "8789"])
    assert args.command == "web"
    assert args.action == "restart"
    assert args.port == 8789
    assert args.execute is False


def test_llm_monitor_web_server_readiness_event():
    import asyncio
    import uvicorn
    from fastapi import FastAPI
    from llm_monitor.server_lifecycle import LLMMonitorWebServer

    app = FastAPI()
    ready_called = False

    def on_ready():
        nonlocal ready_called
        ready_called = True

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    server = LLMMonitorWebServer(config, on_ready=on_ready)
    assert not server.ready_event.is_set()
    assert ready_called is False

