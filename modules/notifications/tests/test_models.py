"""Tests for Notification Event Models and Schema Validation (N01)."""

import pytest
from datetime import datetime, timezone, timedelta
import uuid

from notifications.models import EventEnvelopeV1
from notifications.exceptions import (
    ValidationError,
    UnsupportedSchemaVersionError,
)


def valid_event_payload() -> dict:
    return {
        "schema_version": 1,
        "event_id": str(uuid.uuid4()),
        "source": "resource_coordinator",
        "kind": "miner.recovery_required",
        "incident_key": "resource_coordinator:gpu.inference:recovery",
        "severity": "critical",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "summary": "Inference recovery requires operator verification",
        "correlation_id": "req-123",
        "resource": "gpu.inference",
        "details_ref": "opaque-token-123",
        "labels": {"component": "recovery"},
        "lifecycle": "open",
    }


def test_valid_event_creation():
    payload = valid_event_payload()
    event = EventEnvelopeV1.from_dict(payload)
    assert event.schema_version == 1
    assert event.source == "resource_coordinator"
    assert event.kind == "miner.recovery_required"
    assert event.severity == "critical"
    assert event.lifecycle == "open"
    assert len(event.incident_id) == 64  # sha256 hex
    assert len(event.payload_sha256) == 64


def test_reject_unsupported_schema_version():
    payload = valid_event_payload()
    payload["schema_version"] = 2
    with pytest.raises(UnsupportedSchemaVersionError, match="Unsupported schema version: 2"):
        EventEnvelopeV1.from_dict(payload)


def test_reject_invalid_uuid():
    payload = valid_event_payload()
    payload["event_id"] = "not-a-valid-uuid"
    with pytest.raises(ValidationError, match="event_id must be a valid UUID"):
        EventEnvelopeV1.from_dict(payload)


def test_reject_invalid_source():
    payload = valid_event_payload()
    payload["source"] = "Invalid Source with Spaces!"
    with pytest.raises(ValidationError, match="source must match pattern"):
        EventEnvelopeV1.from_dict(payload)


def test_reject_invalid_kind():
    payload = valid_event_payload()
    payload["kind"] = "Invalid/Kind*Name"
    with pytest.raises(ValidationError, match="kind must match pattern"):
        EventEnvelopeV1.from_dict(payload)


def test_reject_invalid_severity():
    payload = valid_event_payload()
    payload["severity"] = "fatal"
    with pytest.raises(ValidationError, match="severity must be one of"):
        EventEnvelopeV1.from_dict(payload)


def test_reject_invalid_lifecycle():
    payload = valid_event_payload()
    payload["lifecycle"] = "destroyed"
    with pytest.raises(ValidationError, match="lifecycle must be one of"):
        EventEnvelopeV1.from_dict(payload)


def test_reject_future_timestamp():
    payload = valid_event_payload()
    future = datetime.now(timezone.utc) + timedelta(minutes=15)
    payload["occurred_at"] = future.isoformat()
    with pytest.raises(ValidationError, match="occurred_at cannot be > 5 minutes in the future"):
        EventEnvelopeV1.from_dict(payload)


def test_reject_naive_timestamp():
    payload = valid_event_payload()
    payload["occurred_at"] = "2026-11-11T12:00:00"  # no tz
    with pytest.raises(ValidationError, match="occurred_at must include explicit timezone"):
        EventEnvelopeV1.from_dict(payload)


def test_reject_oversized_summary():
    payload = valid_event_payload()
    payload["summary"] = "A" * 300
    with pytest.raises(ValidationError, match="summary must not exceed 256 characters"):
        EventEnvelopeV1.from_dict(payload)


def test_reject_empty_summary():
    payload = valid_event_payload()
    payload["summary"] = "   "
    with pytest.raises(ValidationError, match="summary must be non-empty"):
        EventEnvelopeV1.from_dict(payload)


def test_reject_control_characters_in_summary():
    payload = valid_event_payload()
    payload["summary"] = "Alert with \x00 null byte"
    with pytest.raises(ValidationError, match="summary must not contain control characters"):
        EventEnvelopeV1.from_dict(payload)


def test_reject_command_bearing_details_ref():
    payload = valid_event_payload()
    payload["details_ref"] = "powershell.exe -Command Remove-Item"
    with pytest.raises(ValidationError, match="details_ref must be an opaque reference"):
        EventEnvelopeV1.from_dict(payload)

    payload["details_ref"] = "C:\\Windows\\System32\\cmd.exe"
    with pytest.raises(ValidationError, match="details_ref must be an opaque reference"):
        EventEnvelopeV1.from_dict(payload)

    payload["details_ref"] = "https://user:pass@example.com/api"
    with pytest.raises(ValidationError, match="details_ref must be an opaque reference"):
        EventEnvelopeV1.from_dict(payload)


def test_reject_oversized_labels():
    payload = valid_event_payload()
    payload["labels"] = {f"k{i}": f"v{i}" for i in range(35)}
    with pytest.raises(ValidationError, match="labels must not contain more than 32 entries"):
        EventEnvelopeV1.from_dict(payload)
