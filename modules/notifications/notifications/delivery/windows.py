"""Windows desktop delivery provider connecting to interactive user-session helper."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import httpx

from notifications.config import default_token_path
from notifications.delivery.base import DeliveryProvider
from notifications.models import DeliveryReceipt, RenderedNotification

logger = logging.getLogger(__name__)

DEFAULT_HELPER_URL = "http://127.0.0.1:1238"
DEFAULT_TIMEOUT_SECONDS = 2.0


class WindowsDeliveryProvider(DeliveryProvider):
    """
    Delivery provider for Windows desktop toast notifications.
    Dispatches notifications to the non-elevated user-session helper over authenticated loopback IPC.
    """

    provider_id: str = "windows"

    def __init__(
        self,
        helper_url: Optional[str] = None,
        token_path: Optional[Path] = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.helper_url = (
            helper_url
            or os.environ.get("NOTIFY_WINDOWS_HELPER_URL")
            or DEFAULT_HELPER_URL
        ).rstrip("/")
        self.token_path = token_path or default_token_path()
        self.timeout = timeout
        self._client = client

    def _load_token(self) -> Optional[str]:
        """Read authentication bearer token from secured file or environment."""
        env_token = os.environ.get("NOTIFICATIONS_TOKEN")
        if env_token:
            return env_token.strip()

        if self.token_path and self.token_path.is_file():
            try:
                return self.token_path.read_text(encoding="utf-8").strip()
            except Exception as exc:
                logger.warning("Failed to read notification token from %s: %s", self.token_path, exc)
                return None
        return None

    async def send(self, notification: RenderedNotification) -> DeliveryReceipt:
        """
        Deliver notification to the interactive Windows helper.
        Explicitly detects and reports missing helper / inactive desktop session as retryable error.
        """
        token = self._load_token()
        if not token:
            logger.info("Windows helper token file not present: %s", self.token_path)
            return DeliveryReceipt(
                provider_id=self.provider_id,
                status="retryable_error",
                error_category="session_unavailable",
                error_message="Authentication token file not found; Windows interactive helper not running",
                retry_after_seconds=15.0,
            )

        payload = {
            "title": notification.title[:128],
            "body": notification.body[:512],
            "severity": notification.severity,
            "incident_id": notification.incident_id,
            "dashboard_url": notification.deep_link,
        }

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        url = f"{self.helper_url}/notify"
        client = self._client or httpx.AsyncClient(timeout=self.timeout)
        should_close = self._client is None

        try:
            response = await client.post(url, json=payload, headers=headers)
            status_code = response.status_code

            try:
                data = response.json()
            except Exception:
                data = {}

            if status_code == 200:
                if data.get("ok") is True:
                    toast_id = data.get("toast_id")
                    return DeliveryReceipt(
                        provider_id=self.provider_id,
                        status="provider_accepted",
                        provider_message_id=toast_id,
                    )
                elif data.get("status") == "session_unavailable":
                    return DeliveryReceipt(
                        provider_id=self.provider_id,
                        status="retryable_error",
                        error_category="session_unavailable",
                        error_message=data.get("error", "Interactive session is unavailable"),
                        retry_after_seconds=30.0,
                    )
                else:
                    return DeliveryReceipt(
                        provider_id=self.provider_id,
                        status="retryable_error",
                        error_category="display_failed",
                        error_message=data.get("error", "Toast display failed in helper"),
                        retry_after_seconds=10.0,
                    )

            elif status_code == 401:
                return DeliveryReceipt(
                    provider_id=self.provider_id,
                    status="terminal_error",
                    error_category="unauthorized",
                    error_message="Windows interactive helper rejected bearer token (401 Unauthorized)",
                )

            elif status_code == 400:
                return DeliveryReceipt(
                    provider_id=self.provider_id,
                    status="terminal_error",
                    error_category="bad_payload",
                    error_message=f"Windows interactive helper rejected payload (400): {data.get('error', 'Bad Request')}",
                )

            else:
                return DeliveryReceipt(
                    provider_id=self.provider_id,
                    status="retryable_error",
                    error_category="helper_error",
                    error_message=f"Windows helper returned unexpected HTTP status {status_code}",
                    retry_after_seconds=15.0,
                )

        except httpx.TimeoutException:
            logger.info("Windows helper connection timed out (%ss)", self.timeout)
            return DeliveryReceipt(
                provider_id=self.provider_id,
                status="retryable_error",
                error_category="session_unavailable",
                error_message=f"Windows interactive helper request timed out after {self.timeout}s",
                retry_after_seconds=5.0,
            )

        except (httpx.ConnectError, httpx.NetworkError):
            logger.info("Windows helper connection refused at %s", self.helper_url)
            return DeliveryReceipt(
                provider_id=self.provider_id,
                status="retryable_error",
                error_category="session_unavailable",
                error_message=f"Windows interactive helper is unavailable or session is inactive at {self.helper_url}",
                retry_after_seconds=10.0,
            )

        except Exception as exc:
            logger.warning("Unexpected error communicating with Windows helper: %s", exc)
            return DeliveryReceipt(
                provider_id=self.provider_id,
                status="retryable_error",
                error_category="transport_error",
                error_message=f"Transport error communicating with Windows helper: {exc}",
                retry_after_seconds=10.0,
            )

        finally:
            if should_close:
                await client.aclose()
