"""Invocation-local atomic trial budgeting, raw encode counting, and deadlines."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import math
import threading
import time
from typing import Callable

from .cancellation import check_cancelled


class BudgetExceeded(RuntimeError):
    """Raised when trial budget or monotonic deadline prevents admission or native entry."""


_active_trial_budget: ContextVar[TrialBudget | None] = ContextVar("active_trial_budget", default=None)
_active_recipe_id: ContextVar[str] = ContextVar("active_recipe_id", default="")
_active_permit: ContextVar[TrialPermit | None] = ContextVar("active_permit", default=None)
_active_attempt_callback: ContextVar[Callable[[], None] | None] = ContextVar("active_attempt_callback", default=None)


def get_active_budget() -> TrialBudget | None:
    return _active_trial_budget.get()


def get_active_recipe_id() -> str:
    return _active_recipe_id.get()


def get_active_permit() -> TrialPermit | None:
    return _active_permit.get()


@contextmanager
def active_trial_scope(
    budget: TrialBudget | None,
    recipe_id: str = "",
    permit: TrialPermit | None = None,
    on_attempt: Callable[[], None] | None = None,
):
    """Propagate the active invocation budget, recipe identity, and optional permit across context."""
    t1 = _active_trial_budget.set(budget)
    t2 = _active_recipe_id.set(recipe_id)
    t3 = _active_permit.set(permit)
    t4 = _active_attempt_callback.set(on_attempt)
    try:
        yield budget
    finally:
        _active_trial_budget.reset(t1)
        _active_recipe_id.reset(t2)
        _active_permit.reset(t3)
        _active_attempt_callback.reset(t4)


@contextmanager
def trial_entry(recipe_id: str = "", permit: TrialPermit | None = None):
    """Context manager for entering raw codec execution. Consumes a permit immediately before entry."""
    budget = get_active_budget()
    current_permit = permit or get_active_permit()
    if budget is None and current_permit is None:
        yield None
        return

    if current_permit is not None and not current_permit.consumed:
        active_permit = current_permit
        needs_release_on_error = False
    else:
        rid = recipe_id or get_active_recipe_id()
        if budget is None:
            yield None
            return
        active_permit = budget.admit(rid)
        needs_release_on_error = True

    try:
        active_permit.consume()
        yield active_permit
    finally:
        if needs_release_on_error and not active_permit.consumed:
            active_permit.release()


class TrialPermit:
    """A single reservation for an actual native codec attempt."""

    def __init__(self, budget: TrialBudget, recipe_id: str) -> None:
        self.budget = budget
        self.recipe_id = recipe_id
        self._consumed = False
        self._released = False
        self._lock = threading.Lock()

    @property
    def consumed(self) -> bool:
        with self._lock:
            return self._consumed

    @property
    def released(self) -> bool:
        with self._lock:
            return self._released

    def consume(self) -> None:
        check_cancelled()
        with self._lock:
            if self._consumed:
                return
            if self._released:
                raise RuntimeError("Cannot consume an already released trial permit")
            with self.budget._lock:
                if self.budget.deadline is not None and time.monotonic() >= self.budget.deadline:
                    self.budget._reserved -= 1
                    self._released = True
                    raise BudgetExceeded("Trial runtime deadline exceeded before native encode entry")
                self.budget._reserved -= 1
                self.budget._attempted += 1
                self._consumed = True
            cb = _active_attempt_callback.get()
            if cb is not None:
                cb()

    def release(self) -> None:
        with self._lock:
            if not self._consumed and not self._released:
                with self.budget._lock:
                    self.budget._reserved -= 1
                self._released = True

    def __enter__(self) -> "TrialPermit":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if not self.consumed:
            self.release()


class TrialBudget:
    """Thread-safe, invocation-local budget tracking actual codec attempts against a hard cap."""

    def __init__(
        self,
        max_trials: int,
        *,
        max_runtime_seconds: float | None = None,
        deadline: float | None = None,
    ) -> None:
        if max_trials < 1:
            raise ValueError("Trial budget max_trials must be a positive integer")
        if max_runtime_seconds is not None and (not math.isfinite(max_runtime_seconds) or max_runtime_seconds <= 0):
            raise ValueError("Trial budget max_runtime_seconds must be positive and finite")

        self.max_trials = max_trials
        self.max_runtime_seconds = max_runtime_seconds
        self.deadline = deadline or (
            time.monotonic() + max_runtime_seconds if max_runtime_seconds is not None else None
        )
        self._lock = threading.Lock()
        self._reserved = 0
        self._attempted = 0
        self._peak_reserved = 0

    @property
    def reserved(self) -> int:
        with self._lock:
            return self._reserved

    @property
    def attempted(self) -> int:
        with self._lock:
            return self._attempted

    @property
    def peak_reserved(self) -> int:
        with self._lock:
            return self._peak_reserved

    @property
    def remaining(self) -> int:
        with self._lock:
            return max(0, self.max_trials - (self._attempted + self._reserved))

    @property
    def is_exhausted(self) -> bool:
        with self._lock:
            if self._attempted + self._reserved >= self.max_trials:
                return True
            if self.deadline is not None and time.monotonic() >= self.deadline:
                return True
            return False

    def admit(self, recipe_id: str = "") -> TrialPermit:
        """Atomically reserve an attempt. Raises BudgetExceeded if budget or deadline is reached."""
        with self._lock:
            if self.deadline is not None and time.monotonic() >= self.deadline:
                raise BudgetExceeded("Trial runtime deadline exceeded; admission stopped")
            if self._attempted + self._reserved >= self.max_trials:
                raise BudgetExceeded(f"Trial budget limit of {self.max_trials} reached; admission stopped")
            self._reserved += 1
            if self._reserved > self._peak_reserved:
                self._peak_reserved = self._reserved
            return TrialPermit(self, recipe_id)
