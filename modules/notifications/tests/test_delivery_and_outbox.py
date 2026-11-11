"""Tests for DeliveryProvider abstraction, FakeProvider, and OutboxWorker."""

import pytest
import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

from notifications.models import EventEnvelopeV1
from notifications.storage import StorageEngine
from notifications.lifecycle import IncidentLifecycleEngine
from notifications.delivery.fake import FakeProvider
from notifications.outbox import OutboxWorker


def make_event(summary: str = "Outbox test failure") -> EventEnvelopeV1:
    return EventEnvelopeV1(
        schema_version=1,
        event_id=str(uuid.uuid4()),
        source="test_source",
        kind="test.kind",
        incident_key="test:key",
        severity="critical",
        occurred_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        summary=summary,
        lifecycle="open",
    )


@pytest.mark.asyncio
async def test_outbox_successful_delivery(tmp_path: Path):
    db_path = tmp_path / "outbox.db"
    storage = StorageEngine(db_path)
    storage.migrate()
    lifecycle = IncidentLifecycleEngine(storage)

    fake_provider = FakeProvider(provider_id="fake_provider", mode="success")
    worker = OutboxWorker(storage, providers={"fake_provider": fake_provider})

    event = make_event()
    res = lifecycle.process_event(event, providers=["fake_provider"])
    assert res.outbox_queued is True

    # Process outbox
    processed = await worker.process_pending_once()
    assert processed == 1
    assert len(fake_provider.sent_notifications) == 1
    assert fake_provider.sent_notifications[0].event_id == event.event_id

    # Item in DB transitioned to 'provider_accepted'
    items = storage.list_pending_outbox()
    assert len(items) == 0

    attempts = storage.list_delivery_attempts(1)
    assert len(attempts) == 1
    assert attempts[0].status == "provider_accepted"


@pytest.mark.asyncio
async def test_outbox_retryable_backoff(tmp_path: Path):
    db_path = tmp_path / "outbox.db"
    storage = StorageEngine(db_path)
    storage.migrate()
    lifecycle = IncidentLifecycleEngine(storage)

    fake_provider = FakeProvider(provider_id="fake_provider", mode="retryable_error")
    worker = OutboxWorker(storage, providers={"fake_provider": fake_provider})

    event = make_event()
    lifecycle.process_event(event, providers=["fake_provider"])

    # First attempt: fails with retryable error
    processed = await worker.process_pending_once()
    assert processed == 1

    item = storage.get_outbox_item(1)
    assert item is not None
    assert item.status == "retryable_error"
    assert item.retry_count == 1

    attempts = storage.list_delivery_attempts(1)
    assert len(attempts) == 1
    assert attempts[0].status == "retryable_error"


@pytest.mark.asyncio
async def test_outbox_terminal_error_exhaustion(tmp_path: Path):
    db_path = tmp_path / "outbox.db"
    storage = StorageEngine(db_path)
    storage.migrate()
    lifecycle = IncidentLifecycleEngine(storage)

    fake_provider = FakeProvider(provider_id="fake_provider", mode="terminal_error")
    worker = OutboxWorker(storage, providers={"fake_provider": fake_provider})

    event = make_event()
    lifecycle.process_event(event, providers=["fake_provider"])

    processed = await worker.process_pending_once()
    assert processed == 1

    item = storage.get_outbox_item(1)
    assert item is not None
    assert item.status == "terminal_error"
