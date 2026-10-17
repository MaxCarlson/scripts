"""Tests for raw encode trial budgeting, atomicity, deadlines, and permits."""

from __future__ import annotations

import threading
import time
import pytest

from compresser.trial_budget import (
    BudgetExceeded,
    TrialBudget,
    TrialPermit,
    active_trial_scope,
    get_active_budget,
    trial_entry,
)


def test_trial_budget_validation():
    with pytest.raises(ValueError, match="positive"):
        TrialBudget(0)
    with pytest.raises(ValueError, match="positive"):
        TrialBudget(-5)
    with pytest.raises(ValueError, match="positive"):
        TrialBudget(5, max_runtime_seconds=0)
    with pytest.raises(ValueError, match="positive"):
        TrialBudget(5, max_runtime_seconds=-1.0)


def test_trial_budget_admit_and_consume():
    budget = TrialBudget(3)
    assert budget.max_trials == 3
    assert budget.attempted == 0
    assert budget.reserved == 0
    assert budget.peak_reserved == 0

    permit = budget.admit("recipe-1")
    assert isinstance(permit, TrialPermit)
    assert budget.reserved == 1
    assert budget.attempted == 0
    assert budget.peak_reserved == 1

    permit.consume()
    assert budget.reserved == 0
    assert budget.attempted == 1
    assert budget.peak_reserved == 1

    # Idempotent consume
    permit.consume()
    assert budget.reserved == 0
    assert budget.attempted == 1


def test_trial_budget_release_unused_reservation():
    budget = TrialBudget(3)
    permit = budget.admit("recipe-1")
    assert budget.reserved == 1
    assert budget.attempted == 0

    permit.release()
    assert budget.reserved == 0
    assert budget.attempted == 0

    # Cannot consume after release
    with pytest.raises(RuntimeError, match="released"):
        permit.consume()


def test_trial_budget_context_manager_releases_on_unconsumed_exit():
    budget = TrialBudget(3)
    with budget.admit("recipe-1"):
        assert budget.reserved == 1
        # exit without consume

    assert budget.reserved == 0
    assert budget.attempted == 0


def test_trial_budget_cap_enforcement():
    budget = TrialBudget(2)

    p1 = budget.admit("r1")
    p2 = budget.admit("r2")
    assert budget.reserved == 2

    # Attempting to admit a 3rd reservation exceeds cap
    with pytest.raises(BudgetExceeded, match="limit of 2"):
        budget.admit("r3")

    # Release p2
    p2.release()
    assert budget.reserved == 1

    # Now admission succeeds
    p3 = budget.admit("r3")
    assert budget.reserved == 2

    # Consume both
    p1.consume()
    p3.consume()
    assert budget.attempted == 2
    assert budget.reserved == 0

    # Now cap is reached on attempted
    with pytest.raises(BudgetExceeded, match="limit of 2"):
        budget.admit("r4")


def test_trial_budget_consume_stays_charged_on_failure():
    budget = TrialBudget(2)
    permit = budget.admit("r1")
    permit.consume()
    assert budget.attempted == 1

    try:
        raise OSError("Native encoder crashed")
    except OSError:
        # Encoder failed, permit cleanup runs
        permit.release()

    # Attempted stays charged
    assert budget.attempted == 1
    assert budget.reserved == 0


def test_trial_budget_monotonic_deadline_prevents_admission():
    # Deadline already in past
    budget = TrialBudget(5, deadline=time.monotonic() - 1.0)
    with pytest.raises(BudgetExceeded, match="deadline exceeded"):
        budget.admit("r1")


def test_trial_budget_deadline_before_native_entry():
    budget = TrialBudget(5, max_runtime_seconds=0.05)
    permit = budget.admit("r1")
    assert budget.reserved == 1

    time.sleep(0.08)
    with pytest.raises(BudgetExceeded, match="deadline exceeded"):
        permit.consume()

    # The reservation was cleaned up
    assert budget.reserved == 0
    assert budget.attempted == 0


def test_trial_budget_concurrency():
    cap = 3
    budget = TrialBudget(cap)
    successful_encodes = 0
    denials = 0
    lock = threading.Lock()

    def worker():
        nonlocal successful_encodes, denials
        try:
            permit = budget.admit("recipe-thread")
            time.sleep(0.005)
            permit.consume()
            time.sleep(0.01)
            with lock:
                successful_encodes += 1
        except BudgetExceeded:
            with lock:
                denials += 1

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert successful_encodes == cap
    assert denials == 12 - cap
    assert budget.attempted == cap
    assert budget.reserved == 0
    assert budget.peak_reserved <= cap


def test_trial_entry_context_manager():
    budget = TrialBudget(2)

    # In active scope, trial_entry consumes from budget
    with active_trial_scope(budget, "r1"):
        assert get_active_budget() is budget
        with trial_entry("r1") as permit:
            assert permit is not None
            assert budget.attempted == 1

        with trial_entry("r2") as permit:
            assert permit is not None
            assert budget.attempted == 2

        with pytest.raises(BudgetExceeded):
            with trial_entry("r3"):
                pass

    # Outside active scope, trial_entry is a no-op
    assert get_active_budget() is None
    with trial_entry("r_outside") as p:
        assert p is None
