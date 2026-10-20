"""
Condition evaluation predicates supporting logical composition, metric thresholds, and hold durations.
"""

from __future__ import annotations

import inspect
import time
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Dict, Optional, Sequence

from .leases import LeaseManager
from .processes import ProcessState, ProcessSupervisor


class Condition(ABC):
    """Abstract condition predicate."""

    @abstractmethod
    async def evaluate(self, context: Optional[Dict[str, Any]] = None) -> bool:
        """Evaluate the condition. Returns True if condition matches."""
        ...


class AllCondition(Condition):
    """Logical AND across a sequence of conditions."""

    def __init__(self, conditions: Sequence[Condition]) -> None:
        self.conditions = list(conditions)

    async def evaluate(self, context: Optional[Dict[str, Any]] = None) -> bool:
        for cond in self.conditions:
            if not await cond.evaluate(context):
                return False
        return True


class AnyCondition(Condition):
    """Logical OR across a sequence of conditions."""

    def __init__(self, conditions: Sequence[Condition]) -> None:
        self.conditions = list(conditions)

    async def evaluate(self, context: Optional[Dict[str, Any]] = None) -> bool:
        if not self.conditions:
            return True
        for cond in self.conditions:
            if await cond.evaluate(context):
                return True
        return False


class NotCondition(Condition):
    """Logical NOT inverting a condition."""

    def __init__(self, condition: Condition) -> None:
        self.condition = condition

    async def evaluate(self, context: Optional[Dict[str, Any]] = None) -> bool:
        return not await self.condition.evaluate(context)


class CallableCondition(Condition):
    """Condition wrapping a user-defined synchronous or asynchronous predicate."""

    def __init__(self, func: Callable[[Optional[Dict[str, Any]]], Any]) -> None:
        self.func = func

    async def evaluate(self, context: Optional[Dict[str, Any]] = None) -> bool:
        res = self.func(context)
        if inspect.isawaitable(res):
            res = await res
        return bool(res)


class ProcessRunningCondition(Condition):
    """Condition evaluating whether a monitored process is currently running."""

    def __init__(
        self,
        supervisor: ProcessSupervisor,
        include_external: bool = True,
    ) -> None:
        self.supervisor = supervisor
        self.include_external = include_external

    async def evaluate(self, context: Optional[Dict[str, Any]] = None) -> bool:
        info = await self.supervisor.status()
        if info.state == ProcessState.RUNNING:
            return True
        if self.include_external and info.state == ProcessState.EXTERNAL_RUNNING:
            return True
        return False


class LeaseHeldCondition(Condition):
    """Condition evaluating whether a resource lease is currently held or cooling down."""

    def __init__(
        self,
        lease_mgr: LeaseManager,
        resource: str,
        check_cooldown: bool = False,
    ) -> None:
        self.lease_mgr = lease_mgr
        self.resource = resource
        self.check_cooldown = check_cooldown

    async def evaluate(self, context: Optional[Dict[str, Any]] = None) -> bool:
        if self.lease_mgr.active_count(self.resource) > 0:
            return True
        if self.check_cooldown and self.lease_mgr.is_cooling_down(self.resource):
            return True
        return False


class MetricThresholdCondition(Condition):
    """
    Evaluates numeric metrics against a threshold with optional hold duration (hysteresis).
    """

    def __init__(
        self,
        metric_getter: Callable[[], float | Awaitable[float]],
        operator: str,
        threshold: float,
        hold_seconds: float = 0.0,
    ) -> None:
        if operator not in {"eq", "ne", "gt", "gte", "lt", "lte"}:
            raise ValueError(f"Unsupported operator: {operator}")
        self.metric_getter = metric_getter
        self.operator = operator
        self.threshold = threshold
        self.hold_seconds = max(0.0, hold_seconds)
        self._true_since: Optional[float] = None

    def _compare(self, actual: float) -> bool:
        ops = {
            "eq": actual == self.threshold,
            "ne": actual != self.threshold,
            "gt": actual > self.threshold,
            "gte": actual >= self.threshold,
            "lt": actual < self.threshold,
            "lte": actual <= self.threshold,
        }
        return ops[self.operator]

    async def evaluate(self, context: Optional[Dict[str, Any]] = None) -> bool:
        val = self.metric_getter()
        if inspect.isawaitable(val):
            val = await val
        actual = float(val)

        is_match = self._compare(actual)
        now = time.time()

        if not is_match:
            self._true_since = None
            return False

        if self._true_since is None:
            self._true_since = now

        if self.hold_seconds > 0 and (now - self._true_since) < self.hold_seconds:
            return False

        return True
