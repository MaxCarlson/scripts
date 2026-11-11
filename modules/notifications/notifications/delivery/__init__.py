"""Delivery provider interfaces and adapters."""

from notifications.delivery.base import DeliveryProvider
from notifications.delivery.fake import FakeProvider
from notifications.delivery.telegram import TelegramProvider
from notifications.delivery.telegram_credentials import TelegramCredentials

__all__ = [
    "DeliveryProvider",
    "FakeProvider",
    "TelegramProvider",
    "TelegramCredentials",
]
