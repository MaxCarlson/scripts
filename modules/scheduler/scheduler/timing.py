"""
Timing calculations, recurrence rules, cron matching, and catch-up detection.
"""
from __future__ import annotations

import calendar
import re
from datetime import datetime, timedelta
from typing import List, Optional, Sequence, Set, Tuple

from .models import Schedule, ScheduleTiming, TimingType

WEEKDAYS = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}


def parse_time_string(t_str: str) -> Tuple[int, int]:
    """Parse 'HH:MM' string into (hour, minute). Defaults to (0, 0) on error."""
    if not t_str:
        return 0, 0
    t_str = t_str.strip().lower()
    if t_str == "midnight":
        return 0, 0
    if t_str == "noon":
        return 12, 0
    parts = t_str.split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        return max(0, min(23, hour)), max(0, min(59, minute))
    except (ValueError, IndexError):
        return 0, 0


def parse_interval_string(interval_str: str) -> int:
    """
    Parse an interval like '3h', '30m', '1d', '3600s', '3' (default hours) into seconds.
    """
    if not interval_str:
        return 3600
    interval_str = str(interval_str).strip().lower()
    match = re.match(r"^(\d+)\s*([smhd]?)$", interval_str)
    if not match:
        try:
            return max(1, int(float(interval_str)))
        except ValueError:
            return 3600
    val, unit = int(match.group(1)), match.group(2)
    if unit == "s":
        return max(1, val)
    elif unit == "m":
        return max(1, val * 60)
    elif unit == "d":
        return max(1, val * 86400)
    else:  # default 'h' or hours
        return max(1, val * 3600)


def normalize_days(days: Sequence[str] | str) -> List[str]:
    """Normalize a list or comma-separated string of day names."""
    if isinstance(days, str):
        raw_items = [d.strip().lower() for d in days.split(",") if d.strip()]
    else:
        raw_items = [str(d).strip().lower() for d in days if str(d).strip()]
    normalized = []
    inv_map = {0: "monday", 1: "tuesday", 2: "wednesday", 3: "thursday", 4: "friday", 5: "saturday", 6: "sunday"}
    for item in raw_items:
        if item in WEEKDAYS:
            day_name = inv_map[WEEKDAYS[item]]
            if day_name not in normalized:
                normalized.append(day_name)
    return normalized or ["monday"]


# ── Cron Evaluator (Pure Python, standard 5-part cron) ──

def _parse_cron_field(field_str: str, min_val: int, max_val: int) -> Set[int]:
    """Parse a single cron field expression into a set of integers."""
    result: Set[int] = set()
    field_str = field_str.strip()
    if field_str == "*":
        return set(range(min_val, max_val + 1))

    for part in field_str.split(","):
        part = part.strip()
        if not part:
            continue
        if "/" in part:
            subparts = part.split("/")
            step = int(subparts[1]) if len(subparts) > 1 and subparts[1].isdigit() else 1
            step = max(1, step)
            base = subparts[0]
            if base == "*":
                start, end = min_val, max_val
            elif "-" in base:
                r_parts = base.split("-")
                start, end = int(r_parts[0]), int(r_parts[1])
            else:
                start, end = int(base), max_val
            result.update(range(start, end + 1, step))
        elif "-" in part:
            r_parts = part.split("-")
            start, end = int(r_parts[0]), int(r_parts[1])
            result.update(range(min(start, end), max(start, end) + 1))
        else:
            if part.isdigit():
                val = int(part)
                if min_val <= val <= max_val:
                    result.add(val)
    return result or set(range(min_val, max_val + 1))


def match_cron(cron_expr: str, dt: datetime) -> bool:
    """Check if a datetime matches a 5-part cron expression (min, hour, dom, mon, dow)."""
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        return False
    minutes = _parse_cron_field(parts[0], 0, 59)
    hours = _parse_cron_field(parts[1], 0, 23)
    doms = _parse_cron_field(parts[2], 1, 31)
    months = _parse_cron_field(parts[3], 1, 12)
    # Cron DOW: 0=Sun..6=Sat or 7=Sun
    dows_raw = _parse_cron_field(parts[4], 0, 7)
    dows = {0 if d == 7 else d for d in dows_raw}

    # Python weekday(): Monday=0..Sunday=6. Cron: Sunday=0, Mon=1, ..., Sat=6
    cron_weekday = (dt.weekday() + 1) % 7

    return (
        dt.minute in minutes
        and dt.hour in hours
        and dt.day in doms
        and dt.month in months
        and cron_weekday in dows
    )


def calculate_next_run(timing: ScheduleTiming, after: Optional[datetime] = None) -> datetime:
    """Calculate the next scheduled datetime after the given reference point."""
    if after is None:
        after = datetime.now()
    # Truncate microseconds for clean comparisons
    after = after.replace(microsecond=0)
    t_type = timing.timing_type.lower()
    hour, minute = parse_time_string(timing.at_time)

    if t_type == TimingType.DAILY.value:
        candidate = after.replace(hour=hour, minute=minute, second=0)
        if candidate <= after:
            candidate += timedelta(days=1)
        return candidate

    elif t_type in (TimingType.HOURLY.value, TimingType.INTERVAL.value):
        interval_sec = max(10, timing.interval_seconds)
        return after + timedelta(seconds=interval_sec)

    elif t_type == TimingType.WEEKLY.value:
        target_day = WEEKDAYS.get(timing.days[0].lower(), 0) if timing.days else 0
        candidate = after.replace(hour=hour, minute=minute, second=0)
        days_ahead = (target_day - after.weekday()) % 7
        if days_ahead == 0 and candidate <= after:
            days_ahead = 7
        return candidate + timedelta(days=days_ahead)

    elif t_type == TimingType.SPECIFIC_DAYS.value:
        days_list = normalize_days(timing.days)
        target_weekdays = {WEEKDAYS[d] for d in days_list if d in WEEKDAYS}
        if not target_weekdays:
            target_weekdays = {0}
        # Check upcoming 14 days
        for i in range(15):
            day_candidate = (after + timedelta(days=i)).replace(hour=hour, minute=minute, second=0)
            if day_candidate.weekday() in target_weekdays and day_candidate > after:
                return day_candidate
        return after + timedelta(days=1)

    elif t_type == TimingType.MONTHLY.value:
        # e.g. 1st of month at midnight
        target_dom = max(1, min(31, timing.day_of_month))
        # Try current month
        try:
            candidate = after.replace(day=target_dom, hour=hour, minute=minute, second=0)
            if candidate > after:
                return candidate
        except ValueError:
            pass  # Day does not exist in this month (e.g. Feb 30)

        # Move to next month
        year = after.year + (1 if after.month == 12 else 0)
        month = 1 if after.month == 12 else after.month + 1
        max_days = calendar.monthrange(year, month)[1]
        valid_dom = min(target_dom, max_days)
        return datetime(year, month, valid_dom, hour, minute, 0)

    elif t_type == TimingType.CRON.value:
        # Step minute-by-minute up to 366 days
        curr = after.replace(second=0) + timedelta(minutes=1)
        for _ in range(525600):  # 1 year in minutes
            if match_cron(timing.cron_expression, curr):
                return curr
            curr += timedelta(minutes=1)
        return after + timedelta(days=1)

    # Fallback default: 1 hour later
    return after + timedelta(hours=1)


def is_missed_run(schedule: Schedule, now: Optional[datetime] = None) -> Tuple[bool, Optional[datetime]]:
    """
    Check if a schedule was missed while inactive or off.
    Returns (was_missed, expected_run_time).
    """
    if now is None:
        now = datetime.now()
    if not schedule.enabled or not schedule.catch_up:
        return False, None

    ref_str = schedule.last_run_time or schedule.created_at
    try:
        ref_dt = datetime.fromisoformat(ref_str)
    except (ValueError, TypeError):
        ref_dt = now - timedelta(days=1)

    expected = calculate_next_run(schedule.timing, after=ref_dt)
    if expected < (now - timedelta(seconds=5)):
        return True, expected
    return False, None


def evaluate_schedule_trigger(schedule: Schedule, now: Optional[datetime] = None) -> Tuple[bool, bool, str]:
    """
    Evaluate if a schedule should trigger right now.
    Returns (should_trigger, is_catchup, reason).
    """
    if now is None:
        now = datetime.now()

    if not schedule.enabled:
        return False, False, "Schedule disabled"

    # Check catch-up first
    if schedule.catch_up:
        missed, expected_dt = is_missed_run(schedule, now=now)
        if missed and expected_dt:
            return True, True, f"Catch-up for missed run expected at {expected_dt.isoformat()}"

    # Check normal scheduled time
    if schedule.next_run_time:
        try:
            next_dt = datetime.fromisoformat(schedule.next_run_time)
            if next_dt <= now:
                return True, False, f"Scheduled time {schedule.next_run_time} reached"
        except (ValueError, TypeError):
            pass

    # If no next_run_time was recorded, calculate it
    ref_str = schedule.last_run_time or schedule.created_at
    try:
        ref_dt = datetime.fromisoformat(ref_str)
    except (ValueError, TypeError):
        ref_dt = now - timedelta(hours=1)

    next_expected = calculate_next_run(schedule.timing, after=ref_dt)
    if next_expected <= now:
        return True, False, f"Expected run time {next_expected.isoformat()} reached"

    return False, False, f"Next run scheduled at {next_expected.isoformat()}"
