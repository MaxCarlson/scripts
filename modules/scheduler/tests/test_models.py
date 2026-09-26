"""
Unit tests for scheduler data models and timing formatting.
"""
from scheduler.models import (
    Schedule,
    ScheduleTiming,
    Task,
    ExecutionResult,
    TimingType,
    ShellEnvironment,
)


def test_schedule_timing_human_readable():
    # Daily
    t_daily = ScheduleTiming(timing_type=TimingType.DAILY.value, at_time="02:30")
    assert "Daily at 02:30" in t_daily.human_readable()

    # Interval / Hourly
    t_inv = ScheduleTiming(timing_type=TimingType.INTERVAL.value, interval_seconds=10800)
    assert "Every 3h" in t_inv.human_readable()

    # Weekly
    t_weekly = ScheduleTiming(timing_type=TimingType.WEEKLY.value, days=["monday"], at_time="09:00")
    assert "Weekly on Monday at 09:00" in t_weekly.human_readable()

    # Specific days
    t_days = ScheduleTiming(timing_type=TimingType.SPECIFIC_DAYS.value, days=["mon", "wed"], at_time="14:00")
    assert "Days (Mon, Wed) at 14:00" in t_days.human_readable()

    # Monthly 1st at midnight
    t_month = ScheduleTiming(timing_type=TimingType.MONTHLY.value, day_of_month=1, at_time="00:00")
    assert "1st of the month at midnight" in t_month.human_readable()

    # Monthly other
    t_month2 = ScheduleTiming(timing_type=TimingType.MONTHLY.value, day_of_month=15, at_time="10:00")
    assert "15th of the month at 10:00" in t_month2.human_readable()

    # Cron
    t_cron = ScheduleTiming(timing_type=TimingType.CRON.value, cron_expression="0 0 1 * *")
    assert "Cron: 0 0 1 * *" in t_cron.human_readable()


def test_schedule_serialization():
    timing = ScheduleTiming(timing_type="daily", at_time="04:00")
    sched = Schedule(name="NightlySync", timing=timing, catch_up=True, enabled=True)

    data = sched.to_dict()
    assert data["name"] == "NightlySync"
    assert data["catch_up"] is True
    assert data["timing"]["at_time"] == "04:00"

    recovered = Schedule.from_dict(data)
    assert recovered.name == "NightlySync"
    assert recovered.timing.at_time == "04:00"
    assert recovered.catch_up is True
    assert recovered.enabled is True


def test_task_serialization():
    task = Task(
        name="BackupDb",
        schedule_name="NightlySync",
        environment=ShellEnvironment.PWSH.value,
        admin=True,
        code="Get-Process",
    )

    data = task.to_dict()
    assert data["name"] == "BackupDb"
    assert data["schedule_name"] == "NightlySync"
    assert data["environment"] == "pwsh"
    assert data["admin"] is True
    assert data["code"] == "Get-Process"

    recovered = Task.from_dict(data)
    assert recovered.name == "BackupDb"
    assert recovered.schedule_name == "NightlySync"
    assert recovered.environment == "pwsh"
    assert recovered.admin is True
    assert recovered.code == "Get-Process"


def test_execution_result():
    res = ExecutionResult(
        task_name="TestTask",
        schedule_name="TestSched",
        timestamp="2026-09-26T15:00:00",
        exit_code=0,
        stdout="success output",
        stderr="",
        duration_sec=0.45,
        environment="terminal",
        admin=False,
        success=True,
    )
    d = res.to_dict()
    assert d["success"] is True
    assert d["exit_code"] == 0
    assert d["duration_sec"] == 0.45
