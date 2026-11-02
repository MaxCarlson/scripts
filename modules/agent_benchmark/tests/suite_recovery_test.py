from __future__ import annotations

import json
from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch
import pytest

from agent_benchmark.cli import parser, main
from agent_benchmark.suite_monitor import MonitorPreflightError


def test_suite_cli_parser_accepts_recover_local_flag():
    """Verify -r/--recover-local flag is accepted on plan, run, and resume."""
    p = parser()
    
    plan_args = p.parse_args(["suite", "plan", "-c", "aider-python-10", "-r"])
    assert plan_args.recover_local is True

    run_args = p.parse_args(["suite", "run", "-c", "aider-python-10", "-r", "-x"])
    assert run_args.recover_local is True
    assert run_args.execute is True

    resume_args = p.parse_args(["suite", "resume", "-r", "test-run-id", "--recover-local", "-x"])
    assert resume_args.recover_local is True
    assert resume_args.execute is True


def test_recovery_without_recover_local_fails_closed_when_monitor_absent():
    """When monitor is absent and recover_local is False, preflight fails closed."""
    from agent_benchmark.suite_recovery import recover_managed_monitor

    with patch("agent_benchmark.suite_doctor.find_active_server", return_value=None), \
         patch("agent_benchmark.suite_doctor._is_port_listening", return_value=False):
        with pytest.raises(MonitorPreflightError) as exc_info:
            recover_managed_monitor(host_origin="http://127.0.0.1:8788", recover_local=False)
        assert "MONITOR_NOT_RUNNING" in str(exc_info.value) or "absent" in str(exc_info.value).lower()


def test_recovery_with_recover_local_starts_monitor_once():
    """When monitor is absent and recover_local is True, starts once and acquires token."""
    from agent_benchmark.suite_recovery import recover_managed_monitor

    spawn_calls = []
    real_popen = subprocess.Popen

    def fake_spawn(cmd, **kwargs):
        if isinstance(cmd, list) and cmd and "icacls" in str(cmd[0]):
            return real_popen(cmd, **kwargs)
        spawn_calls.append(cmd)
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 4321
        return mock_proc

    mock_desc = MagicMock(
        pid=4321, process_create_time=2000.0, port=8788,
        gateway_enabled=True, recording_mode="content",
        config_fingerprint="sha256:test", instance_id="inst-1234"
    )

    with patch("agent_benchmark.suite_doctor.find_active_server", return_value=None), \
         patch("agent_benchmark.suite_doctor._is_port_listening", return_value=False), \
         patch("agent_benchmark.suite_recovery.subprocess.Popen", side_effect=fake_spawn), \
         patch("agent_benchmark.suite_recovery._poll_for_server_ready", return_value=mock_desc), \
         patch("agent_benchmark.suite_recovery.ManagedMonitorClient.acquire_capability_token", return_value="tok_rec_123"):
        
        receipt = recover_managed_monitor(
            host_origin="http://127.0.0.1:8788",
            recording="content",
            recover_local=True,
            timeout_seconds=2.0,
        )

        assert len(spawn_calls) == 1
        assert receipt["status"] == "ready"
        assert receipt["recovered_locally"] is True
        assert receipt["server_instance_id"] is not None
        assert receipt["inference_dispatched"] is False
        assert "tok_rec_123" not in json.dumps(receipt)  # Token must NOT be serialized in receipt!


def test_recovery_fails_closed_on_unmanaged_listener():
    """When port is occupied by unmanaged listener, fail closed even with recover_local=True."""
    from agent_benchmark.suite_recovery import recover_managed_monitor

    with patch("agent_benchmark.suite_doctor.find_active_server", return_value=None), \
         patch("agent_benchmark.suite_doctor._is_port_listening", return_value=True):
        with pytest.raises(MonitorPreflightError) as exc_info:
            recover_managed_monitor(host_origin="http://127.0.0.1:8788", recover_local=True)
        assert "MONITOR_UNMANAGED_LISTENER" in str(exc_info.value) or "unmanaged" in str(exc_info.value).lower()


def test_recovery_fails_closed_on_config_mismatch():
    """When existing monitor has config conflict, fail closed even with recover_local=True."""
    from agent_benchmark.suite_recovery import recover_managed_monitor

    fake_desc = MagicMock(
        pid=1234, process_create_time=1000.0, port=8788,
        gateway_enabled=False, recording_mode="off",
        config_fingerprint="sha256:old"
    )

    with patch("agent_benchmark.suite_doctor.find_active_server", return_value=fake_desc), \
         patch("agent_benchmark.suite_doctor._is_port_listening", return_value=True), \
         patch("agent_benchmark.suite_doctor.is_process_alive", return_value=True), \
         patch("agent_benchmark.suite_doctor.compare_config_fingerprint", return_value=False):
        with pytest.raises(MonitorPreflightError) as exc_info:
            recover_managed_monitor(
                host_origin="http://127.0.0.1:8788",
                recording="content",
                recover_local=True,
            )
        assert "MONITOR_CONFIG_MISMATCH" in str(exc_info.value) or "mismatch" in str(exc_info.value).lower()


def test_task_boundary_recorder_check():
    """Task boundary check verifies healthy recorder and catches dropped count increases."""
    from agent_benchmark.suite_recovery import check_task_boundary_recorder
    import httpx

    # Healthy
    mock_resp_ok = MagicMock(
        status_code=200,
        json=lambda: {"recording": {"healthy": True, "dropped_count": 0, "mode": "content"}}
    )
    with patch("httpx.Client.get", return_value=mock_resp_ok):
        check_task_boundary_recorder(monitor_url="http://127.0.0.1:8788", baseline_dropped=0)

    # Unhealthy (dropped count increased)
    mock_resp_bad = MagicMock(
        status_code=200,
        json=lambda: {"recording": {"healthy": True, "dropped_count": 3, "mode": "content"}}
    )
    with patch("httpx.Client.get", return_value=mock_resp_bad):
        with pytest.raises(MonitorPreflightError) as exc_info:
            check_task_boundary_recorder(monitor_url="http://127.0.0.1:8788", baseline_dropped=0)
        assert "dropped" in str(exc_info.value).lower()
