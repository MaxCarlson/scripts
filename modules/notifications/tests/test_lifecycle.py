"""Tests for Incident Lifecycle State Machine, Deduplication, and Cooldown (N03, N04)."""

import pytest
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

from notifications.models import EventEnvelopeV1
from notifications.storage import StorageEngine
from notifications.lifecycle import IncidentLifecycleEngine, IncidentPolicy


def make_event(
    event_id: str | None = None,
    lifecycle: str = "open",
    severity: str = "critical",
    summary: str = "GPU Inference Stalled",
    incident_key: str = "gpu.inference:stall",
    occurred_at: str | None = None,
) -> EventEnvelopeV1:
    return EventEnvelopeV1(
        schema_version=1,
        event_id=event_id or str(uuid.uuid4()),
        source="resource_coordinator",
        kind="miner.recovery_required",
        incident_key=incident_key,
        severity=severity,
        occurred_at=occurred_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        summary=summary,
        lifecycle=lifecycle,
    )


def test_incident_lifecycle_flow(tmp_path: Path):
    """N03: open -> update -> acknowledge -> verified resolve -> new occurrence on reopen."""
    db_path = tmp_path / "lifecycle.db"
    storage = StorageEngine(db_path)
    storage.migrate()
    lifecycle = IncidentLifecycleEngine(storage, policy=IncidentPolicy(cooldown_seconds=60.0))

    # 1. Open new incident
    e1 = make_event(lifecycle="open", summary="Initial failure")
    res1 = lifecycle.process_event(e1, providers=["fake_provider"])
    assert res1.accepted is True
    assert res1.transition == "opened"
    assert res1.outbox_queued is True

    inc1 = storage.get_incident(res1.incident_id)
    assert inc1 is not None
    assert inc1.status == "open"
    assert inc1.occurrence_count == 1
    first_occ_id = inc1.active_occurrence_id
    assert first_occ_id is not None

    # Check outbox queued
    pending = storage.list_pending_outbox()
    assert len(pending) == 1
    assert pending[0].event_id == e1.event_id

    # 2. Update within cooldown: does not queue another notification
    e2 = make_event(lifecycle="update", summary="Ongoing failure observation")
    res2 = lifecycle.process_event(e2, providers=["fake_provider"])
    assert res2.accepted is True
    assert res2.transition == "updated"
    assert res2.outbox_queued is False  # Suppressed by cooldown
    assert len(storage.list_pending_outbox()) == 1  # Still 1

    # 3. Acknowledge: status becomes acknowledged, active occurrence remains open
    e3 = make_event(lifecycle="acknowledge", summary="Operator reviewing issue")
    res3 = lifecycle.process_event(e3, providers=["fake_provider"])
    assert res3.accepted is True
    assert res3.transition == "acknowledged"

    inc3 = storage.get_incident(res3.incident_id)
    assert inc3.status == "acknowledged"
    assert inc3.acknowledged_at is not None
    assert inc3.resolved_at is None  # CRITICAL: Acknowledge is NOT resolve!
    assert inc3.active_occurrence_id == first_occ_id

    # 4. Resolve: closes occurrence, status becomes resolved
    e4 = make_event(lifecycle="resolve", summary="Verified recovered by source check")
    res4 = lifecycle.process_event(e4, providers=["fake_provider"])
    assert res4.accepted is True
    assert res4.transition == "resolved"

    inc4 = storage.get_incident(res4.incident_id)
    assert inc4.status == "resolved"
    assert inc4.resolved_at is not None

    occ4 = storage.get_occurrence(first_occ_id)
    assert occ4.status == "resolved"
    assert occ4.closed_at is not None

    # 5. Subsequent open after resolution: creates a NEW occurrence
    e5 = make_event(lifecycle="open", summary="Recurrence after verified fix")
    res5 = lifecycle.process_event(e5, providers=["fake_provider"])
    assert res5.accepted is True
    assert res5.transition == "opened"
    assert res5.occurrence_id != first_occ_id  # NEW occurrence ID!

    inc5 = storage.get_incident(res5.incident_id)
    assert inc5.status == "open"
    assert inc5.occurrence_count == 2
    assert inc5.acknowledged_at is None  # Fresh occurrence does NOT inherit previous ack!
    assert inc5.resolved_at is None


def test_burst_deduplication_and_cooldown(tmp_path: Path):
    """N04: 1,000 repeated events produce bounded provider tasks with stable incident state."""
    db_path = tmp_path / "burst.db"
    storage = StorageEngine(db_path)
    storage.migrate()
    lifecycle = IncidentLifecycleEngine(storage, policy=IncidentPolicy(cooldown_seconds=300.0))

    # Send 1,000 events in rapid succession for the same incident key
    key = "burst:miner:failure"
    queued_count = 0
    for i in range(1000):
        e = make_event(
            lifecycle="open" if i == 0 else "update",
            summary=f"Burst failure iteration {i}",
            incident_key=key,
        )
        res = lifecycle.process_event(e, providers=["fake_provider"])
        assert res.accepted is True
        if res.outbox_queued:
            queued_count += 1

    # Exactly 1 outbox notification was queued for 1,000 events
    assert queued_count == 1
    pending = storage.list_pending_outbox()
    assert len(pending) == 1

    # Incident state remains stable and reflects last observation
    inc = storage.get_incident(res.incident_id)
    assert inc is not None
    assert inc.status == "open"
    assert inc.occurrence_count == 1
    assert "Burst failure iteration 999" in inc.summary
