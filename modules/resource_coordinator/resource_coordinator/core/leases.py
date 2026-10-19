"""
Resource lease tracking and arbitration with reference-counted concurrency and idle cooldowns.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Optional

from .events import EventDispatcher

logger = logging.getLogger(__name__)


class LeaseType(str, Enum):
    SHARED = "shared"
    EXCLUSIVE = "exclusive"


@dataclass(frozen=True)
class Lease:
    """An active claim on a named resource."""

    resource: str
    lease_type: LeaseType
    holder_id: str
    lease_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    acquired_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resource": self.resource,
            "lease_type": self.lease_type.value,
            "holder_id": self.holder_id,
            "lease_id": self.lease_id,
            "acquired_at": self.acquired_at,
            "metadata": dict(self.metadata),
        }


class LeaseManager:
    """
    Manages named resource leases.

    Supports:
    - Multiple concurrent shared leases on a resource.
    - Exclusive leases (e.g. model loading) that block shared leases.
    - Reference-counted active and pending tracking.
    - Automatic idle cooldown when the final active lease on a resource is released.
    - Immediate cancellation of idle cooldown if a new lease request arrives.
    """

    def __init__(
        self,
        default_cooldown_seconds: float = 60.0,
        event_dispatcher: Optional[EventDispatcher] = None,
    ) -> None:
        self.default_cooldown_seconds = default_cooldown_seconds
        self.dispatcher = event_dispatcher or EventDispatcher()
        self._active: Dict[str, List[Lease]] = {}
        self._pending: Dict[str, int] = {}
        self._cooldown_tasks: Dict[str, asyncio.Task] = {}
        self._cooldown_ends: Dict[str, float] = {}
        self._resource_cooldowns: Dict[str, float] = {}
        self._lock = asyncio.Lock()
        self._condition = asyncio.Condition(self._lock)

    def set_resource_cooldown(self, resource: str, cooldown_seconds: float) -> None:
        """Set a specific cooldown duration for a named resource."""
        self._resource_cooldowns[resource] = max(0.0, cooldown_seconds)

    def get_resource_cooldown(self, resource: str) -> float:
        """Get the configured cooldown duration for a resource."""
        return self._resource_cooldowns.get(resource, self.default_cooldown_seconds)

    def active_count(self, resource: str) -> int:
        """Return the number of active leases on a resource."""
        return len(self._active.get(resource, []))

    def pending_count(self, resource: str) -> int:
        """Return the number of pending lease requests for a resource."""
        return self._pending.get(resource, 0)

    def active_leases_for(self, resource: str) -> List[Lease]:
        """Return a copy of the active leases for a resource."""
        return list(self._active.get(resource, []))

    def is_cooling_down(self, resource: str) -> bool:
        """Check whether a resource is in post-activity cooldown."""
        task = self._cooldown_tasks.get(resource)
        return task is not None and not task.done()

    def cooldown_remaining(self, resource: str) -> float:
        """Return remaining seconds in cooldown, or 0.0 if not cooling down."""
        if not self.is_cooling_down(resource):
            return 0.0
        return max(0.0, self._cooldown_ends.get(resource, 0.0) - time.time())

    def _cancel_cooldown_locked(self, resource: str) -> None:
        """Cancel an in-progress cooldown timer (must hold self._lock)."""
        task = self._cooldown_tasks.pop(resource, None)
        self._cooldown_ends.pop(resource, None)
        if task is not None and not task.done():
            task.cancel()
            logger.debug("Cancelled cooldown timer for resource '%s'", resource)

    def _start_cooldown_locked(self, resource: str) -> None:
        """Start the idle cooldown timer if active_count is 0 (must hold self._lock)."""
        self._cancel_cooldown_locked(resource)
        cooldown = self.get_resource_cooldown(resource)
        if cooldown <= 0.0:
            # Emit idle immediately if cooldown is 0
            asyncio.create_task(
                self.dispatcher.emit(
                    "resource.idle",
                    {"resource": resource, "cooldown_seconds": 0.0},
                )
            )
            return

        end_time = time.time() + cooldown
        self._cooldown_ends[resource] = end_time

        async def _cooldown_worker() -> None:
            try:
                await asyncio.sleep(cooldown)
                async with self._lock:
                    self._cooldown_tasks.pop(resource, None)
                    self._cooldown_ends.pop(resource, None)
                await self.dispatcher.emit(
                    "resource.idle",
                    {"resource": resource, "cooldown_seconds": cooldown},
                )
                logger.info("Resource '%s' cooldown expired; resource is now idle", resource)
            except asyncio.CancelledError:
                pass

        task = asyncio.create_task(_cooldown_worker())
        self._cooldown_tasks[resource] = task
        asyncio.create_task(
            self.dispatcher.emit(
                "resource.cooldown_started",
                {"resource": resource, "cooldown_seconds": cooldown},
            )
        )

    def _can_grant_locked(self, resource: str, lease_type: LeaseType) -> bool:
        active = self._active.get(resource, [])
        if not active:
            return True
        if lease_type == LeaseType.SHARED:
            return all(item.lease_type == LeaseType.SHARED for item in active)
        return False

    @asynccontextmanager
    async def acquire(
        self,
        resource: str,
        lease_type: LeaseType = LeaseType.SHARED,
        holder_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> AsyncIterator[Lease]:
        """
        Acquire a resource lease as an asynchronous context manager.

        If another operation holds an incompatible lease, waits until granted or timed out.
        Cancels any ongoing cooldown on this resource immediately.
        """
        holder = holder_id or uuid.uuid4().hex
        deadline = time.time() + timeout if timeout is not None else None

        async with self._condition:
            # Arrival cancels any pending idle restart
            self._cancel_cooldown_locked(resource)
            self._pending[resource] = self._pending.get(resource, 0) + 1

            await self.dispatcher.emit(
                "resource.lease_requested",
                {"resource": resource, "lease_type": lease_type.value, "holder_id": holder},
            )

            try:
                while not self._can_grant_locked(resource, lease_type):
                    if deadline is not None:
                        remaining = deadline - time.time()
                        if remaining <= 0:
                            raise TimeoutError(f"Timed out acquiring lease on resource '{resource}'")
                        try:
                            await asyncio.wait_for(self._condition.wait(), timeout=remaining)
                        except asyncio.TimeoutError:
                            raise TimeoutError(f"Timed out acquiring lease on resource '{resource}'")
                    else:
                        await self._condition.wait()

                # Grant the lease
                lease = Lease(
                    resource=resource,
                    lease_type=lease_type,
                    holder_id=holder,
                    metadata=metadata or {},
                )
                self._active.setdefault(resource, []).append(lease)
            finally:
                current_pending = self._pending.get(resource, 1) - 1
                if current_pending <= 0:
                    self._pending.pop(resource, None)
                else:
                    self._pending[resource] = current_pending

        await self.dispatcher.emit("resource.acquired", {"lease": lease.to_dict()})

        try:
            yield lease
        finally:
            await self.release(lease)

    async def release(self, lease: Lease) -> None:
        """Release an active lease."""
        resource = lease.resource
        async with self._condition:
            active_list = self._active.get(resource, [])
            if lease in active_list:
                active_list.remove(lease)
                if not active_list:
                    self._active.pop(resource, None)

            await self.dispatcher.emit("resource.released", {"lease": lease.to_dict()})

            if not self._active.get(resource):
                # No active leases remaining
                if not self._pending.get(resource):
                    self._start_cooldown_locked(resource)

            self._condition.notify_all()
