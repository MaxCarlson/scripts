"""Pytest fixtures for remote_control module tests."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Generator, Tuple

import pyotp
import pytest
from fastapi.testclient import TestClient

from notifications.storage import SCHEMA_VERSION_1_SQL, SCHEMA_VERSION_2_SQL
from remote_control.app import create_app
from remote_control.auth.service import AuthService
from remote_control.auth.storage import AuthStorage
from remote_control.config import RemoteControlConfig


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def test_config(tmp_path: Path) -> RemoteControlConfig:
    auth_db = tmp_path / "auth.db"
    notif_db = tmp_path / "notifications.db"
    hc_cfg = tmp_path / "healthchecks.json"
    return RemoteControlConfig(
        host="127.0.0.1",
        port=8443,
        auth_db_path=auth_db,
        notifications_db_path=notif_db,
        healthchecks_config_path=hc_cfg,
        cookie_secure=False,  # Allow HTTP in tests
        cookie_samesite="lax",
        allowed_hosts=["127.0.0.1", "localhost", "testserver"],
    )


@pytest.fixture
def auth_storage(test_config: RemoteControlConfig) -> AuthStorage:
    return AuthStorage(test_config.auth_db_path)


@pytest.fixture
def auth_service(auth_storage: AuthStorage, test_config: RemoteControlConfig) -> AuthService:
    return AuthService(auth_storage, test_config)


@pytest.fixture
def bootstrapped_operator(auth_service: AuthService) -> Tuple[Any, str, str]:
    """Bootstrap a test operator with known credentials."""
    username = "admin"
    password = "SuperSecretPassword123!"
    op, totp_secret, uri = auth_service.bootstrap(username=username, password=password)
    return op, totp_secret, password


@pytest.fixture
def seeded_notifications_db(test_config: RemoteControlConfig) -> Path:
    """Create and seed a notifications SQLite database matching notifications.storage schema."""
    db_path = test_config.notifications_db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_VERSION_1_SQL)
        conn.executescript(SCHEMA_VERSION_2_SQL)
        now_iso = "2026-11-11T12:00:00Z"

        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (1, ?)",
            (now_iso,),
        )
        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (2, ?)",
            (now_iso,),
        )

        # Seed sample event
        conn.execute(
            """
            INSERT INTO events (
                event_id, schema_version, source, kind, incident_key, severity,
                lifecycle, occurred_at, received_at, summary, correlation_id,
                resource, details_ref, labels_json, payload_json, payload_sha256
            ) VALUES (
                'evt-001', 1, 'system_monitor', 'disk_full', 'disk_c_alert', 'critical',
                'active', ?, ?, 'Disk C space critically low', 'corr-1',
                'C:', NULL, '{}', '{"free_gb": 1.2}', 'sha256-dummy'
            )
            """,
            (now_iso, now_iso),
        )

        # Seed sample open incident
        conn.execute(
            """
            INSERT INTO incidents (
                incident_id, source, incident_key, active_occurrence_id,
                status, severity, summary, first_seen, last_seen,
                acknowledged_at, resolved_at, last_notified_at, occurrence_count
            ) VALUES (
                'inc-001', 'system_monitor', 'disk_c_alert', 'occ-001',
                'open', 'critical', 'Disk C space critically low', ?, ?,
                NULL, NULL, ?, 1
            )
            """,
            (now_iso, now_iso, now_iso),
        )

        # Seed sample occurrence
        conn.execute(
            """
            INSERT INTO occurrences (
                occurrence_id, incident_id, status, severity, opened_at, closed_at, resolution_evidence
            ) VALUES (
                'occ-001', 'inc-001', 'open', 'critical', ?, NULL, NULL
            )
            """,
            (now_iso,),
        )

        # Seed sample transition
        conn.execute(
            """
            INSERT INTO transitions (
                incident_id, occurrence_id, event_id, from_status, to_status,
                transition_name, timestamp, details_json
            ) VALUES (
                'inc-001', 'occ-001', 'evt-001', NULL, 'open',
                'open_incident', ?, '{"reason": "threshold_breach"}'
            )
            """,
            (now_iso,),
        )

        # Seed sample outbox item
        conn.execute(
            """
            INSERT INTO outbox (
                outbox_id, event_id, incident_id, provider_id, status,
                retry_count, max_retries, next_retry_at, created_at, updated_at, error_message
            ) VALUES (
                1, 'evt-001', 'inc-001', 'telegram', 'pending',
                0, 5, ?, ?, ?, NULL
            )
            """,
            (now_iso, now_iso, now_iso),
        )

        # Seed sample delivery attempt
        conn.execute(
            """
            INSERT INTO delivery_attempts (
                attempt_id, outbox_id, attempted_at, status, provider_message_id,
                duration_ms, error_category, error_message
            ) VALUES (
                1, 1, ?, 'delivered', 'tg-msg-999', 120, NULL, NULL
            )
            """,
            (now_iso,),
        )

        # Seed a second resolved incident
        conn.execute(
            """
            INSERT INTO incidents (
                incident_id, source, incident_key, active_occurrence_id,
                status, severity, summary, first_seen, last_seen,
                acknowledged_at, resolved_at, last_notified_at, occurrence_count
            ) VALUES (
                'inc-002', 'heartbeat', 'host_offline', 'occ-002',
                'resolved', 'high', 'Host ping recovered', ?, ?,
                NULL, ?, ?, 2
            )
            """,
            (now_iso, now_iso, now_iso, now_iso),
        )

        conn.commit()

    return db_path


@pytest.fixture
def app(test_config: RemoteControlConfig, seeded_notifications_db: Path) -> Any:
    return create_app(test_config)


@pytest.fixture
def client(app: Any) -> Generator[TestClient, None, None]:
    with TestClient(app, base_url="http://127.0.0.1:8443") as c:
        yield c


@pytest.fixture
def authenticated_client(
    client: TestClient,
    bootstrapped_operator: Tuple[Any, str, str],
) -> Tuple[TestClient, str]:
    """Logs in and returns (TestClient, csrf_token)."""
    op, totp_secret, password = bootstrapped_operator
    totp = pyotp.TOTP(totp_secret)
    code = totp.now()

    resp = client.post(
        "/api/auth/login",
        json={
            "username": op.username,
            "password": password,
            "totp_code": code,
            "device_id": "test-device-uuid-1",
            "device_name": "Test iPhone 16",
        },
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    csrf_token = resp.json()["csrf_token"]
    return client, csrf_token
