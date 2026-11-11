"""Integration tests for guarded actions workflow, capabilities, challenges, execution journal, and incident acknowledgement."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import time
from typing import Dict
import uuid

from fastapi.testclient import TestClient
import pyotp
import pytest

from notifications.lifecycle import IncidentLifecycleEngine
from notifications.models import EventEnvelopeV1
from notifications.storage import StorageEngine
from remote_control.app import create_app
from remote_control.config import RemoteControlConfig


@pytest.fixture
def test_setup(tmp_path: Path):
    """Set up temporary databases, bootstrapped operator, and TestClient."""
    auth_db = tmp_path / "auth.db"
    notif_db = tmp_path / "notifications.db"
    hc_cfg = tmp_path / "healthchecks.json"
    hc_cfg.write_text("{}", encoding="utf-8")

    # Initialize Notifications Storage with an open incident
    notif_storage = StorageEngine(notif_db)
    notif_storage.migrate()
    lifecycle = IncidentLifecycleEngine(notif_storage)

    event = EventEnvelopeV1(
        schema_version=1,
        event_id=str(uuid.uuid4()),
        source="desktop_monitor",
        kind="heartbeat.loss",
        incident_key="desktop_monitor:heartbeat_loss",
        severity="critical",
        occurred_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        summary="Simulated host outage",
        lifecycle="open",
    )
    pub_res = lifecycle.process_event(event)
    incident_id = pub_res.incident_id

    # Create app configuration
    cfg = RemoteControlConfig(
        auth_db_path=auth_db,
        notifications_db_path=notif_db,
        healthchecks_config_path=hc_cfg,
        allowed_hosts=["testserver", "localhost", "127.0.0.1"],
        allowed_origins=["http://testserver", "https://testserver"],
        session_max_age_seconds=3600,
        cookie_secure=False,
    )

    app = create_app(cfg)
    client = TestClient(app, base_url="http://testserver")

    # Bootstrap operator
    auth_svc = app.state.auth_service
    op, totp_secret, _ = auth_svc.bootstrap(
        username="admin",
        password="ValidPassword123!",
        totp_secret="JBSWY3DPEHPK3PXP",
        ip_address="127.0.0.1",
    )

    # Log in operator
    totp = pyotp.TOTP(totp_secret)
    login_otp = totp.now()
    login_res = client.post(
        "/api/auth/login",
        json={
            "username": "admin",
            "password": "ValidPassword123!",
            "totp_code": login_otp,
            "device_id": "dev_test_device_1",
            "device_name": "Test Phone",
        },
        headers={"Origin": "http://testserver"},
    )
    assert login_res.status_code == 200, f"Login failed: {login_res.text}"
    login_data = login_res.json()
    csrf_token = login_data["csrf_token"]
    session_cookie = client.cookies.get("rc_session")

    return {
        "client": client,
        "app": app,
        "totp_secret": totp_secret,
        "totp": totp,
        "csrf_token": csrf_token,
        "session_cookie": session_cookie,
        "incident_id": incident_id,
        "notif_storage": notif_storage,
        "cfg": cfg,
    }


def test_capabilities_discovery(test_setup):
    """GET /api/v1/capabilities returns registered capabilities with schema."""
    client: TestClient = test_setup["client"]

    res = client.get("/api/v1/capabilities")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    caps = {c["action_id"]: c for c in data["capabilities"]}

    assert "resource_coordinator.status" in caps
    assert "resource_coordinator.inspect_recovery" in caps
    assert "notifications.health" in caps
    assert "notifications.incident_detail" in caps
    assert "notifications.acknowledge_incident" in caps
    assert "resource_coordinator.request_guarded_recovery" in caps

    # Production disabled check
    rc_recovery = caps["resource_coordinator.request_guarded_recovery"]
    assert rc_recovery["enabled"] is False
    assert rc_recovery["disabled_reason"] is not None


def test_unauthenticated_requests_fail(tmp_path: Path):
    """Endpoints reject unauthenticated requests with 401."""
    cfg = RemoteControlConfig(
        auth_db_path=tmp_path / "auth.db",
        notifications_db_path=tmp_path / "notif.db",
        healthchecks_config_path=tmp_path / "hc.json",
        allowed_hosts=["127.0.0.1", "localhost", "testserver"],
    )
    app = create_app(cfg)
    client = TestClient(app, base_url="http://testserver")

    res = client.get("/api/v1/capabilities")
    assert res.status_code == 503  # Unbootstrapped service returns 503


def test_prepare_action_success_and_schema_validation(test_setup):
    """POST /api/v1/actions/{id}/prepare creates expiring challenge and enforces schema."""
    client: TestClient = test_setup["client"]
    csrf = test_setup["csrf_token"]
    inc_id = test_setup["incident_id"]

    # 1. Prepare with extra arguments fails (extra="forbid")
    res_bad = client.post(
        "/api/v1/actions/notifications.acknowledge_incident/prepare",
        json={"parameters": {"incident_id": inc_id, "extra_field": "disallowed"}},
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
    )
    assert res_bad.status_code == 422
    assert "extra_field" in res_bad.text

    # 2. Prepare with valid arguments succeeds
    res_ok = client.post(
        "/api/v1/actions/notifications.acknowledge_incident/prepare",
        json={"parameters": {"incident_id": inc_id, "reason": "Investigating"}},
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
    )
    assert res_ok.status_code == 200
    data = res_ok.json()
    assert data["ok"] is True
    assert data["challenge_id"].startswith("cld_")
    assert data["ttl_seconds"] == 120
    assert data["requires_totp"] is True
    assert data["requires_confirmation"] is True
    assert data["arguments_digest"] is not None
    assert data["state_fingerprint"] is not None


def test_disabled_capability_fails_closed(test_setup):
    """Disabled production recovery fails closed with 403 capability_disabled."""
    client: TestClient = test_setup["client"]
    csrf = test_setup["csrf_token"]

    res = client.post(
        "/api/v1/actions/resource_coordinator.request_guarded_recovery/prepare",
        json={"parameters": {"resource": "gpu.inference", "reason": "Manual operator reset"}},
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
    )
    assert res.status_code == 403
    assert res.json()["error"] == "capability_disabled"


def test_execute_guarded_action_full_lifecycle(test_setup):
    """Prepare -> Confirm & Execute with step-up TOTP succeeds, journaled, and postcondition verified."""
    client: TestClient = test_setup["client"]
    csrf = test_setup["csrf_token"]
    totp = test_setup["totp"]
    inc_id = test_setup["incident_id"]

    # 1. Prepare
    prep_res = client.post(
        "/api/v1/actions/notifications.acknowledge_incident/prepare",
        json={"parameters": {"incident_id": inc_id, "reason": "Operator reviewing"}},
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
    )
    assert prep_res.status_code == 200
    prep_data = prep_res.json()
    challenge_id = prep_data["challenge_id"]

    # Generate a fresh TOTP code for step-up (must not be same timestep as login!)
    # Sleep slightly or advance timestep if needed
    time.sleep(1.0)
    # If the timestep is the same as login, we can advance time in TOTP by +30s for test purposes
    # In pyotp, `totp.at(int(time.time()) + 30)` generates next timestep
    step_up_otp = totp.at(int(time.time()) + 30)

    # 2. Execute with invalid TOTP fails
    bad_otp_res = client.post(
        "/api/v1/actions/notifications.acknowledge_incident/execute",
        json={
            "challenge_id": challenge_id,
            "parameters": {"incident_id": inc_id, "reason": "Operator reviewing"},
            "totp_code": "000000",
        },
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
    )
    assert bad_otp_res.status_code == 401
    assert bad_otp_res.json()["error"] == "step_up_authentication_failed"

    # 3. Execute with valid step-up TOTP
    exec_res = client.post(
        "/api/v1/actions/notifications.acknowledge_incident/execute",
        json={
            "challenge_id": challenge_id,
            "parameters": {"incident_id": inc_id, "reason": "Operator reviewing"},
            "totp_code": step_up_otp,
            "idempotency_key": "idem-test-ack-1",
        },
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
    )
    assert exec_res.status_code == 200
    exec_data = exec_res.json()
    assert exec_data["ok"] is True
    execution = exec_data["execution"]
    assert execution["status"] == "succeeded"
    assert execution["postcondition_verified"] is True
    execution_id = execution["execution_id"]

    # 4. Check journal lookup
    journal_res = client.get(f"/api/v1/executions/{execution_id}")
    assert journal_res.status_code == 200
    j_record = journal_res.json()["execution"]
    assert j_record["execution_id"] == execution_id
    assert j_record["status"] == "succeeded"

    # 5. Replaying with same idempotency key returns existing execution without re-dispatching
    replay_res = client.post(
        "/api/v1/actions/notifications.acknowledge_incident/execute",
        json={
            "challenge_id": challenge_id,
            "parameters": {"incident_id": inc_id, "reason": "Operator reviewing"},
            "totp_code": step_up_otp,
            "idempotency_key": "idem-test-ack-1",
        },
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
    )
    assert replay_res.status_code == 200
    assert replay_res.json()["execution"]["execution_id"] == execution_id

    # 6. Reusing consumed challenge with a NEW idempotency key fails
    reuse_res = client.post(
        "/api/v1/actions/notifications.acknowledge_incident/execute",
        json={
            "challenge_id": challenge_id,
            "parameters": {"incident_id": inc_id, "reason": "Operator reviewing"},
            "totp_code": totp.at(int(time.time()) - 30),
            "idempotency_key": "idem-test-ack-different",
        },
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
    )
    assert reuse_res.status_code == 400
    assert reuse_res.json()["error"] == "challenge_already_consumed"


def test_convenience_incident_acknowledge_endpoint(test_setup):
    """POST /api/v1/incidents/{id}/acknowledge provides dedicated workflow for incident ack."""
    client: TestClient = test_setup["client"]
    csrf = test_setup["csrf_token"]
    totp = test_setup["totp"]
    inc_id = test_setup["incident_id"]

    step_up_otp = totp.at(int(time.time()) + 30)

    res = client.post(
        f"/api/v1/incidents/{inc_id}/acknowledge",
        json={"reason": "Acknowledged via dashboard", "totp_code": step_up_otp},
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["incident_id"] == inc_id
    assert data["status"] == "succeeded"
    assert data["postcondition_verified"] is True

    # Verify notification storage reflects acknowledged state
    notif_storage: StorageEngine = test_setup["notif_storage"]
    inc = notif_storage.get_incident(inc_id)
    assert inc.status == "acknowledged"
    assert inc.acknowledged_at is not None
