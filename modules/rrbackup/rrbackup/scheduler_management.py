"""Scheduler plan generation and explicitly gated application."""

from __future__ import annotations

import calendar
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .config import Schedule
from .inventory import BackupDefinition
from .schedule_math import normalize_schedule_type, parse_clock, schedule_interval


@dataclass(frozen=True)
class SchedulePlan:
    backup_name: str
    task_name: str
    backend: str
    action: str
    schedule: Schedule
    backup_command: Tuple[str, ...]
    scheduler_command: Tuple[str, ...]
    config_path: Optional[str]

    def to_dict(self) -> Dict[str, object]:
        return {
            "backup_name": self.backup_name,
            "task_name": self.task_name,
            "backend": self.backend,
            "action": self.action,
            "schedule": self.schedule.to_dict(),
            "backup_command": list(self.backup_command),
            "scheduler_command": list(self.scheduler_command),
            "config_path": self.config_path,
        }

    def render_scheduler_command(self) -> str:
        if os.name == "nt":
            return subprocess.list2cmdline(list(self.scheduler_command))
        return shlex.join(list(self.scheduler_command))


@dataclass(frozen=True)
class ScheduleApplyResult:
    plan: SchedulePlan
    executed: bool
    return_code: Optional[int]
    stdout: str = ""
    stderr: str = ""

    @property
    def succeeded(self) -> bool:
        return self.executed and self.return_code == 0

    def to_dict(self) -> Dict[str, object]:
        return {
            "plan": self.plan.to_dict(),
            "executed": self.executed,
            "return_code": self.return_code,
            "succeeded": self.succeeded,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


def build_backup_command(
    definition: BackupDefinition,
    *,
    config_path: Optional[str],
    python_executable: Optional[str] = None,
) -> Tuple[str, ...]:
    """Build a stable scheduled invocation through the canonical application."""

    command: List[str] = [
        str(Path(python_executable or sys.executable).resolve()),
        "-m",
        "rrbackup.application",
    ]
    if config_path:
        command.extend(["--config", config_path])
    command.extend(["run", definition.name])
    return tuple(command)


def _windows_month(value: Optional[int]) -> str:
    month = max(1, min(12, int(value or 1)))
    return calendar.month_abbr[month].upper()


def _windows_schedule_arguments(schedule: Schedule) -> List[str]:
    kind = normalize_schedule_type(schedule.type)
    interval = schedule_interval(schedule)
    if kind == "manual":
        return []
    if kind == "custom":
        raise ValueError("Custom schedule text cannot be applied automatically.")

    hour, minute = parse_clock(schedule.time)
    start_time = "{0:02d}:{1:02d}".format(hour, minute)
    arguments: List[str] = []
    if kind == "minute":
        arguments.extend(["/SC", "MINUTE", "/MO", str(interval)])
    elif kind == "hourly":
        arguments.extend(["/SC", "HOURLY", "/MO", str(interval), "/ST", start_time])
    elif kind == "daily":
        arguments.extend(["/SC", "DAILY", "/MO", str(interval), "/ST", start_time])
    elif kind == "weekly":
        day = (schedule.day_of_week or "SUN").strip()[:3].upper()
        arguments.extend(
            ["/SC", "WEEKLY", "/MO", str(interval), "/D", day, "/ST", start_time]
        )
    elif kind == "monthly":
        day = str(max(1, min(31, int(schedule.day_of_month or 1))))
        arguments.extend(
            ["/SC", "MONTHLY", "/MO", str(interval), "/D", day, "/ST", start_time]
        )
    elif kind == "yearly":
        day = str(max(1, min(31, int(schedule.day_of_month or 1))))
        arguments.extend(
            [
                "/SC",
                "MONTHLY",
                "/MO",
                str(12 * interval),
                "/M",
                _windows_month(schedule.month_of_year),
                "/D",
                day,
                "/ST",
                start_time,
            ]
        )
    else:
        raise ValueError("Unsupported schedule type: {0}".format(schedule.type))
    return arguments


def _cron_expression(schedule: Schedule) -> str:
    kind = normalize_schedule_type(schedule.type)
    interval = schedule_interval(schedule)
    if kind == "manual":
        return ""
    hour, minute = parse_clock(schedule.time)
    if kind == "minute":
        return "*/{0} * * * *".format(interval)
    if kind == "hourly":
        return "{0} */{1} * * *".format(minute, interval)
    if kind == "daily":
        return "{0} {1} */{2} * *".format(minute, hour, interval)
    if kind == "weekly":
        days = {
            "sun": 0,
            "mon": 1,
            "tue": 2,
            "wed": 3,
            "thu": 4,
            "fri": 5,
            "sat": 6,
        }
        day = days.get((schedule.day_of_week or "sun").strip()[:3].lower(), 0)
        return "{0} {1} * * {2}".format(minute, hour, day)
    if kind == "monthly":
        day = max(1, min(31, int(schedule.day_of_month or 1)))
        return "{0} {1} {2} */{3} *".format(minute, hour, day, interval)
    if kind == "yearly":
        day = max(1, min(31, int(schedule.day_of_month or 1)))
        month = max(1, min(12, int(schedule.month_of_year or 1)))
        return "{0} {1} {2} {3} *".format(minute, hour, day, month)
    raise ValueError("Unsupported schedule type: {0}".format(schedule.type))


def build_schedule_plan(
    definition: BackupDefinition,
    *,
    config_path: Optional[str],
    platform_name: Optional[str] = None,
    python_executable: Optional[str] = None,
) -> SchedulePlan:
    """Build a non-mutating scheduler plan."""

    platform_value = os.name if platform_name is None else platform_name
    schedule = definition.schedule
    backup_command = build_backup_command(
        definition,
        config_path=config_path,
        python_executable=python_executable,
    )
    kind = normalize_schedule_type(schedule.type)

    if platform_value == "nt":
        if kind == "manual":
            scheduler_command = ("schtasks", "/Delete", "/TN", definition.task_name, "/F")
            action = "delete"
        else:
            task_command = subprocess.list2cmdline(list(backup_command))
            scheduler_command = tuple(
                [
                    "schtasks",
                    "/Create",
                    "/TN",
                    definition.task_name,
                    "/TR",
                    task_command,
                ]
                + _windows_schedule_arguments(schedule)
                + ["/F", "/RL", "HIGHEST"]
            )
            action = "create-or-update"
        return SchedulePlan(
            backup_name=definition.name,
            task_name=definition.task_name,
            backend="windows-task-scheduler",
            action=action,
            schedule=schedule,
            backup_command=backup_command,
            scheduler_command=scheduler_command,
            config_path=config_path,
        )

    expression = _cron_expression(schedule)
    if kind == "manual":
        scheduler_command = ("crontab", "remove", definition.task_name)
        action = "delete"
    else:
        scheduler_command = tuple(
            [expression] + [shlex.join(list(backup_command))]
        )
        action = "create-or-update"
    return SchedulePlan(
        backup_name=definition.name,
        task_name=definition.task_name,
        backend="cron-plan",
        action=action,
        schedule=schedule,
        backup_command=backup_command,
        scheduler_command=scheduler_command,
        config_path=config_path,
    )


def apply_schedule_plan(
    plan: SchedulePlan,
    *,
    apply: bool,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> ScheduleApplyResult:
    """Apply a Windows plan only after an explicit gate."""

    if not apply:
        return ScheduleApplyResult(plan=plan, executed=False, return_code=None)
    if plan.backend != "windows-task-scheduler":
        raise ValueError(
            "Automatic schedule application is currently implemented only for Windows; "
            "the generated cron plan remains available for manual review."
        )
    completed = runner(
        list(plan.scheduler_command),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return ScheduleApplyResult(
        plan=plan,
        executed=True,
        return_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
