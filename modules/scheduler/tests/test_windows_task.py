"""Tests for Windows runner setup without registering live operating-system tasks."""
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from scheduler import windows_task


def test_registration_uses_limited_daemon_and_highest_admin_worker(tmp_path):
    data_file = tmp_path / "scheduler data.json"
    script = windows_task._registration_script(data_file, 45, "TestRunner", r"DOMAIN\User")

    assert "New-ScheduledTaskTrigger -AtLogOn -User $user" in script
    assert "-LogonType Interactive -RunLevel Limited" in script
    assert "-LogonType Interactive -RunLevel Highest" in script
    assert "-MultipleInstances IgnoreNew" in script
    assert "-RestartCount 3" in script
    assert "scheduler.cli" in script
    assert str(data_file.resolve()) in script
    assert "daemon --interval 45" in script
    assert "daemon --admin-worker --interval 1" in script
    assert "ScriptsSchedulerAdminWorker" in script
    assert "TestRunner" in script
    assert r"DOMAIN\User" in script


def test_registration_rejects_nonpositive_interval(tmp_path):
    with pytest.raises(ValueError, match="at least one second"):
        windows_task._registration_script(tmp_path / "scheduler_data.json", 0, "TestRunner", "User")


def test_powershell_literal_escapes_embedded_single_quotes():
    assert windows_task._ps_quote("C:\\Users\\O'Neil\\scheduler.json") == "'C:\\Users\\O''Neil\\scheduler.json'"


def test_install_requests_one_time_elevation_and_reports_child_error(tmp_path):
    failure = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="access denied")
    with patch.object(windows_task, "_require_windows"), \
         patch.object(windows_task, "_run_powershell", return_value=failure) as run:
        with pytest.raises(RuntimeError, match="access denied"):
            windows_task.install_runner(tmp_path / "scheduler_data.json", interval_seconds=30)

    assert run.call_args.kwargs["elevated"] is True
    assert "-RunLevel Limited" in run.call_args.args[0]
    assert "-RunLevel Highest" in run.call_args.args[0]


def test_status_decodes_read_only_powershell_response():
    status = {"installed": True, "state": "Running", "runLevel": "Highest"}
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(status), stderr="")
    with patch.object(windows_task, "_require_windows"), patch.object(windows_task, "_run_powershell", return_value=completed) as run:
        result = windows_task.get_runner_status()

    assert result == status
    assert run.call_args.kwargs == {}
    assert "$ErrorActionPreference = 'Stop'" in run.call_args.args[0]
    assert "CategoryInfo.Category -eq 'ObjectNotFound'" in run.call_args.args[0]
    assert "Register-ScheduledTask" not in run.call_args.args[0]


def test_start_runner_uses_current_user_context_without_elevation():
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="started", stderr="")
    with patch.object(windows_task, "_require_windows"), patch.object(windows_task, "_run_powershell", return_value=completed) as run:
        assert windows_task.start_runner() == "started"

    assert run.call_args.kwargs == {}
    assert "Start-ScheduledTask" in run.call_args.args[0]
    assert run.call_args.args[0].index("Start-ScheduledTask -TaskName 'ScriptsSchedulerAdminWorker'") < run.call_args.args[0].index("Start-ScheduledTask -TaskName 'ScriptsSchedulerDaemon'")


def test_remove_runner_requests_setup_privilege():
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="removed", stderr="")
    with patch.object(windows_task, "_require_windows"), patch.object(windows_task, "_run_powershell", return_value=completed) as run:
        assert windows_task.remove_runner() == "removed"

    assert run.call_args.kwargs["elevated"] is True


def test_run_as_launcher_waits_for_registration_process_exit(tmp_path):
    output = subprocess.CompletedProcess(args=[], returncode=0, stdout="registered", stderr="")
    with patch.object(windows_task, "_require_windows"), \
         patch.object(windows_task.subprocess, "run", return_value=output) as run:
        result = windows_task._run_powershell("Write-Output 'ok'", elevated=True)

    assert result.returncode == 0
    launcher = run.call_args.args[0][-1]
    assert "-Verb RunAs -Wait -PassThru" in launcher
    assert "$child.Refresh(); exit $child.ExitCode" in launcher


def test_elevated_output_capture_preserves_parent_access_and_survives_read_denial(tmp_path):
    temp_context = type(
        "TemporaryDirectoryContext",
        (),
        {"__enter__": lambda self: str(tmp_path), "__exit__": lambda self, *args: False},
    )()

    def run_child(*args, **kwargs):
        assert (tmp_path / "stdout.txt").is_file()
        assert (tmp_path / "stderr.txt").is_file()
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="outer stdout", stderr="outer stderr")

    with patch.object(windows_task, "_require_windows"), \
         patch.object(windows_task.tempfile, "TemporaryDirectory", return_value=temp_context), \
         patch.object(windows_task.subprocess, "run", side_effect=run_child), \
         patch.object(Path, "read_text", side_effect=PermissionError("access denied")):
        result = windows_task._run_powershell("Write-Output 'ok'", elevated=True)

    assert result.returncode == 0
    assert result.stdout == "outer stdout"
    assert result.stderr == "outer stderr"
