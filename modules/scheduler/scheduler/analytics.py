"""Schedule-aware run statistics and terminal-friendly activity cells."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from math import ceil
from typing import Dict, Iterable, List, Optional

from script_logging import RunRecord

from .models import Schedule, Task, TimingType
from .timing import calculate_next_run


def _local(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.astimezone().replace(tzinfo=None)


@dataclass(frozen=True)
class WindowStats:
    total: int
    success: int
    failure: int
    average_sec: Optional[float]
    minimum_sec: Optional[float]
    maximum_sec: Optional[float]


def window_stats(runs: Iterable[RunRecord], *, now: Optional[datetime] = None, days: Optional[int] = None) -> WindowStats:
    current = (now or datetime.now()).astimezone().replace(tzinfo=None)
    cutoff = current - timedelta(days=days) if days is not None else None
    selected = [run for run in runs if cutoff is None or _local(run.started_at) >= cutoff]
    durations = [run.duration_sec for run in selected]
    return WindowStats(
        total=len(selected), success=sum(run.status == "success" for run in selected),
        failure=sum(run.status != "success" for run in selected),
        average_sec=sum(durations) / len(durations) if durations else None,
        minimum_sec=min(durations) if durations else None,
        maximum_sec=max(durations) if durations else None,
    )


def expected_daily_counts(
    schedule: Schedule, *, start: date, end: date, coverage_start: str,
    attached_at: Optional[str] = None, now: Optional[datetime] = None,
) -> Dict[date, int]:
    """Count expected occurrences for supported recurrence types within a date window."""
    if not schedule.enabled or end < start:
        return {}
    current = (now or datetime.now()).astimezone().replace(tzinfo=None)
    created = _local(schedule.created_at)
    covered = _local(coverage_start)
    begin = max(datetime.combine(start, time.min), created, covered)
    if attached_at:
        begin = max(begin, _local(attached_at))
    finish = min(datetime.combine(end + timedelta(days=1), time.min), current)
    if finish <= begin:
        return {}

    timing_type = schedule.timing.timing_type.lower()
    if timing_type in {TimingType.INTERVAL.value, TimingType.HOURLY.value}:
        interval = max(10, schedule.timing.interval_seconds)
        anchor = created
        counts: Dict[date, int] = {}
        day = begin.date()
        while day <= finish.date():
            left = max(begin, datetime.combine(day, time.min))
            right = min(finish, datetime.combine(day + timedelta(days=1), time.min))
            if right > left:
                first = max(1, ceil((left - anchor).total_seconds() / interval))
                last = ceil((right - anchor).total_seconds() / interval) - 1
                count = max(0, last - first + 1)
                if count:
                    counts[day] = count
            day += timedelta(days=1)
        return counts

    counts = Counter()
    if timing_type == TimingType.CRON.value and len(schedule.timing.cron_expression.split()) != 5:
        return {}
    cursor = begin - timedelta(seconds=1)
    while True:
        upcoming = calculate_next_run(schedule.timing, after=cursor)
        if upcoming >= finish:
            break
        if upcoming <= cursor:
            break
        if upcoming >= begin:
            counts[upcoming.date()] += 1
        cursor = upcoming
    return dict(counts)


def punctuality(
    runs: Iterable[RunRecord], *, tolerance_seconds: int, expected: Optional[Dict[date, int]] = None,
) -> Dict[str, int]:
    results = {"on_time": 0, "late": 0, "early": 0, "catch_up": 0, "missed": 0}
    matched = Counter()
    for run in runs:
        if run.origin not in {"scheduled", "catch_up"} or not run.scheduled_for:
            continue
        due = _local(run.scheduled_for)
        drift = (_local(run.started_at) - due).total_seconds()
        matched[due.date()] += 1
        if run.origin == "catch_up":
            results["catch_up"] += 1
        if drift > tolerance_seconds:
            results["late"] += 1
        elif drift < -tolerance_seconds:
            results["early"] += 1
        else:
            results["on_time"] += 1
    if expected:
        results["missed"] = sum(max(0, count - matched[day]) for day, count in expected.items())
    return results


def activity_cells(
    runs: Iterable[RunRecord], *, expected: Optional[Dict[date, int]] = None,
    tolerance_seconds: int = 300,
) -> Dict[date, str]:
    """Map activity dates to success, failure, late/partial, or missing."""
    groups: Dict[date, List[RunRecord]] = defaultdict(list)
    for run in runs:
        if expected is not None:
            if run.origin not in {"scheduled", "catch_up"} or not run.scheduled_for:
                continue
            day = _local(run.scheduled_for).date()
        else:
            day = _local(run.started_at).date()
        groups[day].append(run)

    cells: Dict[date, str] = {}
    dates = expected.keys() if expected is not None else groups.keys()
    for day in dates:
        daily = groups.get(day, [])
        if not daily:
            cells[day] = "missed"
        elif any(run.status != "success" for run in daily):
            cells[day] = "failure"
        elif expected is not None and len(daily) < expected[day]:
            cells[day] = "partial"
        elif expected is not None and any(
            (_local(run.started_at) - _local(run.scheduled_for)).total_seconds() > tolerance_seconds
            for run in daily if run.scheduled_for
        ):
            cells[day] = "late"
        else:
            cells[day] = "success"
    return cells


def task_expected_counts(
    task: Task, schedule: Optional[Schedule], *, start: date, end: date,
    coverage_start: str, now: Optional[datetime] = None,
) -> Optional[Dict[date, int]]:
    if schedule is None or not task.enabled:
        return None
    return expected_daily_counts(
        schedule, start=start, end=end, coverage_start=coverage_start,
        attached_at=task.attached_at, now=now,
    )
