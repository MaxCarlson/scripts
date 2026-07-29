"""Portable schedule calculations and human descriptions."""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta
from typing import Optional, Tuple

from .config import RetentionPolicy, Schedule

_WEEKDAYS = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}


def normalize_schedule_type(value: str) -> str:
    """Normalize user and legacy frequency spellings."""

    normalized = (value or "manual").strip().lower()
    aliases = {
        "minutely": "minute",
        "minutes": "minute",
        "hour": "hourly",
        "hours": "hourly",
        "day": "daily",
        "days": "daily",
        "week": "weekly",
        "weeks": "weekly",
        "month": "monthly",
        "months": "monthly",
        "year": "yearly",
        "years": "yearly",
    }
    return aliases.get(normalized, normalized)


def parse_clock(value: Optional[str], *, default: str = "03:00") -> Tuple[int, int]:
    """Parse HH:MM and validate the clock value."""

    raw = (value or default).strip()
    parts = raw.split(":")
    if len(parts) != 2:
        raise ValueError("Schedule time must use HH:MM format.")
    hour = int(parts[0])
    minute = int(parts[1])
    if not 0 <= hour <= 23:
        raise ValueError("Schedule hour must be between 00 and 23.")
    if not 0 <= minute <= 59:
        raise ValueError("Schedule minute must be between 00 and 59.")
    return hour, minute


def schedule_interval(schedule: Schedule) -> int:
    """Return a positive interval while honoring the legacy interval_hours field."""

    if schedule.interval_hours is not None and normalize_schedule_type(schedule.type) == "hourly":
        return max(1, int(schedule.interval_hours))
    return max(1, int(schedule.interval or 1))


def describe_schedule(schedule: Schedule) -> str:
    """Return a compact human description of a schedule."""

    kind = normalize_schedule_type(schedule.type)
    interval = schedule_interval(schedule)
    if kind in {"manual", "custom"}:
        return schedule.description or ("Manual" if kind == "manual" else "Custom")

    hour, minute = parse_clock(schedule.time)
    clock = f"{hour:02d}:{minute:02d}"
    unit = {
        "minute": "minute",
        "hourly": "hour",
        "daily": "day",
        "weekly": "week",
        "monthly": "month",
        "yearly": "year",
    }.get(kind, kind)
    cadence = f"Every {unit}" if interval == 1 else f"Every {interval} {unit}s"

    if kind == "minute":
        return cadence
    if kind == "hourly":
        return f"{cadence} at minute {minute:02d}"
    if kind == "daily":
        return f"{cadence} at {clock}"
    if kind == "weekly":
        day = (schedule.day_of_week or "Sunday").strip().title()
        return f"{cadence} on {day} at {clock}"
    if kind == "monthly":
        day = max(1, min(31, int(schedule.day_of_month or 1)))
        return f"{cadence} on day {day} at {clock}"
    if kind == "yearly":
        month = max(1, min(12, int(schedule.month_of_year or 1)))
        day = max(1, min(31, int(schedule.day_of_month or 1)))
        return f"{cadence} on {calendar.month_abbr[month]} {day} at {clock}"
    return schedule.description or kind.title()


def describe_retention(policy: Optional[RetentionPolicy]) -> str:
    """Return a compact retention summary."""

    if policy is None:
        return "Default retention"
    parts = []
    labels = (
        ("keep_last", "latest"),
        ("keep_hourly", "hourly"),
        ("keep_daily", "daily"),
        ("keep_weekly", "weekly"),
        ("keep_monthly", "monthly"),
        ("keep_yearly", "yearly"),
    )
    for field_name, label in labels:
        value = getattr(policy, field_name)
        if value is not None:
            parts.append(f"{value} {label}")
    if policy.max_total_size:
        parts.append(f"max {policy.max_total_size}")
    return ", ".join(parts) if parts else "No automatic retention"


def _replace_clock(value: datetime, schedule: Schedule) -> datetime:
    hour, minute = parse_clock(schedule.time)
    return value.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _add_months(value: datetime, months: int, day: int) -> datetime:
    total = (value.year * 12 + value.month - 1) + months
    year, month_index = divmod(total, 12)
    month = month_index + 1
    last_day = calendar.monthrange(year, month)[1]
    return value.replace(year=year, month=month, day=min(day, last_day))


def _add_years(value: datetime, years: int, month: int, day: int) -> datetime:
    year = value.year + years
    last_day = calendar.monthrange(year, month)[1]
    return value.replace(year=year, month=month, day=min(day, last_day))


def next_scheduled_run(schedule: Schedule, after: datetime) -> Optional[datetime]:
    """Return the first occurrence strictly after ``after``."""

    kind = normalize_schedule_type(schedule.type)
    if kind in {"manual", "custom"}:
        return None
    interval = schedule_interval(schedule)
    tz = after.tzinfo

    if kind == "minute":
        candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
        minute_of_day = candidate.hour * 60 + candidate.minute
        remainder = minute_of_day % interval
        if remainder:
            candidate += timedelta(minutes=interval - remainder)
        return candidate

    if kind == "hourly":
        _, minute = parse_clock(schedule.time)
        candidate = after.replace(minute=minute, second=0, microsecond=0)
        if candidate <= after:
            candidate += timedelta(hours=1)
        remainder = candidate.hour % interval
        if remainder:
            candidate += timedelta(hours=interval - remainder)
        return candidate

    if kind == "daily":
        candidate = _replace_clock(after, schedule)
        if candidate <= after:
            candidate += timedelta(days=1)
        epoch = datetime(1970, 1, 1, tzinfo=tz)
        day_offset = (candidate.date() - epoch.date()).days
        remainder = day_offset % interval
        if remainder:
            candidate += timedelta(days=interval - remainder)
        return candidate

    if kind == "weekly":
        target = _WEEKDAYS.get((schedule.day_of_week or "sunday").strip().lower())
        if target is None:
            raise ValueError(f"Unsupported weekday: {schedule.day_of_week!r}")
        candidate = _replace_clock(after, schedule)
        candidate += timedelta(days=(target - candidate.weekday()) % 7)
        if candidate <= after:
            candidate += timedelta(days=7)
        epoch_monday = datetime(1970, 1, 5, tzinfo=tz)
        week_offset = (candidate.date() - epoch_monday.date()).days // 7
        remainder = week_offset % interval
        if remainder:
            candidate += timedelta(weeks=interval - remainder)
        return candidate

    if kind == "monthly":
        day = max(1, min(31, int(schedule.day_of_month or 1)))
        hour, minute = parse_clock(schedule.time)
        last_day = calendar.monthrange(after.year, after.month)[1]
        candidate = after.replace(
            day=min(day, last_day),
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )
        if candidate <= after:
            candidate = _add_months(candidate, 1, day)
        month_offset = (candidate.year - 1970) * 12 + candidate.month - 1
        remainder = month_offset % interval
        if remainder:
            candidate = _add_months(candidate, interval - remainder, day)
        return candidate

    if kind == "yearly":
        month = max(1, min(12, int(schedule.month_of_year or 1)))
        day = max(1, min(31, int(schedule.day_of_month or 1)))
        hour, minute = parse_clock(schedule.time)
        last_day = calendar.monthrange(after.year, month)[1]
        candidate = after.replace(
            month=month,
            day=min(day, last_day),
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )
        if candidate <= after:
            candidate = _add_years(candidate, 1, month, day)
        remainder = (candidate.year - 1970) % interval
        if remainder:
            candidate = _add_years(candidate, interval - remainder, month, day)
        return candidate

    raise ValueError(f"Unsupported schedule type: {schedule.type!r}")


def count_missed_runs(
    schedule: Schedule,
    *,
    since: Optional[datetime],
    until: datetime,
    limit: int = 100_000,
) -> Optional[int]:
    """Count expected runs after ``since`` through ``until``.

    ``None`` means there is not enough history to calculate a meaningful count.
    """

    if since is None:
        return None
    candidate = next_scheduled_run(schedule, since)
    count = 0
    while candidate is not None and candidate <= until:
        count += 1
        if count >= limit:
            return count
        candidate = next_scheduled_run(schedule, candidate)
    return count
