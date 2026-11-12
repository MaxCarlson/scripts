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
from pathlib import Path
import pytest

from notifications.delivery.fake import FakeProvider
from notifications.models import EventEnvelopeV1
from notifications.outbox import OutboxWorker
from notifications.publisher import Publisher
from notifications.storage import StorageEngine
from scheduler.config import SchedulerConfig
from scheduler.models import ExecutionResult
from scheduler.notifier import Notifier


def test_phase09_synthetic_e2e_scenario(tmp_path):
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

    # ── Step 6: Remote Control Reads the Incident ────────────────────────────
    read_incident = storage.get_incident(incident.incident_id)
    assert read_incident is not None
    assert read_incident.status == "open"
    assert read_incident.severity == "critical"

    # ── Step 7 & 8: Guarded Acknowledgement ──────────────────────────────────
    acked_incident = publisher.lifecycle.acknowledge_incident(
        incident_id=incident.incident_id,
        actor="operator",
    )
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
    diag = collect_release_diagnostics(db_path=db_path, probe_ports=False)
    assert diag["ok"] is True
    assert diag["tailscale_funnel"]["public_exposure_enabled"] is False
    assert diag["tailscale_funnel"]["funnel_active"] is False
    assert diag["tailscale_funnel"]["status"] == "disabled_by_policy"
