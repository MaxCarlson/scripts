"""Targeted tests for Section 6: Barrier reconciliation identity, occurrence matching, and typed verification.

Invariants:
1. Concurrency key resolves to 'notifications:incident:{incident_id}' for per-incident serialization.
2. Reopened incidents (occurrence_count advanced) reject barrier clearance with occurrence_mismatch.
3. Incident with status 'resolved' without acknowledgment rejects barrier clearance (must be 'acknowledged').
4. Stale acknowledgment that occurred before dispatch timestamp is rejected.
5. Resource Coordinator recovery barrier clearance is strictly forbidden (coordinator_recovery_prohibited).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import pytest

from notifications.models import Incident
from notifications.storage import StorageEngine
from remote_control.actions.models import (
    ActionDefinition,
    ActionEffect,
    ActionExecutionRecord,
    ConfirmationPolicy,
    DispatchPhase,
    EmptyParameters,
    ExecutionState,
)
from remote_control.actions.registry import ActionRegistry
from remote_control.actions.storage import ActionStorage
from remote_control.actions.verifiers import (
    IncidentAcknowledgementVerifier,
    get_barrier_verifier,
)
from remote_control.config import RemoteControlConfig
from remote_control.external.client import SimulatedTailscaleClient
from remote_control.external.service import ExternalExposureService


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def test_concurrency_key_per_incident_resolution() -> None:
    """ActionDefinition resolves concurrency_key template with parameters."""
    registry = ActionRegistry()
    ack_def = registry.get("notifications.acknowledge_incident")
    assert ack_def is not None

    key1 = ack_def.resolve_concurrency_key({"incident_id": "inc_123"})
    assert key1 == "notifications:incident:inc_123"

    key2 = ack_def.resolve_concurrency_key({"incident_id": "inc_456"})
    assert key2 == "notifications:incident:inc_456"
    assert key1 != key2


def test_reopened_incident_occurrence_mismatch_rejected(tmp_path: Path) -> None:
    """When an incident reopens and its occurrence_count advances, barrier clearance must be rejected."""
    notif_db = tmp_path / "events.db"
    notif_engine = StorageEngine(notif_db)
    notif_engine.migrate()

    # Incident reopened: occurrence_count is now 2, active_occurrence_id is occ_2
    notif_engine.save_incident(Incident(
        incident_id="inc_reopened",
        source="system",
        incident_key="key_1",
        active_occurrence_id="occ_2",
        status="acknowledged",
        severity="high",
        summary="Reopened incident",
        first_seen="2026-11-11T00:00:00Z",
        last_seen="2026-11-11T01:00:00Z",
        occurrence_count=2,
    ))

    # Barrier was set for occurrence_count 1
    verifier = IncidentAcknowledgementVerifier(notifications_db_path=notif_db)
    result = verifier.verify(
        resource_key="notifications:incident:inc_reopened",
        barrier_record={"execution_id": "exec_reopened_01"},
        evidence_payload={"expected_occurrence": 1},
    )
    assert result.verified is False
    assert result.error == "occurrence_mismatch"
    assert "occurrence count" in result.message


def test_status_resolved_without_acknowledgment_rejected(tmp_path: Path) -> None:
    """An incident that auto-resolved without explicit acknowledgment cannot clear an acknowledgment barrier."""
    notif_db = tmp_path / "events.db"
    notif_engine = StorageEngine(notif_db)
    notif_engine.migrate()

    notif_engine.save_incident(Incident(
        incident_id="inc_resolved",
        source="system",
        incident_key="key_2",
        active_occurrence_id="occ_1",
        status="resolved",  # NOT acknowledged
        severity="medium",
        summary="Auto-resolved incident",
        first_seen="2026-11-11T00:00:00Z",
        last_seen="2026-11-11T01:00:00Z",
        occurrence_count=1,
    ))

    verifier = IncidentAcknowledgementVerifier(notifications_db_path=notif_db)
    result = verifier.verify(
        resource_key="notifications:incident:inc_resolved",
        barrier_record={"execution_id": "exec_resolved_01"},
    )
    assert result.verified is False
    assert result.error == "state_mismatch"
    assert "not 'acknowledged'" in result.message


def test_stale_pre_dispatch_state_rejected(tmp_path: Path) -> None:
    """An acknowledgment timestamp preceding the barrier dispatch timestamp is rejected."""
    notif_db = tmp_path / "events.db"
    notif_engine = StorageEngine(notif_db)
    notif_engine.migrate()

    # Incident was acknowledged at 00:30:00Z
    notif_engine.save_incident(Incident(
        incident_id="inc_stale",
        source="system",
        incident_key="key_3",
        active_occurrence_id="occ_1",
        status="acknowledged",
        severity="low",
        summary="Stale incident",
        first_seen="2026-11-11T00:00:00Z",
        last_seen="2026-11-11T00:30:00Z",
        acknowledged_at="2026-11-11T00:30:00Z",
        occurrence_count=1,
    ))

    auth_db = tmp_path / "auth.db"
    store = ActionStorage(auth_db)
    # Execution journal recorded dispatch starting at 01:00:00Z (after the incident was acknowledged)
    store.reserve_execution(ActionExecutionRecord(
        execution_id="exec_stale_01",
        action_id="notifications.acknowledge_incident",
        action_version="1.0.0",
        actor_id="admin_op",
        session_id_hash="sess_hash",
        device_id="device_1",
        idempotency_key_hash="hash_stale",
        arguments_digest="digest",
        state_fingerprint="fp",
        started_at="2026-11-11T01:00:00Z",
        status=ExecutionState.RESERVED,
        dispatch_phase=DispatchPhase.DISPATCH_STARTED.value,
        resource_key="notifications:incident:inc_stale",
    ))

    verifier = IncidentAcknowledgementVerifier(notifications_db_path=notif_db, action_storage=store)
    result = verifier.verify(
        resource_key="notifications:incident:inc_stale",
        barrier_record={"execution_id": "exec_stale_01"},
    )
    assert result.verified is False
    assert result.error == "state_mismatch"
    assert "predates execution dispatch" in result.message


def test_valid_occurrence_and_status_clears_barrier(tmp_path: Path) -> None:
    """Matching incident occurrence, acknowledged status, and valid timestamp succeeds."""
    notif_db = tmp_path / "events.db"
    notif_engine = StorageEngine(notif_db)
    notif_engine.migrate()

    notif_engine.save_incident(Incident(
        incident_id="inc_valid",
        source="system",
        incident_key="key_4",
        active_occurrence_id="occ_1",
        status="acknowledged",
        severity="high",
        summary="Valid incident",
        first_seen="2026-11-11T00:00:00Z",
        last_seen="2026-11-11T02:00:00Z",
        occurrence_count=1,
    ))

    auth_db = tmp_path / "auth.db"
    store = ActionStorage(auth_db)
    res_key = "notifications:incident:inc_valid"
    exec_id = "exec_valid_ack_001"

    store.set_resource_barrier(
        resource_key=res_key,
        execution_id=exec_id,
        reason="Dispatched but worker timed out",
    )
    assert store.get_active_barrier(res_key) is not None

    cfg = RemoteControlConfig(auth_db_path=auth_db, notifications_db_path=notif_db)
    client = SimulatedTailscaleClient(state_file=tmp_path / ".ts.json")
    service = ExternalExposureService(config=cfg, storage=store, client=client)

    # Reconcile with valid source verification
    res = service.reconcile_barrier(
        resource_key=res_key,
        evidence="Verified in notifications broker",
        apply=True,
        notifications_db_path=notif_db,
    )
    assert res["ok"] is True
    assert res["applied"] is True
    assert store.get_active_barrier(res_key) is None


def test_coordinator_recovery_barrier_clearance_strictly_prohibited(tmp_path: Path) -> None:
    """Attempting to clear a Resource Coordinator recovery barrier must fail with coordinator_recovery_prohibited."""
    auth_db = tmp_path / "auth.db"
    store = ActionStorage(auth_db)
    coord_keys = ["coordinator", "coordinator.recovery", "resource:gpu.inference"]

    cfg = RemoteControlConfig(auth_db_path=auth_db)
    client = SimulatedTailscaleClient(state_file=tmp_path / ".ts.json")
    service = ExternalExposureService(config=cfg, storage=store, client=client)

    for k in coord_keys:
        store.set_resource_barrier(
            resource_key=k,
            execution_id="exec_coord_001",
            reason="Synthetic hold",
        )
        res = service.reconcile_barrier(
            resource_key=k,
            evidence="Operator claims it is safe",
            apply=True,
        )
        assert res["ok"] is False
        assert res["error"] == "coordinator_recovery_prohibited"
        assert store.get_active_barrier(k) is not None
