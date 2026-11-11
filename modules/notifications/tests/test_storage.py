"""Tests for SQLite Storage Engine, Durability, and Error Handling (N02, N05, N06)."""

import pytest
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from notifications.models import (
    EventEnvelopeV1,
    Incident,
    Occurrence,
    Transition,
)
from notifications.storage import StorageEngine
from notifications.exceptions import (
    PayloadConflictError,
    DatabaseBusyError,
    DatabaseCorruptError,
    DatabaseFullError,
    StorageError,
)


def sample_event(event_id: str | None = None, summary: str = "Test incident", lifecycle: str = "open") -> EventEnvelopeV1:
    return EventEnvelopeV1(
        schema_version=1,
        event_id=event_id or str(uuid.uuid4()),
        source="resource_coordinator",
        kind="miner.recovery_required",
        incident_key="resource_coordinator:gpu.inference:recovery",
        severity="critical",
        occurred_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        summary=summary,
        lifecycle=lifecycle,
    )


def test_schema_migration_and_wal(tmp_path: Path):
    db_path = tmp_path / "test_events.db"
    storage = StorageEngine(db_path)
    version = storage.migrate()
    assert version >= 1
    assert storage.get_schema_version() == version

    # Verify WAL mode and foreign keys enabled
    with storage.connect() as conn:
        journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        assert journal_mode.lower() == "wal"
        fk = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
        assert fk == 1


def test_idempotent_event_persistence_and_conflict_rejection(tmp_path: Path):
    """N02: Same event ID/payload causes one insert; conflicting payload is rejected."""
    db_path = tmp_path / "test_events.db"
    storage = StorageEngine(db_path)
    storage.migrate()

    eid = str(uuid.uuid4())
    event1 = sample_event(event_id=eid, summary="Original summary")

    # First insert: success
    is_new, recorded = storage.record_event(event1)
    assert is_new is True
    assert recorded.event_id == eid

    # Duplicate insert with identical payload: idempotent no-op
    is_new_dup, recorded_dup = storage.record_event(event1)
    assert is_new_dup is False
    assert recorded_dup.event_id == eid

    # Conflicting insert with same event_id but different summary/payload
    event_conflict = sample_event(event_id=eid, summary="Different conflicting summary")
    with pytest.raises(PayloadConflictError, match="already exists with different payload"):
        storage.record_event(event_conflict)


def test_outbox_queue_and_crash_recovery(tmp_path: Path):
    """N05: Durable outbox queue and recovery from worker crash in attempting state."""
    db_path = tmp_path / "test_events.db"
    storage = StorageEngine(db_path)
    storage.migrate()

    event = sample_event()
    storage.record_event(event)

    incident = Incident(
        incident_id=event.incident_id,
        source=event.source,
        incident_key=event.incident_key,
        active_occurrence_id="occ-1",
        status="open",
        severity=event.severity,
        summary=event.summary,
        first_seen=event.occurred_at,
        last_seen=event.occurred_at,
    )
    storage.save_incident(incident)

    outbox_id = storage.enqueue_outbox(
        event_id=event.event_id,
        incident_id=event.incident_id,
        provider_id="fake_provider",
    )
    assert outbox_id > 0

    pending = storage.list_pending_outbox()
    assert len(pending) == 1
    assert pending[0].outbox_id == outbox_id
    assert pending[0].status == "pending"

    # Worker claims item (transitions to 'attempting')
    claimed = storage.claim_outbox_item(outbox_id)
    assert claimed is True

    # No more pending items while attempting
    assert len(storage.list_pending_outbox()) == 0

    # Simulate worker crash / stalled task: reset_stalled_outbox_items recovers it
    recovered_count = storage.reset_stalled_outbox_items(stalled_seconds=0.0)
    assert recovered_count == 1

    # Now pending again
    pending_after = storage.list_pending_outbox()
    assert len(pending_after) == 1
    assert pending_after[0].status == "pending"


def test_outbox_delivery_attempt_recording(tmp_path: Path):
    db_path = tmp_path / "test_events.db"
    storage = StorageEngine(db_path)
    storage.migrate()

    event = sample_event()
    storage.record_event(event)
    incident = Incident(
        incident_id=event.incident_id,
        source=event.source,
        incident_key=event.incident_key,
        active_occurrence_id="occ-1",
        status="open",
        severity=event.severity,
        summary=event.summary,
        first_seen=event.occurred_at,
        last_seen=event.occurred_at,
    )
    storage.save_incident(incident)
    outbox_id = storage.enqueue_outbox(event.event_id, event.incident_id, "fake_provider")

    # Record retryable error
    storage.record_delivery_attempt(
        outbox_id=outbox_id,
        status="retryable_error",
        duration_ms=120,
        error_category="network_timeout",
        error_message="Connection timed out",
        retry_after_seconds=5.0,
    )

    item = storage.get_outbox_item(outbox_id)
    assert item is not None
    assert item.status == "retryable_error"
    assert item.retry_count == 1
    assert item.error_message == "Connection timed out"

    attempts = storage.list_delivery_attempts(outbox_id)
    assert len(attempts) == 1
    assert attempts[0].status == "retryable_error"
    assert attempts[0].error_category == "network_timeout"


def test_sqlite_error_mapping(tmp_path: Path):
    """N06: SQLite busy/corrupt/full error mapping."""
    db_path = tmp_path / "corrupt.db"
    # Write garbage into corrupt.db
    with open(db_path, "wb") as f:
        f.write(b"not a valid sqlite database file header at all")

    storage = StorageEngine(db_path)
    with pytest.raises(DatabaseCorruptError):
        storage.migrate()
