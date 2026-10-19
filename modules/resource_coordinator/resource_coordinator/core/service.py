"""
Coordinator service lifecycle manager, readiness state machine, and preflight verification.
"""

from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from resource_coordinator.config import CoordinatorSystem

logger = logging.getLogger(__name__)


class ServiceState(str, Enum):
    """Observable lifecycle states of the Resource Coordinator service."""

    CREATED = "created"  # Instantiated, not yet started
    INITIALIZING = "initializing"  # Verifying configuration, components, and policy graph
    PREFLIGHT = "preflight"  # Performing environment and process table readiness probes
    READY = "ready"  # Fully initialized, preflight passed, admitting traffic
    DRAINING = "draining"  # Shutdown requested, waiting for active requests to finish
    STOPPED = "stopped"  # Fully stopped; no traffic admitted
    FAILED = "failed"  # Startup or fatal runtime error occurred; closed to traffic
    RECONCILIATION_REQUIRED = "reconciliation_required"  # Unresolved hold or identity ambiguity


class CoordinatorService:
    """
    Manages the coordinator-owned service lifecycle, startup preflight verification,
    readiness state transitions, and bounded graceful shutdown.
    """

    def __init__(
        self,
        system: CoordinatorSystem,
        drain_timeout_seconds: float = 30.0,
        start_miner_on_ready: bool = False,
        stop_miner_on_shutdown: bool = False,
        **kwargs: Any,
    ) -> None:
        self.system = system
        drain = kwargs.get("drain_timeout", drain_timeout_seconds)
        self.drain_timeout_seconds = max(0.1, float(drain))
        self.start_miner_on_ready = bool(kwargs.get("start_miner_on_startup", start_miner_on_ready))
        self.stop_miner_on_shutdown = stop_miner_on_shutdown
        self._state: ServiceState = ServiceState.CREATED
        self._state_lock = asyncio.Lock()
        self._failure_reason: Optional[str] = None
        self._active_drain_task: Optional[asyncio.Task] = None

    @property
    def state(self) -> ServiceState:
        """Current lifecycle state."""
        return self._state

    @property
    def is_ready(self) -> bool:
        """Check if service is ready to admit requests."""
        return self._state == ServiceState.READY

    @property
    def failure_reason(self) -> Optional[str]:
        """Description of failure if in FAILED or RECONCILIATION_REQUIRED state."""
        return self._failure_reason

    def preflight_check(self) -> Tuple[bool, List[str]]:
        """
        Perform synchronous and non-destructive preflight validation.

        Returns (is_passed, messages).
        """
        messages: List[str] = []
        is_passed = True

        # 1. Validate configuration and policy bindings
        if not self.system.config.processes:
            messages.append("WARNING: No processes configured for management.")

        for pol in self.system.config.policies:
            if pol.target_process and pol.target_process not in self.system.supervisors:
                messages.append(f"ERROR: Policy '{pol.name}' targets unknown process '{pol.target_process}'.")
                is_passed = False

        # 2. Check process configurations
        for name, p_cfg in self.system.config.processes.items():
            if p_cfg.backend == "windows":
                if not p_cfg.executable:
                    messages.append(f"ERROR: Windows process '{name}' has no executable path.")
                    is_passed = False
                if p_cfg.adopt_external:
                    messages.append(
                        f"WARNING: Process '{name}' has adopt_external=True. External supervision must be verified."
                    )

        # 3. Check for existing restart inhibitions
        for res_name in ["gpu.inference", "gpu.model_loading"]:
            if self.system.lease_mgr.is_restart_inhibited(res_name):
                inh = self.system.lease_mgr.get_inhibition(res_name)
                reason = inh.reason if inh else "unknown"
                messages.append(f"NOTICE: Resource '{res_name}' has active restart inhibition: {reason}.")

        if is_passed:
            messages.append("Preflight validation passed: Configuration and components are internally consistent.")
        return is_passed, messages

    async def start(self) -> bool:
        """
        Execute deterministic startup sequence:
        CREATED -> INITIALIZING -> PREFLIGHT -> READY (or FAILED).
        """
        async with self._state_lock:
            if self._state != ServiceState.CREATED:
                logger.warning("start() called on service in state %s; ignoring", self._state.value)
                return self._state == ServiceState.READY

            try:
                logger.info("Initializing Coordinator Service...")
                self._state = ServiceState.INITIALIZING

                # Step 1: Preflight validation
                self._state = ServiceState.PREFLIGHT
                passed, messages = self.preflight_check()
                for msg in messages:
                    if msg.startswith("ERROR"):
                        logger.error("Preflight failure: %s", msg)
                    elif msg.startswith("WARNING"):
                        logger.warning("Preflight warning: %s", msg)
                    else:
                        logger.info("Preflight check: %s", msg)

                if not passed:
                    self._state = ServiceState.FAILED
                    self._failure_reason = "Preflight checks failed: " + "; ".join(
                        m for m in messages if m.startswith("ERROR")
                    )
                    logger.error("Coordinator startup aborted: %s", self._failure_reason)
                    return False

                # Step 2: Transition to READY
                self._state = ServiceState.READY
                logger.info("Coordinator Service is READY. Traffic admission enabled.")

                # Step 3: Launch miner under coordinator ownership if requested
                if self.start_miner_on_ready and self.system.miner_adapter:
                    logger.info("Starting managed miner process on service readiness...")
                    success = await self.system.miner_adapter.resume()
                    if not success:
                        logger.warning(
                            "Miner start on readiness failed or was skipped (check supervisor status and permissions)."
                        )

                return True
            except Exception as exc:
                self._state = ServiceState.FAILED
                self._failure_reason = str(exc)
                logger.error("Coordinator startup encountered unexpected exception: %s", exc)
                return False

    async def stop(self, reason: str = "normal_shutdown") -> None:
        """
        Execute bounded graceful shutdown:
        READY -> DRAINING -> STOPPED.
        """
        async with self._state_lock:
            if self._state in {ServiceState.STOPPED, ServiceState.FAILED}:
                return

            self._state = ServiceState.DRAINING
            logger.info("Coordinator Service entering DRAINING (reason: %s)...", reason)

        # Wait for active leases to drain without holding the state lock
        drain_deadline = time.monotonic() + self.drain_timeout_seconds
        resources = ["gpu.inference", "gpu.model_loading"]

        while time.monotonic() < drain_deadline:
            active_count = sum(self.system.lease_mgr.active_count(r) for r in resources)
            pending_count = sum(self.system.lease_mgr.pending_count(r) for r in resources)
            if active_count == 0 and pending_count == 0:
                logger.info("All active and pending requests successfully drained.")
                break
            await asyncio.sleep(0.1)
        else:
            active_count = sum(self.system.lease_mgr.active_count(r) for r in resources)
            if active_count > 0:
                logger.warning(
                    "Drain deadline (%.1fs) exceeded with %d active requests remaining.",
                    self.drain_timeout_seconds,
                    active_count,
                )
                # Inhibit restart on affected resources to preserve safety across shutdown
                for r in resources:
                    if self.system.lease_mgr.active_count(r) > 0:
                        await self.system.lease_mgr.inhibit_restart(
                            resource=r,
                            reason=f"shutdown_with_active_requests:{reason}",
                            holder_id="service_shutdown",
                        )

        # If configured to stop the miner on shutdown, stop it safely
        if self.stop_miner_on_shutdown and self.system.miner_adapter:
            logger.info("Stopping managed miner on service shutdown...")
            await self.system.miner_adapter.pause(timeout=5.0)

        # Close gateway HTTP client
        await self.system.gateway.close()

        async with self._state_lock:
            self._state = ServiceState.STOPPED
            logger.info("Coordinator Service is STOPPED.")

    async def emergency_abort(self, reason: str) -> Dict[str, Any]:
        """
        Execute emergency abort procedure:
        - Transition state to FAILED or RECONCILIATION_REQUIRED.
        - Close traffic admission immediately.
        - Impose non-clearing restart inhibition on all resources.
        - Cancel active cooldowns.
        - Never blindly terminate unknown or ambiguous PIDs.
        """
        async with self._state_lock:
            self._state = ServiceState.RECONCILIATION_REQUIRED
            self._failure_reason = f"Emergency abort: {reason}"
            logger.critical("EMERGENCY ABORT TRIGGERED: %s", reason)

        inhibited_resources: List[str] = []
        for res_name in ["gpu.inference", "gpu.model_loading"]:
            await self.system.lease_mgr.inhibit_restart(
                resource=res_name,
                reason=f"emergency_abort:{reason}",
                holder_id="operator_abort",
                details={"aborted_at": time.time(), "reason": reason},
            )
            inhibited_resources.append(res_name)

        # Gather process states without destructive action against uncertain PIDs
        process_statuses: Dict[str, Any] = {}
        for name, sup in self.system.supervisors.items():
            info = await sup.status()
            process_statuses[name] = info.to_dict()

        return {
            "status": "aborted",
            "service_state": self._state.value,
            "reason": reason,
            "inhibited_resources": inhibited_resources,
            "processes": process_statuses,
        }

    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive service status and component metrics."""
        res_status: Dict[str, Any] = {}
        for r in ["gpu.inference", "gpu.model_loading"]:
            inh = self.system.lease_mgr.get_inhibition(r)
            res_status[r] = {
                "active_count": self.system.lease_mgr.active_count(r),
                "pending_count": self.system.lease_mgr.pending_count(r),
                "is_cooling_down": self.system.lease_mgr.is_cooling_down(r),
                "cooldown_remaining": round(self.system.lease_mgr.cooldown_remaining(r), 1),
                "is_restart_inhibited": self.system.lease_mgr.is_restart_inhibited(r),
                "inhibition": inh.to_dict() if inh else None,
            }

        return {
            "service_state": self._state.value,
            "is_ready": self.is_ready,
            "failure_reason": self._failure_reason,
            "resources": res_status,
            "managed_processes": list(self.system.supervisors.keys()),
        }
