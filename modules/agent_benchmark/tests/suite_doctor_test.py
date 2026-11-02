from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any
from unittest.mock import MagicMock, patch
import httpx
import pytest

from agent_benchmark.cli import main, parser


def test_doctor_parser_registration():
    """Verify doctor subcommand is registered with correct options."""
    p = parser()
    args = p.parse_args(["suite", "doctor", "-F", "-f", "json", "-U", "http://host.docker.internal:8789/v1", "-H", "http://127.0.0.1:8789"])
    assert args.suite_command == "doctor"
    assert args.full is True
    assert args.format == "json"
    assert args.monitor_url == "http://host.docker.internal:8789/v1"
    assert args.monitor_host_url == "http://127.0.0.1:8789"


def test_doctor_full_flag_does_not_break_llm_friendly_on_other_commands():
    """Verify -F on doctor is --full, while -F on plan/run/resume/report is --llm-friendly."""
    p = parser()
    doctor_args = p.parse_args(["suite", "doctor", "-F"])
    assert doctor_args.full is True
    assert not hasattr(doctor_args, "llm_friendly") or doctor_args.llm_friendly is False

    plan_args = p.parse_args(["suite", "plan", "-c", "aider-python-10", "-F"])
    assert plan_args.llm_friendly is True
    assert not hasattr(plan_args, "full")


def test_doctor_never_dispatches_inference(monkeypatch, capsys):
    """Doctor must be strictly non-mutating and NEVER dispatch inference."""
    dispatched = []

    def fake_dispatch(*args, **kwargs):
        dispatched.append((args, kwargs))
        raise AssertionError("Inference dispatch forbidden during doctor")

    monkeypatch.setattr("agent_benchmark.suite_doctor._dispatch_inference_forbidden_marker", fake_dispatch, raising=False)
    
    # Run doctor in json format
    exit_code = main(["suite", "doctor", "-f", "json"])
    assert len(dispatched) == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["inference_dispatched"] is False


def test_doctor_returns_valid_preflight_v1_schema(capsys):
    """Verify JSON output strictly satisfies monitor-preflight-v1 schema."""
    exit_code = main(["suite", "doctor", "-f", "json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)

    assert data["schema_version"] == "monitor-preflight-v1"
    assert data["status"] in ("ready", "degraded", "blocked", "unknown")
    assert "execution_context" in data
    assert "components" in data
    assert "recommended_action" in data
    assert "recovery" in data
    assert data["inference_dispatched"] is False
    assert "checked_at" in data
    assert isinstance(data["elapsed_ms"], (int, float))

    # Validate component structure
    components = data["components"]
    for name, comp in components.items():
        assert "state" in comp
        assert "error_code" in comp
        assert "retryable" in comp
        assert "elapsed_ms" in comp
        assert "evidence_kind" in comp
        assert "remedy" in comp
        assert "details" in comp


def test_doctor_detects_docker_pipe_access_denied(monkeypatch, capsys):
    """Simulate Windows Docker Desktop named pipe ACL denial (WinError 5)."""
    from agent_benchmark.suite_doctor import probe_docker

    probe = probe_docker(mock_pipe_error=PermissionError("Access is denied (WinError 5)"))
    assert probe.status == "blocked"
    assert probe.error_code == "DOCKER_PIPE_ACCESS_DENIED"
    assert probe.suggested_action == "USE_APPROVED_HOST_CONTEXT"
    assert probe.retryable is False


def test_doctor_detects_absent_monitor(monkeypatch, capsys):
    """When monitor port is closed and no descriptor exists, diagnose MONITOR_NOT_RUNNING."""
    with patch("agent_benchmark.suite_doctor.find_active_server", return_value=None), \
         patch("agent_benchmark.suite_doctor._is_port_listening", return_value=False):
        exit_code = main(["suite", "doctor", "-f", "json", "-L", "-H", "http://127.0.0.1:9999"])
        assert exit_code == 1
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["status"] == "blocked"
        assert data["components"]["managed_monitor"]["error_code"] == "MONITOR_NOT_RUNNING"
        assert data["recommended_action"] == "START_MANAGED_MONITOR"


def test_doctor_detects_unmanaged_listener(monkeypatch, capsys):
    """When port is occupied but descriptor is absent, diagnose MONITOR_UNMANAGED_LISTENER."""
    with patch("agent_benchmark.suite_doctor.find_active_server", return_value=None), \
         patch("agent_benchmark.suite_doctor._is_port_listening", return_value=True):
        exit_code = main(["suite", "doctor", "-f", "json", "-L", "-H", "http://127.0.0.1:8788"])
        assert exit_code == 1
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["status"] == "blocked"
        assert data["components"]["managed_monitor"]["error_code"] == "MONITOR_UNMANAGED_LISTENER"
        assert data["recommended_action"] == "CHECK_MANAGED_MONITOR"


def test_doctor_detects_config_mismatch(monkeypatch, capsys):
    """When monitor is running but gateway or recording mode doesn't match requested."""
    fake_desc = MagicMock(
        pid=1234, process_create_time=1000.0, port=8788,
        gateway_enabled=False, recording_mode="off",
        config_fingerprint="sha256:abc"
    )
    with patch("agent_benchmark.suite_doctor.find_active_server", return_value=fake_desc), \
         patch("agent_benchmark.suite_doctor._is_port_listening", return_value=True), \
         patch("agent_benchmark.suite_doctor.is_process_alive", return_value=True), \
         patch("agent_benchmark.suite_doctor.compare_config_fingerprint", return_value=False):
        exit_code = main(["suite", "doctor", "-f", "json", "-L", "--recording", "content"])
        assert exit_code == 1
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["status"] == "blocked"
        assert data["components"]["managed_monitor"]["error_code"] == "MONITOR_CONFIG_MISMATCH"
        assert data["recommended_action"] == "FIX_CONFIGURATION"


def test_doctor_detects_auth_control_permission_denied(monkeypatch, capsys):
    """When local named pipe control raises ACL denial, classify MONITOR_CONTROL_PERMISSION_DENIED."""
    from agent_benchmark.suite_doctor import probe_auth_channel

    with patch("llm_monitor.local_client.ManagedMonitorClient.acquire_capability_token",
               side_effect=PermissionError("WinError 5 Access is denied")):
        probe, _ = probe_auth_channel(port=8788, host="127.0.0.1", monitor_ready=True)
        assert probe.status == "blocked"
        assert probe.error_code == "MONITOR_CONTROL_PERMISSION_DENIED"
        assert probe.suggested_action == "USE_APPROVED_HOST_CONTEXT"


def test_doctor_detects_auth_http_401_and_403(monkeypatch):
    """Verify HTTP 401 and 403 errors on capability challenge."""
    from agent_benchmark.suite_doctor import probe_auth_channel

    with patch("llm_monitor.local_client.ManagedMonitorClient.acquire_capability_token", return_value="tok123"):
        # Test 401
        mock_resp_401 = MagicMock(status_code=401)
        with patch("httpx.Client.get", return_value=mock_resp_401):
            probe_401, _ = probe_auth_channel(port=8788, host="127.0.0.1", monitor_ready=True)
            assert probe_401.status == "blocked"
            assert probe_401.error_code == "MONITOR_HTTP_UNAUTHORIZED"
            assert probe_401.suggested_action == "REAUTHENTICATE_MANAGED"

        # Test 403
        mock_resp_403 = MagicMock(status_code=403)
        with patch("httpx.Client.get", return_value=mock_resp_403):
            probe_403, _ = probe_auth_channel(port=8788, host="127.0.0.1", monitor_ready=True)
            assert probe_403.status == "blocked"
            assert probe_403.error_code == "MONITOR_HTTP_ORIGIN_REJECTED"
            assert probe_403.suggested_action == "FIX_CONFIGURATION"


def test_doctor_detects_unhealthy_recorder(monkeypatch, capsys):
    """When recorder reports dropped events or healthy=False."""
    from agent_benchmark.suite_doctor import probe_recorder

    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"recording": {"healthy": False, "dropped_count": 5, "mode": "content"}}
        )
        probe = probe_recorder(origin="http://127.0.0.1:8788", monitor_ready=True, token="tok")
        assert probe.status == "degraded"
        assert probe.error_code == "MONITOR_RECORDER_UNHEALTHY"
        assert probe.suggested_action == "REPAIR_RECORDER"


def test_doctor_detects_lm_studio_unreachable():
    """When LM Studio port refuses connection."""
    from agent_benchmark.suite_doctor import probe_lm_studio

    with patch("httpx.Client.get", side_effect=httpx.ConnectError("Connection refused")):
        probe = probe_lm_studio(endpoint="http://127.0.0.1:1234", model=None)
        assert probe.status == "blocked"
        assert probe.error_code == "LM_STUDIO_UNREACHABLE"
        assert probe.suggested_action == "CHECK_PROVIDER"


def test_doctor_text_format_output(capsys):
    """Verify text format produces readable report and correct exit code."""
    with patch("agent_benchmark.suite_doctor.find_active_server", return_value=None), \
         patch("agent_benchmark.suite_doctor._is_port_listening", return_value=False):
        exit_code = main(["suite", "doctor", "-f", "text", "-L"])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "LLM Benchmark Suite Doctor" in captured.out
        assert "Status:" in captured.out
        assert "Recommended Action:" in captured.out
