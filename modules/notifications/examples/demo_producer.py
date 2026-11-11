"""Example non-blocking notification integration for a producer module.

Demonstrates:
1. Importing notifications safely as an optional dependency.
2. Publishing an event without blocking or crashing if the broker is unavailable.
3. Proper exception handling and logging.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("demo_producer")


def publish_task_alert(task_name: str, error_message: str, broker_url: str = "http://127.0.0.1:1236") -> bool:
    """Safely publish an alert without letting notification errors break the calling task."""
    try:
        from notifications.client import NotificationClient
        from notifications.models import EventEnvelopeV1
        from notifications.exceptions import NotificationError
    except ImportError:
        logger.warning("notifications package not installed; skipping notification")
        return False

    event = EventEnvelopeV1(
        schema_version=1,
        event_id=str(uuid.uuid4()),
        source="demo_producer",
        kind="demo.task_failed",
        incident_key=f"demo_producer:{task_name}",
        severity="warning",
        occurred_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        summary=f"Task '{task_name}' failed: {error_message[:128]}",
        lifecycle="open",
        labels={"task": task_name},
    )

    client = NotificationClient(base_url=broker_url, timeout=1.0)
    try:
        result = client.publish(event)
        logger.info("Published notification successfully: event=%s, transition=%s", result.event_id, result.transition)
        return True
    except NotificationError as exc:
        # Non-blocking: log warning and continue without failing the caller!
        logger.warning("Notification could not be delivered to broker (non-blocking): %s", exc)
        return False


if __name__ == "__main__":
    logger.info("Running demo producer...")
    success = publish_task_alert(
        task_name="sample_background_job",
        error_message="Simulated connection timeout to upstream service",
    )
    logger.info("Demo producer completed without crashing; published=%s", success)
