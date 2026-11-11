"""End-to-end integration smoke test with synthetic Coordinator status server.

Exercises:
  Synthetic HTTP Coordinator status server
    -> ResourceCoordinatorObserver poll
    -> Durable event and rc_observations persistence
    -> Incident lifecycle reconciliation
    -> Durable outbox queue
    -> OutboxWorker claim and delivery to FakeProvider
    -> Delivery attempt receipt recorded
    -> Subsequent poll with cleared state
    -> Incident resolved cleanly
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict

import pytest

from notifications.delivery.fake import FakeProvider
from notifications.integrations.resource_coordinator import ResourceCoordinatorObserver
from notifications.outbox import OutboxWorker
from notifications.publisher import Publisher
from notifications.storage import StorageEngine


class SyntheticCoordinatorHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler serving controllable synthetic Coordinator status responses."""

    payload: Dict[str, Any] = {}

    def do_GET(self) -> None:
        if self.path in ("/_coordinator/status", "/status"):
            content = json.dumps(self.payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress routine request logging in test runs
        pass


@pytest.fixture
def synthetic_coordinator_server():
    """Start an ephemeral loopback HTTP server serving synthetic coordinator payloads."""
    server = HTTPServer(("127.0.0.1", 0), SyntheticCoordinatorHandler)
    port = server.server_port
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    yield f"http://127.0.0.1:{port}/_coordinator/status"

    server.shutdown()
    server.server_close()


def test_rc_end_to_end_notification_delivery_pipeline(
    tmp_path: Path, synthetic_coordinator_server: str
) -> None:
    """Full pipeline smoke test: HTTP status -> observer -> broker -> outbox -> provider delivery -> resolution."""
    db_file = tmp_path / "integration.db"
    storage = StorageEngine(db_file)
    storage.migrate()

    # 1. Configure synthetic coordinator to require recovery (e.g. model-load timeout hold)
    SyntheticCoordinatorHandler.payload = {
        "service": {"status": "ok", "version": "0.1.2"},
        "gpu_inference": {
            "recovery": {
                "required": True,
                "inhibition": {
                    "resource": "gpu.inference",
                    "reason": "upstream_operation_deadline_expired",
                    "active": True,
                },
                "requests": [
                    {
                        "request_id": "coord-smoke-1",
                        "phase": "uncertain",
                        "model": "qwen2.5-coder",
                    }
                ],
                "journal_status": "available",
            },
            "inhibition": {"reason": "upstream_operation_deadline_expired"},
        },
        "miner": {"state": "restart_inhibited"},
    }

    # 2. Run Observer against synthetic loopback server
    fake_provider = FakeProvider(provider_id="fake_provider", mode="success")
    publisher = Publisher(storage, default_providers=["fake_provider"])

    observer = ResourceCoordinatorObserver(
        status_url=synthetic_coordinator_server,
        timeout_seconds=3.0,
        storage=storage,
        publisher=publisher,
    )

    obs = observer.poll_once()
    assert obs.status == "available"
    assert obs.recovery_required is True
    assert obs.has_recovery_contract is True

    # 3. Verify incident opened in durable broker
    incidents = storage.list_incidents(status="open")
    assert len(incidents) == 1
    inc = incidents[0]
    assert inc.incident_key == "gpu_inference_recovery"
    assert inc.severity == "critical"
    assert "restart inhibited" in inc.summary.lower()

    # 4. Verify outbox has pending notification for the configured provider
    outbox_items = storage.list_pending_outbox()
    assert len(outbox_items) == 1
    assert outbox_items[0].provider_id == "fake_provider"
    assert outbox_items[0].incident_id == inc.incident_id

    # 5. Dispatch outbox items through OutboxWorker
    worker = OutboxWorker(storage, providers={"fake_provider": fake_provider})
    delivered_count = asyncio.run(worker.process_pending_once())
    assert delivered_count == 1

    # 6. Verify provider received notification and delivery receipt is recorded
    assert len(fake_provider.sent_notifications) == 1
    sent = fake_provider.sent_notifications[0]
    assert "CRITICAL" in sent.title
    assert "gpu_inference_recovery" in sent.body or "resource_coordinator" in sent.body

    # Pending outbox is now empty (delivered)
    assert len(storage.list_pending_outbox()) == 0

    # 7. Operator recovers coordinator; synthetic server returns cleared status
    SyntheticCoordinatorHandler.payload = {
        "service": {"status": "ok", "version": "0.1.2"},
        "gpu_inference": {
            "recovery": {
                "required": False,
                "inhibition": None,
                "requests": [],
                "journal_status": "available",
            },
            "inhibition": None,
        },
        "miner": {"state": "running"},
    }

    obs_cleared = observer.poll_once()
    assert obs_cleared.status == "available"
    assert obs_cleared.recovery_required is False
    assert obs_cleared.inhibition_active is False

    # 8. Verify safety incident is cleanly resolved
    assert len(storage.list_incidents(status="open")) == 0
    resolved_incidents = storage.list_incidents(status="resolved")
    assert any(i.incident_key == "gpu_inference_recovery" for i in resolved_incidents)
