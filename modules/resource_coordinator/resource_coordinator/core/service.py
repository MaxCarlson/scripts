"""
Coordinator service lifecycle manager, readiness state machine, and preflight verification.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from resource_coordinator.core.durable_state import StateCodec, reconcile_startup_state
from resource_coordinator.core.lock import SingleInstanceLock
from resource_coordinator.core.processes import ProcessState, ProcessLifecycleOwner, WindowsProcessBackend

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
        self.first_boot = bool(kwargs.get("first_boot", False))
        self.supervision_poll_interval = float(kwargs.get("supervision_poll_interval", 1.0))
        self._supervision_task: Optional[asyncio.Task] = None
        self._state = ServiceState.CREATED
        self._failure_reason: Optional[str] = None
        self._startup_task: Optional[asyncio.Task] = None
        self._stop_lock = asyncio.Lock()
        self._aborted = False
        self._instance_lock: Optional[SingleInstanceLock] = kwargs.get("instance_lock")
        self._owns_instance_lock = self._instance_lock is None
        if self._instance_lock is None:
            lock_path = kwargs.get("lock_path")
            if not lock_path and getattr(self.system.config.service, "state_persistence_path", ""):
                lock_path = Path(self.system.config.service.state_persistence_path).with_suffix(".lock")
            if lock_path:
                self._instance_lock = SingleInstanceLock(lock_path)
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
            if not supervisor.is_manual_override:
                supervisor.set_manual_override(True, persist=False)
        tasks = self.system.lease_mgr.block_restarts(reason)
        startup = self._startup_task
        if startup is not None and startup is not asyncio.current_task() and not startup.done():
            startup.cancel()
        if self._supervision_task is not None and not self._supervision_task.done():
            self._supervision_task.cancel()
            tasks.append(self._supervision_task)
        return tasks

    def preflight_check(self) -> Tuple[bool, List[str]]:
        """Configuration checks only; does not certify upstream idle/watchdog absence."""
        messages: List[str] = []
        for policy in self.system.config.policies:
            if policy.target_process and policy.target_process not in self.system.supervisors:
                messages.append(f"ERROR: Policy '{policy.name}' targets unknown process '{policy.target_process}'.")
            if policy.restart_process and not policy.only_if_stopped_by_coordinator:
                messages.append(f"ERROR: Policy '{policy.name}' restart requires a coordinator-owned stop.")
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
        if self._instance_lock is not None:
            if not self._instance_lock.is_acquired and not self._instance_lock.acquire():
                self._state = ServiceState.FAILED
                self._failure_reason = (
                    f"Coordinator instance lock at '{self._instance_lock.lock_path}' is already held"
                )
                self._freeze(self._failure_reason)
                logger.error(self._failure_reason)
                return False
        self._startup_task = asyncio.current_task()
        self._state = ServiceState.INITIALIZING
        try:
            self._state = ServiceState.PREFLIGHT
            passed, messages = self.preflight_check()
            if not passed:
                raise RuntimeError("Preflight checks failed: " + "; ".join(messages))

            # Reconcile durable state if configured
            if getattr(self.system.config.service, "state_persistence_path", ""):
                state_path = Path(self.system.config.service.state_persistence_path)
                if not state_path.exists():
                    if self.first_boot:
                        StateCodec.initialize(state_path)
                        logger.info("First-boot initialization created clean state journal at '%s'", state_path)
                    else:
                        raise RuntimeError(
                            f"Missing required durable state journal at '{state_path}'. "
                            "Refusing normal startup to prevent unrecorded crash recovery; "
                            "run with explicit first-boot initialization if this is a fresh deployment."
                        )
                try:
                    loaded_state = StateCodec.load(state_path)
                except Exception as exc:
                    raise RuntimeError(f"Corrupted or invalid durable state journal at {state_path}: {exc}")
                await reconcile_startup_state(loaded_state, self.system.lease_mgr, self.system.supervisors)
                for supervisor in self.system.supervisors.values():
                    if not supervisor.state_persistence_path:
                        supervisor.state_persistence_path = str(state_path)
            for supervisor in self.system.supervisors.values():
                info = await supervisor.status()
                if info.state not in {ProcessState.STOPPED, ProcessState.RUNNING}:
                    raise RuntimeError("Process identity/ownership requires reconciliation")
                if info.state == ProcessState.RUNNING and info.lifecycle_owner != ProcessLifecycleOwner.COORDINATOR:
                    raise RuntimeError("Running process is not coordinator-owned")
            if self.start_miner_on_ready:
                assert self.system.miner_adapter is not None
                if self.system.lease_mgr.is_restart_inhibited("gpu.inference"):
                    logger.warning(
                        "Miner launch on ready skipped: restart on gpu.inference is currently inhibited (hold=%s)",
                        self.system.lease_mgr.get_inhibition("gpu.inference"),
                    )
                elif self.system.miner_adapter.is_manual_override:
                    logger.warning("Miner launch on ready skipped: manual override is active")
                else:
                    # Initial explicit launch is distinct from resuming a process we paused.
                    success = await self.system.miner_adapter.resume(only_if_stopped_by_coordinator=False)
                    info = await self.system.miner_adapter.status()
                    if not success or info.state != ProcessState.RUNNING or not info.is_coordinator_owned:
                        raise RuntimeError("Requested miner launch was not verified coordinator-owned RUNNING")
            if self.start_process_on_ready:
                supervisor = self.system.supervisors[self.start_process_on_ready]
                if self.system.lease_mgr.is_restart_inhibited("gpu.inference"):
                    logger.warning(
                        "Process '%s' launch on ready skipped: restart on gpu.inference is inhibited",
                        self.start_process_on_ready,
                    )
                elif supervisor.is_manual_override:
                    logger.warning(
                        "Process '%s' launch on ready skipped: manual override is active",
                        self.start_process_on_ready,
                    )
                else:
                    success = await supervisor.start(only_if_stopped_by_coordinator=False)
                    info = await supervisor.status()
                    if not success or info.state != ProcessState.RUNNING or not info.is_coordinator_owned:
                        raise RuntimeError("Requested process launch was not verified coordinator-owned RUNNING")
            if self._state != ServiceState.PREFLIGHT or self.system.lease_mgr.restarts_blocked:
                if self._instance_lock is not None and self._owns_instance_lock:
                    self._instance_lock.release()
                return False
            self._state = ServiceState.READY
            self._supervision_task = asyncio.create_task(self._run_supervision_loop())
            return True
        except asyncio.CancelledError:
            self._state = ServiceState.RECONCILIATION_REQUIRED
            self._failure_reason = "Startup cancelled; external execution state requires reconciliation"
            self._freeze(self._failure_reason)
            if self._instance_lock is not None and self._owns_instance_lock:
                self._instance_lock.release()
            raise
        except Exception as exc:
            self._state = ServiceState.FAILED
            self._failure_reason = str(exc)
            self._freeze(self._failure_reason)
            if self._instance_lock is not None and self._owns_instance_lock:
                self._instance_lock.release()
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
                # A timed-out drain is not proof that an inference has ended. Keep the
                # upstream client and instance lock alive so an uncertain request is
                # never interrupted and a second coordinator cannot take ownership.
                if not uncertain and self.stop_miner_on_shutdown and self.system.miner_adapter:
                    info = await self.system.miner_adapter.status()
                    if info.state != ProcessState.STOPPED:
                        if not info.is_coordinator_owned:
                            uncertain = True  # Never mutate an external process during shutdown.
                        else:
                            stopped = await asyncio.wait_for(
                                self.system.miner_adapter.pause(timeout=5.0, origin="shutdown"), timeout=7.0
                            )
                            uncertain = uncertain or not stopped
                            uncertain = (
                                uncertain or (await self.system.miner_adapter.status()).state != ProcessState.STOPPED
                            )
                if not uncertain and self.stop_process_on_shutdown:
                    supervisor = self.system.supervisors[self.stop_process_on_shutdown]
                    info = await supervisor.status()
                    if info.state != ProcessState.STOPPED:
                        if not info.is_coordinator_owned:
                            uncertain = True
                        else:
                            stop_timeout = self.system.config.processes[
                                self.stop_process_on_shutdown
                            ].stop_timeout_seconds
                            stopped = await asyncio.wait_for(
                                supervisor.stop(timeout=stop_timeout, origin="shutdown"), timeout=stop_timeout + 2.0
                            )
                            uncertain = uncertain or not stopped
                            uncertain = uncertain or (await supervisor.status()).state != ProcessState.STOPPED
                if not uncertain:
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
        finally:
            if self._state == ServiceState.STOPPED and self._instance_lock is not None and self._owns_instance_lock:
                self._instance_lock.release()

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

    async def manual_miner_control(
        self,
        action: str,
        *,
        duration_seconds: Optional[float] = None,
        timeout_seconds: float = 10.0,
    ) -> Dict[str, Any]:
        """Perform a miner mutation only while all GPU claims and cooldowns are clear."""
        adapter = self.system.miner_adapter
        state_path = getattr(self.system.config.service, "state_persistence_path", "")
        if adapter is None:
            return {"status": "unavailable", "reason": "No miner is configured"}
        if action not in {"start", "stop", "resume", "pause", "status"}:
            return {"status": "invalid", "reason": "Unsupported miner action"}
        if action == "status":
            info = await adapter.status()
            return {
                "status": "ok", "process": info.to_dict(),
                "manual_override": adapter.is_manual_override,
                "manual_override_until": adapter.supervisor.manual_override_until,
            }
        if not state_path:
            return {"status": "unavailable", "reason": "Durable state persistence is required for manual controls"}
        if action == "pause" and (
            duration_seconds is None or not math.isfinite(duration_seconds) or duration_seconds <= 0
        ):
            return {"status": "invalid", "reason": "Pause requires a finite positive duration"}

        supervisor = adapter.supervisor
        async def mutate() -> None:
            if not self.is_ready:
                raise RuntimeError("Coordinator stopped admitting work")
            if action in {"pause", "stop"}:
                deadline = time.time() + duration_seconds if action == "pause" else None
                supervisor.set_manual_override(True, until=deadline)
                stopped = await adapter.pause(timeout=timeout_seconds, origin="manual")
                verified = await adapter.status()
                if not stopped or verified.state != ProcessState.STOPPED:
                    supervisor.set_manual_override(False)
                    raise RuntimeError("Miner stop was not verified; manual hold cleared")
                result.update(status="paused" if action == "pause" else "stopped", manual_override_until=deadline)
                return
            if action in {"start", "resume"}:
                supervisor.set_manual_override(False)
                started = await adapter.resume(
                    origin="manual", only_if_stopped_by_coordinator=(action == "resume")
                )
                verified = await adapter.status()
                if not started or verified.state != ProcessState.RUNNING or not verified.is_coordinator_owned:
                    raise RuntimeError("Coordinator-owned miner start was not verified")
                result.update(status="running", manual_override_until=None)

        result: Dict[str, Any] = {}
        try:
            admitted = await self.system.lease_mgr.run_if_idle(
                "gpu.inference", mutate,
                additionally_guarded_resources={"gpu.model_loading"},
                check_self_cooldown=True,
            )
        except Exception as exc:
            return {"status": "failed", "reason": str(exc)}
        if not admitted:
            return {"status": "blocked", "reason": "GPU claims, cooldown, inhibition, or safety gate is active"}
        return result

    async def _run_supervision_loop(self) -> None:
        """
        Continuous supervision loop: inspects managed processes configured for restart.
        If a process unexpectedly stopped while safe idle, initiates backoff recovery.
        """
        while self.is_ready:
            try:
                await asyncio.sleep(self.supervision_poll_interval)
                if not self.is_ready:
                    break

                adapter = self.system.miner_adapter
                if adapter is not None:
                    supervisor = adapter.supervisor
                    deadline = supervisor.manual_override_until
                    if supervisor.is_manual_override and deadline is not None and deadline <= time.time():
                        async def resume_expired_hold() -> None:
                            supervisor.set_manual_override(False)
                            if supervisor.was_stopped_by_coordinator:
                                started = await adapter.resume(origin="manual_deadline")
                                info = await adapter.status()
                                if not started or info.state != ProcessState.RUNNING or not info.is_coordinator_owned:
                                    supervisor.set_manual_override(True, until=deadline)
                                    logger.error("Expired manual miner hold could not safely resume")
                        await self.system.lease_mgr.run_if_idle(
                            "gpu.inference", resume_expired_hold,
                            additionally_guarded_resources={"gpu.model_loading"},
                            check_self_cooldown=True,
                        )

                for policy in self.system.config.policies:
                    if not policy.restart_process:
                        continue
                    supervisor = self.system.supervisors.get(policy.target_process)
                    if supervisor is None:
                        continue

                    if (
                        supervisor._has_started
                        and not supervisor.is_manual_override
                        and not supervisor.was_stopped_by_coordinator
                    ):
                        info = await supervisor.status()
                        if info.state == ProcessState.STOPPED:
                            res = policy.resource
                            if (
                                not self.system.lease_mgr.active_count(res)
                                and not self.system.lease_mgr.pending_count(res)
                                and not self.system.lease_mgr.is_restart_inhibited(res)
                                and not self.system.lease_mgr.is_cooling_down(res)
                                and not self.system.lease_mgr.restarts_blocked
                            ):
                                await supervisor.handle_unexpected_exit_backoff(
                                    lease_manager=self.system.lease_mgr,
                                    resource=res,
                                    base_backoff_seconds=min(self.supervision_poll_interval, 1.0),
                                )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Error in process supervision loop: %s", exc)
