"""Tests for remote_control read-only dashboard API endpoints."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any, Tuple

import pytest
from fastapi.testclient import TestClient

from remote_control.adapters.notifications_adapter import ReadOnlyNotificationsAdapter
from remote_control.adapters.coordinator_adapter import ReadOnlyCoordinatorAdapter
from remote_control.config import RemoteControlConfig


def test_unauthenticated_api_access_rejected(
    client: TestClient,
    bootstrapped_operator: Tuple[Any, str, str],
) -> None:
    """Accessing protected /api/* endpoints without active session cookie returns 401."""
    endpoints = [
        "/api/summary",
        "/api/incidents",
        "/api/incidents/inc-001",
        "/api/notifications",
        "/api/providers",
        "/api/heartbeat",
        "/api/coordinator",
        "/api/auth/session",
        "/api/auth/devices",
    ]
    for ep in endpoints:
        resp = client.get(ep)
        assert resp.status_code == 401, f"Expected 401 for {ep}, got {resp.status_code}"
        assert resp.json().get("error") == "unauthenticated"


def test_dashboard_summary_endpoint(authenticated_client: Tuple[TestClient, str]) -> None:
    """Dashboard summary aggregates notifications, heartbeat, and coordinator contracts."""
    client, _ = authenticated_client
    resp = client.get("/api/summary")
    assert resp.status_code == 200
    data = resp.json()

    assert data["ok"] is True
    notif = data["notifications"]
    assert notif["available"] is True
    assert notif["active_incidents"] == 1
    assert notif["resolved_incidents"] == 1
    assert notif["total_incidents"] == 2
    assert notif["pending_outbox"] == 1

    hb = data["heartbeat"]
    assert "task_installed" in hb
    assert "execution_mode" in hb

    coord = data["coordinator"]
    assert coord["status"] in ("unconnected", "unmonitored")
    assert coord["available"] is False


def test_incidents_listing_and_filtering(authenticated_client: Tuple[TestClient, str]) -> None:
    """Incidents listing supports pagination and status/severity filtering."""
    client, _ = authenticated_client

    # All incidents
    resp_all = client.get("/api/incidents")
    assert resp_all.status_code == 200
    data_all = resp_all.json()
    assert data_all["total"] == 2
    assert len(data_all["items"]) == 2

    # Filter active
    resp_act = client.get("/api/incidents?status=active")
    assert resp_act.status_code == 200
    data_act = resp_act.json()
    assert data_act["total"] == 1
    assert data_act["items"][0]["incident_id"] == "inc-001"

    # Filter resolved
    resp_res = client.get("/api/incidents?status=resolved")
    assert resp_res.status_code == 200
    data_res = resp_res.json()
    assert data_res["total"] == 1
    assert data_res["items"][0]["incident_id"] == "inc-002"

    # Filter severity
    resp_sev = client.get("/api/incidents?severity=critical")
    assert resp_sev.status_code == 200
    assert resp_sev.json()["total"] == 1

    # Pagination limit
    resp_lim = client.get("/api/incidents?limit=1")
    assert resp_lim.status_code == 200
    assert len(resp_lim.json()["items"]) == 1


def test_incident_detail_with_occurrences_and_attempts(
    authenticated_client: Tuple[TestClient, str],
) -> None:
    """Fetching specific incident returns full occurrences and provider attempts."""
    client, _ = authenticated_client

    # Existing incident
    resp = client.get("/api/incidents/inc-001")
    assert resp.status_code == 200
    inc = resp.json()["incident"]
    assert inc["incident_id"] == "inc-001"
    assert inc["incident_key"] == "disk_c_alert"
    assert len(inc["occurrences"]) == 1
    assert len(inc["transitions"]) == 1
    assert len(inc["delivery_attempts"]) == 1
    assert inc["delivery_attempts"][0]["provider_id"] == "telegram"

    # Non-existent incident returns 404
    resp_404 = client.get("/api/incidents/inc-nonexistent")
    assert resp_404.status_code == 404
    assert resp_404.json()["error"] == "incident_not_found"


def test_notifications_outbox_endpoint(authenticated_client: Tuple[TestClient, str]) -> None:
    """Outbox notifications endpoint lists recent tasks."""
    client, _ = authenticated_client
    resp = client.get("/api/notifications")
    assert resp.status_code == 200
    items = resp.json()["notifications"]
    assert len(items) == 1
    assert items[0]["provider_id"] == "telegram"
    assert items[0]["status"] == "pending"


def test_providers_status_endpoint(authenticated_client: Tuple[TestClient, str]) -> None:
    """Providers endpoint lists delivery providers and operational readiness."""
    client, _ = authenticated_client
    resp = client.get("/api/providers")
    assert resp.status_code == 200
    providers = resp.json()["providers"]
    assert isinstance(providers, list)
    assert any(p["provider"] == "telegram" for p in providers)


def test_heartbeat_status_endpoint(authenticated_client: Tuple[TestClient, str]) -> None:
    """Heartbeat endpoint returns host monitoring configuration and state."""
    client, _ = authenticated_client
    resp = client.get("/api/heartbeat")
    assert resp.status_code == 200
    hb = resp.json()["heartbeat"]
    assert "configured" in hb
    assert "task_installed" in hb


def test_coordinator_placeholder_contract(authenticated_client: Tuple[TestClient, str]) -> None:
    """Coordinator adapter adheres to Phase 05 contract."""
    client, _ = authenticated_client
    resp = client.get("/api/coordinator")
    assert resp.status_code == 200
    coord = resp.json()
    assert coord["ok"] is True
    assert coord["status"] in ("unconnected", "unmonitored")
    assert coord["available"] is False
    assert coord["recovery_required"] == "unknown"
    assert coord["inhibition_active"] == "unknown"
    assert "contract_capabilities" in coord


def test_coordinator_endpoint_with_active_recovery(
    authenticated_client: Tuple[TestClient, str],
    test_config: RemoteControlConfig,
) -> None:
    """Coordinator reports active recovery and inhibition from observation."""
    import json
    with sqlite3.connect(test_config.notifications_db_path) as conn:
        conn.execute(
            """
            INSERT INTO rc_observations (
                observed_at, status, contract_version, has_recovery_contract,
                recovery_required, inhibition_active, inhibition_reason,
                journal_status, miner_state, error_message, details_json
            ) VALUES (
                '2026-11-11T12:00:00Z', 'available', 'v1', 1,
                1, 1, 'model load timeout on miner-1',
                'available', 'inhibited', NULL, ?
            )
            """,
            (json.dumps({"test": True}),),
        )

    client, _ = authenticated_client
    resp = client.get("/api/coordinator")
    assert resp.status_code == 200
    coord = resp.json()
    assert coord["ok"] is True
    assert coord["status"] == "available"
    assert coord["available"] is True
    assert coord["recovery_required"] is True
    assert coord["inhibition_active"] is True
    assert coord["inhibition_reason"] == "model load timeout on miner-1"
    assert coord["contract_capabilities"]["has_recovery_contract"] is True


def test_coordinator_endpoint_preserves_uncertainty_when_unavailable(
    authenticated_client: Tuple[TestClient, str],
    test_config: RemoteControlConfig,
) -> None:
    """When coordinator is unavailable, recovery and inhibition must remain 'unknown'."""
    with sqlite3.connect(test_config.notifications_db_path) as conn:
        conn.execute(
            """
            INSERT INTO rc_observations (
                observed_at, status, contract_version, has_recovery_contract,
                recovery_required, inhibition_active, inhibition_reason,
                journal_status, miner_state, error_message, details_json
            ) VALUES (
                '2026-11-11T12:05:00Z', 'unavailable', 'v1', 1,
                NULL, NULL, NULL,
                'unknown', 'unknown', 'Connection refused', '{}'
            )
            """
        )

    client, _ = authenticated_client
    resp = client.get("/api/coordinator")
    assert resp.status_code == 200
    coord = resp.json()
    assert coord["ok"] is True
    assert coord["status"] == "unavailable"
    assert coord["available"] is False
    assert coord["recovery_required"] == "unknown"
    assert coord["inhibition_active"] == "unknown"


def test_graceful_degradation_when_notifications_db_missing(tmp_path: Path) -> None:
    """If notifications DB does not exist, adapter degrades cleanly without crashing."""
    adapter = ReadOnlyNotificationsAdapter(tmp_path / "nonexistent.db")

    summary = adapter.get_summary()
    assert summary["ok"] is True
    assert summary["available"] is False
    assert summary["total_incidents"] == 0

    incidents = adapter.list_incidents()
    assert incidents["available"] is False
    assert incidents["items"] == []

    detail = adapter.get_incident("inc-001")
    assert detail is None

    notifs = adapter.list_recent_notifications()
    assert notifs == []
