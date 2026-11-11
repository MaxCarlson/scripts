"""Independent outbound heartbeat client for off-host outage detection via Healthchecks.io."""

from __future__ import annotations

import logging
import ssl
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from notifications.monitoring.config import redact_ping_url

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 10.0
USER_AGENT = "scripts-notifications-heartbeat/1.0"


@dataclass(frozen=True)
class HeartbeatResult:
    """Outcome of an independent host heartbeat ping attempt."""

    success: bool
    status_code: Optional[int] = None
    duration_ms: int = 0
    error_category: Optional[str] = None
    error_message: Optional[str] = None
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "status_code": self.status_code,
            "duration_ms": self.duration_ms,
            "error_category": self.error_category,
            "error_message": self.error_message,
            "timestamp": self.timestamp
            or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }


def send_heartbeat(
    ping_url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    client: Optional[httpx.Client] = None,
    mode: str = "ping",  # "ping", "start", "fail"
    diagnostic_body: Optional[str] = None,
) -> HeartbeatResult:
    """
    Dispatch an HTTPS heartbeat to Healthchecks.io.

    Operates completely independently of the notification broker, database,
    Telegram provider, or user desktop session.
    Secrets and UUIDs in URLs are strictly redacted from any diagnostics or errors.
    """
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    clean_url = ping_url.rstrip("/")

    # Resolve target URL path
    if mode == "start":
        target_url = f"{clean_url}/start"
    elif mode == "fail":
        target_url = f"{clean_url}/fail"
    else:
        target_url = clean_url

    headers = {
        "User-Agent": USER_AGENT,
    }

    start_time = time.monotonic()
    http_client = client or httpx.Client(timeout=timeout)
    should_close = client is None

    try:
        if diagnostic_body:
            # POST with diagnostic log (bounded to 10KB by Healthchecks.io API)
            truncated_body = diagnostic_body[:10240]
            response = http_client.post(target_url, content=truncated_body.encode("utf-8"), headers=headers)
        else:
            response = http_client.get(target_url, headers=headers)

        duration_ms = int((time.monotonic() - start_time) * 1000)
        status_code = response.status_code

        if 200 <= status_code < 300:
            logger.info("Heartbeat ping succeeded (%dms, HTTP %d)", duration_ms, status_code)
            return HeartbeatResult(
                success=True,
                status_code=status_code,
                duration_ms=duration_ms,
                timestamp=now_iso,
            )
        else:
            raw_preview = response.text[:128] if response.text else ""
            err_msg = f"Healthchecks returned HTTP {status_code}: {redact_ping_url(raw_preview)}"
            logger.warning("Heartbeat ping rejected: %s", err_msg)
            return HeartbeatResult(
                success=False,
                status_code=status_code,
                duration_ms=duration_ms,
                error_category="http_error",
                error_message=err_msg,
                timestamp=now_iso,
            )

    except httpx.TimeoutException:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        err_msg = f"Heartbeat ping timed out after {timeout:.1f}s"
        logger.warning(err_msg)
        return HeartbeatResult(
            success=False,
            duration_ms=duration_ms,
            error_category="timeout",
            error_message=err_msg,
            timestamp=now_iso,
        )

    except ssl.SSLError as exc:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        sanitized = redact_ping_url(str(exc))
        err_msg = f"TLS certificate validation failure: {sanitized}"
        logger.error(err_msg)
        return HeartbeatResult(
            success=False,
            duration_ms=duration_ms,
            error_category="tls_error",
            error_message=err_msg,
            timestamp=now_iso,
        )

    except httpx.ConnectError as exc:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        sanitized = redact_ping_url(str(exc))
        err_str = str(exc).lower()
        if "ssl" in err_str or "certificate" in err_str:
            err_cat = "tls_error"
            err_msg = f"TLS certificate validation failure: {sanitized}"
        else:
            err_cat = "dns_connect_error"
            err_msg = f"Network connection / DNS resolution failure: {sanitized}"
        logger.warning(err_msg)
        return HeartbeatResult(
            success=False,
            duration_ms=duration_ms,
            error_category=err_cat,
            error_message=err_msg,
            timestamp=now_iso,
        )

    except Exception as exc:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        sanitized = redact_ping_url(str(exc))
        err_msg = f"Unexpected error during heartbeat ping: {sanitized}"
        logger.warning(err_msg)
        return HeartbeatResult(
            success=False,
            duration_ms=duration_ms,
            error_category="unexpected_error",
            error_message=err_msg,
            timestamp=now_iso,
        )

    finally:
        if should_close:
            http_client.close()
