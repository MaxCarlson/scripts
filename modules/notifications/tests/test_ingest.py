"""Tests for authenticated local HTTP ingestion server and client."""

import pytest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi.testclient import TestClient

from notifications.models import EventEnvelopeV1
from notifications.storage import StorageEngine
from notifications.lifecycle import IncidentLifecycleEngine
from notifications.ingest import create_ingest_app
from notifications.client import NotificationClient


TEST_TOKEN = "test-secret-token-abcdef1234567890"


@pytest.fixture
def test_setup(tmp_path: Path):
    db_path = tmp_path / "ingest.db"
    storage = StorageEngine(db_path)
    storage.migrate()
    lifecycle = IncidentLifecycleEngine(storage)
    app = create_ingest_app(storage, lifecycle, auth_token=TEST_TOKEN, default_providers=["fake_provider"])
    client = TestClient(app)
    return storage, lifecycle, client


def valid_payload() -> dict:
    return {
        "schema_version": 1,
        "event_id": str(uuid.uuid4()),
        "source": "scheduler",
        "kind": "task.failure",
        "incident_key": "scheduler:task:backup",
        "severity": "warning",
        "occurred_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "summary": "Backup task failed with exit code 1",
        "lifecycle": "open",
    }


def test_ingest_unauthenticated_rejected(test_setup):
    _, _, client = test_setup
    payload = valid_payload()
    resp = client.post("/api/v1/publish", json=payload)
    assert resp.status_code == 401


def test_ingest_bad_token_rejected(test_setup):
    _, _, client = test_setup
    payload = valid_payload()
    resp = client.post(
        "/api/v1/publish",
        json=payload,
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert resp.status_code == 401


def test_ingest_valid_event_accepted(test_setup):
    _, _, client = test_setup
    payload = valid_payload()
    resp = client.post(
        "/api/v1/publish",
        json=payload,
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["ok"] is True
    assert data["result"]["accepted"] is True
    assert data["result"]["transition"] == "opened"


def test_ingest_unsupported_version_rejected(test_setup):
    _, _, client = test_setup
    payload = valid_payload()
    payload["schema_version"] = 99
    resp = client.post(
        "/api/v1/publish",
        json=payload,
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
    )
    assert resp.status_code == 400
    data = resp.json()
    assert data["ok"] is False
    assert "Unsupported schema version" in data["error"]


def test_ingest_conflict_rejected(test_setup):
    _, _, client = test_setup
    payload = valid_payload()
    headers = {"Authorization": f"Bearer {TEST_TOKEN}"}

    # First publish
    resp1 = client.post("/api/v1/publish", json=payload, headers=headers)
    assert resp1.status_code == 202

    # Second publish with SAME event_id but DIFFERENT summary -> 409 Conflict
    payload_conflict = dict(payload)
    payload_conflict["summary"] = "Different conflicting summary"
    resp2 = client.post("/api/v1/publish", json=payload_conflict, headers=headers)
    assert resp2.status_code == 409
    data = resp2.json()
    assert data["ok"] is False
    assert "already exists with different payload" in data["error"]


def test_health_endpoint(test_setup):
    _, _, client = test_setup
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["schema_version"] == 1


def test_acknowledge_endpoint(test_setup):
    _, _, client = test_setup
    payload = valid_payload()
    headers = {"Authorization": f"Bearer {TEST_TOKEN}"}
    resp1 = client.post("/api/v1/publish", json=payload, headers=headers)
    incident_id = resp1.json()["result"]["incident_id"]

    # Acknowledge via endpoint
    resp2 = client.post(
        f"/api/v1/incidents/{incident_id}/acknowledge",
        json={"reason": "Operator checked"},
        headers=headers,
    )
    assert resp2.status_code == 200
    data = resp2.json()
    assert data["ok"] is True
    assert data["status"] == "acknowledged"
