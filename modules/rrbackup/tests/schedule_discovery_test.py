from __future__ import annotations

import json
import subprocess

import pytest

from rrbackup import schedule_discovery
from rrbackup.schedule_discovery import ScheduleRecord, is_owned_schedule_record


def completed(
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
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


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        (
            ScheduleRecord(
                backend="windows-task-scheduler",
                identifier="\\RRBackup::local-main",
                enabled=True,
                state="Ready",
                executable="backup.exe",
                arguments=("run", "local-main"),
            ),
            True,
        ),
        (
            ScheduleRecord(
                backend="windows-task-scheduler",
                identifier="\\CustomTask",
                enabled=True,
                state="Ready",
                executable="backup.exe",
                arguments=("run", "local-main"),
            ),
            True,
        ),
        (
            ScheduleRecord(
                backend="windows-task-scheduler",
                identifier="\\LegacyBackup",
                enabled=True,
                state="Ready",
                executable="python.exe",
                arguments=("-m", "backup_module", "backup"),
            ),
            True,
        ),
        (
            ScheduleRecord(
                backend="windows-task-scheduler",
                identifier="\\BackupInstalledPrograms",
                enabled=True,
                state="Ready",
                executable="pwsh.exe",
                arguments=("-File", "BackupInstalledPrograms.ps1"),
            ),
            False,
        ),
        (
            ScheduleRecord(
                backend="windows-task-scheduler",
                identifier="\\Microsoft\\Windows\\CloudRestore\\Backup",
                enabled=True,
                state="Ready",
                executable="rundll32.exe",
                arguments=("cloudrestore.dll",),
            ),
            False,
        ),
        (
            ScheduleRecord(
                backend="windows-task-scheduler",
                identifier="\\BackupViewer",
                enabled=True,
                state="Ready",
                executable="backup.exe",
                arguments=("view",),
            ),
            False,
        ),
    ],
)
def test_schedule_ownership_is_strict(
    record: ScheduleRecord,
    expected: bool,
) -> None:
    assert is_owned_schedule_record(record) is expected


def test_windows_discovery_drops_unrelated_backup_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(schedule_discovery.shutil, "which", lambda name: "pwsh.exe")
    payload = [
        {
            "backend": "windows-task-scheduler",
            "identifier": "\\RRBackup::local-main",
            "enabled": True,
            "state": "Ready",
            "executable": "backup.exe",
            "arguments": ["run", "local-main"],
        },
        {
            "backend": "windows-task-scheduler",
            "identifier": "\\BackupInstalledPrograms",
            "enabled": True,
            "state": "Ready",
            "executable": "pwsh.exe",
            "arguments": ["-File", "BackupInstalledPrograms.ps1"],
        },
    ]

    discovery = schedule_discovery.discover_schedules(
        platform_name="nt",
        command_runner=lambda *args, **kwargs: completed(json.dumps(payload)),
    )

    assert [record.identifier for record in discovery.records] == [
        "\\RRBackup::local-main"
    ]


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
