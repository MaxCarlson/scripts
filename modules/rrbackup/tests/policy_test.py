from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from rrbackup.policy import CpuPolicy, evaluate_cpu_policy, wait_for_cpu_window

UTC = timezone.utc
NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def test_policy_validation_rejects_invalid_thresholds():
    with pytest.raises(ValueError, match="between 0 and 100"):
        CpuPolicy(normal_threshold=-1).validate()
    with pytest.raises(ValueError, match="cannot be greater"):
        CpuPolicy(normal_threshold=90, overdue_threshold=80).validate()
    with pytest.raises(ValueError, match="sample_seconds"):
        CpuPolicy(sample_seconds=0).validate()


def test_recent_backup_uses_normal_threshold():
    decision = evaluate_cpu_policy(
        CpuPolicy(normal_threshold=25, overdue_threshold=85),
        last_success=NOW - timedelta(hours=4),
        cpu_percent=30,
        now=NOW,
    )

    assert not decision.should_run
    assert not decision.overdue
    assert decision.threshold == 25
    assert "normal threshold" in decision.reason


def test_overdue_backup_uses_overdue_threshold():
    decision = evaluate_cpu_policy(
        CpuPolicy(
            normal_threshold=25,
            overdue_threshold=85,
            overdue_after=timedelta(days=3),
        ),
        last_success=NOW - timedelta(days=4),
        cpu_percent=70,
        now=NOW,
    )

    assert decision.should_run
    assert decision.overdue
    assert decision.threshold == 85
    assert decision.age == timedelta(days=4)


def test_missing_success_is_always_overdue():
    decision = evaluate_cpu_policy(
        CpuPolicy(normal_threshold=25, overdue_threshold=85),
        last_success=None,
        cpu_percent=86,
        now=NOW,
    )

    assert not decision.should_run
    assert decision.overdue
    assert decision.age is None
    assert "No prior successful backup" in decision.reason


def test_future_success_time_is_clamped_to_zero_age():
    decision = evaluate_cpu_policy(
        CpuPolicy(),
        last_success=NOW + timedelta(hours=1),
        cpu_percent=0,
        now=NOW,
    )

    assert decision.age == timedelta(0)
    assert not decision.overdue


def test_wait_returns_immediately_when_first_sample_is_acceptable():
    samples = []

    result = wait_for_cpu_window(
        CpuPolicy(max_wait=timedelta(minutes=30)),
        last_success=NOW,
        sampler=lambda seconds: samples.append(seconds) or 10,
        sleeper=lambda seconds: pytest.fail("sleeper should not be called"),
        clock=lambda: NOW,
    )

    assert result.decision.should_run
    assert result.attempts == 1
    assert result.waited == timedelta(0)
    assert samples == [5.0]


def test_wait_retries_without_holding_execution_state():
    current = [NOW]
    samples = iter([90.0, 80.0])
    decisions = []

    def clock():
        return current[0]

    def sleeper(seconds):
        current[0] += timedelta(seconds=seconds)

    result = wait_for_cpu_window(
        CpuPolicy(
            overdue_threshold=85,
            retry_interval=timedelta(minutes=5),
            max_wait=timedelta(minutes=30),
        ),
        last_success=None,
        sampler=lambda seconds: next(samples),
        sleeper=sleeper,
        clock=clock,
        on_decision=decisions.append,
    )

    assert result.decision.should_run
    assert result.attempts == 2
    assert result.waited == timedelta(minutes=5)
    assert [decision.cpu_percent for decision in decisions] == [90.0, 80.0]


def test_wait_reports_deadline_after_final_rejected_sample():
    current = [NOW]

    def clock():
        return current[0]

    def sleeper(seconds):
        current[0] += timedelta(seconds=seconds)

    result = wait_for_cpu_window(
        CpuPolicy(
            retry_interval=timedelta(minutes=5),
            max_wait=timedelta(minutes=5),
        ),
        last_success=NOW,
        sampler=lambda seconds: 100,
        sleeper=sleeper,
        clock=clock,
    )

    assert not result.decision.should_run
    assert result.deadline_reached
    assert result.attempts == 2
    assert result.waited == timedelta(minutes=5)
