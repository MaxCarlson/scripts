"""
Unit tests for scheduler timing calculations, cron parsing, and catch-up detection.
"""
from datetime import datetime, timedelta
from scheduler.models import Schedule, ScheduleTiming, TimingType
from scheduler.timing import (
    calculate_next_run,
    is_missed_run,
    match_cron,
    normalize_days,
    parse_interval_string,
    parse_time_string,
    evaluate_schedule_trigger,
)


def test_parse_time_string():
    assert parse_time_string("00:00") == (0, 0)
    assert parse_time_string("midnight") == (0, 0)
    assert parse_time_string("noon") == (12, 0)
    assert parse_time_string("15:45") == (15, 45)
    assert parse_time_string("9:5") == (9, 5)
    assert parse_time_string("invalid") == (0, 0)


def test_parse_interval_string():
    assert parse_interval_string("3h") == 10800
    assert parse_interval_string("30m") == 1800
    assert parse_interval_string("45s") == 45
    assert parse_interval_string("2d") == 172800
    assert parse_interval_string("3") == 10800  # defaults to hours
    assert parse_interval_string("invalid") == 3600


def test_normalize_days():
    assert normalize_days(["mon", "wednesday"]) == ["monday", "wednesday"]
    assert normalize_days("tue, thu, Friday") == ["tuesday", "thursday", "friday"]
    assert normalize_days(["invalid"]) == ["monday"]


def test_match_cron():
    dt = datetime(2026, 9, 26, 12, 0, 0)  # 2026-09-26 is a Saturday
    assert match_cron("0 12 * * *", dt) is True
    assert match_cron("0 13 * * *", dt) is False
    assert match_cron("0 12 26 9 *", dt) is True
    assert match_cron("*/5 * * * *", dt) is True


def test_calculate_next_run_daily():
    ref = datetime(2026, 9, 26, 10, 0, 0)
    # Next run today at 14:00
    timing_today = ScheduleTiming(timing_type=TimingType.DAILY.value, at_time="14:00")
    next_dt = calculate_next_run(timing_today, after=ref)
    assert next_dt == datetime(2026, 9, 26, 14, 0, 0)

    # Next run tomorrow at 08:00
    timing_tomorrow = ScheduleTiming(timing_type=TimingType.DAILY.value, at_time="08:00")
    next_dt = calculate_next_run(timing_tomorrow, after=ref)
    assert next_dt == datetime(2026, 9, 27, 8, 0, 0)


def test_calculate_next_run_interval():
    ref = datetime(2026, 9, 26, 10, 0, 0)
    timing = ScheduleTiming(timing_type=TimingType.INTERVAL.value, interval_seconds=10800)  # 3 hours
    next_dt = calculate_next_run(timing, after=ref)
    assert next_dt == datetime(2026, 9, 26, 13, 0, 0)


def test_calculate_next_run_monthly():
    # Test 1st of month at midnight
    ref = datetime(2026, 9, 26, 10, 0, 0)
    timing = ScheduleTiming(timing_type=TimingType.MONTHLY.value, day_of_month=1, at_time="00:00")
    next_dt = calculate_next_run(timing, after=ref)
    assert next_dt == datetime(2026, 10, 1, 0, 0, 0)


def test_catch_up_detection():
    now = datetime(2026, 9, 26, 16, 0, 0)
    # Last run was yesterday morning at 02:00
    timing = ScheduleTiming(timing_type=TimingType.DAILY.value, at_time="02:00")
    sched = Schedule(
        name="NightlyTask",
        timing=timing,
        catch_up=True,
        enabled=True,
        created_at=(now - timedelta(days=2)).isoformat(),
        last_run_time=(now - timedelta(days=1, hours=14)).isoformat(),  # Yesterday at 02:00
    )

    # Expected today at 02:00, which has passed (now is 16:00)!
    missed, expected_dt = is_missed_run(sched, now=now)
    assert missed is True
    assert expected_dt == datetime(2026, 9, 26, 2, 0, 0)

    should_trig, is_catchup, reason = evaluate_schedule_trigger(sched, now=now)
    assert should_trig is True
    assert is_catchup is True
    assert "Catch-up" in reason


def test_no_catch_up_when_disabled():
    now = datetime(2026, 9, 26, 16, 0, 0)
    timing = ScheduleTiming(timing_type=TimingType.DAILY.value, at_time="02:00")
    sched = Schedule(
        name="NightlyTask",
        timing=timing,
        catch_up=False,  # Catch up disabled
        enabled=True,
        created_at=(now - timedelta(days=2)).isoformat(),
        last_run_time=(now - timedelta(days=1, hours=14)).isoformat(),
    )

    missed, expected_dt = is_missed_run(sched, now=now)
    assert missed is False
