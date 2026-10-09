"""Setup readiness checks for the operating system integration."""
from unittest.mock import patch

from scheduler.readiness import get_setup_state


def test_linux_reports_setup_unavailable_without_windows_task_query():
    system = type("System", (), {"os_name": "linux", "is_windows": lambda self: False, "is_linux": lambda self: True})()
    with patch("scheduler.readiness.SystemUtils", return_value=system), patch(
        "scheduler.readiness.windows_task.get_runner_status"
    ) as get_status:
        state = get_setup_state()

    assert state.complete is False
    assert state.platform_name == "Linux"
    assert state.setup_command is None
    assert "not available" in state.message
    get_status.assert_not_called()


def test_windows_requires_limited_daemon_and_highest_interactive_admin_worker():
    system = type("System", (), {"os_name": "windows", "is_windows": lambda self: True, "is_linux": lambda self: False})()
    status = {
        "installed": True,
        "enabled": True,
        "state": "Ready",
        "runLevel": "Limited",
        "logonType": "InteractiveToken",
        "arguments": "-m scheduler.cli --config-file scheduler_data.json daemon --interval 30",
        "user": "DOMAIN\\User",
        "adminWorker": {
            "installed": True,
            "enabled": True,
            "state": "Ready",
            "runLevel": "Highest",
            "logonType": "InteractiveToken",
            "arguments": "-m scheduler.cli --config-file scheduler_data.json daemon --admin-worker --interval 1",
            "user": "DOMAIN\\User",
        },
    }
    with patch("scheduler.readiness.SystemUtils", return_value=system), patch(
        "scheduler.readiness.windows_task.get_runner_status", return_value=status
    ):
        state = get_setup_state()

    assert state.complete is True
    assert state.setup_command is None


def test_windows_recommends_reinstall_for_incorrect_privilege_configuration():
    system = type("System", (), {"os_name": "windows", "is_windows": lambda self: True, "is_linux": lambda self: False})()
    status = {
        "installed": True,
        "enabled": False,
        "state": "Disabled",
        "runLevel": "LeastPrivilege",
        "logonType": "Password",
    }
    with patch("scheduler.readiness.SystemUtils", return_value=system), patch(
        "scheduler.readiness.windows_task.get_runner_status", return_value=status
    ):
        state = get_setup_state()

    assert state.complete is False
    assert state.setup_command == "scheduler setup windows"
    assert "disabled" in state.message
    assert "limited privileges" in state.message
    assert "interactive user logon" in state.message
    assert "elevated Admin task worker" in state.message


def test_windows_status_failure_keeps_setup_available():
    system = type("System", (), {"os_name": "windows", "is_windows": lambda self: True, "is_linux": lambda self: False})()
    with patch("scheduler.readiness.SystemUtils", return_value=system), patch(
        "scheduler.readiness.windows_task.get_runner_status", side_effect=OSError("Task Scheduler unavailable")
    ):
        state = get_setup_state()

    assert state.complete is False
    assert state.setup_command == "scheduler setup windows"
    assert "Task Scheduler unavailable" in state.message
