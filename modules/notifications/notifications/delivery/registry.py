"""Provider registry and dynamic loader for notification outbox workers."""

from __future__ import annotations

import logging
from typing import Optional

from notifications.delivery.base import DeliveryProvider
from notifications.delivery.fake import FakeProvider
from notifications.delivery.telegram import TelegramProvider
from notifications.delivery.telegram_credentials import load_telegram_credentials
from notifications.models import DeliveryReceipt, RenderedNotification
from notifications.storage import StorageEngine

logger = logging.getLogger(__name__)


class UnconfiguredProvider(DeliveryProvider):
    """Stub provider returned when credentials or configuration are missing."""

    def __init__(self, provider_id: str, reason: str) -> None:
        self.provider_id = provider_id
        self.reason = reason

    async def send(self, notification: RenderedNotification) -> DeliveryReceipt:
        logger.warning(
            "Provider '%s' invoked but unconfigured: %s",
            self.provider_id,
            self.reason,
        )
        return DeliveryReceipt(
            provider_id=self.provider_id,
            status="terminal_error",
            error_category="unconfigured_provider",
            error_message=f"Provider '{self.provider_id}' is not configured: {self.reason}",
        )


def get_registered_providers(
    storage: Optional[StorageEngine] = None,
    *,
    include_test: bool = True,
) -> dict[str, DeliveryProvider]:
    """
    Resolve and instantiate all configured delivery providers.
    Returns mapping of provider_id -> DeliveryProvider.
    """
    providers: dict[str, DeliveryProvider] = {}

    if include_test:
        providers["fake_provider"] = FakeProvider(provider_id="fake_provider")

    # 1. Telegram provider
    creds = load_telegram_credentials()
    if creds:
        providers["telegram"] = TelegramProvider(credentials=creds)
    else:
        providers["telegram"] = UnconfiguredProvider(
            provider_id="telegram",
            reason="Telegram provider is not configured. Missing bot token or chat ID (run 'scripts-notify telegram enroll')",
        )

    # 2. Windows provider
    try:
        from notifications.delivery.windows import WindowsDeliveryProvider

        providers["windows"] = WindowsDeliveryProvider()
    except (ImportError, ModuleNotFoundError):
        pass

    return providers
