from __future__ import annotations

import json
import subprocess

import pytest

from rrbackup import schedule_discovery


def completed(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["pwsh"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_windows_schedule_discovery_normalizes_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(schedule_discovery.shutil, "which", lambda name: "pwsh.exe")
    payload = [
        {
            "backend": "windows-task-scheduler",
            "identifier": "\\BackupModuleLocalBackup",
            "enabled": True,
            "state": "Ready",
            "executable": "python.exe",
            "arguments": ["-m backup_module backup"],
            "working_directory": "C:\\Users\\mcarls\\src\\scripts",
            "principal": "XERES\\mcarls",
            "triggers": [{"type": "MSFT_TaskDailyTrigger", "enabled": True}],
            "settings": {"start_when_available": True},
            "last_run": "2026-07-28T03:00:00",
            "next_run": "2026-07-29T03:00:00",
            "last_result": 0,
            "missed_runs": 1,
        }
    ]

    discovery = schedule_discovery.discover_schedules(
        platform_name="nt",
        command_runner=lambda *args, **kwargs: completed(json.dumps(payload)),
    )

    assert discovery.available
    assert len(discovery.records) == 1
    record = discovery.records[0]
    assert record.identifier == "\\BackupModuleLocalBackup"
    assert record.enabled is True
    assert record.missed_runs == 1
    assert record.settings["start_when_available"] is True


def test_windows_discovery_reports_missing_powershell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(schedule_discovery.shutil, "which", lambda name: None)

    discovery = schedule_discovery.discover_schedules(platform_name="nt")

    assert not discovery.available
    assert not discovery.records
    assert "PowerShell" in discovery.warnings[0]


def test_windows_discovery_reports_command_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(schedule_discovery.shutil, "which", lambda name: "pwsh.exe")

    discovery = schedule_discovery.discover_schedules(
        platform_name="nt",
        command_runner=lambda *args, **kwargs: completed(
            stderr="Access denied",
            returncode=1,
        ),
    )

    assert discovery.available
    assert not discovery.records
    assert "Access denied" in discovery.warnings[0]


def test_windows_discovery_reports_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(schedule_discovery.shutil, "which", lambda name: "pwsh.exe")

    discovery = schedule_discovery.discover_schedules(
        platform_name="nt",
        command_runner=lambda *args, **kwargs: completed("not-json"),
    )

    assert discovery.available
    assert "invalid JSON" in discovery.warnings[0]


def test_non_windows_discovery_is_explicitly_unavailable() -> None:
    discovery = schedule_discovery.discover_schedules(platform_name="posix")

    assert not discovery.available
    assert discovery.backend == "systemd-cron"
    assert "planned" in discovery.warnings[0]
