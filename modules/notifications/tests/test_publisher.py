"""Tests for in-process Publisher API."""

import pytest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from notifications.models import EventEnvelopeV1
from notifications.storage import StorageEngine
from notifications.lifecycle import IncidentLifecycleEngine
from notifications.publisher import Publisher


def test_publisher_publish(tmp_path: Path):
    db_path = tmp_path / "pub.db"
    storage = StorageEngine(db_path)
    storage.migrate()
    lifecycle = IncidentLifecycleEngine(storage)
    publisher = Publisher(storage, lifecycle=lifecycle, default_providers=["fake_provider"])

    event = EventEnvelopeV1(
        schema_version=1,
        event_id=str(uuid.uuid4()),
        source="demo_module",
        kind="demo.task_failed",
        incident_key="demo:task_failed:job-42",
        severity="warning",
        occurred_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        summary="Demo job 42 failed",
        lifecycle="open",
    )

    res = publisher.publish(event)
    assert res.accepted is True
    assert res.transition == "opened"
    assert res.outbox_queued is True

    # Verify incident created
    incident = storage.get_incident(res.incident_id)
    assert incident is not None
    assert incident.summary == "Demo job 42 failed"
    assert incident.status == "open"


def test_publisher_create_and_publish_convenience(tmp_path: Path):
    db_path = tmp_path / "pub2.db"
    storage = StorageEngine(db_path)
    storage.migrate()
    publisher = Publisher(storage, default_providers=["fake_provider"])

    res = publisher.create_and_publish(
        source="demo_module",
        kind="demo.heartbeat_missed",
        incident_key="demo:heartbeat",
        severity="critical",
        summary="Heartbeat was missed by demo module",
        lifecycle="open",
    )
    assert res.accepted is True
    assert res.transition == "opened"
