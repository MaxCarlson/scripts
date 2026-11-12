"""
Tests for Scheduler integration with the Notifications broker and safe dispatch.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch
import pytest

from scheduler.config import SchedulerConfig
from scheduler.models import ExecutionResult
from scheduler.notifier import Notifier


def test_scheduler_config_broker_option():
    cfg = SchedulerConfig()
    assert hasattr(cfg, "use_notifications_broker")
    assert cfg.use_notifications_broker is True

    cfg_dict = cfg.to_dict()
    assert cfg_dict["use_notifications_broker"] is True

    reloaded = SchedulerConfig.from_dict(cfg_dict)
    assert reloaded.use_notifications_broker is True

    custom = SchedulerConfig.from_dict({"use_notifications_broker": False})
    assert custom.use_notifications_broker is False


def test_scheduler_task_failure_emits_broker_incident():
    cfg = SchedulerConfig(notifications_enabled=True, notify_on_failure=True, use_notifications_broker=True)
    notifier = Notifier(cfg)

    fail_result = ExecutionResult(
        task_name="BackupJob",
        schedule_name="Nightly",
        timestamp="2026-11-11T12:00:00Z",
        exit_code=1,
        stdout="",
        stderr="Connection refused",
        duration_sec=3.45,
        environment="terminal",
        admin=False,
        success=False,
        error_message="Connection refused to storage endpoint",
    )

    with patch.object(notifier, "_publish_to_broker", return_value=True) as mock_pub:
        sent = notifier.notify_task_result(fail_result)
        assert sent is True
        mock_pub.assert_called_once()
        kwargs = mock_pub.call_args[1]
        assert kwargs["severity"] == "critical"
        assert kwargs["lifecycle"] == "open"
        assert kwargs["incident_key"] == "scheduler:task:BackupJob"
        assert "BackupJob" in kwargs["summary"]
        assert "Connection refused" in kwargs["summary"]
        assert kwargs["labels"]["schedule"] == "Nightly"
        assert kwargs["labels"]["exit_code"] == "1"


def test_scheduler_task_success_resolves_broker_incident():
    cfg = SchedulerConfig(notifications_enabled=True, notify_on_success=True, use_notifications_broker=True)
    notifier = Notifier(cfg)

    success_result = ExecutionResult(
        task_name="BackupJob",
        schedule_name="Nightly",
        timestamp="2026-11-11T12:05:00Z",
        exit_code=0,
        stdout="All 10 files backed up",
        stderr="",
        duration_sec=1.23,
        environment="terminal",
        admin=False,
        success=True,
    )

    with patch.object(notifier, "_publish_to_broker", return_value=True) as mock_pub:
        sent = notifier.notify_task_result(success_result)
        assert sent is True
        mock_pub.assert_called_once()
        kwargs = mock_pub.call_args[1]
        assert kwargs["severity"] == "info"
        assert kwargs["lifecycle"] == "resolve"
        assert kwargs["incident_key"] == "scheduler:task:BackupJob"
        assert "BackupJob" in kwargs["summary"]


def test_scheduler_schedule_trigger_emits_broker_incident():
    cfg = SchedulerConfig(notifications_enabled=True, notify_on_run=True, use_notifications_broker=True)
    notifier = Notifier(cfg)

    with patch.object(notifier, "_publish_to_broker", return_value=True) as mock_pub:
        sent = notifier.notify_schedule_trigger("WeeklyMaintenance", 5, is_catchup=False)
        assert sent is True
        mock_pub.assert_called_once()
        kwargs = mock_pub.call_args[1]
        assert kwargs["severity"] == "info"
        assert kwargs["lifecycle"] == "open"
        assert kwargs["incident_key"] == "scheduler:schedule:WeeklyMaintenance"
        assert "WeeklyMaintenance" in kwargs["summary"]
        assert kwargs["labels"]["tasks"] == "5"


def test_scheduler_fallback_when_broker_fails():
    cfg = SchedulerConfig(notifications_enabled=True, notify_on_failure=True, use_notifications_broker=True)
    notifier = Notifier(cfg)

    fail_result = ExecutionResult(
        task_name="CriticalJob",
        schedule_name=None,
        timestamp="2026-11-11T12:00:00Z",
        exit_code=2,
        stdout="",
        stderr="Disk full",
        duration_sec=0.5,
        environment="terminal",
        admin=False,
        success=False,
        error_message="No space left on device",
    )

    # Broker throws an exception; notifier must catch and fallback to platform notification
    with patch.object(notifier, "_publish_to_broker", side_effect=RuntimeError("Storage locked")), \
         patch.object(notifier, "_notify_platform", return_value=True) as mock_platform:
        sent = notifier.notify_task_result(fail_result)
        assert sent is True
        mock_platform.assert_called_once()
        assert "CriticalJob" in mock_platform.call_args[0][0]


def test_scheduler_safe_windows_powershell_no_injection():
    cfg = SchedulerConfig(notifications_enabled=True, use_notifications_broker=False)
    notifier = Notifier(cfg)

    malicious_title = 'Injection"; Start-Process calc.exe; "'
    malicious_msg = 'Test $(whoami) & notepad.exe'

    def fake_which(cmd):
        if "powershell" in cmd:
            return "powershell.exe"
        return None

    with patch("subprocess.run") as mock_subproc, \
         patch("shutil.which", side_effect=fake_which):
        notifier._notify_platform(malicious_title, malicious_msg, urgency="critical")
        assert mock_subproc.called
        cmd_args = mock_subproc.call_args[0][0]
        # Verify script does NOT contain the interpolated strings directly
        script_arg = cmd_args[cmd_args.index("-Command") + 1]
        assert malicious_title not in script_arg
        assert malicious_msg not in script_arg
        # Verify title and message are passed as separate parameterized arguments
        assert malicious_title in cmd_args
        assert malicious_msg in cmd_args


def test_scheduler_real_broker_in_process_roundtrip(tmp_path):
    """Test actual in-process integration with Notifications StorageEngine and Publisher."""
    from notifications.storage import StorageEngine
    from notifications.publisher import Publisher

    db_path = tmp_path / "events.db"
    storage = StorageEngine(db_path=db_path)
    storage.migrate()
    publisher = Publisher(storage, default_providers=[])

    cfg = SchedulerConfig(notifications_enabled=True, notify_on_failure=True, use_notifications_broker=True)
    notifier = Notifier(cfg)
    notifier._broker_publisher = publisher

    fail_res = ExecutionResult(
        task_name="SyncData",
        schedule_name="Hourly",
        timestamp="2026-11-11T13:00:00Z",
        exit_code=1,
        stdout="",
        stderr="Failed",
        duration_sec=2.0,
        environment="terminal",
        admin=False,
        success=False,
        error_message="Network timeout",
    )

    sent = notifier.notify_task_result(fail_res)
    assert sent is True

    # Verify incident in storage
    incidents = storage.list_incidents()
    assert len(incidents) == 1
    assert incidents[0].incident_key == "scheduler:task:SyncData"
    assert incidents[0].status == "open"
    assert incidents[0].severity == "critical"

    # Now verify success resolves the incident
    success_res = ExecutionResult(
        task_name="SyncData",
        schedule_name="Hourly",
        timestamp="2026-11-11T13:01:00Z",
        exit_code=0,
        stdout="OK",
        stderr="",
        duration_sec=1.0,
        environment="terminal",
        admin=False,
        success=True,
    )
    sent_success = notifier.notify_task_result(success_res)
    assert sent_success is True

    # Verify incident is now resolved!
    incidents_after = storage.list_incidents()
    assert len(incidents_after) == 1
    assert incidents_after[0].status == "resolved"
