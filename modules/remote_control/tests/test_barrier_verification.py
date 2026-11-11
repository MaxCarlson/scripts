"""Unit tests for Stage E: Authoritative typed barrier verification.

Demonstrates:
- Free-text explanations without authoritative verifiers are rejected (verification_unavailable).
- Resource Coordinator recovery barriers cannot be cleared (coordinator_recovery_prohibited).
- Incident acknowledgement barriers require genuine source verification from notifications storage.
- Dry-run verification reports state fingerprint and does not mutate.
- Authoritative clearance atomically updates barrier and records audit.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import pytest

from notifications.models import Incident
from notifications.storage import StorageEngine
from remote_control.actions.storage import ActionStorage
from remote_control.config import RemoteControlConfig
from remote_control.external.client import SimulatedTailscaleClient
from remote_control.external.service import ExternalExposureService


@pytest.fixture
def test_setup(tmp_path: Path) -> Dict[str, Any]:
    rc_db = tmp_path / "rc_test.db"
    notif_db = tmp_path / "notif_test.db"

    # Set up notifications database
    notif_engine = StorageEngine(notif_db)
    notif_engine.migrate()

    # Set up remote control storage
    rc_store = ActionStorage(rc_db)
    cfg = RemoteControlConfig(
        auth_db_path=rc_db,
        notifications_db_path=notif_db,
        cookie_security_mode="auto",
    )
    client = SimulatedTailscaleClient(state_file=tmp_path / ".tailscale.json")
    service = ExternalExposureService(config=cfg, storage=rc_store, client=client)

    return {
        "rc_db": rc_db,
        "notif_db": notif_db,
        "notif_engine": notif_engine,
        "rc_store": rc_store,
        "service": service,
    }


def test_reconcile_nonexistent_barrier(test_setup: Dict[str, Any]) -> None:
    service: ExternalExposureService = test_setup["service"]
    res = service.reconcile_barrier(
        resource_key="nonexistent:key",
        evidence="Some operator claim",
    )
    assert res["ok"] is False
    assert res["error"] == "barrier_not_found"


def test_coordinator_recovery_barrier_prohibited(test_setup: Dict[str, Any]) -> None:
    rc_store: ActionStorage = test_setup["rc_store"]
    service: ExternalExposureService = test_setup["service"]

    # Establish barrier on coordinator recovery
    rc_store.set_resource_barrier(
        resource_key="coordinator:recovery",
        execution_id="exec_coord_001",
        reason="Synthetic test barrier",
        barrier_status="locked_unresolved",
    )

    # Reconcile attempt MUST fail closed even with apply=True and operator evidence
    res = service.reconcile_barrier(
        resource_key="coordinator:recovery",
        evidence="Operator claims GPU was restarted safely",
        apply=True,
    )
    assert res["ok"] is False
    assert res["applied"] is False
    assert res["error"] == "coordinator_recovery_prohibited"
    assert "prohibited" in res["message"]

    # Barrier remains active
    assert rc_store.get_active_barrier("coordinator:recovery") is not None


def test_unsupported_resource_rejects_free_text(test_setup: Dict[str, Any]) -> None:
    rc_store: ActionStorage = test_setup["rc_store"]
    service: ExternalExposureService = test_setup["service"]

    rc_store.set_resource_barrier(
        resource_key="arbitrary:subsystem:task",
        execution_id="exec_arb_001",
        reason="Dispatched but unknown outcome",
        barrier_status="locked_unresolved",
    )

    # Free-text evidence without a registered source verifier MUST be rejected
    res = service.reconcile_barrier(
        resource_key="arbitrary:subsystem:task",
        evidence="I manually verified the task finished fine in logs.",
        apply=True,
    )
    assert res["ok"] is False
    assert res["applied"] is False
    assert res["error"] == "verification_unavailable"
    assert "No authoritative source verifier is registered" in res["message"]

    # Barrier is still active
    assert rc_store.get_active_barrier("arbitrary:subsystem:task") is not None


def test_incident_acknowledgement_verifier_state_mismatch(test_setup: Dict[str, Any]) -> None:
    rc_store: ActionStorage = test_setup["rc_store"]
    notif_engine: StorageEngine = test_setup["notif_engine"]
    notif_db: Path = test_setup["notif_db"]
    service: ExternalExposureService = test_setup["service"]

    incident_id = "inc_unacked_001"
    res_key = f"notifications:incident:{incident_id}"

    # Create incident in notifications DB with status='open'
    inc = Incident(
        incident_id=incident_id,
        source="system_watchdog",
        incident_key="disk_full_alert",
        active_occurrence_id="occ_001",
        status="open",
        severity="critical",
        summary="Disk usage 95%",
        first_seen=datetime.now(timezone.utc).isoformat(),
        last_seen=datetime.now(timezone.utc).isoformat(),
        occurrence_count=1,
    )
    notif_engine.save_incident(inc)

    # Set barrier in RC
    rc_store.set_resource_barrier(
        resource_key=res_key,
        execution_id="exec_ack_001",
        reason="Timed out waiting for acknowledgement",
        barrier_status="locked_unresolved",
    )

    # Reconcile attempt fails because incident is still 'open' in source DB
    res = service.reconcile_barrier(
        resource_key=res_key,
        evidence="I think it acknowledged",
        apply=True,
        notifications_db_path=notif_db,
    )
    assert res["ok"] is False
    assert res["applied"] is False
    assert res["error"] == "state_mismatch"
    assert "in state 'open'" in res["message"]
    assert rc_store.get_active_barrier(res_key) is not None


def test_incident_acknowledgement_authoritative_verification_and_clearance(test_setup: Dict[str, Any]) -> None:
    rc_store: ActionStorage = test_setup["rc_store"]
    notif_engine: StorageEngine = test_setup["notif_engine"]
    notif_db: Path = test_setup["notif_db"]
    service: ExternalExposureService = test_setup["service"]

    incident_id = "inc_acked_002"
    res_key = f"notifications:incident:{incident_id}"
    now_iso = datetime.now(timezone.utc).isoformat()

    # Create incident and mark it acknowledged in notifications source DB
    inc = Incident(
        incident_id=incident_id,
        source="system_watchdog",
        incident_key="memory_alert",
        active_occurrence_id="occ_002",
        status="acknowledged",
        severity="high",
        summary="High memory consumption",
        first_seen=now_iso,
        last_seen=now_iso,
        acknowledged_at=now_iso,
        occurrence_count=1,
    )
    notif_engine.save_incident(inc)

    # Set barrier in RC
    rc_store.set_resource_barrier(
        resource_key=res_key,
        execution_id="exec_ack_002",
        reason="Crash during acknowledge dispatch",
        barrier_status="locked_unresolved",
    )

    # 1. Dry run verification
    dry_res = service.reconcile_barrier(
        resource_key=res_key,
        evidence="Investigated alert",
        apply=False,
        notifications_db_path=notif_db,
    )
    assert dry_res["ok"] is True
    assert dry_res["applied"] is False
    assert dry_res["verified"] is True
    assert dry_res["verifier_id"] == "notifications_incident_verifier"
    assert len(dry_res["state_fingerprint"]) == 64  # SHA-256 fingerprint
    # Barrier is still active
    assert rc_store.get_active_barrier(res_key) is not None

    # 2. Applied reconciliation
    app_res = service.reconcile_barrier(
        resource_key=res_key,
        evidence="Investigated alert",
        apply=True,
        notifications_db_path=notif_db,
        operator_id="operator:admin",
    )
    assert app_res["ok"] is True
    assert app_res["applied"] is True
    assert app_res["verified"] is True
    assert app_res["verifier_id"] == "notifications_incident_verifier"
    assert app_res["state_fingerprint"] == dry_res["state_fingerprint"]

    # Barrier is now cleared in storage
    assert rc_store.get_active_barrier(res_key) is None

    # Audit record exists with verifier details
    audits = rc_store.list_action_audits(action_id="barrier:reconcile")
    assert len(audits) >= 1
    assert audits[0]["decision"] == "cleared"
    assert audits[0]["details"]["verifier_id"] == "notifications_incident_verifier"
    assert audits[0]["details"]["state_fingerprint"] == dry_res["state_fingerprint"]


def test_stale_execution_id_prevents_toctou_clearance(test_setup: Dict[str, Any]) -> None:
    rc_store: ActionStorage = test_setup["rc_store"]
    notif_engine: StorageEngine = test_setup["notif_engine"]
    notif_db: Path = test_setup["notif_db"]

    incident_id = "inc_acked_toctou"
    res_key = f"notifications:incident:{incident_id}"
    now_iso = datetime.now(timezone.utc).isoformat()

    inc = Incident(
        incident_id=incident_id,
        source="system_watchdog",
        incident_key="cpu_alert",
        active_occurrence_id="occ_toctou",
        status="acknowledged",
        severity="medium",
        summary="High CPU load",
        first_seen=now_iso,
        last_seen=now_iso,
        acknowledged_at=now_iso,
        occurrence_count=1,
    )
    notif_engine.save_incident(inc)

    # Establish barrier under execution ID 'exec_current'
    rc_store.set_resource_barrier(
        resource_key=res_key,
        execution_id="exec_current",
        reason="Current active barrier",
        barrier_status="locked_unresolved",
    )

    # Attempt to clear passing a stale execution_id 'exec_stale_old'
    cleared = rc_store.clear_resource_barrier(
        resource_key=res_key,
        cleared_by="operator:admin",
        evidence="Some evidence",
        execution_id="exec_stale_old",
    )
    assert cleared is False

    # Barrier is still active
    assert rc_store.get_active_barrier(res_key) is not None

    # Clear passing exact execution_id succeeds
    cleared_exact = rc_store.clear_resource_barrier(
        resource_key=res_key,
        cleared_by="operator:admin",
        evidence="Exact match evidence",
        execution_id="exec_current",
    )
    assert cleared_exact is True
    assert rc_store.get_active_barrier(res_key) is None
