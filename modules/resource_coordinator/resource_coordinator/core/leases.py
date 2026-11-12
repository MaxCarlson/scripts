"""
Resource lease tracking and arbitration with reference-counted concurrency and idle cooldowns.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional

import anyio

from .events import EventDispatcher

logger = logging.getLogger(__name__)


class MaintenanceAdmissionBlocked(RuntimeError):
    """Raised when a protected GPU operation arrives behind a maintenance fence."""


def _is_gpu_resource(resource: str) -> bool:
    """Treat named GPU resources as one physical conflict domain."""
    return resource.startswith("gpu.")


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
        self._gpu_maintenance_owner: Optional[str] = None
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
        resources = set(self._active) | set(self._pending) | set(self._inhibitions) | set(self._cooldown_tasks)
        if self._gpu_maintenance_owner is not None:
            resources.add("gpu.maintenance")
        return resources

    @property
    def gpu_maintenance_owner(self) -> Optional[str]:
        """Current in-process maintenance fence owner, if admission is closed."""
        return self._gpu_maintenance_owner

    async def begin_gpu_maintenance(
        self,
        holder_id: str,
        *,
        precondition: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """Atomically close GPU admission when no protected claim or safety hold exists.

        The optional precondition executes synchronously under the arbitration lock and
        must not perform process control or await. It is intended for small durable-state
        checks such as ensuring gaming mode is inactive.
        """
        if not holder_id:
            raise ValueError("Maintenance holder identity is required")
        async with self._condition:
            if self._gpu_maintenance_owner is not None or self.restarts_blocked:
                return False
            resources = self.tracked_resources() | {"gpu.inference", "gpu.model_loading"}
            gpu_resources = {resource for resource in resources if _is_gpu_resource(resource)}
            if any(
                self.active_count(resource)
                or self.pending_count(resource)
                or self.is_restart_inhibited(resource)
                or self.is_cooling_down(resource)
                for resource in gpu_resources
            ):
                return False
            if precondition is not None and not precondition():
                return False
            self._gpu_maintenance_owner = holder_id
            for resource in gpu_resources:
                self._cancel_cooldown_locked(resource)
            self._condition.notify_all()
            return True

    async def end_gpu_maintenance(self, holder_id: str, *, cooldown_resource: Optional[str] = None) -> None:
        """Open GPU admission only for the current fence owner, then start cooldown atomically."""
        async with self._condition:
            if self._gpu_maintenance_owner != holder_id:
                raise RuntimeError("Maintenance fence owner does not match")
            if cooldown_resource is not None:
                if self.active_count(cooldown_resource) or self.pending_count(cooldown_resource):
                    raise RuntimeError("Cannot finish GPU maintenance while protected claims remain")
            self._gpu_maintenance_owner = None
            if cooldown_resource is not None:
                self._start_cooldown_locked(cooldown_resource)
            self._condition.notify_all()

    async def restore_gpu_maintenance_fence(self, holder_id: str) -> None:
        """Restore a durable maintenance fence before service startup admits work."""
        if not holder_id:
            raise ValueError("Maintenance holder identity is required")
        async with self._condition:
            if self._gpu_maintenance_owner not in {None, holder_id}:
                raise RuntimeError("A different maintenance owner already holds the GPU fence")
            self._gpu_maintenance_owner = holder_id
            resources = self.tracked_resources() | {"gpu.inference", "gpu.model_loading"}
            for resource in resources:
                if _is_gpu_resource(resource):
                    self._cancel_cooldown_locked(resource)
            self._condition.notify_all()

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
        *,
        check_self_cooldown: bool = False,
    ) -> bool:
        """Run one idle action while reservations cannot cross the final safety check."""
        async with self._condition:
            if _is_gpu_resource(resource) and self._gpu_maintenance_owner is not None:
                return False
            resources = (
                self.tracked_resources()
                | {"gpu.inference", "gpu.model_loading", resource}
                | (additionally_guarded_resources or set())
            )
            if self.restarts_blocked or any(
                self.active_count(name)
                or self.pending_count(name)
                or self.is_restart_inhibited(name)
                or ((check_self_cooldown or name != resource) and self.is_cooling_down(name))
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
                if previous.holder_id == holder_id:
                    return previous
                additional = previous.details.setdefault("additional_uncertain_holders", [])
                if not any(item.get("holder_id") == holder_id for item in additional):
                    additional.append(inhibition.to_dict())
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
        self,
        resource: str,
        origin: str = "recovery",
        *,
        require_all_idle: bool = False,
        before_clear: Optional[Callable[[], None]] = None,
        start_cooldown: bool = True,
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
            if before_clear is not None:
                before_clear()
            removed = self._inhibitions.pop(resource, None)
            if removed is not None:
                logger.info(
                    "Restart inhibition cleared for resource '%s' via %s (previous reason: %s)",
                    resource,
                    origin,
                    removed.reason,
                )
                if start_cooldown and not self._active.get(resource) and not self._pending.get(resource):
                    self._start_cooldown_locked(resource)
                self._condition.notify_all()

        if removed is not None:
            await self.dispatcher.emit(
                "resource.restart_inhibition_cleared",
                {"resource": resource, "origin": origin, "previous": removed.to_dict()},
            )
        return removed

    async def clear_inhibition_holder(
        self,
        resource: str,
        holder_id: str,
        *,
        before_change: Optional[Callable[[], None]] = None,
        start_cooldown: bool = True,
    ) -> Optional[RestartInhibition]:
        """Remove one inhibition owner without discarding other uncertain holders."""
        changed: Optional[RestartInhibition] = None
        async with self._condition:
            current = self._inhibitions.get(resource)
            if current is None or self.active_count(resource) or self.pending_count(resource):
                return None
            details = dict(current.details)
            additional = list(details.get("additional_uncertain_holders", []))
            matched_extra = next((item for item in additional if item.get("holder_id") == holder_id), None)
            if current.holder_id != holder_id and matched_extra is None:
                return None
            if before_change is not None:
                before_change()
            changed = current
            if current.holder_id == holder_id:
                if additional:
                    promoted = dict(additional.pop(0))
                    promoted_details = dict(promoted.get("details", {}))
                    remaining = list(promoted_details.get("additional_uncertain_holders", [])) + additional
                    if remaining:
                        promoted_details["additional_uncertain_holders"] = remaining
                    else:
                        promoted_details.pop("additional_uncertain_holders", None)
                    self._inhibitions[resource] = RestartInhibition(
                        resource=resource,
                        reason=promoted["reason"],
                        holder_id=promoted["holder_id"],
                        inhibited_at=promoted.get("inhibited_at", time.time()),
                        details=promoted_details,
                    )
                else:
                    self._inhibitions.pop(resource, None)
            else:
                retained = [item for item in additional if item.get("holder_id") != holder_id]
                if retained:
                    details["additional_uncertain_holders"] = retained
                else:
                    details.pop("additional_uncertain_holders", None)
                self._inhibitions[resource] = RestartInhibition(
                    resource=resource,
                    reason=current.reason,
                    holder_id=current.holder_id,
                    inhibited_at=current.inhibited_at,
                    details=details,
                )
            if (
                start_cooldown
                and resource not in self._inhibitions
                and not self._active.get(resource)
                and not self._pending.get(resource)
            ):
                self._start_cooldown_locked(resource)
            self._condition.notify_all()
        await self.dispatcher.emit(
            "resource.restart_inhibition_cleared",
            {
                "resource": resource,
                "origin": "holder_reconciled",
                "previous": changed.to_dict(),
                "holder_id": holder_id,
                "another_hold_remains": resource in self._inhibitions,
            },
        )
        return changed

    def _cancel_cooldown_locked(self, resource: str) -> None:
        """Cancel an in-progress cooldown timer (must hold self._lock)."""
        task = self._cooldown_tasks.pop(resource, None)
        self._cooldown_ends.pop(resource, None)
        if task is not None and not task.done():
            task.cancel()
            logger.debug("Cancelled cooldown timer for resource '%s'", resource)

    def _start_cooldown_locked(self, resource: str, duration_seconds: Optional[float] = None) -> None:
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

        cooldown = self.get_resource_cooldown(resource) if duration_seconds is None else max(0.0, duration_seconds)
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

    async def restore_cooldown(self, resource: str, remaining_seconds: float) -> None:
        """Re-arm a persisted cooldown after restart using its remaining wall-clock duration."""
        if not math.isfinite(remaining_seconds) or remaining_seconds < 0:
            raise ValueError("Cooldown duration must be finite and non-negative")
        async with self._condition:
            if self.active_count(resource) or self.pending_count(resource):
                raise RuntimeError("Cannot restore cooldown while a resource has active claims")
            self._start_cooldown_locked(resource, remaining_seconds)
            self._condition.notify_all()

    def _remove_pending_reservation_locked(self, reservation: LeaseReservation) -> None:
        pending = self._pending_reservations.get(reservation.resource, [])
        if reservation in pending:
            pending.remove(reservation)
        if not pending:
            self._pending_reservations.pop(reservation.resource, None)

    def _can_grant_locked(self, resource: str, lease_type: LeaseType, reservation: LeaseReservation) -> bool:
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
            if _is_gpu_resource(resource) and self._gpu_maintenance_owner is not None:
                raise MaintenanceAdmissionBlocked("GPU admission is closed by an active maintenance session")
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
            if _is_gpu_resource(resource) and self._gpu_maintenance_owner is not None:
                raise MaintenanceAdmissionBlocked("GPU admission closed before lease activation")
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
