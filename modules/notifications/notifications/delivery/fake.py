"""Fake in-memory delivery provider for tests and simulation."""

from __future__ import annotations

import uuid
from typing import Optional

from notifications.delivery.base import DeliveryProvider
from notifications.models import DeliveryReceipt, RenderedNotification


class FakeProvider(DeliveryProvider):
    """Configurable in-memory delivery provider for validation testing."""

    def __init__(
        self,
        provider_id: str = "fake_provider",
        mode: str = "success",  # "success", "retryable_error", "terminal_error", "rate_limited"
        retry_after_seconds: Optional[float] = None,
    ) -> None:
        self.provider_id = provider_id
        self.mode = mode
        self.retry_after_seconds = retry_after_seconds
        self.sent_notifications: list[RenderedNotification] = []

    async def send(self, notification: RenderedNotification) -> DeliveryReceipt:
        """Simulate delivery according to configured mode."""
        self.sent_notifications.append(notification)

        if self.mode == "success":
            return DeliveryReceipt(
                provider_id=self.provider_id,
                status="provider_accepted",
                provider_message_id=f"fake-msg-{uuid.uuid4().hex[:8]}",
            )
        elif self.mode == "retryable_error":
            return DeliveryReceipt(
                provider_id=self.provider_id,
                status="retryable_error",
                error_category="transient_network_error",
                error_message="Simulated temporary network failure",
                retry_after_seconds=self.retry_after_seconds or 2.0,
            )
        elif self.mode == "rate_limited":
            return DeliveryReceipt(
                provider_id=self.provider_id,
                status="retryable_error",
                error_category="rate_limited_429",
                error_message="Too Many Requests",
                retry_after_seconds=self.retry_after_seconds or 60.0,
            )
        elif self.mode == "terminal_error":
            return DeliveryReceipt(
                provider_id=self.provider_id,
                status="terminal_error",
                error_category="bad_credentials_401",
                error_message="Simulated invalid credentials or chat ID",
            )
        else:
            return DeliveryReceipt(
                provider_id=self.provider_id,
                status="terminal_error",
                error_category="unknown_mode",
                error_message=f"Unknown fake provider mode: {self.mode}",
            )
