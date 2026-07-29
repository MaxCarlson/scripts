"""CPU and overdue-policy evaluation for backup scheduling."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, List, Optional

import psutil

from .models import ensure_utc, utc_now


@dataclass(frozen=True)
class CpuPolicy:
    """CPU thresholds and wait behavior for a backup profile."""

    normal_threshold: float = 25.0
    overdue_threshold: float = 85.0
    overdue_after: timedelta = timedelta(days=3)
    sample_seconds: float = 5.0
    retry_interval: timedelta = timedelta(minutes=5)
    max_wait: timedelta = timedelta(hours=1)

    def validate(self) -> None:
        """Validate policy values."""

        for name, value in (
            ("normal_threshold", self.normal_threshold),
            ("overdue_threshold", self.overdue_threshold),
        ):
            if value < 0 or value > 100:
                raise ValueError("{0} must be between 0 and 100.".format(name))

        if self.normal_threshold > self.overdue_threshold:
            raise ValueError(
                "normal_threshold cannot be greater than overdue_threshold."
            )
        if self.overdue_after.total_seconds() < 0:
            raise ValueError("overdue_after cannot be negative.")
        if self.sample_seconds <= 0:
            raise ValueError("sample_seconds must be greater than zero.")
        if self.retry_interval.total_seconds() <= 0:
            raise ValueError("retry_interval must be greater than zero.")
        if self.max_wait.total_seconds() < 0:
            raise ValueError("max_wait cannot be negative.")


@dataclass(frozen=True)
class CpuDecision:
    """One CPU-policy decision."""

    should_run: bool
    cpu_percent: float
    threshold: float
    overdue: bool
    age: Optional[timedelta]
    reason: str


@dataclass(frozen=True)
class WaitResult:
    """Result of waiting for an acceptable CPU window."""

    decision: CpuDecision
    attempts: int
    waited: timedelta
    deadline_reached: bool


def measure_cpu_percent(sample_seconds: float) -> float:
    """Measure system-wide CPU usage."""

    return float(psutil.cpu_percent(interval=sample_seconds))


def evaluate_cpu_policy(
    policy: CpuPolicy,
    *,
    last_success: Optional[datetime],
    cpu_percent: float,
    now: Optional[datetime] = None,
) -> CpuDecision:
    """Evaluate a CPU sample against normal or overdue thresholds."""

    policy.validate()
    current = ensure_utc(now or utc_now())
    age: Optional[timedelta]

    if last_success is None:
        age = None
        overdue = True
        age_text = "No prior successful backup is recorded."
    else:
        normalized_success = ensure_utc(last_success)
        age = max(timedelta(0), current - normalized_success)
        overdue = age >= policy.overdue_after
        age_text = "Last successful backup was {0:.2f} day(s) ago.".format(
            age.total_seconds() / 86400.0
        )

    threshold = policy.overdue_threshold if overdue else policy.normal_threshold
    should_run = cpu_percent <= threshold
    mode_text = "overdue" if overdue else "normal"
    comparison = "within" if should_run else "above"
    reason = (
        "{0} CPU usage is {1:.2f}%, which is {2} the {3} threshold "
        "of {4:.2f}%."
    ).format(age_text, cpu_percent, comparison, mode_text, threshold)

    return CpuDecision(
        should_run=should_run,
        cpu_percent=float(cpu_percent),
        threshold=float(threshold),
        overdue=overdue,
        age=age,
        reason=reason,
    )


def wait_for_cpu_window(
    policy: CpuPolicy,
    *,
    last_success: Optional[datetime],
    sampler: Optional[Callable[[float], float]] = None,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], datetime] = utc_now,
    on_decision: Optional[Callable[[CpuDecision], None]] = None,
) -> WaitResult:
    """Wait for an acceptable CPU window without acquiring an execution lock."""

    policy.validate()
    sample = sampler or measure_cpu_percent
    started = ensure_utc(clock())
    deadline = started + policy.max_wait
    decisions: List[CpuDecision] = []

    while True:
        current = ensure_utc(clock())
        decision = evaluate_cpu_policy(
            policy,
            last_success=last_success,
            cpu_percent=float(sample(policy.sample_seconds)),
            now=current,
        )
        decisions.append(decision)
        if on_decision is not None:
            on_decision(decision)

        if decision.should_run:
            finished = ensure_utc(clock())
            return WaitResult(
                decision=decision,
                attempts=len(decisions),
                waited=max(timedelta(0), finished - started),
                deadline_reached=False,
            )

        current = ensure_utc(clock())
        if current >= deadline:
            return WaitResult(
                decision=decision,
                attempts=len(decisions),
                waited=max(timedelta(0), current - started),
                deadline_reached=True,
            )

        remaining = max(0.0, (deadline - current).total_seconds())
        sleep_seconds = min(policy.retry_interval.total_seconds(), remaining)
        if sleep_seconds <= 0:
            return WaitResult(
                decision=decision,
                attempts=len(decisions),
                waited=max(timedelta(0), current - started),
                deadline_reached=True,
            )
        sleeper(sleep_seconds)
