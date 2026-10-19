"""
Event dispatch system with support for blocking lifecycle hooks and observational listeners.
"""

from __future__ import annotations

import asyncio
import fnmatch
import inspect
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


class VetoOperation(Exception):
    """Raised by a blocking lifecycle hook to cancel or reject an operation."""

    def __init__(self, message: str = "Operation was vetoed by a registered hook", reason: Any = None) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class Event:
    """An immutable event record published through the event system."""

    name: str
    data: Dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)
    origin: str = "core"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "data": dict(self.data),
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "origin": self.origin,
        }


EventListener = Callable[[Event], Union[None, Awaitable[None]]]


@dataclass
class _RegisteredListener:
    pattern: str
    callback: EventListener
    is_blocking: bool
    priority: int  # Higher priority executes first

    def matches(self, event_name: str) -> bool:
        if self.pattern == event_name or self.pattern == "*":
            return True
        return fnmatch.fnmatch(event_name, self.pattern)


class EventDispatcher:
    """
    Central event broker.

    Distinguishes:
    - Blocking lifecycle hooks: executed sequentially in priority order before an action proceeds.
      A hook may raise VetoOperation to prevent the action.
    - Observational listeners: executed asynchronously without blocking the caller, isolated
      from failures in individual listeners.
    """

    def __init__(self) -> None:
        self._listeners: List[_RegisteredListener] = []
        self._lock = asyncio.Lock()

    def on(
        self,
        pattern: str,
        callback: EventListener,
        is_blocking: bool = False,
        priority: int = 0,
    ) -> None:
        """Register a callback for an event pattern."""
        self._listeners.append(
            _RegisteredListener(
                pattern=pattern,
                callback=callback,
                is_blocking=is_blocking,
                priority=priority,
            )
        )
        # Sort so highest priority comes first
        self._listeners.sort(key=lambda item: item.priority, reverse=True)

    def has_blocking_listeners(self, event_name: str) -> bool:
        """Whether this lifecycle event has an explicit blocking policy/hook."""
        return any(item.is_blocking and item.matches(event_name) for item in self._listeners)

    def off(self, pattern: str, callback: EventListener) -> bool:
        """Unregister a callback. Returns True if removed."""
        initial_len = len(self._listeners)
        self._listeners = [
            item for item in self._listeners if not (item.pattern == pattern and item.callback == callback)
        ]
        return len(self._listeners) < initial_len

    async def emit_blocking(
        self,
        event_name: str,
        data: Optional[Dict[str, Any]] = None,
        origin: str = "core",
        timeout: Optional[float] = None,
    ) -> Event:
        """
        Execute blocking lifecycle hooks matching the event name.

        Hooks run sequentially in priority order. If any hook raises VetoOperation,
        it immediately bubbles up. If timeout is given and exceeded, raises TimeoutError.
        """
        event = Event(name=event_name, data=data or {}, origin=origin)
        matching = [item for item in self._listeners if item.is_blocking and item.matches(event_name)]

        async def _run_all() -> None:
            for item in matching:
                result = item.callback(event)
                if inspect.isawaitable(result):
                    await result

        if timeout is not None:
            await asyncio.wait_for(_run_all(), timeout=timeout)
        else:
            await _run_all()

        # After blocking hooks pass, notify non-blocking observational listeners
        observational = [item for item in self._listeners if not item.is_blocking and item.matches(event_name)]
        if observational:

            async def _safe_call(cb: EventListener) -> None:
                try:
                    res = cb(event)
                    if inspect.isawaitable(res):
                        await res
                except Exception as exc:
                    logger.warning("Observational listener %r failed on event %r: %s", cb, event_name, exc)

            tasks = [asyncio.create_task(_safe_call(item.callback)) for item in observational]
            await asyncio.gather(*tasks, return_exceptions=True)

        return event

    async def emit(
        self,
        event_name: str,
        data: Optional[Dict[str, Any]] = None,
        origin: str = "core",
    ) -> Event:
        """
        Dispatch non-blocking observational listeners.

        Listeners execute concurrently in background tasks or in the current loop.
        Exceptions are caught and logged so one failing listener does not affect others.
        """
        event = Event(name=event_name, data=data or {}, origin=origin)
        matching = [item for item in self._listeners if not item.is_blocking and item.matches(event_name)]

        if not matching:
            return event

        async def _safe_call(cb: EventListener) -> None:
            try:
                res = cb(event)
                if inspect.isawaitable(res):
                    await res
            except Exception as exc:
                logger.warning("Observational listener %r failed on event %r: %s", cb, event_name, exc)

        tasks = [asyncio.create_task(_safe_call(item.callback)) for item in matching]
        # Allow caller to proceed without waiting if desired, but we also yield briefly
        await asyncio.gather(*tasks, return_exceptions=True)
        return event
