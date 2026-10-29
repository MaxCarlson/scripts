"""Tests for Runmux optional LLM Monitor integration factory and configuration."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from runmux.llm_monitor_integration import (
    LLMMonitorConfig,
    LLMMonitorIntegration,
    create_model_metadata_provider,
    get_monitor_integration,
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

    def snapshot(self, *, force_refresh: bool = False) -> dict[str, Any]:
        self.snapshot_calls += 1
        return {
            "schema_version": 1,
            "refreshed_at": "2026-10-29T00:00:00Z",
            "provider": {"type": "opencode", "instance_id": "http://127.0.0.1:4096"},
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


def test_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RUNMUX_LLM_MONITOR_ENABLED", raising=False)
    integration = LLMMonitorIntegration(config=LLMMonitorConfig.from_env({}))
    status = integration.status()
    assert status["availability"] == "disabled"
    assert status["reason"] == "disabled"
    assert status["capabilities"] == []
    assert integration.get_adapter() is None


def test_disabled_with_explicit_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    config = LLMMonitorConfig.from_env({"RUNMUX_LLM_MONITOR_ENABLED": "0"})
    integration = LLMMonitorIntegration(config=config)
    status = integration.status()
    assert status["availability"] == "disabled"
    assert status["reason"] == "disabled"


def test_python_310_incompatibility_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    config = LLMMonitorConfig.from_env({"RUNMUX_LLM_MONITOR_ENABLED": "1"})
    with patch("sys.version_info", (3, 10, 8, "final", 0)):
        integration = LLMMonitorIntegration(config=config)
        status = integration.status()
        assert status["availability"] == "unavailable"
        assert status["reason"] == "python_incompatible"
        assert integration.get_adapter() is None


def test_package_missing_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    config = LLMMonitorConfig.from_env({"RUNMUX_LLM_MONITOR_ENABLED": "1"})
    with patch.dict(sys.modules, {"llm_monitor": None, "llm_monitor.runmux_adapter": None}):
        integration = LLMMonitorIntegration(config=config)
        status = integration.status()
        assert status["availability"] == "unavailable"
        assert status["reason"] == "package_missing"


def test_url_validation_safe_endpoints() -> None:
    assert validate_provider_url("http://127.0.0.1:4096") == "http://127.0.0.1:4096"
    assert validate_provider_url("https://localhost:8080") == "https://localhost:8080"
    assert validate_provider_url("http://10.0.0.2:1234/") == "http://10.0.0.2:1234"

    with pytest.raises(ValueError, match="scheme"):
        validate_provider_url("ftp://127.0.0.1:4096")
    with pytest.raises(ValueError, match="userinfo"):
        validate_provider_url("http://user:pass@127.0.0.1:4096")
    with pytest.raises(ValueError, match="query"):
        validate_provider_url("http://127.0.0.1:4096?foo=bar")
    with pytest.raises(ValueError, match="fragment"):
        validate_provider_url("http://127.0.0.1:4096#section")


def test_database_existing_only(tmp_path: Path) -> None:
    non_existent = tmp_path / "does_not_exist.db"
    config = LLMMonitorConfig.from_env({
        "RUNMUX_LLM_MONITOR_ENABLED": "1",
        "RUNMUX_LLM_MONITOR_DATABASE": str(non_existent),
    })
    # Non-existent DB file should be filtered to None and NOT created
    assert config.database_path is None
    assert not non_existent.exists()

    real_db = tmp_path / "real.db"
    real_db.write_bytes(b"sqlite header placeholder")
    config2 = LLMMonitorConfig.from_env({
        "RUNMUX_LLM_MONITOR_ENABLED": "1",
        "RUNMUX_LLM_MONITOR_DATABASE": str(real_db),
    })
    assert config2.database_path == real_db


def test_status_never_calls_provider_io() -> None:
    mock_adapter = FakeMonitoringAdapter()
    config = LLMMonitorConfig(enabled=True)
    integration = LLMMonitorIntegration(config=config, adapter=mock_adapter)

    # Calling status multiple times must not invoke snapshot or detail
    for _ in range(5):
        st = integration.status()
        assert st["availability"] == "available"
        assert st["capabilities"] == ["snapshot", "session_detail", "timeline", "alerts", "hardware"]

    assert mock_adapter.snapshot_calls == 0
    assert mock_adapter.detail_calls == 0


def test_injected_adapter_delegation() -> None:
    mock_adapter = FakeMonitoringAdapter()
    config = LLMMonitorConfig(enabled=True)
    integration = LLMMonitorIntegration(config=config, adapter=mock_adapter)

    snap = integration.snapshot()
    assert snap["availability"] == "available"
    assert snap["snapshot"]["provider"]["instance_id"] == "http://127.0.0.1:4096"
    assert mock_adapter.snapshot_calls == 1

    detail = integration.session_detail("http://127.0.0.1:4096", "sess-1")
    assert detail is not None
    assert detail["summary"]["session_id"] == "sess-1"
    # detail requires snapshot seeding first
    assert mock_adapter.snapshot_calls == 2
    assert mock_adapter.detail_calls == 1

    timeline = integration.timeline("http://127.0.0.1:4096", "sess-1", limit=50)
    assert timeline["availability"] == "available"
    assert mock_adapter.timeline_calls == 1

    alerts = integration.alerts(status="active", limit=10)
    assert alerts["availability"] == "available"
    assert mock_adapter.alerts_calls == 1

    hw = integration.hardware()
    assert hw["availability"] == "available"
    assert hw["hardware"]["devices"][0]["name"] == "RTX 4090"


def test_model_metadata_caching() -> None:
    mock_client = MagicMock()
    mock_client.get_json.return_value = MagicMock(data={"providers": []})
    mock_lmstudio = MagicMock()
    mock_lmstudio.list_models.return_value = [{"id": "qwen38", "state": "loaded"}]

    provider_fn = create_model_metadata_provider(mock_client, mock_lmstudio)
    snapshot = {"session_info": {"model": "qwen38", "provider": "lmstudio"}}

    limits, loaded = provider_fn("sess-1", snapshot)
    assert loaded == {"id": "qwen38", "state": "loaded"}
    assert mock_lmstudio.list_models.call_count == 1

    # Second call should use cache
    limits2, loaded2 = provider_fn("sess-1", snapshot)
    assert loaded2 == {"id": "qwen38", "state": "loaded"}
    assert mock_lmstudio.list_models.call_count == 1


def test_get_monitor_integration_singleton() -> None:
    mock_adapter = FakeMonitoringAdapter()
    config = LLMMonitorConfig(enabled=True)
    inst1 = get_monitor_integration(config=config, adapter=mock_adapter, force_reload=True)
    inst2 = get_monitor_integration()
    assert inst1 is inst2
