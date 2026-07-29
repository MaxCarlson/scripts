"""Read-only discovery of backup-related schedulers and launchers."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence


@dataclass(frozen=True)
class ScheduleRecord:
    """Normalized scheduler record."""

    backend: str
    identifier: str
    enabled: Optional[bool]
    state: Optional[str]
    executable: Optional[str]
    arguments: Sequence[str] = field(default_factory=tuple)
    working_directory: Optional[str] = None
    principal: Optional[str] = None
    triggers: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    settings: Mapping[str, Any] = field(default_factory=dict)
    last_run: Optional[str] = None
    next_run: Optional[str] = None
    last_result: Optional[int] = None
    missed_runs: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the schedule record."""

        return {
            "backend": self.backend,
            "identifier": self.identifier,
            "enabled": self.enabled,
            "state": self.state,
            "executable": self.executable,
            "arguments": list(self.arguments),
            "working_directory": self.working_directory,
            "principal": self.principal,
            "triggers": [dict(trigger) for trigger in self.triggers],
            "settings": dict(self.settings),
            "last_run": self.last_run,
            "next_run": self.next_run,
            "last_result": self.last_result,
            "missed_runs": self.missed_runs,
        }


@dataclass(frozen=True)
class ScheduleDiscovery:
    """Result of scheduler inspection on the current platform."""

    backend: str
    available: bool
    records: Sequence[ScheduleRecord]
    warnings: Sequence[str] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize scheduler discovery."""

        return {
            "backend": self.backend,
            "available": self.available,
            "records": [record.to_dict() for record in self.records],
            "warnings": list(self.warnings),
        }


_WINDOWS_DISCOVERY_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$pattern = '(?i)(backup|restic|rrbackup|rrb|backup_module)'
$records = foreach ($task in Get-ScheduledTask) {
    $actionText = (($task.Actions | ForEach-Object { "{0} {1}" -f $_.Execute, $_.Arguments }) -join ' ')
    if ($task.TaskName -notmatch $pattern -and $task.TaskPath -notmatch $pattern -and $actionText -notmatch $pattern) {
        continue
    }
    $info = $null
    try { $info = Get-ScheduledTaskInfo -TaskName $task.TaskName -TaskPath $task.TaskPath } catch {}
    [pscustomobject]@{
        backend = 'windows-task-scheduler'
        identifier = ('{0}{1}' -f $task.TaskPath, $task.TaskName)
        enabled = [bool]($task.State -ne 'Disabled')
        state = [string]$task.State
        executable = if ($task.Actions.Count -gt 0) { [string]$task.Actions[0].Execute } else { $null }
        arguments = @($task.Actions | ForEach-Object { [string]$_.Arguments })
        working_directory = if ($task.Actions.Count -gt 0) { [string]$task.Actions[0].WorkingDirectory } else { $null }
        principal = [string]$task.Principal.UserId
        triggers = @($task.Triggers | ForEach-Object {
            [ordered]@{
                type = $_.CimClass.CimClassName
                enabled = $_.Enabled
                start_boundary = $_.StartBoundary
                end_boundary = $_.EndBoundary
            }
        })
        settings = [ordered]@{
            multiple_instances = [string]$task.Settings.MultipleInstances
            start_when_available = [bool]$task.Settings.StartWhenAvailable
            wake_to_run = [bool]$task.Settings.WakeToRun
            execution_time_limit = [string]$task.Settings.ExecutionTimeLimit
            restart_count = $task.Settings.RestartCount
            restart_interval = [string]$task.Settings.RestartInterval
        }
        last_run = if ($info) { [string]$info.LastRunTime } else { $null }
        next_run = if ($info) { [string]$info.NextRunTime } else { $null }
        last_result = if ($info) { [int]$info.LastTaskResult } else { $null }
        missed_runs = if ($info) { [int]$info.NumberOfMissedRuns } else { $null }
    }
}
@($records) | ConvertTo-Json -Depth 8 -Compress
"""


def _parse_windows_records(payload: Any) -> List[ScheduleRecord]:
    if payload in (None, "", []):
        return []
    items = payload if isinstance(payload, list) else [payload]
    records: List[ScheduleRecord] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        records.append(
            ScheduleRecord(
                backend=str(item.get("backend") or "windows-task-scheduler"),
                identifier=str(item.get("identifier") or ""),
                enabled=(
                    None if item.get("enabled") is None else bool(item.get("enabled"))
                ),
                state=None if item.get("state") is None else str(item.get("state")),
                executable=(
                    None
                    if item.get("executable") is None
                    else str(item.get("executable"))
                ),
                arguments=tuple(str(value) for value in item.get("arguments", [])),
                working_directory=(
                    None
                    if item.get("working_directory") is None
                    else str(item.get("working_directory"))
                ),
                principal=(
                    None if item.get("principal") is None else str(item.get("principal"))
                ),
                triggers=tuple(
                    dict(value)
                    for value in item.get("triggers", [])
                    if isinstance(value, Mapping)
                ),
                settings=(
                    dict(item.get("settings", {}))
                    if isinstance(item.get("settings", {}), Mapping)
                    else {}
                ),
                last_run=(
                    None if item.get("last_run") is None else str(item.get("last_run"))
                ),
                next_run=(
                    None if item.get("next_run") is None else str(item.get("next_run"))
                ),
                last_result=(
                    None
                    if item.get("last_result") is None
                    else int(item.get("last_result"))
                ),
                missed_runs=(
                    None
                    if item.get("missed_runs") is None
                    else int(item.get("missed_runs"))
                ),
            )
        )
    return records


def discover_schedules(
    *,
    platform_name: Optional[str] = None,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> ScheduleDiscovery:
    """Discover backup-related schedules without mutating scheduler state."""

    platform_value = os.name if platform_name is None else platform_name
    if platform_value == "nt":
        executable = shutil.which("pwsh") or shutil.which("powershell")
        if not executable:
            return ScheduleDiscovery(
                backend="windows-task-scheduler",
                available=False,
                records=tuple(),
                warnings=("PowerShell was not found; Task Scheduler discovery is unavailable.",),
            )
        completed = command_runner(
            [executable, "-NoLogo", "-NoProfile", "-Command", _WINDOWS_DISCOVERY_SCRIPT],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            return ScheduleDiscovery(
                backend="windows-task-scheduler",
                available=True,
                records=tuple(),
                warnings=(
                    "Task Scheduler discovery failed: {0}".format(
                        completed.stderr.strip() or "unknown error"
                    ),
                ),
            )
        text = completed.stdout.strip()
        try:
            payload = [] if not text else json.loads(text)
        except json.JSONDecodeError as exc:
            return ScheduleDiscovery(
                backend="windows-task-scheduler",
                available=True,
                records=tuple(),
                warnings=("Task Scheduler returned invalid JSON: {0}".format(exc),),
            )
        return ScheduleDiscovery(
            backend="windows-task-scheduler",
            available=True,
            records=tuple(_parse_windows_records(payload)),
        )

    return ScheduleDiscovery(
        backend="systemd-cron",
        available=False,
        records=tuple(),
        warnings=(
            "systemd and cron discovery are planned for the scheduler stage; no mutation occurred.",
        ),
    )
