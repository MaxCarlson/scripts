from __future__ import annotations

from datetime import datetime, timezone

import pytest

from rrbackup.config import RetentionPolicy, Schedule
from rrbackup.schedule_math import (
    count_missed_runs,
    describe_retention,
    describe_schedule,
    next_scheduled_run,
    normalize_schedule_type,
    parse_clock,
)

UTC = timezone.utc
NOW = datetime(2026, 7, 29, 9, 37, tzinfo=UTC)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("minutes", "minute"),
        ("hour", "hourly"),
        ("days", "daily"),
        ("week", "weekly"),
        ("months", "monthly"),
        ("year", "yearly"),
        ("manual", "manual"),
    ],
)
def test_normalize_schedule_type(raw: str, expected: str) -> None:
    assert normalize_schedule_type(raw) == expected


@pytest.mark.parametrize("value", ["24:00", "09:60", "9", "invalid"])
def test_parse_clock_rejects_invalid_values(value: str) -> None:
    with pytest.raises((ValueError, TypeError)):
        parse_clock(value)


@pytest.mark.parametrize(
    ("schedule", "expected"),
    [
        (Schedule(type="manual"), "Manual"),
        (Schedule(type="minute", interval=15), "Every 15 minutes"),
        (Schedule(type="hourly", interval=2, time="00:20"), "Every 2 hours at minute 20"),
        (Schedule(type="daily", time="03:15"), "Every day at 03:15"),
        (
            Schedule(type="weekly", time="04:00", day_of_week="Monday"),
            "Every week on Monday at 04:00",
        ),
        (
            Schedule(type="monthly", interval=3, time="05:00", day_of_month=12),
            "Every 3 months on day 12 at 05:00",
        ),
        (
            Schedule(
                type="yearly",
                time="06:30",
                day_of_month=4,
                month_of_year=7,
            ),
            "Every year on Jul 4 at 06:30",
        ),
    ],
)
def test_describe_schedule(schedule: Schedule, expected: str) -> None:
    assert describe_schedule(schedule) == expected


def test_describe_retention_is_compact() -> None:
    policy = RetentionPolicy(
        keep_last=10,
        keep_daily=7,
        keep_weekly=4,
        keep_monthly=3,
        keep_yearly=1,
    )

    assert describe_retention(policy) == "10 latest, 7 daily, 4 weekly, 3 monthly, 1 yearly"


@pytest.mark.parametrize(
    ("schedule", "expected"),
    [
        (Schedule(type="minute", interval=15), datetime(2026, 7, 29, 9, 45, tzinfo=UTC)),
        (Schedule(type="hourly", interval=2, time="00:20"), datetime(2026, 7, 29, 10, 20, tzinfo=UTC)),
        (Schedule(type="daily", time="03:00"), datetime(2026, 7, 30, 3, 0, tzinfo=UTC)),
        (
            Schedule(type="weekly", time="04:00", day_of_week="Sunday"),
            datetime(2026, 8, 2, 4, 0, tzinfo=UTC),
        ),
        (
            Schedule(type="monthly", time="05:00", day_of_month=1),
            datetime(2026, 8, 1, 5, 0, tzinfo=UTC),
        ),
        (
            Schedule(type="yearly", time="06:30", day_of_month=4, month_of_year=7),
            datetime(2027, 7, 4, 6, 30, tzinfo=UTC),
        ),
    ],
)
def test_next_scheduled_run(schedule: Schedule, expected: datetime) -> None:
    assert next_scheduled_run(schedule, NOW) == expected


def test_manual_schedule_has_no_next_or_missed_runs() -> None:
    schedule = Schedule(type="manual")

    assert next_scheduled_run(schedule, NOW) is None
    assert count_missed_runs(schedule, since=NOW, until=NOW) == 0


def test_count_missed_daily_runs_after_last_snapshot() -> None:
    schedule = Schedule(type="daily", time="03:00")
    last_snapshot = datetime(2026, 7, 25, 3, 30, tzinfo=UTC)

    assert count_missed_runs(schedule, since=last_snapshot, until=NOW) == 4


def test_count_missed_runs_is_unknown_without_history() -> None:
    assert count_missed_runs(
        Schedule(type="daily", time="03:00"),
        since=None,
        until=NOW,
    ) is None
