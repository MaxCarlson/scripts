"""In-process Python Publisher API for emitting notification events."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from notifications.lifecycle import IncidentLifecycleEngine
from notifications.models import EventEnvelopeV1, PublishResult
from notifications.storage import StorageEngine


class Publisher:
    """In-process publisher interface for Python modules to emit notifications."""

    def __init__(
        self,
        storage: StorageEngine,
        lifecycle: Optional[IncidentLifecycleEngine] = None,
        default_providers: Optional[list[str]] = None,
    ) -> None:
        self.storage = storage
        self.lifecycle = lifecycle or IncidentLifecycleEngine(storage)
        if default_providers is not None:
            self.default_providers = list(default_providers)
        else:
            from notifications.delivery.registry import get_configured_provider_ids

            self.default_providers = get_configured_provider_ids(storage=storage)

    def publish(
        self,
        event: EventEnvelopeV1,
        providers: Optional[list[str]] = None,
    ) -> PublishResult:
        """
        Publish an event envelope synchronously.
        Persists event, updates incident state, and queues outbox deliveries.
        Raises ValidationError, PayloadConflictError, or StorageError on failure.
        """
        target_providers = providers or self.default_providers
        return self.lifecycle.process_event(event, providers=target_providers)

    def create_and_publish(
        self,
        source: str,
        kind: str,
        incident_key: str,
        severity: str,
        summary: str,
        lifecycle: str = "open",
        correlation_id: Optional[str] = None,
        resource: Optional[str] = None,
        details_ref: Optional[str] = None,
        labels: Optional[dict[str, str]] = None,
        providers: Optional[list[str]] = None,
        occurred_at: Optional[str] = None,
    ) -> PublishResult:
        """Convenience method to construct and publish an event in one call."""
        now_iso = occurred_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        event = EventEnvelopeV1(
            schema_version=1,
            event_id=str(uuid.uuid4()),
            source=source,
            kind=kind,
            incident_key=incident_key,
            severity=severity,
            occurred_at=now_iso,
            summary=summary,
            correlation_id=correlation_id,
            resource=resource,
            details_ref=details_ref,
            labels=labels or {},
            lifecycle=lifecycle,
        )
        return self.publish(event, providers=providers)
