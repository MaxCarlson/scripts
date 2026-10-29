"""Tests for Runmux authenticated LLM Monitor HTTP API routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from runmux.llm_monitor_integration import LLMMonitorConfig, LLMMonitorIntegration
from runmux.web import create_runmux_web_app


class FakeMonitoringAdapter:
    """Mock adapter for API route testing."""

    def __init__(self, database_path: Path | None = None) -> None:
        self.database_path = database_path
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
            "system": {"total_sessions": 2, "loaded_models": []},
            "sessions": [
                {
                    "provider_instance_id": "http://127.0.0.1:4096",
                    "session_id": "sess-live",
                    "model": "qwen38",
                    "state": "running",
                }
            ],
            "hardware": {"scope": "point_in_time", "devices": [{"name": "RTX 4090"}]},
        }

    def session_detail(self, provider_instance_id: str, session_id: str) -> dict[str, Any] | None:
        self.detail_calls += 1
        if session_id == "sess-live":
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
        if cursor == "malformed-hostile-cursor":
            raise ValueError("Corrupt cursor encoding with sensitive path C:/secret/db.sqlite")
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
            "alerts": [{"alert_id": "alt-1", "status": status or "active"}],
            "limit": limit,
        }


@pytest.fixture
def monitor_integration() -> LLMMonitorIntegration:
    mock_adapter = FakeMonitoringAdapter()
    config = LLMMonitorConfig(enabled=True)
    return LLMMonitorIntegration(config=config, adapter=mock_adapter)


def test_monitor_routes_require_authentication_and_same_origin(
    tmp_path: Path,
    monitor_integration: LLMMonitorIntegration,
) -> None:
    app = create_runmux_web_app(
        tmp_path / "state",
        login_code="test-login",
        llm_monitor_integration=monitor_integration,
    )
    with TestClient(app, base_url="http://localhost") as client:
        # Unauthenticated request without session cookie -> 401
        res = client.get("/api/llm-monitor/v1/status", headers={"Origin": "http://localhost"})
        assert res.status_code == 401
        assert "no-store" in res.headers.get("Cache-Control", "")

        # Authenticate
        login_res = client.post("/auth/login", json={"code": "test-login"}, headers={"Origin": "http://localhost"})
        assert login_res.status_code in {200, 204}

        # Hostile Origin -> 403
        cross_res = client.get("/api/llm-monitor/v1/status", headers={"Origin": "http://hostile.site"})
        assert cross_res.status_code == 403


def test_monitor_status_endpoint(tmp_path: Path, monitor_integration: LLMMonitorIntegration) -> None:
    app = create_runmux_web_app(
        tmp_path / "state",
        login_code="test-login",
        llm_monitor_integration=monitor_integration,
    )
    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "test-login"}, headers={"Origin": "http://localhost"})
        res = client.get("/api/llm-monitor/v1/status", headers={"Origin": "http://localhost"})
        assert res.status_code == 200
        data = res.json()
        assert data["schema_version"] == 1
        assert data["availability"] == "available"
        assert "snapshot" in data["capabilities"]
        assert data["max_sessions"] == 200


def test_monitor_snapshot_endpoint(tmp_path: Path, monitor_integration: LLMMonitorIntegration) -> None:
    app = create_runmux_web_app(
        tmp_path / "state",
        login_code="test-login",
        llm_monitor_integration=monitor_integration,
    )
    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "test-login"}, headers={"Origin": "http://localhost"})
        res = client.get("/api/llm-monitor/v1/snapshot", headers={"Origin": "http://localhost"})
        assert res.status_code == 200
        data = res.json()
        assert data["availability"] == "available"
        assert len(data["snapshot"]["sessions"]) == 1


def test_monitor_session_detail_endpoint(tmp_path: Path, monitor_integration: LLMMonitorIntegration) -> None:
    app = create_runmux_web_app(
        tmp_path / "state",
        login_code="test-login",
        llm_monitor_integration=monitor_integration,
    )
    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "test-login"}, headers={"Origin": "http://localhost"})

        # Found session
        res = client.get(
            "/api/llm-monitor/v1/sessions/detail?provider_instance_id=http://127.0.0.1:4096&session_id=sess-live",
            headers={"Origin": "http://localhost"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["detail"]["summary"]["session_id"] == "sess-live"

        # Not found session -> 404
        res404 = client.get(
            "/api/llm-monitor/v1/sessions/detail?provider_instance_id=http://127.0.0.1:4096&session_id=sess-absent",
            headers={"Origin": "http://localhost"},
        )
        assert res404.status_code == 404
        assert res404.json()["detail"] == "LLM session not found"


def test_monitor_timeline_endpoint(tmp_path: Path, monitor_integration: LLMMonitorIntegration) -> None:
    app = create_runmux_web_app(
        tmp_path / "state",
        login_code="test-login",
        llm_monitor_integration=monitor_integration,
    )
    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "test-login"}, headers={"Origin": "http://localhost"})

        res = client.get(
            "/api/llm-monitor/v1/sessions/timeline?provider_instance_id=http://127.0.0.1:4096&session_id=sess-live&limit=50",
            headers={"Origin": "http://localhost"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["availability"] == "available"
        assert data["limit"] == 50

        # Oversized limit -> 422
        bad_limit = client.get(
            "/api/llm-monitor/v1/sessions/timeline?provider_instance_id=http://127.0.0.1:4096&session_id=sess-live&limit=9999",
            headers={"Origin": "http://localhost"},
        )
        assert bad_limit.status_code == 422

        # Malformed cursor triggering ValueError -> generic 400 without leaking sensitive paths
        err_res = client.get(
            "/api/llm-monitor/v1/sessions/timeline?provider_instance_id=http://127.0.0.1:4096&session_id=sess-live&cursor=malformed-hostile-cursor",
            headers={"Origin": "http://localhost"},
        )
        assert err_res.status_code == 400
        assert "secret" not in err_res.text
        assert err_res.json()["detail"] == "Invalid timeline request parameters"


def test_monitor_alerts_endpoint(tmp_path: Path, monitor_integration: LLMMonitorIntegration) -> None:
    app = create_runmux_web_app(
        tmp_path / "state",
        login_code="test-login",
        llm_monitor_integration=monitor_integration,
    )
    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "test-login"}, headers={"Origin": "http://localhost"})

        res = client.get(
            "/api/llm-monitor/v1/alerts?status=active&limit=10",
            headers={"Origin": "http://localhost"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["availability"] == "available"
        assert data["alerts"][0]["status"] == "active"

        # Invalid status parameter -> 400
        bad_status = client.get(
            "/api/llm-monitor/v1/alerts?status=invalid_status",
            headers={"Origin": "http://localhost"},
        )
        assert bad_status.status_code == 400


def test_monitor_hardware_endpoint(tmp_path: Path, monitor_integration: LLMMonitorIntegration) -> None:
    app = create_runmux_web_app(
        tmp_path / "state",
        login_code="test-login",
        llm_monitor_integration=monitor_integration,
    )
    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "test-login"}, headers={"Origin": "http://localhost"})

        res = client.get("/api/llm-monitor/v1/hardware", headers={"Origin": "http://localhost"})
        assert res.status_code == 200
        data = res.json()
        assert data["availability"] == "available"
        assert data["hardware"]["devices"][0]["name"] == "RTX 4090"
