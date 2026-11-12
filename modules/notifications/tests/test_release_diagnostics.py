"""
Tests for unified read-only release diagnostics.
Ensures zero mutation, strict read-only SQLite mode, and complete reporting.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from notifications.diagnostics import collect_release_diagnostics
from notifications.storage import StorageEngine
from notifications.models import EventEnvelopeV1
from notifications.publisher import Publisher


def test_release_diagnostics_uninitialized(tmp_path):
    """Diagnostics on uninitialized paths must report clean not_created status without throwing."""
    db_path = tmp_path / "nonexistent" / "events.db"
    auth_db_path = tmp_path / "nonexistent" / "auth.db"

    data = collect_release_diagnostics(db_path=db_path, auth_db_path=auth_db_path, probe_ports=False)
    assert data["ok"] is True
    assert data["storage"]["status"] == "not_created"
    assert data["remote_control"]["status"] == "not_created"
    assert "acceptance_gates_pending" in data
    assert "RC_recovery" in data["acceptance_gates_pending"]


def test_release_diagnostics_with_active_data(tmp_path):
    """Diagnostics must report accurate counts and maintain mode=ro read-only status."""
    db_path = tmp_path / "events.db"
    storage = StorageEngine(db_path=db_path)
    storage.migrate()

    pub = Publisher(storage=storage, default_providers=["fake_provider"])
    # Emit an open event
    pub.create_and_publish(
        source="scheduler",
        kind="task_result",
        incident_key="task:1",
        severity="critical",
        summary="Test failure",
        lifecycle="open",
    )

    data = collect_release_diagnostics(db_path=db_path, auth_db_path=tmp_path / "auth.db", probe_ports=False)
    assert data["ok"] is True
    assert data["storage"]["status"] == "healthy"
    assert data["storage"]["open_incidents"] == 1
    assert data["storage"]["pending_outbox"] == 1


def test_release_diagnostics_cli_output(tmp_path):
    """CLI subcommand release-check must support --json and human-readable output."""
    from notifications.cli import main
    import io
    import sys

    db_path = tmp_path / "events.db"
    storage = StorageEngine(db_path=db_path)
    storage.migrate()

    old_stdout = sys.stdout
    sys.stdout = buffer = io.StringIO()
    try:
        ret = main(["release-check", "-j", "-d", str(db_path)])
        assert ret == 0
        output = buffer.getvalue()
        parsed = json.loads(output)
        assert parsed["ok"] is True
        assert parsed["storage"]["status"] == "healthy"
    finally:
        sys.stdout = old_stdout


def test_release_diagnostics_with_action_barriers(tmp_path):
    """Diagnostics must correctly query actual Remote Control action_resource_barriers schema."""
    import sqlite3

    db_path = tmp_path / "events.db"
    storage = StorageEngine(db_path=db_path)
    storage.migrate()

    # Create real Remote Control auth DB with action_resource_barriers schema
    auth_db = tmp_path / "auth.db"
    with sqlite3.connect(auth_db) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS operators (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                totp_secret TEXT
            );
        """)
        conn.execute("INSERT INTO operators VALUES ('admin', 'hash123', 'JBSWY3DPEHPK3PXP');")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS action_resource_barriers (
                resource_key TEXT PRIMARY KEY,
                execution_id TEXT NOT NULL,
                barrier_status TEXT NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL,
                cleared_at TEXT,
                cleared_by TEXT,
                evidence TEXT
            );
        """)
        conn.execute("""
            INSERT INTO action_resource_barriers (resource_key, execution_id, barrier_status, reason, created_at, cleared_at)
            VALUES ('resource_coordinator:recovery', 'exec_001', 'active', 'Ambiguous recovery timeout', '2026-11-11T12:00:00Z', NULL);
        """)
        conn.commit()

    data = collect_release_diagnostics(db_path=db_path, auth_db_path=auth_db, probe_ports=False)
    assert data["ok"] is True
    assert data["ready_for_release"] is False  # Active barrier blocks release
    rc = data["remote_control"]
    assert rc["status"] == "action_barrier_active"
    assert rc["operator_enrolled"] is True
    assert rc["totp_enrolled"] is True
    assert len(rc["active_barriers"]) == 1
    barrier = rc["active_barriers"][0]
    assert barrier["resource_key"] == "resource_coordinator:recovery"
    assert barrier["execution_id"] == "exec_001"
    assert barrier["reason"] == "Ambiguous recovery timeout"
    assert len(data["blockers"]) >= 1
    assert any("resource_coordinator:recovery" in b for b in data["blockers"])


def test_release_diagnostics_outbox_status_categories(tmp_path):
    """Diagnostics must count actual outbox statuses (pending, attempting, accepted, retryable, terminal)."""
    import sqlite3

    db_path = tmp_path / "events.db"
    storage = StorageEngine(db_path=db_path)
    storage.migrate()

    pub = Publisher(storage=storage, default_providers=["fake_provider"])
    res = pub.create_and_publish(
        source="scheduler",
        kind="task_result",
        incident_key="test:1",
        severity="info",
        summary="Test event",
        lifecycle="open",
    )

    # Insert items directly into outbox with various statuses
    with sqlite3.connect(db_path) as conn:
        # Clear outbox from initial publish
        conn.execute("DELETE FROM outbox;")
        # Insert outbox items
        conn.execute("INSERT INTO outbox (event_id, incident_id, provider_id, status, retry_count, max_retries, next_retry_at, created_at, updated_at) VALUES (?, ?, 'tg', 'pending', 0, 5, '2026', '2026', '2026');", (res.event_id, res.incident_id))
        conn.execute("INSERT INTO outbox (event_id, incident_id, provider_id, status, retry_count, max_retries, next_retry_at, created_at, updated_at) VALUES (?, ?, 'win', 'attempting', 1, 5, '2026', '2026', '2026');", (res.event_id, res.incident_id))
        conn.execute("INSERT INTO outbox (event_id, incident_id, provider_id, status, retry_count, max_retries, next_retry_at, created_at, updated_at) VALUES (?, ?, 'tg', 'provider_accepted', 1, 5, '2026', '2026', '2026');", (res.event_id, res.incident_id))
        conn.execute("INSERT INTO outbox (event_id, incident_id, provider_id, status, retry_count, max_retries, next_retry_at, created_at, updated_at) VALUES (?, ?, 'win', 'retryable_error', 2, 5, '2026', '2026', '2026');", (res.event_id, res.incident_id))
        conn.execute("INSERT INTO outbox (event_id, incident_id, provider_id, status, retry_count, max_retries, next_retry_at, created_at, updated_at) VALUES (?, ?, 'tg', 'terminal_error', 5, 5, '2026', '2026', '2026');", (res.event_id, res.incident_id))
        conn.commit()

    data = collect_release_diagnostics(db_path=db_path, auth_db_path=tmp_path / "auth.db", probe_ports=False)
    st = data["storage"]
    assert st["status"] == "healthy"
    assert st["pending_outbox"] == 1
    assert st["attempting_outbox"] == 1
    assert st["accepted_outbox"] == 1
    assert st["retryable_outbox"] == 1
    assert st["terminal_outbox"] == 1
    assert any("terminal error" in w for w in data["warnings"])


def test_release_diagnostics_secrets_redacted_and_paths(tmp_path, monkeypatch):
    """Diagnostics must use canonical secrets paths and never leak raw secrets."""
    # Set telegram env vars
    monkeypatch.setenv("NOTIFY_TELEGRAM_BOT_TOKEN", "123456789:ABCDEF_secret_token_value_xyz")
    monkeypatch.setenv("NOTIFY_TELEGRAM_CHAT_ID", "987654321")
    monkeypatch.setenv("NOTIFY_HEALTHCHECKS_PING_URL", "https://hc-ping.com/11223344-5566-7788-99aa-bbccddeeff00")

    db_path = tmp_path / "events.db"
    storage = StorageEngine(db_path=db_path)
    storage.migrate()

    data = collect_release_diagnostics(db_path=db_path, auth_db_path=tmp_path / "auth.db", probe_ports=False)
    raw_json = json.dumps(data)

    # Assert secret tokens are NEVER present in JSON
    assert "ABCDEF_secret_token_value_xyz" not in raw_json
    assert "11223344-5566-7788-99aa-bbccddeeff00" not in raw_json
    # Masked chat ID is present
    assert data["providers"]["telegram"]["owner_chat_id"] == "987***321"
    assert data["providers"]["telegram"]["token_enrolled"] is True
    assert data["providers"]["healthchecks"]["ping_url_configured"] is True


def test_release_diagnostics_strict_read_only_invariance(tmp_path):
    """Diagnostics must not create or modify files or databases."""
    db_path = tmp_path / "uninitialized_events.db"
    auth_db_path = tmp_path / "uninitialized_auth.db"

    assert not db_path.exists()
    assert not auth_db_path.exists()

    data = collect_release_diagnostics(db_path=db_path, auth_db_path=auth_db_path, probe_ports=False)
    assert data["ok"] is True
    assert not db_path.exists(), "Diagnostics must never create missing database files"
    assert not auth_db_path.exists(), "Diagnostics must never create missing auth files"

