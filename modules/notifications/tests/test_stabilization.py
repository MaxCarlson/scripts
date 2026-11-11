"""Regression tests for Phase 01 stabilization and security hardening."""

from __future__ import annotations

import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from notifications.cli import main
from notifications.config import _secure_path, load_or_create_token
from notifications.exceptions import (
    IncidentNotFoundError,
    InvalidTransitionError,
    PayloadConflictError,
    SecurityError,
)
from notifications.ingest import create_ingest_app
from notifications.lifecycle import IncidentLifecycleEngine
from notifications.models import EventEnvelopeV1
from notifications.storage import StorageEngine


def _make_event(
    event_id: str | None = None,
    incident_key: str = "disk.root.full",
    lifecycle: str = "open",
    severity: str = "critical",
    summary: str = "Root disk usage exceeded 95%",
) -> EventEnvelopeV1:
    eid = event_id or str(uuid.uuid4())
    return EventEnvelopeV1(
        event_id=eid,
        schema_version=1,
        source="system_monitor",
        kind="system.disk.full",
        incident_key=incident_key,
        severity=severity,
        lifecycle=lifecycle,
        occurred_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        summary=summary,
    )


def test_end_to_end_event_idempotency(tmp_path: Path) -> None:
    db = tmp_path / "events.db"
    storage = StorageEngine(db)
    storage.migrate()
    engine = IncidentLifecycleEngine(storage)

    eid = str(uuid.uuid4())
    event = _make_event(event_id=eid)

    # First publication: creates incident, transitions, and outbox item
    res1 = engine.process_event(event)
    assert res1.accepted is True
    assert res1.transition == "opened"
    assert res1.outbox_queued is True

    assert len(storage.list_transitions(res1.incident_id)) == 1
    assert len(storage.list_pending_outbox()) == 1

    # Replaying the exact same event: must be a no-op duplicate
    res2 = engine.process_event(event)
    assert res2.accepted is True
    assert res2.transition == "duplicate"
    assert res2.outbox_queued is False

    # Verify no additional side effects
    assert len(storage.list_transitions(res1.incident_id)) == 1
    assert len(storage.list_pending_outbox()) == 1

    # Submitting duplicate event_id with CONFLICTING payload must be rejected
    conflicting_event = _make_event(event_id=eid, summary="Different summary content")
    with pytest.raises(PayloadConflictError):
        engine.process_event(conflicting_event)


def test_authoritative_acknowledgement_lifecycle(tmp_path: Path) -> None:
    db = tmp_path / "events.db"
    storage = StorageEngine(db)
    storage.migrate()
    engine = IncidentLifecycleEngine(storage)

    event = _make_event(incident_key="svc.unhealthy")
    res = engine.process_event(event)

    # Acknowledge the incident
    ack_incident = engine.acknowledge_incident(
        incident_id=res.incident_id,
        actor="oncall_operator",
        reason="Investigating alert",
    )
    assert ack_incident.status == "acknowledged"
    assert ack_incident.acknowledged_at is not None

    # Verify active occurrence is also updated
    occ = storage.get_occurrence(ack_incident.active_occurrence_id)
    assert occ is not None
    assert occ.status == "acknowledged"

    # Verify transition audit record was appended
    transitions = storage.list_transitions(res.incident_id)
    assert len(transitions) == 2
    assert transitions[-1].to_status == "acknowledged"
    assert transitions[-1].transition_name == "acknowledged"

    # Repeated acknowledgement must be idempotent
    re_ack = engine.acknowledge_incident(
        incident_id=res.incident_id,
        actor="oncall_operator",
        reason="Repeated click",
    )
    assert re_ack.status == "acknowledged"
    assert re_ack.acknowledged_at == ack_incident.acknowledged_at
    # No duplicate transition appended
    assert len(storage.list_transitions(res.incident_id)) == 2

    # Resolve incident
    resolve_event = _make_event(
        incident_key="svc.unhealthy",
        lifecycle="resolve",
        summary="Service recovered",
    )
    res_resolve = engine.process_event(resolve_event)
    assert res_resolve.transition == "resolved"

    resolved_inc = storage.get_incident(res.incident_id)
    assert resolved_inc.status == "resolved"

    # Attempting to acknowledge a resolved incident must fail
    with pytest.raises(InvalidTransitionError):
        engine.acknowledge_incident(res.incident_id, actor="operator")

    # Nonexistent incident must raise IncidentNotFoundError
    with pytest.raises(IncidentNotFoundError):
        engine.acknowledge_incident("nonexistent-id", actor="operator")


def test_api_acknowledgement_behavior(tmp_path: Path) -> None:
    db = tmp_path / "events.db"
    storage = StorageEngine(db)
    storage.migrate()
    engine = IncidentLifecycleEngine(storage)
    app = create_ingest_app(storage, auth_token="test-secret-token", engine=engine)
    client = TestClient(app)

    event = _make_event()
    engine.process_event(event)

    # Valid acknowledgement via API updates durable state
    resp = client.post(
        f"/api/v1/incidents/{event.incident_id}/acknowledge",
        headers={"Authorization": "Bearer test-secret-token"},
        json={"reason": "Acknowledged from web", "actor": "sre_user"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["status"] == "acknowledged"
    assert data["incident"]["status"] == "acknowledged"

    # Verified in storage
    durable_inc = storage.get_incident(event.incident_id)
    assert durable_inc.status == "acknowledged"
    assert durable_inc.acknowledged_at is not None

    # Idempotent re-acknowledgement succeeds
    resp2 = client.post(
        f"/api/v1/incidents/{event.incident_id}/acknowledge",
        headers={"Authorization": "Bearer test-secret-token"},
        json={"reason": "Repeat"},
    )
    assert resp2.status_code == 200

    # Resolve incident
    resolve_event = _make_event(
        incident_key=event.incident_key,
        lifecycle="resolve",
    )
    engine.process_event(resolve_event)

    # Acknowledging resolved incident returns 409 Conflict
    resp3 = client.post(
        f"/api/v1/incidents/{event.incident_id}/acknowledge",
        headers={"Authorization": "Bearer test-secret-token"},
        json={"reason": "Too late"},
    )
    assert resp3.status_code == 409


def test_cli_acknowledgement_behavior(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "events.db"
    storage = StorageEngine(db)
    storage.migrate()
    engine = IncidentLifecycleEngine(storage)

    event = _make_event()
    engine.process_event(event)

    # Dry run does not mutate
    rc_dry = main(["--db", str(db), "incidents", "acknowledge", "--incident-id", event.incident_id, "-j"])
    assert rc_dry == 0
    captured_dry = capsys.readouterr().out
    assert "Dry-run" in captured_dry

    inc_after_dry = storage.get_incident(event.incident_id)
    assert inc_after_dry.status == "open"

    # Apply mutates state
    rc_apply = main(["--db", str(db), "incidents", "acknowledge", "--incident-id", event.incident_id, "-a", "-j"])
    assert rc_apply == 0
    captured_apply = capsys.readouterr().out
    assert '"status": "acknowledged"' in captured_apply

    inc_after_apply = storage.get_incident(event.incident_id)
    assert inc_after_apply.status == "acknowledged"
    assert inc_after_apply.acknowledged_at is not None


def test_secure_path_fails_securely(tmp_path: Path) -> None:
    test_file = tmp_path / "token.txt"
    test_file.write_text("dummy-token-for-test", "ascii")

    # Mock icacls failure
    mock_run = MagicMock(return_value=subprocess.CompletedProcess(args=[], returncode=1, stderr="Access denied mock"))
    with patch("notifications.config.os.name", "nt"), patch("notifications.config.subprocess.run", mock_run), patch("notifications.config._windows_user_sid", return_value="S-1-5-21-12345"):
        with pytest.raises(SecurityError) as exc_info:
            _secure_path(test_file)
        assert "icacls /reset failed" in str(exc_info.value)

    # Mock user SID discovery failure
    with patch("notifications.config.os.name", "nt"), patch("notifications.config._windows_user_sid", return_value=None):
        with pytest.raises(SecurityError) as exc_info:
            _secure_path(test_file)
        assert "Cannot determine Windows user SID" in str(exc_info.value)


def test_provider_test_false_success_prevention(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "events.db"
    storage = StorageEngine(db)
    storage.migrate()

    # Dry run does not deliver
    rc_dry = main(["--db", str(db), "providers", "test", "--provider", "fake_provider", "-j"])
    assert rc_dry == 0
    captured_dry = capsys.readouterr().out
    assert '"dry_run": true' in captured_dry

    # Test unknown provider fails
    rc_unknown = main(["--db", str(db), "providers", "test", "--provider", "nonexistent_provider", "-a", "-j"])
    assert rc_unknown == 1
    captured_unknown = capsys.readouterr().err
    assert "Unknown provider" in captured_unknown

    # Test unconfigured telegram provider fails with error rather than false success
    rc_unconf = main(["--db", str(db), "providers", "test", "--provider", "telegram", "-a", "-j"])
    assert rc_unconf == 1
    captured_unconf = capsys.readouterr().err
    assert "Telegram provider is not configured" in captured_unconf

    # Test fake_provider reports simulated delivery
    rc_fake = main(["--db", str(db), "providers", "test", "--provider", "fake_provider", "-a", "-j"])
    assert rc_fake == 0
    captured_fake = capsys.readouterr().out
    assert '"simulated": true' in captured_fake
    assert '"status": "provider_accepted"' in captured_fake
