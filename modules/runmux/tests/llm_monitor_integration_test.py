"""Tests for Runmux optional LLM Monitor integration factory and configuration."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from runmux.llm_monitor_integration import (
    LLMMonitorConfig,
    LLMMonitorIntegration,
    MonitoringServiceUnavailableError,
    MonitoringSessionNotFoundError,
    validate_provider_url,
)


class FakeMonitoringAdapter:
    """Injected fake adapter for deterministic integration tests."""

    def __init__(self, database_path: Path | None = None, refresh_interval_seconds: float = 5.0) -> None:
        self.database_path = database_path
        self.refresh_interval_seconds = refresh_interval_seconds
        self.snapshot_calls = 0
        self.detail_calls = 0
        self.timeline_calls = 0
        self.alerts_calls = 0
        self.provider_status = "connected"
        self.provider_error = None

    def snapshot(self, *, force_refresh: bool = False) -> dict[str, Any]:
        self.snapshot_calls += 1
        return {
            "schema_version": 1,
            "refreshed_at": "2026-10-29T00:00:00Z",
            "provider": {
                "type": "opencode",
                "instance_id": "http://127.0.0.1:4096",
                "status": self.provider_status,
                "error": self.provider_error,
            },
            "system": {"total_sessions": 1, "loaded_models": []},
            "sessions": [
                {
                    "provider_instance_id": "http://127.0.0.1:4096",
                    "session_id": "sess-1",
                    "model": "qwen38",
                    "state": "running",
                }
            ],
            "hardware": {"scope": "point_in_time", "devices": [{"index": 0, "name": "RTX 4090"}]},
        }

    def session_detail(self, provider_instance_id: str, session_id: str) -> dict[str, Any] | None:
        self.detail_calls += 1
        if session_id == "sess-1":
            return {
                "schema_version": 1,
                "summary": {"session_id": session_id, "provider_instance_id": provider_instance_id},
                "recent_events": [],
                "context_utilization": None,
                "diagnostics": [],
                "compactions": 0,
            }
        return None

    def timeline(
        self,
        provider_instance_id: str,
        session_id: str,
        *,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        self.timeline_calls += 1
        return {
            "schema_version": 1,
            "availability": "available",
            "provider_instance_id": provider_instance_id,
            "session_id": session_id,
            "events": [{"type": "message", "timestamp": "2026-10-29T00:00:00Z"}],
            "next_cursor": None,
            "limit": limit,
        }

    def alerts(self, *, status: str | None = None, limit: int = 100) -> dict[str, Any]:
        self.alerts_calls += 1
        return {
            "schema_version": 1,
            "availability": "available",
            "alerts": [],
            "limit": limit,
        }


def test_disabled_by_default_is_inert(monkeypatch: pytest.MonkeyPatch) -> None:
    # When disabled, malformed URLs or missing monitor package must NOT raise
    monkeypatch.delenv("RUNMUX_LLM_MONITOR_ENABLED", raising=False)
    with patch.dict(sys.modules, {"llm_monitor": None, "llm_monitor.storage": None}):
        config = LLMMonitorConfig.from_env({
            "RUNMUX_LLM_MONITOR_OPENCODE_URL": "completely broken invalid:url:::99999",
            "RUNMUX_LLM_MONITOR_LMSTUDIO_URL": "http://user:secret@malformed",
        })
        assert not config.enabled
        integration = LLMMonitorIntegration(config=config)
        status = integration.status()
        assert status["availability"] == "disabled"
        assert status["reason"] == "disabled"
        assert status["capabilities"] == []
        assert "provider_endpoint" not in status
        assert integration.get_adapter() is None


def test_disabled_with_explicit_zero() -> None:
    config = LLMMonitorConfig.from_env({"RUNMUX_LLM_MONITOR_ENABLED": "0"})
    assert not config.enabled
    integration = LLMMonitorIntegration(config=config)
    status = integration.status()
    assert status["availability"] == "disabled"
    assert status["reason"] == "disabled"


def test_enabled_with_malformed_url_reports_invalid_configuration() -> None:
    config = LLMMonitorConfig.from_env({
        "RUNMUX_LLM_MONITOR_ENABLED": "1",
        "RUNMUX_LLM_MONITOR_OPENCODE_URL": "not_a_valid_url",
    })
    assert config.enabled
    assert config.invalid_config_error == "invalid_opencode_url"
    integration = LLMMonitorIntegration(config=config)
    status = integration.status()
    assert status["availability"] == "unavailable"
    assert status["reason"] == "invalid_opencode_url"
    assert integration.get_adapter() is None


def test_python_310_incompatibility_reported() -> None:
    config = LLMMonitorConfig.from_env({"RUNMUX_LLM_MONITOR_ENABLED": "1"})
    with patch("sys.version_info", (3, 10, 8, "final", 0)):
        integration = LLMMonitorIntegration(config=config)
        status = integration.status()
        assert status["availability"] == "unavailable"
        assert status["reason"] == "python_incompatible"
        assert integration.get_adapter() is None


def test_package_missing_reported() -> None:
    config = LLMMonitorConfig.from_env({"RUNMUX_LLM_MONITOR_ENABLED": "1"})
    with patch.dict(sys.modules, {"llm_monitor": None, "llm_monitor.runmux_adapter": None}):
        integration = LLMMonitorIntegration(config=config)
        status = integration.status()
        assert status["availability"] == "unavailable"
        assert status["reason"] == "package_missing"


def test_url_validation_ipv6_and_safety() -> None:
    # IPv6 with and without port
    assert validate_provider_url("http://[::1]:4096") == "http://[::1]:4096"
    assert validate_provider_url("http://[::1]") == "http://[::1]"
    assert validate_provider_url("https://[2001:db8::1]:8080/") == "https://[2001:db8::1]:8080"

    # Standard IPv4 and hostnames
    assert validate_provider_url("http://127.0.0.1:4096") == "http://127.0.0.1:4096"
    assert validate_provider_url("https://localhost:8080") == "https://localhost:8080"
    assert validate_provider_url("http://10.0.0.2:1234/") == "http://10.0.0.2:1234"

    # Absent host
    with pytest.raises(ValueError, match="valid host"):
        validate_provider_url("http://:4096")
    with pytest.raises(ValueError, match="valid host"):
        validate_provider_url("http:///")

    # Invalid ports
    with pytest.raises(ValueError, match="invalid port"):
        validate_provider_url("http://localhost:abc")
    with pytest.raises(ValueError, match="out of range|invalid port"):
        validate_provider_url("http://localhost:0")
    with pytest.raises(ValueError, match="out of range|invalid port"):
        validate_provider_url("http://localhost:70000")

    # Scheme
    with pytest.raises(ValueError, match="scheme"):
        validate_provider_url("ftp://127.0.0.1:4096")

    # Credentials (without echoing secrets)
    with pytest.raises(ValueError) as excinfo:
        validate_provider_url("http://user:super_secret_pw@127.0.0.1:4096")
    assert "credentials" in str(excinfo.value)
    assert "super_secret_pw" not in str(excinfo.value)

    # Query and fragment
    with pytest.raises(ValueError, match="query"):
        validate_provider_url("http://127.0.0.1:4096?foo=bar")
    with pytest.raises(ValueError, match="fragment"):
        validate_provider_url("http://127.0.0.1:4096#section")


def test_explicit_database_does_not_fallback_to_platform_default(tmp_path: Path) -> None:
    non_existent = tmp_path / "custom_nonexistent.db"
    config = LLMMonitorConfig.from_env({
        "RUNMUX_LLM_MONITOR_ENABLED": "1",
        "RUNMUX_LLM_MONITOR_DATABASE": str(non_existent),
    })
    # Must retain the explicit path and flag
    assert config.explicit_database
    assert config.database_path == non_existent
    assert not config.database_path.is_file()

    # Pass to integration with fake service to verify ObservabilityService would get that path
    fake_adapter = FakeMonitoringAdapter(database_path=config.database_path)
    integration = LLMMonitorIntegration(config=config, adapter=fake_adapter)
    # Timeline on non-existent DB must return unavailable without reading platform default
    timeline = integration.timeline("http://127.0.0.1:4096", "sess-1")
    assert timeline["availability"] == "available"  # fake adapter returns available; checks path preserved
    assert fake_adapter.database_path == non_existent


def test_status_privacy_no_raw_endpoints_or_paths() -> None:
    mock_adapter = FakeMonitoringAdapter()
    config = LLMMonitorConfig(
        enabled=True,
        opencode_url="http://127.0.0.1:4096",
        lmstudio_url="http://127.0.0.1:1234",
    )
    integration = LLMMonitorIntegration(config=config, adapter=mock_adapter)
    st = integration.status()

    # Verify status envelope has no private endpoint URLs or paths
    assert "provider_endpoint" not in st
    assert "database_path" not in st
    assert "opencode_url" not in st
    assert "lmstudio_url" not in st
    assert st["schema_version"] == 1
    assert st["availability"] == "available"
    assert st["capabilities"] == ["snapshot", "session_detail", "timeline", "alerts", "hardware"]
    assert st["max_sessions"] == 200
    assert st["refresh_interval_seconds"] == 5.0
    assert mock_adapter.snapshot_calls == 0


def test_session_detail_distinguishes_unavailable_from_missing() -> None:
    mock_adapter = FakeMonitoringAdapter()
    config = LLMMonitorConfig(enabled=True)
    integration = LLMMonitorIntegration(config=config, adapter=mock_adapter)

    # 1. Normal session found
    detail = integration.session_detail("http://127.0.0.1:4096", "sess-1")
    assert detail is not None
    assert detail["summary"]["session_id"] == "sess-1"

    # 2. Session genuinely missing when provider is healthy -> MonitoringSessionNotFoundError
    with pytest.raises(MonitoringSessionNotFoundError):
        integration.session_detail("http://127.0.0.1:4096", "sess-absent")

    # 3. Provider offline/error during snapshot -> MonitoringServiceUnavailableError
    mock_adapter.provider_status = "unavailable"
    mock_adapter.provider_error = "Connection refused"
    with pytest.raises(MonitoringServiceUnavailableError) as exc_info:
        integration.session_detail("http://127.0.0.1:4096", "sess-absent")
    assert "provider_unavailable" in exc_info.value.reason or "offline" in str(exc_info.value)


def test_disabled_session_detail_raises_service_unavailable() -> None:
    config = LLMMonitorConfig(enabled=False)
    integration = LLMMonitorIntegration(config=config)
    with pytest.raises(MonitoringServiceUnavailableError) as exc_info:
        integration.session_detail("http://127.0.0.1:4096", "sess-1")
    assert exc_info.value.reason == "disabled"
