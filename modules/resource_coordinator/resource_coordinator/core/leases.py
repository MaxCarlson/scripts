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
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional

import anyio

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


@dataclass(frozen=True)
class RestartInhibition:
    """A protective hold inhibiting resource restart due to uncertain or interrupted execution."""

    resource: str
    reason: str
    holder_id: str
    inhibited_at: float = field(default_factory=time.time)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resource": self.resource,
            "reason": self.reason,
            "holder_id": self.holder_id,
            "inhibited_at": self.inhibited_at,
            "details": dict(self.details),
        }


class LeaseReservation:
    """
    Two-stage lease reservation.

    Entering reservation immediately increments pending_count and cancels any active cooldown.
    Calling activate() promotes the reservation to an active Lease once conditions are satisfied.
    Closing the reservation cleans up the active lease (if activated) or pending count (if not).
    """

    def __init__(
        self,
        manager: LeaseManager,
        resource: str,
        lease_type: LeaseType,
        holder_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.manager = manager
        self.resource = resource
        self.lease_type = lease_type
        self.holder_id = holder_id
        self.metadata = metadata or {}
        self._lease: Optional[Lease] = None
        self._is_active = False
        self._is_closed = False
        self._activation_lock = asyncio.Lock()

    @property
    def is_active(self) -> bool:
        return self._is_active

    @property
    def lease(self) -> Optional[Lease]:
        return self._lease

    async def activate(self, timeout: Optional[float] = None) -> Lease:
        """Promote reservation from pending to active lease."""
        async with self._activation_lock:
            if self._is_closed:
                raise RuntimeError("Cannot activate a closed reservation")
            if self._is_active and self._lease is not None:
                return self._lease
            lease = await self.manager._promote_reservation(self, timeout=timeout)
            if self._is_closed:
                raise RuntimeError("Reservation closed during activation")
            return lease

    async def close(self) -> None:
        """Close reservation, releasing active lease or unwinding pending claim."""
        if self._is_closed:
            return
        with anyio.CancelScope(shield=True):
            await self.manager._close_reservation(self)

    async def __aenter__(self) -> LeaseReservation:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()


class LeaseManager:
    """
    Manages named resource leases.

    Supports:
    - Multiple concurrent shared leases on a resource.
    - Exclusive leases (e.g. model loading) that block shared leases.
    - Reference-counted active and pending tracking.
    - Two-stage atomic reservation (pending claim + cooldown cancellation before blocking hooks).
    - Protective restart inhibition for indeterminate/uncertain upstream termination.
    - Automatic idle cooldown when the final active lease on a resource is released.
    - Immediate cancellation of idle cooldown if a new lease request arrives.
    """

    def __init__(
        self,
        default_cooldown_seconds: float = 60.0,
        event_dispatcher: Optional[EventDispatcher] = None,
        *,
        monotonic_clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.default_cooldown_seconds = default_cooldown_seconds
        self.dispatcher = event_dispatcher or EventDispatcher()
        self._active: Dict[str, List[Lease]] = {}
        self._pending: Dict[str, int] = {}
        self._pending_reservations: Dict[str, List[LeaseReservation]] = {}
        self._cooldown_tasks: Dict[str, asyncio.Task] = {}
        self._cooldown_ends: Dict[str, float] = {}
        self._resource_cooldowns: Dict[str, float] = {}
        self._inhibitions: Dict[str, RestartInhibition] = {}
        self._lock = asyncio.Lock()
        self._condition = asyncio.Condition(self._lock)
        self.restarts_blocked = False
        self._monotonic_clock = monotonic_clock
        self._sleep = sleep

    def set_resource_cooldown(self, resource: str, cooldown_seconds: float) -> None:
        """Set a specific cooldown duration for a named resource."""
        self._resource_cooldowns[resource] = max(0.0, cooldown_seconds)

    def get_resource_cooldown(self, resource: str) -> float:
        """Get the configured cooldown duration for a resource."""
        return self._resource_cooldowns.get(resource, self.default_cooldown_seconds)

    def block_restarts(self, reason: str, holder_id: str = "service") -> list[asyncio.Task]:
        """Latch lifecycle restart denial and holds before any callback can suspend.

        Event-loop confined, like the count accessors. This gate cannot be cleared
        by operator inhibition recovery; a terminal service needs reconciliation.
        """
        self.restarts_blocked = True
        tasks = list(self._cooldown_tasks.values())
        resources = self.tracked_resources() | {"gpu.inference", "gpu.model_loading"}
        for resource in resources:
            self._cancel_cooldown_locked(resource)
            if resource not in self._inhibitions:
                self._inhibitions[resource] = RestartInhibition(resource, reason, holder_id)
        logger.warning("Lifecycle restart gate latched: %s", reason)
        return tasks

    def tracked_resources(self) -> set[str]:
        """Snapshot of resource names with claims, cooldowns or unresolved holds."""
        return set(self._active) | set(self._pending) | set(self._inhibitions) | set(self._cooldown_tasks)

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
        return max(0.0, self._cooldown_ends.get(resource, 0.0) - self._monotonic_clock())

    def is_restart_inhibited(self, resource: str) -> bool:
        """Check if restart is inhibited for a resource."""
        return resource in self._inhibitions

    def get_inhibition(self, resource: str) -> Optional[RestartInhibition]:
        """Get active restart inhibition details if present."""
        return self._inhibitions.get(resource)

    async def run_if_idle(
        self,
        resource: str,
        callback: Callable[[], Awaitable[None]],
        additionally_guarded_resources: Optional[set[str]] = None,
    ) -> bool:
        """Run one idle action while reservations cannot cross the final safety check."""
        async with self._condition:
            resources = (
                self.tracked_resources()
                | {"gpu.inference", "gpu.model_loading", resource}
                | (additionally_guarded_resources or set())
            )
            if self.restarts_blocked or any(
                self.active_count(name)
                or self.pending_count(name)
                or self.is_restart_inhibited(name)
                or (name != resource and self.is_cooling_down(name))
                for name in resources
            ):
                return False
            await callback()
            return True

    async def inhibit_restart(
        self,
        resource: str,
        reason: str,
        holder_id: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> RestartInhibition:
        """
        Impose a protective restart inhibition on a resource.

        Cancels any active cooldown and prevents mining/process restart until cleared.
        """
        inhibition = RestartInhibition(
            resource=resource,
            reason=reason,
            holder_id=holder_id,
            details=details or {},
        )
        async with self._lock:
            self._cancel_cooldown_locked(resource)
            # Later activity cannot resolve an earlier request's unknown execution state.
            if resource in self._inhibitions:
                previous = self._inhibitions[resource]
                previous.details.setdefault("additional_uncertain_holders", []).append(inhibition.to_dict())
                return previous
            self._inhibitions[resource] = inhibition

        logger.warning(
            "Restart inhibited for resource '%s' (holder=%s): %s",
            resource,
            holder_id,
            reason,
        )
        await self.dispatcher.emit("resource.restart_inhibited", {"inhibition": inhibition.to_dict()})
        return inhibition

    async def clear_inhibition(
        self, resource: str, origin: str = "recovery", *, require_all_idle: bool = False
    ) -> Optional[RestartInhibition]:
        """
        Clear a protective restart inhibition and start idle cooldown if eligible.
        """
        removed: Optional[RestartInhibition] = None
        async with self._condition:
            if (
                (require_all_idle and (any(self._active.values()) or any(self._pending.values())))
                or self.active_count(resource)
                or self.pending_count(resource)
            ):
                raise RuntimeError("Cannot recover a resource with active or pending requests")
            removed = self._inhibitions.pop(resource, None)
            if removed is not None:
                logger.info(
                    "Restart inhibition cleared for resource '%s' via %s (previous reason: %s)",
                    resource,
                    origin,
                    removed.reason,
                )
                if not self._active.get(resource) and not self._pending.get(resource):
                    self._start_cooldown_locked(resource)
                self._condition.notify_all()

        if removed is not None:
            await self.dispatcher.emit(
                "resource.restart_inhibition_cleared",
                {"resource": resource, "origin": origin, "previous": removed.to_dict()},
            )
        return removed

    def _cancel_cooldown_locked(self, resource: str) -> None:
        """Cancel an in-progress cooldown timer (must hold self._lock)."""
        task = self._cooldown_tasks.pop(resource, None)
        self._cooldown_ends.pop(resource, None)
        if task is not None and not task.done():
            task.cancel()
            logger.debug("Cancelled cooldown timer for resource '%s'", resource)

    def _start_cooldown_locked(self, resource: str) -> None:
        """Start the idle cooldown timer if eligible (must hold self._lock)."""
        self._cancel_cooldown_locked(resource)

        if self.restarts_blocked:
            return
        if self.is_restart_inhibited(resource):
            inhibition = self._inhibitions[resource]
            logger.warning(
                "Resource '%s' restart is inhibited (%s); idle cooldown will not start",
                resource,
                inhibition.reason,
            )
            return

        cooldown = self.get_resource_cooldown(resource)
        end_time = self._monotonic_clock() + cooldown
        self._cooldown_ends[resource] = end_time

        async def _cooldown_worker() -> None:
            try:
                await self._sleep(cooldown)
                async with self._lock:
                    if self.active_count(resource) or self.pending_count(resource):
                        return
                    if self.is_restart_inhibited(resource):
                        logger.warning(
                            "Resource '%s' cooldown expired but restart is inhibited; skipping idle emit",
                            resource,
                        )
                        return
                await self.dispatcher.emit(
                    "resource.idle",
                    {"resource": resource, "cooldown_seconds": cooldown},
                )
                logger.info("Resource '%s' cooldown expired; resource is now idle", resource)
            except asyncio.CancelledError:
                pass
            finally:
                if self._cooldown_tasks.get(resource) is asyncio.current_task():
                    self._cooldown_tasks.pop(resource, None)
                    self._cooldown_ends.pop(resource, None)

        task = asyncio.create_task(_cooldown_worker())
        self._cooldown_tasks[resource] = task
        asyncio.create_task(
            self.dispatcher.emit(
                "resource.cooldown_started",
                {"resource": resource, "cooldown_seconds": cooldown},
            )
        )

    def _remove_pending_reservation_locked(self, reservation: LeaseReservation) -> None:
        pending = self._pending_reservations.get(reservation.resource, [])
        if reservation in pending:
            pending.remove(reservation)
        if not pending:
            self._pending_reservations.pop(reservation.resource, None)

    def _can_grant_locked(
        self, resource: str, lease_type: LeaseType, reservation: LeaseReservation
    ) -> bool:
        active = self._active.get(resource, [])
        pending = self._pending_reservations.get(resource, [])
        try:
            earlier = pending[: pending.index(reservation)]
        except ValueError:
            earlier = []
        if any(item.lease_type == LeaseType.EXCLUSIVE for item in earlier):
            return False
        if lease_type == LeaseType.EXCLUSIVE and earlier:
            return False
        if not active:
            return True
        if lease_type == LeaseType.SHARED:
            return all(item.lease_type == LeaseType.SHARED for item in active)
        return False

    @asynccontextmanager
    async def reserve(
        self,
        resource: str,
        lease_type: LeaseType = LeaseType.SHARED,
        holder_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[LeaseReservation]:
        """
        Reserve a pending resource claim.

        Immediately cancels any active cooldown and records pending_count > 0.
        Call reservation.activate() once pre-conditions are met.
        """
        holder = holder_id or uuid.uuid4().hex
        reservation = LeaseReservation(
            manager=self,
            resource=resource,
            lease_type=lease_type,
            holder_id=holder,
            metadata=metadata,
        )
        async with self._lock:
            self._cancel_cooldown_locked(resource)
            self._pending[resource] = self._pending.get(resource, 0) + 1
            self._pending_reservations.setdefault(resource, []).append(reservation)
        try:
            await self.dispatcher.emit(
                "resource.lease_requested",
                {"resource": resource, "lease_type": lease_type.value, "holder_id": holder},
            )
            yield reservation
        finally:
            await reservation.close()

    async def _promote_reservation(
        self,
        reservation: LeaseReservation,
        timeout: Optional[float] = None,
    ) -> Lease:
        resource = reservation.resource
        lease_type = reservation.lease_type
        holder = reservation.holder_id
        deadline = time.monotonic() + timeout if timeout is not None else None

        async with self._condition:
            while not self._can_grant_locked(resource, lease_type, reservation):
                if reservation._is_closed:
                    raise RuntimeError("Reservation closed while waiting")
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError(f"Timed out acquiring lease on resource '{resource}'")
                    try:
                        await asyncio.wait_for(self._condition.wait(), timeout=remaining)
                    except asyncio.TimeoutError:
                        raise TimeoutError(f"Timed out acquiring lease on resource '{resource}'")
                else:
                    await self._condition.wait()

            if reservation._is_closed:
                raise RuntimeError("Cannot promote a closed reservation")
            # Decrement pending and grant active lease
            current_pending = self._pending.get(resource, 1) - 1
            if current_pending <= 0:
                self._pending.pop(resource, None)
            else:
                self._pending[resource] = current_pending
            self._remove_pending_reservation_locked(reservation)

            lease = Lease(
                resource=resource,
                lease_type=lease_type,
                holder_id=holder,
                metadata=reservation.metadata,
            )
            self._active.setdefault(resource, []).append(lease)
            # Publish ownership before callbacks can suspend or cancel promotion.
            reservation._lease = lease
            reservation._is_active = True

        await self.dispatcher.emit("resource.acquired", {"lease": lease.to_dict()})
        return lease

    async def _close_reservation(self, reservation: LeaseReservation) -> None:
        async with self._condition:
            if reservation._is_closed:
                return
            reservation._is_closed = True
        if reservation.is_active and reservation.lease is not None:
            await self.release(reservation.lease)
        else:
            resource = reservation.resource
            async with self._condition:
                current_pending = self._pending.get(resource, 1) - 1
                if current_pending <= 0:
                    self._pending.pop(resource, None)
                else:
                    self._pending[resource] = current_pending
                self._remove_pending_reservation_locked(reservation)

                if not self._active.get(resource) and not self._pending.get(resource):
                    self._start_cooldown_locked(resource)
                self._condition.notify_all()

            await self.dispatcher.emit(
                "resource.reservation_cancelled",
                {
                    "resource": reservation.resource,
                    "holder_id": reservation.holder_id,
                    "lease_type": reservation.lease_type.value,
                },
            )

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
        Cancels any ongoing cooldown on this resource immediately upon entry.
        """
        async with self.reserve(
            resource=resource,
            lease_type=lease_type,
            holder_id=holder_id,
            metadata=metadata,
        ) as reservation:
            lease = await reservation.activate(timeout=timeout)
            yield lease

    async def release(self, lease: Lease) -> None:
        """Release an active lease."""
        resource = lease.resource
        async with self._condition:
            active_list = self._active.get(resource, [])
            if lease not in active_list:
                return
            active_list.remove(lease)
            if not active_list:
                self._active.pop(resource, None)

            if not self._active.get(resource):
                # No active leases remaining
                if not self._pending.get(resource):
                    self._start_cooldown_locked(resource)

            self._condition.notify_all()

        await self.dispatcher.emit("resource.released", {"lease": lease.to_dict()})
