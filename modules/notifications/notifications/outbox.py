"""Outbox delivery worker and retry dispatcher."""

from __future__ import annotations

import time
import logging
from typing import Optional

from notifications.delivery.base import DeliveryProvider
from notifications.models import RenderedNotification
from notifications.storage import StorageEngine

logger = logging.getLogger(__name__)


class OutboxWorker:
    """Processes pending outbox items and dispatches to registered providers."""

    def __init__(self, storage: StorageEngine, providers: dict[str, DeliveryProvider]) -> None:
        self.storage = storage
        self.providers = providers

    async def process_pending_once(self, limit: int = 50) -> int:
        """Claim and dispatch up to `limit` pending outbox items."""
        items = self.storage.list_pending_outbox(limit=limit)
        processed_count = 0

        for item in items:
            if not self.storage.claim_outbox_item(item.outbox_id):
                continue

            event = self.storage.get_event(item.event_id)
            if not event:
                self.storage.record_delivery_attempt(
                    outbox_id=item.outbox_id,
                    status="terminal_error",
                    error_category="missing_event",
                    error_message=f"Event '{item.event_id}' not found in journal",
                )
                processed_count += 1
                continue

            provider = self.providers.get(item.provider_id)
            if not provider:
                self.storage.record_delivery_attempt(
                    outbox_id=item.outbox_id,
                    status="terminal_error",
                    error_category="unknown_provider",
                    error_message=f"Delivery provider '{item.provider_id}' is not registered",
                )
                processed_count += 1
                continue

            # Render notification
            rendered = RenderedNotification(
                notification_id=str(item.outbox_id),
                event_id=event.event_id,
                incident_id=item.incident_id,
                severity=event.severity,
                title=f"[{event.severity.upper()}] {event.summary}",
                body=f"Source: {event.source}\nKind: {event.kind}\nTime: {event.occurred_at}",
                deep_link=None,
                created_at=item.created_at,
            )

            start_time = time.time()
            try:
                receipt = await provider.send(rendered)
            except Exception as exc:
                logger.exception("Provider '%s' raised an unhandled exception: %s", item.provider_id, exc)
                self.storage.record_delivery_attempt(
                    outbox_id=item.outbox_id,
                    status="retryable_error",
                    error_category="provider_exception",
                    error_message=str(exc),
                )
                processed_count += 1
                continue

            duration_ms = int((time.time() - start_time) * 1000)
            self.storage.record_delivery_attempt(
                outbox_id=item.outbox_id,
                status=receipt.status,
                provider_message_id=receipt.provider_message_id,
                duration_ms=duration_ms,
                error_category=receipt.error_category,
                error_message=receipt.error_message,
                retry_after_seconds=receipt.retry_after_seconds,
            )
            processed_count += 1

        return processed_count

    def recover_stalled(self, stalled_seconds: float = 300.0) -> int:
        """Reset items stuck in 'attempting' state due to worker interruption."""
        return self.storage.reset_stalled_outbox_items(stalled_seconds=stalled_seconds)
