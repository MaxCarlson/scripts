"""Typed data models and validation for notifications and incident lifecycle."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from notifications.exceptions import (
    ValidationError,
    UnsupportedSchemaVersionError,
)

SOURCE_PATTERN = re.compile(r"^[a-z0-9_-]{1,64}$")
KIND_PATTERN = re.compile(r"^[a-z0-9_.-]{1,64}$")
INCIDENT_KEY_PATTERN = re.compile(r"^[a-zA-Z0-9_:.-]{1,128}$")
IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z0-9_:.-]*$")
LABEL_KEY_PATTERN = re.compile(r"^[a-z0-9_.-]{1,64}$")

VALID_SEVERITIES = frozenset({"info", "warning", "critical"})
VALID_LIFECYCLES = frozenset({"open", "update", "acknowledge", "resolve", "reopen"})
VALID_INCIDENT_STATUSES = frozenset({"open", "acknowledged", "resolved", "stale"})
VALID_OUTBOX_STATUSES = frozenset({"pending", "attempting", "provider_accepted", "retryable_error", "terminal_error"})

FORBIDDEN_DETAILS_PATTERNS = [
    re.compile(r"\b(powershell|cmd|sh|bash|python|wscript|cscript)\b", re.IGNORECASE),
    re.compile(r"[\\/]|https?://", re.IGNORECASE),
]


def _validate_iso_timestamp(value: str) -> str:
    """Validate and normalize an ISO 8601 timestamp with explicit timezone."""
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("occurred_at must be a non-empty ISO 8601 string")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception as exc:
        raise ValidationError(f"Invalid ISO 8601 timestamp: {value}") from exc

    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValidationError("occurred_at must include explicit timezone")

    utc_dt = dt.astimezone(timezone.utc)
    now = datetime.now(timezone.utc)
    if utc_dt > now + timedelta(minutes=5):
        raise ValidationError("occurred_at cannot be > 5 minutes in the future")

    return utc_dt.isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class EventEnvelopeV1:
    """Version 1 typed notification event envelope."""

    schema_version: int
    event_id: str
    source: str
    kind: str
    incident_key: str
    severity: str
    occurred_at: str
    summary: str
    correlation_id: Optional[str] = None
    resource: Optional[str] = None
    details_ref: Optional[str] = None
    labels: dict[str, str] = field(default_factory=dict)
    lifecycle: str = "open"

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise UnsupportedSchemaVersionError(f"Unsupported schema version: {self.schema_version}")

        # Validate event_id is valid UUID
        try:
            uuid_obj = uuid.UUID(self.event_id)
            if str(uuid_obj) != self.event_id.lower() and uuid_obj.hex != self.event_id.lower():
                raise ValueError("non-canonical uuid")
        except Exception:
            raise ValidationError("event_id must be a valid UUID")

        if not SOURCE_PATTERN.match(self.source):
            raise ValidationError(f"source must match pattern {SOURCE_PATTERN.pattern}")

        if not KIND_PATTERN.match(self.kind):
            raise ValidationError(f"kind must match pattern {KIND_PATTERN.pattern}")

        if not INCIDENT_KEY_PATTERN.match(self.incident_key):
            raise ValidationError(f"incident_key must match pattern {INCIDENT_KEY_PATTERN.pattern}")

        if self.severity not in VALID_SEVERITIES:
            raise ValidationError(f"severity must be one of {sorted(VALID_SEVERITIES)}")

        if self.lifecycle not in VALID_LIFECYCLES:
            raise ValidationError(f"lifecycle must be one of {sorted(VALID_LIFECYCLES)}")

        if not isinstance(self.summary, str) or not self.summary.strip():
            raise ValidationError("summary must be non-empty")
        if len(self.summary) > 256:
            raise ValidationError("summary must not exceed 256 characters")

        for char in self.summary:
            code = ord(char)
            if code < 32 and char not in "\t\n":
                raise ValidationError("summary must not contain control characters")

        if self.correlation_id is not None:
            if len(self.correlation_id) > 128 or not IDENTIFIER_PATTERN.match(self.correlation_id):
                raise ValidationError("correlation_id must be max 128 alphanumeric/safe characters")

        if self.resource is not None:
            if len(self.resource) > 64 or not IDENTIFIER_PATTERN.match(self.resource):
                raise ValidationError("resource must be max 64 alphanumeric/safe characters")

        if self.details_ref is not None:
            if len(self.details_ref) > 256:
                raise ValidationError("details_ref must not exceed 256 characters")
            for pattern in FORBIDDEN_DETAILS_PATTERNS:
                if pattern.search(self.details_ref):
                    raise ValidationError("details_ref must be an opaque reference without paths, URLs, or commands")

        if len(self.labels) > 32:
            raise ValidationError("labels must not contain more than 32 entries")
        for k, v in self.labels.items():
            if not LABEL_KEY_PATTERN.match(k):
                raise ValidationError(f"label key '{k}' must match {LABEL_KEY_PATTERN.pattern}")
            if not isinstance(v, str) or len(v) > 128:
                raise ValidationError(f"label value for key '{k}' must be string with max length 128")

    @property
    def incident_id(self) -> str:
        """Deterministic incident identifier."""
        return hashlib.sha256(f"{self.source}\0{self.incident_key}".encode("utf-8")).hexdigest()

    @property
    def payload_sha256(self) -> str:
        """SHA256 digest of normalized payload."""
        return hashlib.sha256(self.to_canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_canonical_json(self) -> str:
        """Deterministic canonical JSON representation for hashing and auditing."""
        d = self.to_dict()
        return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EventEnvelopeV1:
        if not isinstance(data, dict):
            raise ValidationError("Event data must be a dictionary")

        schema_version = data.get("schema_version")
        if schema_version != 1:
            raise UnsupportedSchemaVersionError(f"Unsupported schema version: {schema_version}")

        occurred_at_raw = data.get("occurred_at")
        if not occurred_at_raw:
            raise ValidationError("occurred_at is required")
        occurred_at = _validate_iso_timestamp(str(occurred_at_raw))

        labels = data.get("labels", {})
        if not isinstance(labels, dict):
            raise ValidationError("labels must be a dictionary")

        return cls(
            schema_version=1,
            event_id=str(data.get("event_id", "")),
            source=str(data.get("source", "")),
            kind=str(data.get("kind", "")),
            incident_key=str(data.get("incident_key", "")),
            severity=str(data.get("severity", "")),
            occurred_at=occurred_at,
            summary=str(data.get("summary", "")),
            correlation_id=data.get("correlation_id"),
            resource=data.get("resource"),
            details_ref=data.get("details_ref"),
            labels={str(k): str(v) for k, v in labels.items()},
            lifecycle=str(data.get("lifecycle", "open")),
        )


@dataclass(frozen=True)
class Incident:
    """Logical tracking entity for an ongoing issue."""

    incident_id: str
    source: str
    incident_key: str
    active_occurrence_id: Optional[str]
    status: str
    severity: str
    summary: str
    first_seen: str
    last_seen: str
    acknowledged_at: Optional[str] = None
    resolved_at: Optional[str] = None
    last_notified_at: Optional[str] = None
    occurrence_count: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Occurrence:
    """Discrete temporal episode of an incident."""

    occurrence_id: str
    incident_id: str
    status: str
    severity: str
    opened_at: str
    closed_at: Optional[str] = None
    resolution_evidence: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Transition:
    """Audit record of an incident state change."""

    transition_id: int
    incident_id: str
    occurrence_id: str
    event_id: str
    from_status: Optional[str]
    to_status: str
    transition_name: str
    timestamp: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PublishResult:
    """Outcome of publishing an event."""

    accepted: bool
    event_id: str
    incident_id: str
    occurrence_id: str
    transition: str
    outbox_queued: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OutboxItem:
    """Pending or completed delivery task for an external provider."""

    outbox_id: int
    event_id: str
    incident_id: str
    provider_id: str
    status: str
    retry_count: int
    max_retries: int
    next_retry_at: str
    created_at: str
    updated_at: str
    error_message: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RenderedNotification:
    """Rendered message payload delivered to a provider adapter."""

    notification_id: str
    event_id: str
    incident_id: str
    severity: str
    title: str
    body: str
    deep_link: Optional[str] = None
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DeliveryReceipt:
    """Response returned by a delivery provider."""

    provider_id: str
    status: str  # "provider_accepted", "retryable_error", "terminal_error"
    provider_message_id: Optional[str] = None
    retry_after_seconds: Optional[float] = None
    error_category: Optional[str] = None
    error_message: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DeliveryAttempt:
    """Audit record of a single delivery attempt."""

    attempt_id: int
    outbox_id: int
    attempted_at: str
    status: str
    provider_message_id: Optional[str] = None
    duration_ms: Optional[int] = None
    error_category: Optional[str] = None
    error_message: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
