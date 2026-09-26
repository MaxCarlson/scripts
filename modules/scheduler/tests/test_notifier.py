"""
Unit tests for scheduler notification dispatch.
"""
from unittest.mock import patch
from scheduler.config import SchedulerConfig
from scheduler.models import ExecutionResult
from scheduler.notifier import Notifier


def test_notifier_disabled():
    cfg = SchedulerConfig(notifications_enabled=False)
    notifier = Notifier(cfg)
    assert notifier.notify("Title", "Message") is False


def test_notifier_schedule_trigger():
    cfg = SchedulerConfig(notifications_enabled=True, notify_on_run=True)
    notifier = Notifier(cfg)

    with patch.object(notifier, "notify", return_value=True) as mock_notify:
        sent = notifier.notify_schedule_trigger("DailySync", 3, is_catchup=False)
        assert sent is True
        mock_notify.assert_called_once()
        assert "DailySync" in mock_notify.call_args[0][0]


def test_notifier_task_success_and_failure():
    cfg = SchedulerConfig(notifications_enabled=True, notify_on_success=True, notify_on_failure=True)
    notifier = Notifier(cfg)

    success_res = ExecutionResult(
        task_name="SuccessTask",
        schedule_name="Sched",
        timestamp="2026-09-26T12:00:00",
        exit_code=0,
        stdout="OK",
        stderr="",
        duration_sec=1.0,
        environment="terminal",
        admin=False,
        success=True,
    )

    with patch.object(notifier, "notify", return_value=True) as mock_notify:
        sent = notifier.notify_task_result(success_res)
        assert sent is True
        assert "SuccessTask" in mock_notify.call_args[0][0]

    fail_res = ExecutionResult(
        task_name="FailTask",
        schedule_name="Sched",
        timestamp="2026-09-26T12:00:00",
        exit_code=1,
        stdout="",
        stderr="Error message",
        duration_sec=1.0,
        environment="terminal",
        admin=False,
        success=False,
        error_message="Fatal error",
    )

    with patch.object(notifier, "notify", return_value=True) as mock_notify:
        sent = notifier.notify_task_result(fail_res)
        assert sent is True
        assert "FailTask" in mock_notify.call_args[0][0]
        assert mock_notify.call_args[1]["urgency"] == "critical"
