"""Recurrence, punctuality, and activity-grid behavior."""
from datetime import date, datetime, timedelta, timezone
import pytest

from script_logging import RunRecord

from scheduler.analytics import activity_cells, expected_daily_counts, punctuality, window_stats
from scheduler.models import Schedule, ScheduleTiming


def _run(name: str, due: datetime, started: datetime, *, success: bool = True) -> RunRecord:
    return RunRecord(
        source="scheduler", entity_type="schedule", entity_id=name, display_name=name,
        started_at=started.isoformat(), finished_at=(started + timedelta(seconds=4)).isoformat(),
        status="success" if success else "failure", duration_sec=4.0, exit_code=0 if success else 1,
        origin="scheduled", scheduled_for=due.isoformat(),
    )


def test_specific_days_only_count_expected_dates():
    schedule = Schedule(
        name="MWF", timing=ScheduleTiming(timing_type="specific_days", at_time="13:00", days=["monday", "wednesday", "friday"]),
        created_at="2026-10-01T00:00:00",
    )
    counts = expected_daily_counts(
        schedule, start=date(2026, 10, 5), end=date(2026, 10, 11),
        coverage_start="2026-10-01T00:00:00", now=datetime(2026, 10, 12, tzinfo=timezone.utc),
    )
    assert set(counts) == {date(2026, 10, 5), date(2026, 10, 7), date(2026, 10, 9)}


def test_hourly_recurrence_counts_multiple_slots_per_day():
    schedule = Schedule(
        name="Hourly", timing=ScheduleTiming(timing_type="interval", interval_seconds=3600),
        created_at="2026-10-01T00:00:00",
    )
    counts = expected_daily_counts(
        schedule, start=date(2026, 10, 2), end=date(2026, 10, 2),
        coverage_start="2026-10-01T00:00:00", now=datetime(2026, 10, 4, tzinfo=timezone.utc),
    )
    assert counts[date(2026, 10, 2)] == 24


def test_punctuality_activity_and_runtime_stats():
    monday = datetime(2026, 10, 5, 13, 0, tzinfo=timezone.utc)
    wednesday = monday + timedelta(days=2)
    friday = monday + timedelta(days=4)
    runs = [
        _run("MWF", monday, monday + timedelta(minutes=1)),
        _run("MWF", wednesday, wednesday + timedelta(minutes=12)),
    ]
    expected = {monday.date(): 1, wednesday.date(): 1, friday.date(): 1}

    assert punctuality(runs, tolerance_seconds=300, expected=expected) == {
        "on_time": 1, "late": 1, "early": 0, "catch_up": 0, "missed": 1,
    }
    assert activity_cells(runs, expected=expected, tolerance_seconds=300) == {
        monday.date(): "success", wednesday.date(): "late", friday.date(): "missed",
    }
    summary = window_stats(runs, now=datetime(2026, 10, 12, tzinfo=timezone.utc), days=30)
    assert (summary.total, summary.success, summary.failure) == (2, 2, 0)
    assert (summary.average_sec, summary.minimum_sec, summary.maximum_sec) == (4.0, 4.0, 4.0)


@pytest.mark.parametrize("timing,expected", [
    (ScheduleTiming(timing_type="daily", at_time="12:00"), {date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7)}),
    (ScheduleTiming(timing_type="weekly", days=["monday"], at_time="12:00"), {date(2026, 10, 5)}),
    (ScheduleTiming(timing_type="monthly", day_of_month=6, at_time="12:00"), {date(2026, 10, 6)}),
    (ScheduleTiming(timing_type="cron", cron_expression="0 12 * * 2"), {date(2026, 10, 6)}),
])
def test_other_recurrence_types(timing, expected):
    schedule = Schedule(name="Various", timing=timing, created_at="2026-10-01T00:00:00")
    counts = expected_daily_counts(
        schedule, start=date(2026, 10, 5), end=date(2026, 10, 7),
        coverage_start="2026-10-01T00:00:00", now=datetime(2026, 10, 8, tzinfo=timezone.utc),
    )
    assert set(counts) == expected


def test_activity_distinguishes_failure_and_partial_day():
    day = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)
    assert activity_cells([_run("x", day, day, success=False)], expected={day.date(): 1})[day.date()] == "failure"
    assert activity_cells([_run("x", day, day)], expected={day.date(): 2})[day.date()] == "partial"
    assert punctuality([_run("x", day, day)], tolerance_seconds=300, expected={day.date(): 2})["missed"] == 1
