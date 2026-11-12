"""Telegram Bot API delivery provider for Android notifications."""

from __future__ import annotations

import asyncio
import logging
import re
import ssl
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from notifications.delivery.base import DeliveryProvider
from notifications.delivery.telegram_credentials import (
    TelegramCredentials,
    install_http_log_redaction,
    redact_token,
)
from notifications.models import DeliveryReceipt, RenderedNotification

logger = logging.getLogger(__name__)

_MAX_TELEGRAM_MESSAGE_LENGTH = 4000
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class TelegramProvider(DeliveryProvider):
    """Provider adapter for delivering notifications via official Telegram Bot API."""

    provider_id: str = "telegram"

    def __init__(
        self,
        credentials: TelegramCredentials,
        client: Optional[httpx.AsyncClient] = None,
        rate_limit_delay: float = 1.0,
        quiet_hours: Optional[tuple[int, int]] = None,
    ) -> None:
        self.credentials = credentials
        self._client = client
        self.rate_limit_delay = rate_limit_delay
        self.quiet_hours = quiet_hours
        self._last_send_monotonic = 0.0
        install_http_log_redaction(self.credentials.bot_token)

    def render(self, notification: RenderedNotification) -> str:
        """Format notification as clean, plain-text message within Telegram limits."""
        # Sanitize control characters
        clean_title = _CONTROL_CHAR_RE.sub("", notification.title).strip()
        clean_body = _CONTROL_CHAR_RE.sub("", notification.body).strip()

        header = (
            clean_title
            if clean_title.upper().startswith(f"[{notification.severity.upper()}]")
            else f"[{notification.severity.upper()}] {clean_title}"
        )

        lines = [
            header,
            "",
            clean_body,
            f"Incident: {notification.incident_id[:8]}",
            f"Severity: {notification.severity.upper()}",
        ]

        if notification.created_at:
            lines.append(f"Timestamp: {notification.created_at}")

        dashboard = notification.deep_link or self.credentials.dashboard_url
        if dashboard and dashboard.startswith("https://") and "@" not in dashboard:
            lines.append("")
            lines.append(f"Dashboard: {dashboard}")

        text = "\n".join(lines)

        # Enforce hard length limit
        if len(text) > _MAX_TELEGRAM_MESSAGE_LENGTH:
            overflow = len(text) - _MAX_TELEGRAM_MESSAGE_LENGTH + 20
            clean_body = clean_body[:-overflow] + " ...[truncated]"
            lines[2] = clean_body
            text = "\n".join(lines)[:_MAX_TELEGRAM_MESSAGE_LENGTH]

        return text

    def is_quiet_hours(self, now: Optional[datetime] = None) -> bool:
        """Check if current time falls within configured quiet hours."""
        if not self.quiet_hours:
            return False

        current_dt = now or datetime.now(timezone.utc)
        hour = current_dt.hour
        start, end = self.quiet_hours

        if start > end:
            # e.g. 22:00 to 07:00
            return hour >= start or hour < end
        elif start < end:
            # e.g. 01:00 to 06:00
            return start <= hour < end
        else:
            return False

    async def send(self, notification: RenderedNotification) -> DeliveryReceipt:
        """Deliver a rendered notification to the authorized Telegram chat."""
        # 1. Quiet hours policy check: critical notifications bypass quiet hours
        if self.is_quiet_hours() and notification.severity != "critical":
            logger.info("Notification %s deferred due to quiet hours", notification.notification_id)
            return DeliveryReceipt(
                provider_id=self.provider_id,
                status="retryable_error",
                error_category="quiet_hours_deferred",
                error_message="Alert deferred during operator quiet hours",
                retry_after_seconds=300.0,
            )

        # 2. Pacing / rate control: enforce <= 1 message/sec per chat
        now_mono = time.monotonic()
        elapsed = now_mono - self._last_send_monotonic
        if elapsed < self.rate_limit_delay:
            wait_time = self.rate_limit_delay - elapsed
            await asyncio.sleep(wait_time)
        self._last_send_monotonic = time.monotonic()

        rendered_text = self.render(notification)
        target_url = f"https://api.telegram.org/bot{self.credentials.bot_token}/sendMessage"
        redacted_url = redact_token(target_url, self.credentials.bot_token)
        payload = {
            "chat_id": self.credentials.chat_id,
            "text": rendered_text,
            "disable_web_page_preview": True,
        }

        # 3. HTTP Dispatch with strict token redaction and error mapping
        install_http_log_redaction(self.credentials.bot_token)
        client = self._client or httpx.AsyncClient(timeout=5.0)
        should_close = self._client is None
        start_mono = time.monotonic()

        try:
            response = await client.post(target_url, json=payload)
            duration_ms = int((time.monotonic() - start_mono) * 1000)
            status_code = response.status_code

            # Try parsing JSON body
            try:
                data = response.json()
            except Exception:
                data = {}

            if status_code == 200 and data.get("ok") is True:
                msg_id = str(data.get("result", {}).get("message_id", ""))
                logger.info(
                    "Telegram HTTP POST %s -> HTTP %d (%dms, message_id=%s)",
                    redacted_url,
                    status_code,
                    duration_ms,
                    msg_id or "none",
                )
                return DeliveryReceipt(
                    provider_id=self.provider_id,
                    status="provider_accepted",
                    provider_message_id=msg_id or None,
                )

            elif status_code == 429:
                retry_after = data.get("parameters", {}).get("retry_after", 30)
                logger.warning(
                    "Telegram HTTP POST %s -> HTTP %d (%dms): rate_limited_429 (retry_after=%ss)",
                    redacted_url,
                    status_code,
                    duration_ms,
                    retry_after,
                )
                return DeliveryReceipt(
                    provider_id=self.provider_id,
                    status="retryable_error",
                    error_category="rate_limited_429",
                    error_message=f"Rate limited by Telegram API (retry after {retry_after}s)",
                    retry_after_seconds=float(retry_after),
                )

            elif status_code in (401, 403):
                desc = redact_token(data.get("description", "Unauthorized"), self.credentials.bot_token)
                logger.warning(
                    "Telegram HTTP POST %s -> HTTP %d (%dms): unauthorized_credentials (%s)",
                    redacted_url,
                    status_code,
                    duration_ms,
                    desc,
                )
                return DeliveryReceipt(
                    provider_id=self.provider_id,
                    status="terminal_error",
                    error_category="unauthorized_credentials",
                    error_message=f"Telegram authentication failure ({status_code}): {desc}",
                )

            elif status_code == 400:
                desc = redact_token(data.get("description", "Bad Request"), self.credentials.bot_token)
                logger.warning(
                    "Telegram HTTP POST %s -> HTTP %d (%dms): bad_request_400 (%s)",
                    redacted_url,
                    status_code,
                    duration_ms,
                    desc,
                )
                return DeliveryReceipt(
                    provider_id=self.provider_id,
                    status="terminal_error",
                    error_category="bad_request_400",
                    error_message=f"Telegram rejected request (400): {desc}",
                )

            elif 500 <= status_code < 600:
                logger.warning(
                    "Telegram HTTP POST %s -> HTTP %d (%dms): server_error_5xx",
                    redacted_url,
                    status_code,
                    duration_ms,
                )
                return DeliveryReceipt(
                    provider_id=self.provider_id,
                    status="retryable_error",
                    error_category="server_error_5xx",
                    error_message=f"Telegram API server error (HTTP {status_code})",
                    retry_after_seconds=15.0,
                )

            else:
                desc = redact_token(data.get("description", response.text[:128]), self.credentials.bot_token)
                logger.warning(
                    "Telegram HTTP POST %s -> HTTP %d (%dms): unexpected_http_status (%s)",
                    redacted_url,
                    status_code,
                    duration_ms,
                    desc,
                )
                return DeliveryReceipt(
                    provider_id=self.provider_id,
                    status="retryable_error",
                    error_category="unexpected_http_status",
                    error_message=f"Telegram HTTP {status_code}: {desc}",
                    retry_after_seconds=30.0,
                )

        except httpx.TimeoutException:
            duration_ms = int((time.monotonic() - start_mono) * 1000)
            logger.warning(
                "Telegram HTTP POST %s failed (%dms): network_timeout",
                redacted_url,
                duration_ms,
            )
            return DeliveryReceipt(
                provider_id=self.provider_id,
                status="retryable_error",
                error_category="network_timeout",
                error_message="Telegram API request timed out (5s)",
                retry_after_seconds=5.0,
            )

        except ssl.SSLError as exc:
            duration_ms = int((time.monotonic() - start_mono) * 1000)
            sanitized = redact_token(str(exc), self.credentials.bot_token)
            logger.warning(
                "Telegram HTTP POST %s failed (%dms): security_tls_error (%s)",
                redacted_url,
                duration_ms,
                sanitized,
            )
            return DeliveryReceipt(
                provider_id=self.provider_id,
                status="terminal_error",
                error_category="security_tls_error",
                error_message=f"TLS/Certificate verification error connecting to Telegram API: {sanitized}",
            )

        except httpx.ConnectError as exc:
            duration_ms = int((time.monotonic() - start_mono) * 1000)
            err_str = str(exc).lower()
            if "certificate" in err_str or "ssl" in err_str:
                sanitized = redact_token(str(exc), self.credentials.bot_token)
                logger.warning(
                    "Telegram HTTP POST %s failed (%dms): security_tls_error (%s)",
                    redacted_url,
                    duration_ms,
                    sanitized,
                )
                return DeliveryReceipt(
                    provider_id=self.provider_id,
                    status="terminal_error",
                    error_category="security_tls_error",
                    error_message=f"TLS/Certificate verification error: {sanitized}",
                )
            logger.warning(
                "Telegram HTTP POST %s failed (%dms): connection_failure",
                redacted_url,
                duration_ms,
            )
            return DeliveryReceipt(
                provider_id=self.provider_id,
                status="retryable_error",
                error_category="connection_failure",
                error_message="Failed to establish connection to api.telegram.org",
                retry_after_seconds=5.0,
            )

        except Exception as exc:
            duration_ms = int((time.monotonic() - start_mono) * 1000)
            sanitized = redact_token(str(exc), self.credentials.bot_token)
            logger.warning(
                "Telegram HTTP POST %s failed (%dms): transport_error (%s)",
                redacted_url,
                duration_ms,
                sanitized,
            )
            return DeliveryReceipt(
                provider_id=self.provider_id,
                status="retryable_error",
                error_category="transport_error",
                error_message=f"Unexpected transport error: {sanitized}",
                retry_after_seconds=10.0,
            )

        finally:
            if should_close:
                await client.aclose()
