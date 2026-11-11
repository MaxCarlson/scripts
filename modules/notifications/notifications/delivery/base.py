"""Base delivery provider abstraction."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from notifications.models import DeliveryReceipt, RenderedNotification


@runtime_checkable
class DeliveryProvider(Protocol):
    """Protocol for external notification delivery adapters."""

    provider_id: str

    async def send(self, notification: RenderedNotification) -> DeliveryReceipt:
        """
        Deliver a rendered notification.
        Implementations must not raise unhandled network exceptions; return DeliveryReceipt.
        """
        ...
