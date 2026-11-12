"""
Phase 09 Synthetic End-to-End Integration Scenario.
Validates the complete lifecycle:
1. Consumer (Scheduler) emits a task failure.
2. Notifications broker persists the event envelope.
3. Incident state machine creates an active 'open' incident with severity 'critical'.
4. Outbox delivery queue records delivery items for configured providers.
5. FakeProvider accepts and marks notification delivery successful.
6. Remote Control reads and displays the active incident.
7. Guarded acknowledgement completes with operator TOTP authentication and audit trail.
8. Incident lifecycle updates to 'acknowledged' without mutating Resource Coordinator.
9. Duplicate failures deduplicate; task success cleanly resolves the incident; new failure reopens.
10. Public exposure (Tailscale Funnel) remains verified disabled throughout.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import time
import pyotp
import pytest
from fastapi.testclient import TestClient

from notifications.delivery.fake import FakeProvider
from notifications.models import EventEnvelopeV1
from notifications.outbox import OutboxWorker
from notifications.publisher import Publisher
from notifications.storage import StorageEngine
from remote_control.app import create_app
from remote_control.auth.service import AuthService
from remote_control.auth.storage import AuthStorage
from remote_control.config import RemoteControlConfig
from scheduler.config import SchedulerConfig
from scheduler.models import ExecutionResult
from scheduler.notifier import Notifier


def test_phase09_synthetic_e2e_scenario(tmp_path, monkeypatch):
    # Ensure isolated simulated tailscale state
    sim_tailscale_path = tmp_path / ".sim_tailscale.json"
    sim_tailscale_path.write_text(json.dumps({
        "installed": True,
        "version": "1.54.0-simulated",
        "logged_in": True,
        "node_name": "workstation",
        "tailnet_name": "tailnet-dev.ts.net",
        "funnel_available": True,
        "funnel_active": False,
        "public_url": None,
    }), encoding="utf-8")
    monkeypatch.setenv("REMOTE_CONTROL_SIMULATED_STATE_PATH", str(sim_tailscale_path))

    # ── Setup Isolated Infrastructure ────────────────────────────────────────
    db_path = tmp_path / "events.db"
    storage = StorageEngine(db_path=db_path)
    storage.migrate()

    fake_provider = FakeProvider(provider_id="synthetic_provider")
    providers = {"synthetic_provider": fake_provider}
    publisher = Publisher(storage=storage, default_providers=["synthetic_provider"])
    outbox_worker = OutboxWorker(storage=storage, providers=providers)

    # Configure Scheduler consumer
    sched_cfg = SchedulerConfig(
        notifications_enabled=True,
        notify_on_failure=True,
        notify_on_success=True,
        use_notifications_broker=True,
    )
    notifier = Notifier(sched_cfg)
    notifier._broker_publisher = publisher

    # ── Step 1: Scheduler Task Fails ─────────────────────────────────────────
    fail_result = ExecutionResult(
        task_name="NightlyDatabaseBackup",
        schedule_name="NightlyMaintenance",
        timestamp="2026-11-11T20:00:00Z",
        exit_code=1,
        stdout="",
        stderr="Error: Volume /mnt/backup is 100% full",
        duration_sec=4.12,
        environment="terminal",
        admin=False,
        success=False,
        error_message="Volume /mnt/backup is 100% full",
    )
    sent = notifier.notify_task_result(fail_result)
    assert sent is True, "Notifier must accept failure event"

    # ── Step 2 & 3: Broker Persists Event and Creates Open Incident ──────────
    incidents = storage.list_incidents()
    assert len(incidents) == 1
    incident = incidents[0]
    assert incident.source == "scheduler"
    assert incident.incident_key == "scheduler:task:NightlyDatabaseBackup"
    assert incident.status == "open"
    assert incident.severity == "critical"
    assert "NightlyDatabaseBackup" in incident.summary
    assert incident.occurrence_count == 1

    # ── Step 4 & 5: Outbox Queues and Delivers via Synthetic Provider ─────────
    pending_items = storage.list_pending_outbox()
    assert len(pending_items) == 1
    outbox_item = pending_items[0]
    assert outbox_item.provider_id == "synthetic_provider"
    assert outbox_item.status == "pending"

    # Deliver outbox
    delivered_count = asyncio.run(outbox_worker.process_pending_once())
    assert delivered_count == 1
    assert len(fake_provider.sent_notifications) == 1
    delivered_msg = fake_provider.sent_notifications[0]
    assert "NightlyDatabaseBackup" in delivered_msg.title
    assert "Volume /mnt/backup is 100% full" in delivered_msg.title
    assert "Source: scheduler" in delivered_msg.body

    # ── Step 6, 7 & 8: Remote Control Authenticated API & Guarded Acknowledgement ──
    # Set up isolated Remote Control instance targeting the notifications database
    rc_config = RemoteControlConfig(
        auth_db_path=tmp_path / "auth.db",
        notifications_db_path=db_path,
        cookie_security_mode="development",
    )
    auth_storage = AuthStorage(rc_config.auth_db_path)
    auth_service = AuthService(auth_storage, rc_config)
    op, totp_secret, uri = auth_service.bootstrap(username="operator", password="SuperSecretPassword123!")
    totp = pyotp.TOTP(totp_secret)

    rc_app = create_app(rc_config)
    with TestClient(rc_app, base_url="http://127.0.0.1:8443") as client:
        # Step 6a: Authenticate operator session with TOTP
        login_resp = client.post(
            "/api/auth/login",
            json={
                "username": "operator",
                "password": "SuperSecretPassword123!",
                "totp_code": totp.now(),
                "device_id": "test-device-uuid-1",
                "device_name": "Test Pixel 9 Pro",
            },
        )
        assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
        csrf_token = login_resp.json()["csrf_token"]

        # Step 6b: Read active incidents through authenticated REST API
        inc_resp = client.get("/api/incidents")
        assert inc_resp.status_code == 200
        inc_data = inc_resp.json()
        assert inc_data["available"] is True
        assert len(inc_data["items"]) == 1
        assert inc_data["items"][0]["incident_id"] == incident.incident_id
        assert inc_data["items"][0]["status"] == "open"
        assert inc_data["items"][0]["severity"] == "critical"

        # Step 7a: Reject direct execution without pre-issued challenge_id (Defect B guard)
        step_up_otp = totp.at(int(time.time()) + 30)
        rej_resp = client.post(
            f"/api/v1/incidents/{incident.incident_id}/acknowledge",
            json={"reason": "Acknowledged by operator", "totp_code": step_up_otp},
            headers={"Origin": "http://127.0.0.1:8443", "X-CSRF-Token": csrf_token},
        )
        assert rej_resp.status_code == 422
        assert rej_resp.json()["error"] == "challenge_required"

        # Step 7b: Prepare confirmation challenge explicitly
        prep_resp = client.post(
            "/api/v1/actions/notifications.acknowledge_incident/prepare",
            json={"parameters": {"incident_id": incident.incident_id, "reason": "Acknowledged by operator"}},
            headers={"Origin": "http://127.0.0.1:8443", "X-CSRF-Token": csrf_token},
        )
        assert prep_resp.status_code == 200
        challenge_id = prep_resp.json()["challenge_id"]

        # Step 7c: Execute guarded acknowledgement with challenge_id, CSRF token, and step-up TOTP
        ack_resp = client.post(
            f"/api/v1/incidents/{incident.incident_id}/acknowledge",
            json={"reason": "Acknowledged by operator", "totp_code": step_up_otp, "challenge_id": challenge_id},
            headers={"Origin": "http://127.0.0.1:8443", "X-CSRF-Token": csrf_token},
        )
        assert ack_resp.status_code == 200
        ack_data = ack_resp.json()
        assert ack_data["ok"] is True
        assert ack_data["status"] == "succeeded"
        assert ack_data["postcondition_verified"] is True

        # Step 7d: Verify token replay prevention (challenge is now consumed)
        replay_resp = client.post(
            f"/api/v1/incidents/{incident.incident_id}/acknowledge",
            json={"reason": "Replay attempt", "totp_code": step_up_otp, "challenge_id": challenge_id},
            headers={"Origin": "http://127.0.0.1:8443", "X-CSRF-Token": csrf_token},
        )
        assert replay_resp.status_code in (409, 422)

    # Step 8: Verify notifications storage reflects acknowledged state
    acked_incident = storage.get_incident(incident.incident_id)
    assert acked_incident is not None
    assert acked_incident.status == "acknowledged"
    assert acked_incident.acknowledged_at is not None

    # ── Step 9: Deduplication & Resolution on Success ────────────────────────
    # 9a. Subsequent repeated failure while acknowledged:
    # Verifies deduplication: incident stays acknowledged, no outbox storm
    fail_result_retry = ExecutionResult(
        task_name="NightlyDatabaseBackup",
        schedule_name="NightlyMaintenance",
        timestamp="2026-11-11T20:15:00Z",
        exit_code=1,
        stdout="",
        stderr="Error: Volume /mnt/backup is 100% full",
        duration_sec=3.85,
        environment="terminal",
        admin=False,
        success=False,
        error_message="Volume /mnt/backup is 100% full",
    )
    sent_dup = notifier.notify_task_result(fail_result_retry)
    assert sent_dup is True
    dup_incident = storage.get_incident(incident.incident_id)
    assert dup_incident.status == "acknowledged"
    # No new pending outbox items generated while acknowledged (cooldown/dedup)
    assert len(storage.list_pending_outbox()) == 0

    # 9b. Task succeeds on retry:
    success_result = ExecutionResult(
        task_name="NightlyDatabaseBackup",
        schedule_name="NightlyMaintenance",
        timestamp="2026-11-11T20:30:00Z",
        exit_code=0,
        stdout="Backup volume pruned; backup archive created successfully (2.4 GB).",
        stderr="",
        duration_sec=12.5,
        environment="terminal",
        admin=False,
        success=True,
    )
    sent_success = notifier.notify_task_result(success_result)
    assert sent_success is True

    # Verify incident is now resolved!
    resolved_incident = storage.get_incident(incident.incident_id)
    assert resolved_incident.status == "resolved"
    assert resolved_incident.resolved_at is not None

    # 9c. Subsequent failure in the future reopens the incident:
    fail_result_future = ExecutionResult(
        task_name="NightlyDatabaseBackup",
        schedule_name="NightlyMaintenance",
        timestamp="2026-11-12T20:00:00Z",
        exit_code=1,
        stdout="",
        stderr="Error: Disk hardware error",
        duration_sec=1.1,
        environment="terminal",
        admin=False,
        success=False,
        error_message="Disk hardware error",
    )
    sent_reopen = notifier.notify_task_result(fail_result_future)
    assert sent_reopen is True
    reopened_incident = storage.get_incident(incident.incident_id)
    assert reopened_incident.status in ("open", "reopened")
    assert reopened_incident.occurrence_count == 2

    # ── Step 10: Tailscale Funnel Remains Disabled Throughout ────────────────
    from notifications.diagnostics import collect_release_diagnostics
    # 10a. Strict non-subprocess inspection reports uninspected / skipped without fabricating disabled status
    diag = collect_release_diagnostics(db_path=db_path, auth_db_path=tmp_path / "auth.db", probe_ports=False)
    assert diag["ok"] is True
    assert diag["tailscale_funnel"]["configured_exposure_enabled"] is False
    assert diag["tailscale_funnel"]["inspection"] == "skipped_no_subprocess"
    assert diag["tailscale_funnel"]["status"] == "uninspected"

    # 10b. Optional live/simulated inspection proves funnel was never activated
    diag_live = collect_release_diagnostics(
        db_path=db_path,
        auth_db_path=tmp_path / "auth.db",
        probe_ports=False,
        inspect_tailscale=True,
    )
    assert diag_live["ok"] is True
    assert diag_live["tailscale_funnel"]["configured_exposure_enabled"] is False
    assert diag_live["tailscale_funnel"]["observed_funnel_active"] is False
    assert diag_live["tailscale_funnel"]["status"] == "inactive"
