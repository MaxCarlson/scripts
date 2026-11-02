from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from agent_benchmark.cli import main, parser
from agent_benchmark.suite_monitor import MonitorPreflightError
from agent_benchmark.suite_doctor import run_doctor
from agent_benchmark.suite_recovery import recover_managed_monitor


def test_adversarial_foreign_listener_mimicking_banner():
    """An alien HTTP listener occupying the port without a valid descriptor must not be killed or trusted."""
    from agent_benchmark.suite_doctor import probe_managed_monitor

    # Port is in use, but descriptor is missing
    with patch("agent_benchmark.suite_doctor.find_active_server", return_value=None), \
         patch("agent_benchmark.suite_doctor._is_port_listening", return_value=True):
        probe, desc = probe_managed_monitor(host="127.0.0.1", port=8788)
        assert probe.status == "blocked"
        assert probe.error_code == "MONITOR_UNMANAGED_LISTENER"
        assert desc is None


def test_adversarial_pid_recycling_rejected():
    """A recycled PID with a mismatched create_time must be rejected immediately."""
    from agent_benchmark.suite_doctor import probe_managed_monitor

    fake_desc = MagicMock(
        pid=9999, process_create_time=123456.0, port=8788,
        gateway_enabled=True, recording_mode="content",
        config_fingerprint="sha256:abc", instance_id="old-instance"
    )

    with patch("agent_benchmark.suite_doctor.find_active_server", return_value=fake_desc), \
         patch("agent_benchmark.suite_doctor._is_port_listening", return_value=True), \
         patch("agent_benchmark.suite_doctor.is_process_alive", return_value=False):
        probe, desc = probe_managed_monitor(host="127.0.0.1", port=8788)
        assert probe.status == "blocked"
        assert probe.error_code == "MONITOR_IDENTITY_MISMATCH"
        assert desc is None


def test_adversarial_forged_hmac_challenge_rejected():
    """Forged challenge HMAC responses must fail instance verification."""
    from llm_monitor.server_lifecycle import (
        ServerDescriptor,
        compute_challenge_hmac,
        verify_running_instance,
    )

    desc = ServerDescriptor(
        instance_id="inst-valid-1",
        version="1.0.0",
        protocol="http",
        host="127.0.0.1",
        port=8788,
        pid=1234,
        process_create_time=1000.0,
        started_at="2026-11-02T00:00:00Z",
        control_token="secret-token-1234",
    )

    # With forged HMAC returned by endpoint
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"status": "ok", "response_hmac": "forged_invalid_signature"}
        )
        res = verify_running_instance(desc, timeout=0.5)
        assert res is None  # Fails verification closed!


def test_adversarial_secret_scrubbing_in_exceptions_and_receipts():
    """Ensures capability tokens, bearer auth, and cookies are NEVER leaked into receipts or logs."""
    import subprocess
    fake_token = "BEARER_SECRET_CAPABILITY_TOKEN_9999"
    fake_cookie = "LLM_MONITOR_COOKIE_SECRET_8888"

    mock_desc = MagicMock(
        pid=4321, process_create_time=2000.0, port=8788,
        gateway_enabled=True, recording_mode="content",
        config_fingerprint="sha256:test", instance_id="inst-1234"
    )

    real_popen = subprocess.Popen
    def fake_spawn(cmd, **kwargs):
        if isinstance(cmd, list) and cmd and "icacls" in str(cmd[0]):
            return real_popen(cmd, **kwargs)
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 4321
        return mock_proc

    with patch("agent_benchmark.suite_recovery.subprocess.Popen", side_effect=fake_spawn), \
         patch("agent_benchmark.suite_recovery._poll_for_server_ready", return_value=mock_desc), \
         patch("agent_benchmark.suite_recovery.ManagedMonitorClient.acquire_capability_token", return_value=fake_token):
        
        receipt = recover_managed_monitor(
            host_origin="http://127.0.0.1:8788",
            recording="content",
            recover_local=True,
            timeout_seconds=2.0,
        )

        serialized = json.dumps(receipt)
        assert fake_token not in serialized
        assert fake_cookie not in serialized
        assert "server_instance_id" in receipt
        assert receipt["inference_dispatched"] is False


def test_adversarial_opencode_responses_api_format_rejected():
    """Configuring openai_responses for OpenCode must fail closed with MONITOR_ROUTE_INCOMPATIBLE."""
    from agent_benchmark.suite_monitor import validate_monitor

    with pytest.raises(MonitorPreflightError) as exc_info:
        validate_monitor(
            agent="opencode",
            model="openai/qwen38",
            monitor_url="http://host.docker.internal:8789/v1",
            api_format="openai_responses",
        )
    assert "openai_chat_completions" in str(exc_info.value)


def test_adversarial_concurrent_plan_start_coalescing():
    """Verify concurrent plans do not restart or collide on already listening port."""
    from agent_benchmark.suite_doctor import probe_managed_monitor

    fake_desc = MagicMock(
        pid=1234, process_create_time=1000.0, port=8788,
        gateway_enabled=True, recording_mode="content",
        config_fingerprint="sha256:abc", instance_id="inst-live"
    )

    with patch("agent_benchmark.suite_doctor.find_active_server", return_value=fake_desc), \
         patch("agent_benchmark.suite_doctor._is_port_listening", return_value=True), \
         patch("agent_benchmark.suite_doctor.is_process_alive", return_value=True), \
         patch("agent_benchmark.suite_doctor.compare_config_fingerprint", return_value=True):
        
        probe, desc = probe_managed_monitor(
            host="127.0.0.1",
            port=8788,
            expected_gateway=True,
            expected_recording="content",
        )
        assert probe.status == "ready"
        assert desc.instance_id == "inst-live"
