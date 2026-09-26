"""
Data models for schedules, tasks, timing rules, and execution outcomes.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class TimingType(str, Enum):
    DAILY = "daily"
    HOURLY = "hourly"
    INTERVAL = "interval"
    WEEKLY = "weekly"
    SPECIFIC_DAYS = "specific_days"
    MONTHLY = "monthly"
    CRON = "cron"


class ShellEnvironment(str, Enum):
    PWSH = "pwsh"
    POWERSHELL = "powershell"
    TERMINAL = "terminal"


@dataclass
class ScheduleTiming:
    timing_type: str = TimingType.DAILY.value
    at_time: str = "00:00"  # HH:MM
    interval_seconds: int = 3600  # Default 1 hour for interval/hourly
    days: List[str] = field(default_factory=list)  # e.g. ["monday", "friday"]
    day_of_month: int = 1  # 1st of month
    cron_expression: str = ""

    def human_readable(self) -> str:
        t_type = self.timing_type.lower()
        if t_type == TimingType.DAILY.value:
            return f"Daily at {self.at_time}"
        elif t_type in (TimingType.HOURLY.value, TimingType.INTERVAL.value):
            hours = self.interval_seconds // 3600
            minutes = (self.interval_seconds % 3600) // 60
            parts = []
            if hours > 0:
                parts.append(f"{hours}h")
            if minutes > 0 or not parts:
                parts.append(f"{minutes}m")
            return f"Every {' '.join(parts)}"
        elif t_type == TimingType.WEEKLY.value:
            day_str = self.days[0].capitalize() if self.days else "Monday"
            return f"Weekly on {day_str} at {self.at_time}"
        elif t_type == TimingType.SPECIFIC_DAYS.value:
            days_str = ", ".join(d.capitalize() for d in self.days) if self.days else "Monday"
            return f"Days ({days_str}) at {self.at_time}"
        elif t_type == TimingType.MONTHLY.value:
            suffix = "th"
            if self.day_of_month in (1, 21, 31):
                suffix = "st"
            elif self.day_of_month in (2, 22):
                suffix = "nd"
            elif self.day_of_month in (3, 23):
                suffix = "rd"
            time_label = "at midnight" if self.at_time == "00:00" else f"at {self.at_time}"
            return f"{self.day_of_month}{suffix} of the month {time_label}"
        elif t_type == TimingType.CRON.value:
            return f"Cron: {self.cron_expression}"
        return f"{self.timing_type} ({self.at_time})"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ScheduleTiming:
        return cls(
            timing_type=data.get("timing_type", TimingType.DAILY.value),
            at_time=data.get("at_time", "00:00"),
            interval_seconds=int(data.get("interval_seconds", 3600)),
            days=list(data.get("days", [])),
            day_of_month=int(data.get("day_of_month", 1)),
            cron_expression=data.get("cron_expression", ""),
        )


@dataclass
class Schedule:
    name: str
    timing: ScheduleTiming = field(default_factory=ScheduleTiming)
    catch_up: bool = True
    enabled: bool = True
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_run_time: Optional[str] = None
    next_run_time: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "timing": self.timing.to_dict(),
            "catch_up": self.catch_up,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_run_time": self.last_run_time,
            "next_run_time": self.next_run_time,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Schedule:
        timing_data = data.get("timing", {})
        timing = ScheduleTiming.from_dict(timing_data) if isinstance(timing_data, dict) else ScheduleTiming()
        return cls(
            name=data["name"],
            timing=timing,
            catch_up=bool(data.get("catch_up", True)),
            enabled=bool(data.get("enabled", True)),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            last_run_time=data.get("last_run_time"),
            next_run_time=data.get("next_run_time"),
        )


@dataclass
class Task:
    name: str
    schedule_name: Optional[str] = None
    environment: str = ShellEnvironment.TERMINAL.value
    admin: bool = False
    code: str = ""
    enabled: bool = True
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_run_time: Optional[str] = None
    last_status: Optional[str] = None  # "success" or "failure"
    last_exit_code: Optional[int] = None
    last_duration_sec: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Task:
        return cls(
            name=data["name"],
            schedule_name=data.get("schedule_name"),
            environment=data.get("environment", ShellEnvironment.TERMINAL.value),
            admin=bool(data.get("admin", False)),
            code=data.get("code", ""),
            enabled=bool(data.get("enabled", True)),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            last_run_time=data.get("last_run_time"),
            last_status=data.get("last_status"),
            last_exit_code=data.get("last_exit_code"),
            last_duration_sec=data.get("last_duration_sec"),
        )


@dataclass
class ExecutionResult:
    task_name: str
    schedule_name: Optional[str]
    timestamp: str
    exit_code: int
    stdout: str
    stderr: str
    duration_sec: float
    environment: str
    admin: bool
    success: bool
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
