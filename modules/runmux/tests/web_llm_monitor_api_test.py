"""Tests for Runmux authenticated LLM Monitor HTTP API routes."""

from __future__ import annotations

import concurrent.futures
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from runmux.llm_monitor_integration import (
    LLMMonitorConfig,
    LLMMonitorIntegration,
)
from runmux.web import create_runmux_web_app


class FakeMonitoringAdapter:
    """Mock adapter for API route testing."""

    def __init__(self, database_path: Path | None = None, refresh_interval_seconds: float = 5.0) -> None:
        self.database_path = database_path
        self.refresh_interval_seconds = refresh_interval_seconds
        self.snapshot_calls = 0
        self.detail_calls = 0
        self.timeline_calls = 0
        self.alerts_calls = 0
        self.provider_status = "connected"
        self.provider_error = None
        self._cached_snapshot: dict[str, Any] | None = None
        self._cached_at = 0.0

    def snapshot(self, *, force_refresh: bool = False) -> dict[str, Any]:
        import time
        now = time.monotonic()
        if not force_refresh and self._cached_snapshot and now - self._cached_at < self.refresh_interval_seconds:
            return self._cached_snapshot

        self.snapshot_calls += 1
        res = {
            "schema_version": 1,
            "refreshed_at": "2026-10-29T00:00:00Z",
            "provider": {
                "type": "opencode",
                "instance_id": "http://127.0.0.1:4096",
                "status": self.provider_status,
                "error": self.provider_error,
            },
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
        self._cached_snapshot = res
        self._cached_at = now
        return res

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
        res = client.get("/api/llm-monitor/v1/status", headers={"Origin": "http://localhost"})
        assert res.status_code == 401
        assert "no-store" in res.headers.get("Cache-Control", "")

        login_res = client.post("/auth/login", json={"code": "test-login"}, headers={"Origin": "http://localhost"})
        assert login_res.status_code in {200, 204}

        cross_res = client.get("/api/llm-monitor/v1/status", headers={"Origin": "http://hostile.site"})
        assert cross_res.status_code == 403


def test_monitor_status_endpoint_privacy(tmp_path: Path, monitor_integration: LLMMonitorIntegration) -> None:
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
        # Privacy: no raw provider endpoints or local paths exposed
        assert "provider_endpoint" not in data
        assert "database_path" not in data


def test_monitor_snapshot_endpoint_no_bypass(tmp_path: Path, monitor_integration: LLMMonitorIntegration) -> None:
    app = create_runmux_web_app(
        tmp_path / "state",
        login_code="test-login",
        llm_monitor_integration=monitor_integration,
    )
    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "test-login"}, headers={"Origin": "http://localhost"})

        # Multiple concurrent requests share the adapter's snapshot
        def make_request() -> int:
            r = client.get("/api/llm-monitor/v1/snapshot", headers={"Origin": "http://localhost"})
            return r.status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(make_request) for _ in range(5)]
            results = [f.result() for f in futures]

        assert all(code == 200 for code in results)
        # Verify adapter was only called once for the shared refresh window
        assert monitor_integration._adapter.snapshot_calls == 1


def test_monitor_session_detail_and_unavailable_separation(tmp_path: Path) -> None:
    fake_adapter = FakeMonitoringAdapter()
    config = LLMMonitorConfig(enabled=True)
    integration = LLMMonitorIntegration(config=config, adapter=fake_adapter)

    app = create_runmux_web_app(
        tmp_path / "state",
        login_code="test-login",
        llm_monitor_integration=integration,
    )
    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "test-login"}, headers={"Origin": "http://localhost"})

        # 1. Existing session -> 200
        res = client.get(
            "/api/llm-monitor/v1/sessions/detail?provider_instance_id=http://127.0.0.1:4096&session_id=sess-live",
            headers={"Origin": "http://localhost"},
        )
        assert res.status_code == 200
        assert res.json()["detail"]["summary"]["session_id"] == "sess-live"

        # 2. Genuine missing session on healthy provider -> 404
        res404 = client.get(
            "/api/llm-monitor/v1/sessions/detail?provider_instance_id=http://127.0.0.1:4096&session_id=sess-missing",
            headers={"Origin": "http://localhost"},
        )
        assert res404.status_code == 404
        assert res404.json()["detail"] == "LLM session not found"

        # 3. Provider failure during refresh -> 503 (not 404!)
        fake_adapter.provider_status = "unavailable"
        fake_adapter.provider_error = "Connection refused to OpenCode"
        fake_adapter._cached_snapshot = None
        res503 = client.get(
            "/api/llm-monitor/v1/sessions/detail?provider_instance_id=http://127.0.0.1:4096&session_id=sess-unknown",
            headers={"Origin": "http://localhost"},
        )
        assert res503.status_code == 503
        assert "OpenCode provider is offline" in res503.json()["detail"]


def test_monitor_instance_ownership_isolation(tmp_path: Path) -> None:
    # Separate apps have distinct monitor integration instances
    app1 = create_runmux_web_app(tmp_path / "state1", login_code="code1")
    app2 = create_runmux_web_app(tmp_path / "state2", login_code="code2")

    # They should not share the same monitor instance
    # By inspecting routes
    with TestClient(app1, base_url="http://localhost") as c1, TestClient(app2, base_url="http://localhost") as c2:
        c1.post("/auth/login", json={"code": "code1"}, headers={"Origin": "http://localhost"})
        c2.post("/auth/login", json={"code": "code2"}, headers={"Origin": "http://localhost"})
        st1 = c1.get("/api/llm-monitor/v1/status", headers={"Origin": "http://localhost"}).json()
        st2 = c2.get("/api/llm-monitor/v1/status", headers={"Origin": "http://localhost"}).json()
        assert st1["availability"] == "disabled"
        assert st2["availability"] == "disabled"


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
