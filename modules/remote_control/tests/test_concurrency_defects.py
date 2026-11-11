"""Regression test suite for Defects A through G:
- Defect A: Execution reservation race & tuple truthiness.
- Defect B: Incident acknowledgement confirmation bypass elimination & reopened occurrence scoping.
- Defect C: Cross-process serialization via SQLite leases & TOCTOU state drift prevention.
- Defect D: Idempotency context binding and conflict rejection (HTTP 409).
- Defect E: Direct read action execution without TypeError or challenge requirements.
- Defect F: Step-up authentication ordering preventing TOTP burn on invalid challenge.
- Defect G: Error message redaction, sensitive data scrubbing, and valid 64KB bounded JSON payloads.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict

from fastapi.testclient import TestClient
import pyotp
import pytest

from notifications.storage import (
    SCHEMA_VERSION_1_SQL,
    SCHEMA_VERSION_2_SQL,
    StorageEngine,
)
from remote_control.actions.adapters.synthetic import SyntheticCoordinatorRecoveryAdapter
from remote_control.actions.models import (
    ActionDefinition,
    ActionEffect,
    ActionExecutionRecord,
    ConfirmationPolicy,
    EmptyParameters,
    ExecutionState,
    PostconditionPolicy,
    StepUpPolicy,
)
from remote_control.actions.registry import ActionRegistry
from remote_control.actions.service import (
    ActionService,
    ActionServiceError,
    ChallengeNotFoundError,
    StateDriftError,
    StepUpAuthenticationError,
)
from remote_control.actions.state_fingerprint import compute_arguments_digest, redact_sensitive_data
from remote_control.actions.storage import ActionStorage
from remote_control.app import create_app
from remote_control.auth.service import AuthService
from remote_control.auth.storage import AuthStorage
from remote_control.config import RemoteControlConfig


def _setup_test_app_and_client(tmp_path: Path):
    """Helper to set up isolated test app, databases, bootstrapped operator, and logged-in client."""
    auth_db = tmp_path / "auth.db"
    notif_db = tmp_path / "notifications.db"
    hc_cfg = tmp_path / "healthchecks.json"

    # Seed notification schema with full FK relationships
    notif_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(notif_db) as conn:
        conn.executescript(SCHEMA_VERSION_1_SQL)
        conn.executescript(SCHEMA_VERSION_2_SQL)
        now_iso = "2026-11-11T12:00:00Z"
        conn.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (1, ?)", (now_iso,))
        conn.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (2, ?)", (now_iso,))
        
        # Seed event
        conn.execute(
            """
            INSERT INTO events (
                event_id, schema_version, source, kind, incident_key, severity,
                lifecycle, occurred_at, received_at, summary, correlation_id,
                resource, details_ref, labels_json, payload_json, payload_sha256
            ) VALUES (
                'evt-001', 1, 'system_monitor', 'disk_full', 'disk_c_alert', 'critical',
                'active', ?, ?, 'Disk C space critically low', 'corr-1',
                'C:', NULL, '{}', '{"free_gb": 1.2}', 'sha256-dummy'
            )
            """,
            (now_iso, now_iso),
        )

        # Seed open incident
        conn.execute(
            """
            INSERT INTO incidents (
                incident_id, source, incident_key, active_occurrence_id,
                status, severity, summary, first_seen, last_seen,
                acknowledged_at, resolved_at, last_notified_at, occurrence_count
            ) VALUES (
                'inc-001', 'system_monitor', 'disk_c_alert', 'occ-001',
                'open', 'critical', 'Disk C space critically low', ?, ?,
                NULL, NULL, ?, 1
            )
            """,
            (now_iso, now_iso, now_iso),
        )

        # Seed occurrence
        conn.execute(
            """
            INSERT INTO occurrences (
                occurrence_id, incident_id, status, severity, opened_at, closed_at, resolution_evidence
            ) VALUES (
                'occ-001', 'inc-001', 'open', 'critical', ?, NULL, NULL
            )
            """,
            (now_iso,),
        )

        # Seed transition
        conn.execute(
            """
            INSERT INTO transitions (
                incident_id, occurrence_id, event_id, from_status, to_status,
                transition_name, timestamp, details_json
            ) VALUES (
                'inc-001', 'occ-001', 'evt-001', NULL, 'open',
                'open_incident', ?, '{"reason": "threshold_breach"}'
            )
            """,
            (now_iso,),
        )

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

    auth_svc = app.state.auth_service
    totp_secret = "JBSWY3DPEHPK3PXP"
    auth_svc.bootstrap(
        username="admin",
        password="ValidPassword123!",
        totp_secret=totp_secret,
        ip_address="127.0.0.1",
    )

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
    csrf_token = login_res.json()["csrf_token"]

    return {
        "app": app,
        "client": client,
        "csrf_token": csrf_token,
        "totp_secret": totp_secret,
        "totp": totp,
        "notif_db": notif_db,
        "auth_db": auth_db,
    }


# ── Defect A: Execution Reservation Race & Tuple Truthiness ──────────────────


@pytest.mark.asyncio
async def test_defect_a_reservation_race_tuple_truthiness(tmp_path: Path):
    """Defect A: ActionStorage.reserve_execution returns (bool, record).
    ActionService must unpack the tuple and never invoke adapter when created is False.
    """
    db_path = tmp_path / "auth.db"
    storage = ActionStorage(db_path)
    auth_storage = AuthStorage(db_path)
    auth_service = AuthService(auth_storage, RemoteControlConfig(auth_db_path=db_path))
    _, totp_secret, _ = auth_service.bootstrap("admin", "SuperSecretPassword123!", totp_secret="JBSWY3DPEHPK3PXP")

    registry = ActionRegistry()
    synth_adapter = SyntheticCoordinatorRecoveryAdapter(recovery_required=True, inhibition_active=True)
    registry.bind_handler("resource_coordinator.request_guarded_recovery", synth_adapter)

    # Enable for synthetic testing with operator.action permission
    synth_def = ActionDefinition(
        action_id="resource_coordinator.request_guarded_recovery",
        version="1.0.0",
        label="Guarded Recovery",
        description="Synthetic test action",
        module="resource_coordinator",
        effect=ActionEffect.MUTATION,
        required_permission="operator.action",
        parameter_model=EmptyParameters,
        timeout_seconds=5.0,
        concurrency_key="coordinator:recovery",
        confirmation_policy=ConfirmationPolicy.EXPLICIT_CHALLENGE,
        step_up_policy=StepUpPolicy.TOTP,
        postcondition_policy=PostconditionPolicy.VERIFY_SOURCE_STATE,
        enabled=True,
    )
    registry._actions["resource_coordinator.request_guarded_recovery"] = synth_def

    service = ActionService(storage, registry, auth_storage)

    # Prepare challenge
    prep = await service.prepare_action(
        action_id="resource_coordinator.request_guarded_recovery",
        arguments={},
        actor_id="admin",
        actor_role="operator",
        session_id_hash="sess_hash_1",
        device_id="dev-1",
    )
    challenge_id = prep["challenge_id"]

    totp = pyotp.TOTP(totp_secret)
    totp_code = totp.now()

    # First execution succeeds and calls adapter once
    rec1 = await service.execute_action(
        action_id="resource_coordinator.request_guarded_recovery",
        challenge_id=challenge_id,
        arguments={},
        actor_id="admin",
        actor_role="operator",
        session_id_hash="sess_hash_1",
        device_id="dev-1",
        idempotency_key="idemp_key_defect_a",
        totp_code=totp_code,
    )
    assert rec1.status == ExecutionState.SUCCEEDED
    assert synth_adapter.execution_count == 1

    # Second call with SAME idempotency key must return existing execution WITHOUT executing adapter again
    rec2 = await service.execute_action(
        action_id="resource_coordinator.request_guarded_recovery",
        challenge_id=challenge_id,
        arguments={},
        actor_id="admin",
        actor_role="operator",
        session_id_hash="sess_hash_1",
        device_id="dev-1",
        idempotency_key="idemp_key_defect_a",
        totp_code=totp_code,
    )
    assert rec2.execution_id == rec1.execution_id
    assert synth_adapter.execution_count == 1  # STILL 1!


# ── Defect B: Incident Acknowledgement Confirmation Bypass & Reopen Scope ─────


def test_defect_b_acknowledge_confirmation_bypass_and_reopen_scope(tmp_path: Path):
    """Defect B: POST /api/v1/incidents/{id}/acknowledge must require pre-issued challenge_id
    and properly scope idempotency keys across reopened incident occurrences.
    """
    ctx = _setup_test_app_and_client(tmp_path)
    client: TestClient = ctx["client"]
    csrf = ctx["csrf_token"]
    totp: pyotp.TOTP = ctx["totp"]
    notif_db: Path = ctx["notif_db"]

    # 1. Reject acknowledgement without challenge_id (422)
    step_up_otp = totp.at(int(time.time()) + 30)
    res_no_ch = client.post(
        "/api/v1/incidents/inc-001/acknowledge",
        json={"reason": "Test without challenge", "totp_code": step_up_otp},
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
    )
    assert res_no_ch.status_code == 422
    assert res_no_ch.json()["error"] == "challenge_required"

    # 2. Prepare challenge
    prep_res = client.post(
        "/api/v1/actions/notifications.acknowledge_incident/prepare",
        json={"parameters": {"incident_id": "inc-001", "reason": "Acknowledged occurrence 1"}},
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
    )
    assert prep_res.status_code == 200
    ch1 = prep_res.json()["challenge_id"]

    # 3. Acknowledge occurrence 1
    res1 = client.post(
        "/api/v1/incidents/inc-001/acknowledge",
        json={"reason": "Acknowledged occurrence 1", "totp_code": step_up_otp, "challenge_id": ch1},
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
    )
    assert res1.status_code == 200
    assert res1.json()["status"] == "succeeded"

    # Verify notification storage reflects acknowledged state
    notif_storage = StorageEngine(notif_db)
    inc = notif_storage.get_incident("inc-001")
    assert inc.status == "acknowledged"

    # 4. Simulate incident reopening (new occurrence opened)
    with notif_storage.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO occurrences (
                occurrence_id, incident_id, status, severity, opened_at, closed_at, resolution_evidence
            ) VALUES (
                'occ-002', 'inc-001', 'open', 'critical', '2026-11-11T13:00:00Z', NULL, NULL
            )
            """
        )
        conn.execute("UPDATE incidents SET status = 'open', active_occurrence_id = 'occ-002', occurrence_count = 2, last_seen = '2026-11-11T13:00:00Z' WHERE incident_id = 'inc-001'")

    # 5. Attempting to reuse old challenge ch1 with a fresh idempotency key must fail (consumed)
    step_up_otp2 = totp.at(int(time.time()) + 60)
    res_reuse = client.post(
        "/api/v1/incidents/inc-001/acknowledge",
        json={"reason": "Acknowledged occurrence 2", "totp_code": step_up_otp2, "challenge_id": ch1},
        headers={
            "Origin": "http://testserver",
            "X-CSRF-Token": csrf,
            "X-Idempotency-Key": "fresh_idemp_key_attempt_reuse",
        },
    )
    assert res_reuse.status_code == 400
    assert res_reuse.json()["error"] == "challenge_already_consumed"

    # 6. Prepare new challenge for occurrence 2
    prep_res2 = client.post(
        "/api/v1/actions/notifications.acknowledge_incident/prepare",
        json={"parameters": {"incident_id": "inc-001", "reason": "Acknowledged occurrence 2"}},
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
    )
    assert prep_res2.status_code == 200
    ch2 = prep_res2.json()["challenge_id"]
    assert ch2 != ch1

    # Clear consumed timesteps to simulate next time window without waiting 30 wall-clock seconds
    auth_db: Path = ctx["auth_db"]
    with sqlite3.connect(auth_db) as conn:
        conn.execute("DELETE FROM used_totp_timesteps")

    # 7. Acknowledge occurrence 2 with new challenge: succeeds without idempotency collision
    res2 = client.post(
        "/api/v1/incidents/inc-001/acknowledge",
        json={"reason": "Acknowledged occurrence 2", "totp_code": totp.now(), "challenge_id": ch2},
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
    )
    assert res2.status_code == 200
    assert res2.json()["status"] == "succeeded"
    assert res2.json()["execution_id"] != res1.json()["execution_id"]


# ── Defect C: Cross-Process Serialization & TOCTOU State Drift Prevention ─────


@pytest.mark.asyncio
async def test_defect_c_cross_process_locks_and_toctou_prevention(tmp_path: Path):
    """Defect C: action_resource_locks provides cross-process serialization;
    state re-inspection inside the lock boundary detects state drift (TOCTOU).
    """
    db_path = tmp_path / "auth.db"
    storage = ActionStorage(db_path)
    auth_storage = AuthStorage(db_path)
    auth_service = AuthService(auth_storage, RemoteControlConfig(auth_db_path=db_path))
    _, totp_secret, _ = auth_service.bootstrap("admin", "SuperSecretPassword123!", totp_secret="JBSWY3DPEHPK3PXP")

    # 1. Verify cross-process resource locking primitives
    res_key = "test:resource:lock"
    assert storage.acquire_resource_lock(res_key, "exec-1", ttl_seconds=10.0) is True
    # Second holder cannot acquire while active
    assert storage.acquire_resource_lock(res_key, "exec-2", ttl_seconds=10.0) is False
    # Re-acquisition by same holder succeeds
    assert storage.acquire_resource_lock(res_key, "exec-1", ttl_seconds=10.0) is True
    # Release lock
    storage.release_resource_lock(res_key, "exec-1")
    # Now holder 2 can acquire
    assert storage.acquire_resource_lock(res_key, "exec-2", ttl_seconds=10.0) is True
    storage.release_resource_lock(res_key, "exec-2")

    # 2. Test TOCTOU state drift inside execution boundary
    synth_adapter = SyntheticCoordinatorRecoveryAdapter(
        recovery_required=True,
        inhibition_active=True,
        request_id="req-initial",
    )
    registry = ActionRegistry()
    registry.bind_handler("resource_coordinator.request_guarded_recovery", synth_adapter)

    synth_def = ActionDefinition(
        action_id="resource_coordinator.request_guarded_recovery",
        version="1.0.0",
        label="Guarded Recovery",
        description="Synthetic test action",
        module="resource_coordinator",
        effect=ActionEffect.MUTATION,
        required_permission="operator.action",
        parameter_model=EmptyParameters,
        timeout_seconds=5.0,
        concurrency_key="coordinator:recovery",
        confirmation_policy=ConfirmationPolicy.EXPLICIT_CHALLENGE,
        step_up_policy=StepUpPolicy.TOTP,
        postcondition_policy=PostconditionPolicy.VERIFY_SOURCE_STATE,
        enabled=True,
    )
    registry._actions["resource_coordinator.request_guarded_recovery"] = synth_def

    service = ActionService(storage, registry, auth_storage)

    # Prepare challenge bound to initial state
    prep = await service.prepare_action(
        action_id="resource_coordinator.request_guarded_recovery",
        arguments={},
        actor_id="admin",
        actor_role="operator",
        session_id_hash="sess_hash_c",
        device_id="dev-c",
    )
    ch_id = prep["challenge_id"]

    # Mutate source state right before execution to simulate concurrent background change
    synth_adapter.request_id = "req-drifted-in-background"

    totp = pyotp.TOTP(totp_secret)
    with pytest.raises(StateDriftError) as exc_info:
        await service.execute_action(
            action_id="resource_coordinator.request_guarded_recovery",
            challenge_id=ch_id,
            arguments={},
            actor_id="admin",
            actor_role="operator",
            session_id_hash="sess_hash_c",
            device_id="dev-c",
            idempotency_key="idemp_toctou_1",
            totp_code=totp.now(),
        )

    assert exc_info.value.error_code == "state_drift_detected"
    assert "source state changed" in str(exc_info.value).lower()
    # Adapter was NOT called because drift was detected inside the lock before dispatch
    assert synth_adapter.execution_count == 0
    # Lock was cleanly released
    assert storage.get_resource_lock("coordinator:recovery") is None


# ── Defect D: Idempotency Context Binding ─────────────────────────────────────


@pytest.mark.asyncio
async def test_defect_d_idempotency_binding_conflict_detection(tmp_path: Path):
    """Defect D: Using the same idempotency key with different parameters,
    actor, or device must be rejected with HTTP 409 idempotency_conflict.
    """
    db_path = tmp_path / "auth.db"
    storage = ActionStorage(db_path)
    auth_storage = AuthStorage(db_path)
    auth_service = AuthService(auth_storage, RemoteControlConfig(auth_db_path=db_path))
    _, totp_secret, _ = auth_service.bootstrap("admin", "SuperSecretPassword123!", totp_secret="JBSWY3DPEHPK3PXP")

    synth_adapter = SyntheticCoordinatorRecoveryAdapter(recovery_required=True, inhibition_active=True)
    registry = ActionRegistry()
    registry.bind_handler("resource_coordinator.request_guarded_recovery", synth_adapter)

    synth_def = ActionDefinition(
        action_id="resource_coordinator.request_guarded_recovery",
        version="1.0.0",
        label="Guarded Recovery",
        description="Synthetic test action",
        module="resource_coordinator",
        effect=ActionEffect.MUTATION,
        required_permission="operator.action",
        parameter_model=EmptyParameters,
        timeout_seconds=5.0,
        concurrency_key="coordinator:recovery",
        confirmation_policy=ConfirmationPolicy.NONE,
        step_up_policy=StepUpPolicy.NONE,
        enabled=True,
    )
    registry._actions["resource_coordinator.request_guarded_recovery"] = synth_def

    service = ActionService(storage, registry, auth_storage)

    # 1. Execute initial action
    rec = await service.execute_action(
        action_id="resource_coordinator.request_guarded_recovery",
        challenge_id=None,
        arguments={},
        actor_id="admin",
        actor_role="operator",
        session_id_hash="sess_1",
        device_id="dev-1",
        idempotency_key="reused_key_1",
    )
    assert rec.status == ExecutionState.SUCCEEDED

    # 2. Re-send with different actor: must raise ActionServiceError with 409
    with pytest.raises(ActionServiceError) as exc_actor:
        await service.execute_action(
            action_id="resource_coordinator.request_guarded_recovery",
            challenge_id=None,
            arguments={},
            actor_id="different_actor",
            actor_role="operator",
            session_id_hash="sess_1",
            device_id="dev-1",
            idempotency_key="reused_key_1",
        )
    assert exc_actor.value.error_code == "idempotency_conflict"
    assert exc_actor.value.status_code == 409

    # 3. Re-send with different device: must raise ActionServiceError with 409
    with pytest.raises(ActionServiceError) as exc_device:
        await service.execute_action(
            action_id="resource_coordinator.request_guarded_recovery",
            challenge_id=None,
            arguments={},
            actor_id="admin",
            actor_role="operator",
            session_id_hash="sess_1",
            device_id="different_device",
            idempotency_key="reused_key_1",
        )
    assert exc_device.value.error_code == "idempotency_conflict"
    assert exc_device.value.status_code == 409


# ── Defect E: Direct Read Actions Execution & No TypeError ────────────────────


def test_defect_e_direct_read_actions_execution_no_typeerror(tmp_path: Path):
    """Defect E: Direct HTTP execution of all 4 read capabilities:
    resource_coordinator.status, resource_coordinator.inspect_recovery,
    notifications.health, notifications.incident_detail.
    Must succeed without TypeError on actor_id or requiring challenges/TOTP.
    """
    ctx = _setup_test_app_and_client(tmp_path)
    client: TestClient = ctx["client"]
    csrf = ctx["csrf_token"]

    read_actions = [
        ("resource_coordinator.status", {}),
        ("resource_coordinator.inspect_recovery", {}),
        ("notifications.health", {}),
        ("notifications.incident_detail", {"incident_id": "inc-001"}),
    ]

    for action_id, params in read_actions:
        res = client.post(
            f"/api/v1/actions/{action_id}/execute",
            json={"parameters": params},
            headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
        )
        assert res.status_code == 200, f"Action {action_id} failed with {res.status_code}: {res.text}"
        data = res.json()
        assert data["ok"] is True
        assert data["action_id"] == action_id
        assert data["read_only"] is True
        assert "result" in data
        assert data["result"]["ok"] is True


# ── Defect F: Step-Up Ordering Prevents TOTP Burn ─────────────────────────────


@pytest.mark.asyncio
async def test_defect_f_step_up_ordering_prevents_totp_burn(tmp_path: Path):
    """Defect F: Invalid or expired challenge must be rejected BEFORE consuming TOTP.
    Operator's TOTP token remains unconsumed so they can retry without waiting 30 seconds.
    """
    db_path = tmp_path / "auth.db"
    storage = ActionStorage(db_path)
    auth_storage = AuthStorage(db_path)
    auth_service = AuthService(auth_storage, RemoteControlConfig(auth_db_path=db_path))
    _, totp_secret, _ = auth_service.bootstrap("admin", "SuperSecretPassword123!", totp_secret="JBSWY3DPEHPK3PXP")

    synth_adapter = SyntheticCoordinatorRecoveryAdapter(recovery_required=True, inhibition_active=True)
    registry = ActionRegistry()
    registry.bind_handler("resource_coordinator.request_guarded_recovery", synth_adapter)

    synth_def = ActionDefinition(
        action_id="resource_coordinator.request_guarded_recovery",
        version="1.0.0",
        label="Guarded Recovery",
        description="Synthetic test action",
        module="resource_coordinator",
        effect=ActionEffect.MUTATION,
        required_permission="operator.action",
        parameter_model=EmptyParameters,
        timeout_seconds=5.0,
        concurrency_key="coordinator:recovery",
        confirmation_policy=ConfirmationPolicy.EXPLICIT_CHALLENGE,
        step_up_policy=StepUpPolicy.TOTP,
        postcondition_policy=PostconditionPolicy.VERIFY_SOURCE_STATE,
        enabled=True,
    )
    registry._actions["resource_coordinator.request_guarded_recovery"] = synth_def

    service = ActionService(storage, registry, auth_storage)

    totp = pyotp.TOTP(totp_secret)
    valid_code = totp.now()

    # 1. Attempt with non-existent challenge ID
    with pytest.raises(ChallengeNotFoundError):
        await service.execute_action(
            action_id="resource_coordinator.request_guarded_recovery",
            challenge_id="non_existent_cld_12345",
            arguments={},
            actor_id="admin",
            actor_role="operator",
            session_id_hash="sess_f",
            device_id="dev-f",
            idempotency_key="idemp_f_1",
            totp_code=valid_code,
        )

    # 2. Verify TOTP code was NOT consumed: the same valid_code can still be used!
    prep = await service.prepare_action(
        action_id="resource_coordinator.request_guarded_recovery",
        arguments={},
        actor_id="admin",
        actor_role="operator",
        session_id_hash="sess_f",
        device_id="dev-f",
    )
    ch_id = prep["challenge_id"]

    rec = await service.execute_action(
        action_id="resource_coordinator.request_guarded_recovery",
        challenge_id=ch_id,
        arguments={},
        actor_id="admin",
        actor_role="operator",
        session_id_hash="sess_f",
        device_id="dev-f",
        idempotency_key="idemp_f_2",
        totp_code=valid_code,
    )
    assert rec.status == ExecutionState.SUCCEEDED


# ── Defect G: Error Redaction & Payload Bounding ──────────────────────────────


def test_defect_g_error_redaction_and_payload_bounding(tmp_path: Path):
    """Defect G: redact_sensitive_data scrubs paths and secrets;
    update_execution bounds payloads to 64KB valid JSON.
    """
    storage = ActionStorage(tmp_path / "auth.db")

    # 1. Redact sensitive string
    raw_error = "Failed connecting to C:\\Users\\Administrator\\secrets\\token.txt with Bearer secret_live_token_12345 and OTP 987654"
    scrubbed = redact_sensitive_data(raw_error)
    assert "Administrator" not in scrubbed
    assert "secret_live_token_12345" not in scrubbed
    assert "987654" not in scrubbed
    assert "[REDACTED]" in scrubbed
    assert "[REDACTED_OTP]" in scrubbed

    # 2. Record execution with oversized details payload (> 100KB)
    large_payload = {"entry_" + str(i): "x" * 200 for i in range(1000)}
    exec_id = "exec_large_1"

    rec = ActionExecutionRecord(
        execution_id=exec_id,
        action_id="test.action",
        action_version="1.0.0",
        actor_id="admin",
        session_id_hash="sess_g",
        device_id="dev-g",
        idempotency_key_hash="hash_g",
        arguments_digest="args_g",
        state_fingerprint="fp_g",
        started_at="2026-11-11T12:00:00Z",
        status=ExecutionState.RESERVED,
    )
    storage.reserve_execution(rec)

    storage.update_execution(
        execution_id=exec_id,
        status=ExecutionState.SUCCEEDED,
        finished_at="2026-11-11T12:00:01Z",
        summary="Large payload test",
        details=large_payload,
    )

    stored = storage.get_execution(exec_id)
    assert stored is not None
    assert stored.details_json is not None
    assert len(stored.details_json) <= 65536
    # Must be valid parseable JSON
    parsed = json.loads(stored.details_json)
    assert parsed.get("truncated") is True
