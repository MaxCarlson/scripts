"""Tests for Stage D: Simulated Tailscale Funnel Lifecycle CLI and Amendment 2 Invariants."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from remote_control.actions.storage import ActionStorage
from remote_control.cli import build_parser, main
from remote_control.auth.storage import AuthStorage
from remote_control.config import RemoteControlConfig
from remote_control.external.client import SimulatedTailscaleClient
from remote_control.external.doctor import ExternalDoctor
from remote_control.external.service import ExternalExposureService


def test_doctor_read_only_invariant(tmp_path: Path) -> None:
    """Mandatory Amendment 2: doctor must remain 100% read-only and never clear barriers."""
    auth_db = tmp_path / "auth.db"
    store = ActionStorage(auth_db)
    cfg = RemoteControlConfig(auth_db_path=auth_db)

    # Set an active barrier
    store.set_resource_barrier(
        resource_key="notifications:incident:101",
        execution_id="exec_test_001",
        reason="Simulated timeout during dispatch",
        barrier_status="locked_unresolved",
    )
    assert store.get_active_barrier("notifications:incident:101") is not None

    client = SimulatedTailscaleClient(state_file=tmp_path / ".simulated_tailscale.json")
    doctor = ExternalDoctor(config=cfg, storage=store, client=client)

    # Run doctor check
    results = doctor.check_all()
    assert results["ok"] is True
    assert "checks" in results
    assert "barriers" in results
    assert results["barriers"]["active_count"] == 1

    # INVARIANT CHECK: Barrier MUST NOT be cleared or mutated
    barrier_after = store.get_active_barrier("notifications:incident:101")
    assert barrier_after is not None
    assert barrier_after["cleared_at"] is None
    assert barrier_after["barrier_status"] == "locked_unresolved"


def test_status_read_only_invariant(tmp_path: Path) -> None:
    """Mandatory Amendment 2: status must remain 100% read-only."""
    auth_db = tmp_path / "auth.db"
    store = ActionStorage(auth_db)
    cfg = RemoteControlConfig(auth_db_path=auth_db)
    client = SimulatedTailscaleClient(state_file=tmp_path / ".simulated_tailscale.json")
    service = ExternalExposureService(config=cfg, storage=store, client=client)

    stat = service.status()
    assert stat["ok"] is True
    assert "tailscale" in stat
    assert "exposure" in stat


def test_plan_dry_run(tmp_path: Path) -> None:
    """Plan outputs proposed topology and commands without applying."""
    auth_db = tmp_path / "auth.db"
    store = ActionStorage(auth_db)
    cfg = RemoteControlConfig(auth_db_path=auth_db)
    client = SimulatedTailscaleClient(state_file=tmp_path / ".simulated_tailscale.json")
    service = ExternalExposureService(config=cfg, storage=store, client=client)

    plan_res = service.plan(port=8443, public_port=8443)
    assert plan_res["ok"] is True
    assert plan_res["applied"] is False
    assert len(plan_res["commands"]) >= 2
    assert any("funnel" in cmd for cmd in plan_res["commands"])


def test_enable_and_disable_lifecycle(tmp_path: Path) -> None:
    """Enable requires apply=True to activate; disable removes funnel reachability."""
    auth_db = tmp_path / "auth.db"
    auth_store = AuthStorage(auth_db)
    auth_store.create_operator("admin_op", "admin", "$argon2id$dummy", "JBSWY3DPEHPK3PXP")
    store = ActionStorage(auth_db)
    cfg = RemoteControlConfig(
        auth_db_path=auth_db,
        public_origin="https://workstation.tailnet-dev.ts.net:8443",
        allowed_public_hosts=["workstation.tailnet-dev.ts.net"],
    )
    client = SimulatedTailscaleClient(state_file=tmp_path / ".simulated_tailscale.json")
    service = ExternalExposureService(config=cfg, storage=store, client=client)

    # Dry-run enable
    dry = service.enable(apply=False, port=8443, public_port=8443, verify_listener=False)
    assert dry["applied"] is False
    assert client.get_status().funnel_active is False

    # Apply enable
    en = service.enable(apply=True, port=8443, public_port=8443, verify_listener=False)
    assert en["applied"] is True
    assert en["public_url"].startswith("https://")
    assert client.get_status().funnel_active is True

    # Dry-run disable
    dry_dis = service.disable(apply=False, public_port=8443)
    assert dry_dis["applied"] is False
    assert client.get_status().funnel_active is True

    # Apply disable
    dis = service.disable(apply=True, public_port=8443)
    assert dis["applied"] is True
    assert client.get_status().funnel_active is False


def test_reconcile_barrier_requires_apply_and_evidence(tmp_path: Path) -> None:
    """Dedicated reconciliation requires -a/--apply and authoritative source evidence (Stage E)."""
    auth_db = tmp_path / "auth.db"
    store = ActionStorage(auth_db)
    cfg = RemoteControlConfig(auth_db_path=auth_db)
    client = SimulatedTailscaleClient(state_file=tmp_path / ".simulated_tailscale.json")
    service = ExternalExposureService(config=cfg, storage=store, client=client)

    resource_key = "notifications:incident:202"
    store.set_resource_barrier(
        resource_key=resource_key,
        execution_id="exec_unresolved_002",
        reason="Network disconnect during dispatch",
    )

    # Free-text evidence without source verification in notifications DB MUST fail closed
    unverified = service.reconcile_barrier(
        resource_key=resource_key,
        evidence="Broker log proves event was not processed",
        apply=True,
    )
    assert unverified["ok"] is False
    assert unverified["error"] == "incident_not_found"

    # Now create the incident as acknowledged in notifications DB
    from notifications.models import Incident
    from notifications.storage import StorageEngine
    notif_db = tmp_path / "events.db"
    notif_engine = StorageEngine(notif_db)
    notif_engine.migrate()
    notif_engine.save_incident(Incident(
        incident_id="202",
        source="system",
        incident_key="test_202",
        active_occurrence_id="occ_202",
        status="acknowledged",
        severity="high",
        summary="Test incident",
        first_seen="2026-11-11T00:00:00Z",
        last_seen="2026-11-11T00:00:00Z",
        occurrence_count=1,
    ))

    # Dry-run reconciliation with valid source state
    preview = service.reconcile_barrier(
        resource_key=resource_key,
        evidence="Broker log proves event was not processed",
        apply=False,
        notifications_db_path=notif_db,
    )
    assert preview["applied"] is False
    assert preview["verified"] is True
    assert store.get_active_barrier(resource_key) is not None

    # Apply reconciliation with authoritative source verification
    reconciled = service.reconcile_barrier(
        resource_key=resource_key,
        evidence="Broker log proves event was not processed",
        apply=True,
        operator_id="operator:admin",
        notifications_db_path=notif_db,
    )
    assert reconciled["ok"] is True
    assert reconciled["applied"] is True
    assert store.get_active_barrier(resource_key) is None


def test_reconcile_barrier_prohibits_coordinator_recovery_override(tmp_path: Path) -> None:
    """Generic manual override of unresolved Resource Coordinator recovery is strictly prohibited."""
    auth_db = tmp_path / "auth.db"
    store = ActionStorage(auth_db)
    cfg = RemoteControlConfig(auth_db_path=auth_db)
    client = SimulatedTailscaleClient(state_file=tmp_path / ".simulated_tailscale.json")
    service = ExternalExposureService(config=cfg, storage=store, client=client)

    resource_key = "resource:gpu.inference"
    store.set_resource_barrier(
        resource_key=resource_key,
        execution_id="exec_rc_001",
        reason="Coordinator recovery unverified",
    )

    result = service.reconcile_barrier(
        resource_key=resource_key,
        evidence="Operator claims GPU looks fine",
        apply=True,
        operator_id="operator:admin",
    )
    assert result["ok"] is False
    assert result["error"] == "coordinator_recovery_prohibited"
    # Barrier remains active
    assert store.get_active_barrier(resource_key) is not None


def test_cli_external_subcommands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    """Test CLI external commands (status, doctor, plan, enable, disable, reconcile-barrier)."""
    auth_db = tmp_path / "cli_auth.db"
    auth_store = AuthStorage(auth_db)
    auth_store.create_operator("admin_op", "admin", "$argon2id$dummy", "JBSWY3DPEHPK3PXP")
    monkeypatch.setenv("REMOTE_CONTROL_AUTH_DB_PATH", str(auth_db))
    monkeypatch.setenv("REMOTE_CONTROL_SIMULATE_TAILSCALE", "1")
    monkeypatch.setenv("REMOTE_CONTROL_SIMULATED_STATE_PATH", str(tmp_path / ".cli_tailscale.json"))
    monkeypatch.setenv("REMOTE_CONTROL_PUBLIC_ORIGIN", "https://workstation.tailnet-dev.ts.net:8443")

    # Seed notifications DB for CLI reconcile-barrier
    from notifications.models import Incident
    from notifications.storage import StorageEngine
    notif_db = tmp_path / "events.db"
    notif_engine = StorageEngine(notif_db)
    notif_engine.migrate()
    notif_engine.save_incident(Incident(
        incident_id="303",
        source="system",
        incident_key="test_303",
        active_occurrence_id="occ_303",
        status="acknowledged",
        severity="medium",
        summary="Fault injection test incident",
        first_seen="2026-11-11T00:00:00Z",
        last_seen="2026-11-11T00:00:00Z",
        occurrence_count=1,
    ))
    monkeypatch.setenv("NOTIFICATIONS_DB_PATH", str(notif_db))

    # 1. doctor
    code = main(["external", "doctor", "--json"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True

    # 2. plan
    code = main(["external", "plan", "--json"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True

    # 3. enable dry-run
    code = main(["external", "enable", "--json"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["applied"] is False

    # 4. enable with apply
    code = main(["external", "enable", "-a", "--skip-listener-check", "--json"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["applied"] is True

    # 5. status
    code = main(["external", "status", "--json"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["tailscale"]["funnel_active"] is True

    # 6. disable with apply
    code = main(["external", "disable", "-a", "--json"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["applied"] is True

    # 7. repair with apply
    code = main(["external", "repair", "-a", "--skip-listener-check", "--json"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["applied"] is True

    # 8. reconcile-barrier via CLI
    store = ActionStorage(auth_db)
    store.set_resource_barrier(
        resource_key="notifications:incident:303",
        execution_id="exec_unresolved_003",
        reason="Fault injection",
    )
    # Dry-run
    code = main(["reconcile-barrier", "--resource-key", "notifications:incident:303", "--evidence", "Verified offline", "--json"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["applied"] is False
    assert store.get_active_barrier("notifications:incident:303") is not None

    # Apply
    code = main(["reconcile-barrier", "--resource-key", "notifications:incident:303", "--evidence", "Verified offline", "-a", "--json"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["applied"] is True
    assert store.get_active_barrier("notifications:incident:303") is None

    # Human-readable output format check
    code = main(["external", "status"])
    assert code == 0
    text_out = capsys.readouterr().out
    assert "External Exposure & Tailscale Status:" in text_out
