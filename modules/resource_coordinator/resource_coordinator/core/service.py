"""
Coordinator service lifecycle manager, readiness state machine, and preflight verification.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from enum import Enum

from resource_coordinator.core.processes import ProcessState, ProcessLifecycleOwner, WindowsProcessBackend
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
    """Event-loop confined service lifecycle; terminal transitions latch restart denial."""

    def __init__(
        self,
        system: CoordinatorSystem,
        drain_timeout_seconds: float = 30.0,
        start_miner_on_ready: bool = False,
        stop_miner_on_shutdown: bool = False,
        start_process_on_ready: Optional[str] = None,
        stop_process_on_shutdown: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        self.system = system
        self.drain_timeout_seconds = float(kwargs.get("drain_timeout", drain_timeout_seconds))
        if not math.isfinite(self.drain_timeout_seconds) or self.drain_timeout_seconds <= 0:
            raise ValueError("Drain timeout must be finite and positive")
        self.start_miner_on_ready = bool(kwargs.get("start_miner_on_startup", start_miner_on_ready))
        self.stop_miner_on_shutdown = stop_miner_on_shutdown
        self.start_process_on_ready = start_process_on_ready
        self.stop_process_on_shutdown = stop_process_on_shutdown
        self._state = ServiceState.CREATED
        self._failure_reason: Optional[str] = None
        self._startup_task: Optional[asyncio.Task] = None
        self._stop_lock = asyncio.Lock()
        self._aborted = False
        self.system.gateway.set_service(self)

    def has_model_load_policy(self) -> bool:
        """Whether a configured blocking policy stops the process under inference arbitration."""
        load_policies = [
            policy
            for policy in self.system.config.policies
            if (
                policy.trigger_event == "lmstudio.model_load_requested"
                and policy.target_process in self.system.supervisors
                and policy.stop_process
                and policy.restart_process
                and policy.resource == "gpu.inference"
                and policy.lease_type == "exclusive"
            )
        ]
        return any(
            any(
                inference.trigger_event == "lmstudio.inference_requested"
                and inference.target_process == load.target_process
                and inference.stop_process
                and inference.restart_process
                and inference.resource == "gpu.inference"
                and inference.cooldown_seconds == load.cooldown_seconds
                for inference in self.system.config.policies
            )
            for load in load_policies
        )

    @property
    def state(self) -> ServiceState:
        return self._state

    @property
    def is_ready(self) -> bool:
        return self._state == ServiceState.READY and not self.system.lease_mgr.restarts_blocked

    @property
    def failure_reason(self) -> Optional[str]:
        return self._failure_reason

    def _freeze(self, reason: str) -> list[asyncio.Task]:
        # No await before all restart protections are latched. Do not acquire a
        # supervisor mutex here: startup/stop may already be waiting inside one.
        for supervisor in self.system.supervisors.values():
            supervisor.set_manual_override(True)
        tasks = self.system.lease_mgr.block_restarts(reason)
        startup = self._startup_task
        if startup is not None and startup is not asyncio.current_task() and not startup.done():
            startup.cancel()
        return tasks

    def preflight_check(self) -> Tuple[bool, List[str]]:
        """Configuration checks only; does not certify upstream idle/watchdog absence."""
        messages: List[str] = []
        for policy in self.system.config.policies:
            if policy.target_process and policy.target_process not in self.system.supervisors:
                messages.append(f"ERROR: Policy '{policy.name}' targets unknown process '{policy.target_process}'.")
        for name, cfg in self.system.config.processes.items():
            if not any(
                p.target_process == name
                and p.trigger_event == "lmstudio.inference_requested"
                and p.stop_process
                and p.resource == "gpu.inference"
                for p in self.system.config.policies
            ):
                messages.append(f"ERROR: Process '{name}' has no required inference stop policy.")
            backend = self.system.supervisors.get(name)
            if backend and isinstance(backend.backend, WindowsProcessBackend):
                from pathlib import Path

                if not Path(cfg.executable).is_file():
                    messages.append(f"ERROR: Windows executable for '{name}' is missing.")
                if cfg.new_console and not cfg.allow_force_termination:
                    messages.append(f"ERROR: '{name}' has no supported shared-console stop mode.")
        if self.start_miner_on_ready and self.system.miner_adapter is None:
            messages.append("ERROR: Requested miner startup has no miner adapter.")
        if self.start_process_on_ready and self.start_process_on_ready not in self.system.supervisors:
            messages.append(
                f"ERROR: Requested process startup targets unknown process '{self.start_process_on_ready}'."
            )
        if self.stop_process_on_shutdown and self.stop_process_on_shutdown not in self.system.supervisors:
            messages.append(
                f"ERROR: Requested shutdown stop targets unknown process '{self.stop_process_on_shutdown}'."
            )
        for resource in self.system.lease_mgr.tracked_resources():
            if self.system.lease_mgr.is_restart_inhibited(resource):
                hold = self.system.lease_mgr.get_inhibition(resource)
                messages.append(
                    f"ERROR: Unresolved restart inhibition on '{resource}': {hold.reason if hold else 'unknown'}."
                )
            if self.system.lease_mgr.active_count(resource) or self.system.lease_mgr.pending_count(resource):
                messages.append(f"ERROR: Startup resource '{resource}' is already claimed.")
        passed = not any(m.startswith("ERROR") for m in messages)
        if passed:
            messages.append(
                "Configuration preflight passed; upstream idle and watchdog absence require independent evidence."
            )
        return passed, messages

    async def start(self) -> bool:
        if self._state != ServiceState.CREATED:
            return self.is_ready
        self._startup_task = asyncio.current_task()
        self._state = ServiceState.INITIALIZING
        try:
            self._state = ServiceState.PREFLIGHT
            passed, messages = self.preflight_check()
            if not passed:
                raise RuntimeError("Preflight checks failed: " + "; ".join(messages))
            for supervisor in self.system.supervisors.values():
                info = await supervisor.status()
                if info.state not in {ProcessState.STOPPED, ProcessState.RUNNING}:
                    raise RuntimeError("Process identity/ownership requires reconciliation")
                if info.state == ProcessState.RUNNING and info.lifecycle_owner != ProcessLifecycleOwner.COORDINATOR:
                    raise RuntimeError("Running process is not coordinator-owned")
            if self.start_miner_on_ready:
                assert self.system.miner_adapter is not None
                # Initial explicit launch is distinct from resuming a process we paused.
                success = await self.system.miner_adapter.resume(only_if_stopped_by_coordinator=False)
                info = await self.system.miner_adapter.status()
                if not success or info.state != ProcessState.RUNNING or not info.is_coordinator_owned:
                    raise RuntimeError("Requested miner launch was not verified coordinator-owned RUNNING")
            if self.start_process_on_ready:
                supervisor = self.system.supervisors[self.start_process_on_ready]
                success = await supervisor.start(only_if_stopped_by_coordinator=False)
                info = await supervisor.status()
                if not success or info.state != ProcessState.RUNNING or not info.is_coordinator_owned:
                    raise RuntimeError("Requested process launch was not verified coordinator-owned RUNNING")
            if self._state != ServiceState.PREFLIGHT or self.system.lease_mgr.restarts_blocked:
                return False
            self._state = ServiceState.READY
            return True
        except asyncio.CancelledError:
            self._state = ServiceState.RECONCILIATION_REQUIRED
            self._failure_reason = "Startup cancelled; external execution state requires reconciliation"
            self._freeze(self._failure_reason)
            raise
        except Exception as exc:
            self._state = ServiceState.FAILED
            self._failure_reason = str(exc)
            self._freeze(self._failure_reason)
            logger.error("Startup failed closed: %s", exc)
            return False
        finally:
            self._startup_task = None

    async def verify_before_forward(self) -> None:
        """Last managed-process check; no policy result substitutes for actual absence."""
        from resource_coordinator.core.events import VetoOperation

        for supervisor in self.system.supervisors.values():
            if (await supervisor.status()).state != ProcessState.STOPPED:
                raise VetoOperation("Required managed-process stop is not verified")
        if not self.is_ready:
            raise VetoOperation("Service admission closed before forwarding")

    async def stop(self, reason: str = "normal_shutdown") -> None:
        if self._state == ServiceState.STOPPED:
            return
        if not self._aborted:
            self._state = ServiceState.DRAINING
        tasks = self._freeze(f"shutdown:{reason}")
        try:
            async with self._stop_lock:
                other_tasks = [t for t in tasks if t is not asyncio.current_task()]
                if other_tasks:
                    await asyncio.wait(other_tasks, timeout=0.2)
                deadline = time.monotonic() + self.drain_timeout_seconds

                def claimed() -> bool:
                    return any(
                        self.system.lease_mgr.active_count(r) or self.system.lease_mgr.pending_count(r)
                        for r in self.system.lease_mgr.tracked_resources()
                    )

                while claimed() and time.monotonic() < deadline:
                    await asyncio.sleep(min(0.05, max(0, deadline - time.monotonic())))
                uncertain = claimed()
                if self.stop_miner_on_shutdown and self.system.miner_adapter:
                    info = await self.system.miner_adapter.status()
                    if info.state != ProcessState.STOPPED:
                        if not info.is_coordinator_owned:
                            uncertain = True  # Never mutate an external process during shutdown.
                        else:
                            stopped = await asyncio.wait_for(self.system.miner_adapter.pause(timeout=5.0), timeout=7.0)
                            uncertain = uncertain or not stopped
                            uncertain = (
                                uncertain or (await self.system.miner_adapter.status()).state != ProcessState.STOPPED
                            )
                if self.stop_process_on_shutdown:
                    supervisor = self.system.supervisors[self.stop_process_on_shutdown]
                    info = await supervisor.status()
                    if info.state != ProcessState.STOPPED:
                        if not info.is_coordinator_owned:
                            uncertain = True
                        else:
                            stopped = await asyncio.wait_for(supervisor.stop(timeout=5.0), timeout=7.0)
                            uncertain = uncertain or not stopped
                            uncertain = uncertain or (await supervisor.status()).state != ProcessState.STOPPED
                await asyncio.wait_for(self.system.gateway.close(), timeout=2.0)
                self._state = (
                    ServiceState.RECONCILIATION_REQUIRED if uncertain or self._aborted else ServiceState.STOPPED
                )
                if uncertain:
                    self._failure_reason = "Shutdown left active/pending work or unverified process stop"
        except asyncio.CancelledError:
            self._state = ServiceState.RECONCILIATION_REQUIRED
            self._failure_reason = "Shutdown cancelled; protections remain latched"
            raise
        except Exception as exc:
            self._state = ServiceState.RECONCILIATION_REQUIRED
            self._failure_reason = f"Shutdown failed: {exc}"
            logger.error(self._failure_reason)

    async def emergency_abort(self, reason: str) -> Dict[str, Any]:
        self._aborted = True
        self._state = ServiceState.RECONCILIATION_REQUIRED
        self._failure_reason = f"Emergency abort: {reason}"
        self._freeze(self._failure_reason)
        # Abort is non-destructive and independent of slow process status callbacks.
        return {
            "status": "aborted",
            "service_state": self.state.value,
            "reason": reason,
            "inhibited_resources": sorted(self.system.lease_mgr.tracked_resources()),
            "processes": {name: "unverified; inspect independently" for name in self.system.supervisors},
        }

    def get_status(self) -> Dict[str, Any]:
        resources: Dict[str, Any] = {}
        for resource in self.system.lease_mgr.tracked_resources() | {"gpu.inference", "gpu.model_loading"}:
            inhibition = self.system.lease_mgr.get_inhibition(resource)
            resources[resource] = {
                "active_count": self.system.lease_mgr.active_count(resource),
                "pending_count": self.system.lease_mgr.pending_count(resource),
                "is_restart_inhibited": inhibition is not None,
                "inhibition": inhibition.to_dict() if inhibition else None,
            }
        return {
            "service_state": self.state.value,
            "is_ready": self.is_ready,
            "failure_reason": self.failure_reason,
            "resources": resources,
            "managed_processes": list(self.system.supervisors),
        }
