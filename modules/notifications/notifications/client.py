"""Lightweight HTTP client for publishing events to the local notification broker."""

from __future__ import annotations

import httpx
from typing import Any, Optional

from notifications.exceptions import (
    AuthenticationError,
    BrokerUnavailableError,
    PayloadConflictError,
    ValidationError,
)
from notifications.models import EventEnvelopeV1, PublishResult


class NotificationClient:
    """Client for out-of-process modules to publish events to the local broker."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:1236",
        token: Optional[str] = None,
        timeout: float = 2.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def publish(self, event: EventEnvelopeV1) -> PublishResult:
        """Publish an event envelope to the local ingestion endpoint."""
        url = f"{self.base_url}/api/v1/publish"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token or ''}",
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(url, json=event.to_dict(), headers=headers)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
            raise BrokerUnavailableError(f"Could not connect to notification broker at {self.base_url}: {exc}") from exc

        if response.status_code == 202:
            data = response.json().get("result", {})
            return PublishResult(
                accepted=data.get("accepted", True),
                event_id=data.get("event_id", event.event_id),
                incident_id=data.get("incident_id", event.incident_id),
                occurrence_id=data.get("occurrence_id", ""),
                transition=data.get("transition", "opened"),
                outbox_queued=data.get("outbox_queued", False),
            )
        elif response.status_code == 400:
            err = response.json().get("error") or response.text
            raise ValidationError(f"Broker rejected event as invalid: {err}")
        elif response.status_code == 401:
            raise AuthenticationError("Broker rejected ingestion request: Unauthorized")
        elif response.status_code == 409:
            err = response.json().get("error") or response.text
            raise PayloadConflictError(f"Broker rejected event conflict: {err}")
        elif response.status_code == 503:
            err = response.json().get("error") or response.text
            raise BrokerUnavailableError(f"Broker storage unavailable: {err}")
        else:
            raise BrokerUnavailableError(f"Unexpected broker response {response.status_code}: {response.text}")

    def health(self) -> dict[str, Any]:
        """Check broker health."""
        url = f"{self.base_url}/api/v1/health"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(url)
                return resp.json()
        except Exception as exc:
            return {"status": "unreachable", "error": str(exc)}
