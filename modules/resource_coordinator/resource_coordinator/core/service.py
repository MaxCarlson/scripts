"""
Coordinator service lifecycle manager, readiness state machine, and preflight verification.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
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


def _gpu_idle_sampling_allowed(condition: Dict[str, Any], gaming_mode: Dict[str, Any], *,
                               manual_override: bool) -> bool:
    """Only a pending one-shot idle pause may resume mining outside gaming/recovery."""
    return bool(condition) and manual_override and gaming_mode.get("state", "inactive") == "inactive"


def _manual_action_clears_gpu_idle_condition(action: str, *, gpu_idle_pause: bool) -> bool:
    """A new explicit pause/stop supersedes an older automatic-resume condition."""
    return action in {"pause", "stop"} and not gpu_idle_pause


def _manual_miner_mutations_allowed(gaming_mode: Dict[str, Any]) -> bool:
    """Gaming owns all miner mutations until its restore/reconciliation completes."""
    return gaming_mode.get("state", "inactive") == "inactive"


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
        self._lmstudio_client_factory = kwargs.get("lmstudio_client_factory")
        self._gpu_monitor = kwargs.get("gpu_monitor")
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
                if loaded_state.gaming_mode.get("state") != "inactive" and self.system.miner_adapter is not None:
                    self.system.miner_adapter.supervisor.set_manual_override(True, persist=False)
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
        was_operational = self._state in {ServiceState.READY, ServiceState.DRAINING}
        manual_overrides = {
            name: (supervisor.is_manual_override, supervisor.manual_override_until)
            for name, supervisor in self.system.supervisors.items()
        }
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
                    state_path = getattr(self.system.config.service, "state_persistence_path", "")
                    if was_operational and state_path:
                        try:
                            for name, (was_manually_held, held_until) in manual_overrides.items():
                                supervisor = self.system.supervisors[name]
                                supervisor.set_manual_override(
                                    was_manually_held, persist=False, until=held_until
                                )
                                await self._persist_supervisor_state(supervisor)
                        except Exception as exc:
                            uncertain = True
                            self._failure_reason = f"Could not persist clean shutdown hold state: {exc}"
                            logger.error(self._failure_reason)
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

    async def _persist_supervisor_state(self, supervisor: Any, *, was_stopped_by_coordinator: Optional[bool] = None) -> None:
        """Strictly persist a process snapshot before or after a privileged manual transition."""
        path = getattr(self.system.config.service, "state_persistence_path", "")
        if not path:
            raise RuntimeError("Durable state persistence is required for process control")
        info = await supervisor.status()
        running = info.state in {ProcessState.RUNNING, ProcessState.EXTERNAL_RUNNING}
        StateCodec.record_process_state(
            path,
            supervisor.name,
            pid=info.pid if running else None,
            create_time=info.create_time if running else None,
            lifecycle_owner=info.lifecycle_owner.value,
            was_stopped_by_coordinator=(
                supervisor.was_stopped_by_coordinator
                if was_stopped_by_coordinator is None else was_stopped_by_coordinator
            ),
            is_manual_override=supervisor.is_manual_override,
            manual_override_until=supervisor.manual_override_until,
        )

    async def manual_miner_control(
        self,
        action: str,
        *,
        duration_seconds: Optional[float] = None,
        threshold_pct: Optional[float] = None,
        window_seconds: Optional[float] = None,
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
                "gpu_idle_condition": StateCodec.load(state_path).gpu_idle_condition if state_path else {},
            }
        if not state_path:
            return {"status": "unavailable", "reason": "Durable state persistence is required for manual controls"}
        gaming_mode = StateCodec.load(state_path).gaming_mode
        if not _manual_miner_mutations_allowed(gaming_mode):
            return {"status": "blocked", "reason": "Gaming mode or recovery hold owns miner controls; use gaming stop"}
        gpu_condition = threshold_pct is not None or window_seconds is not None
        if action == "pause" and gpu_condition and (
            threshold_pct is None or window_seconds is None or not math.isfinite(threshold_pct)
            or not 0 <= threshold_pct <= 100 or not math.isfinite(window_seconds) or window_seconds <= 0
        ):
            return {"status": "invalid", "reason": "GPU-idle pause requires threshold 0..100 and a positive window"}
        if action == "pause" and not gpu_condition and (
            duration_seconds is None or not math.isfinite(duration_seconds) or duration_seconds <= 0
        ):
            return {"status": "invalid", "reason": "Pause requires a finite positive duration or GPU-idle condition"}

        supervisor = adapter.supervisor
        async def mutate() -> None:
            if not self.is_ready:
                raise RuntimeError("Coordinator stopped admitting work")
            if action in {"pause", "stop"}:
                if gpu_condition:
                    info = await adapter.status()
                    if info.state != ProcessState.RUNNING or not info.is_coordinator_owned:
                        raise RuntimeError("GPU-idle pause requires a running coordinator-owned miner")
                elif _manual_action_clears_gpu_idle_condition(action, gpu_idle_pause=gpu_condition):
                    StateCodec.record_gpu_idle_condition(state_path)
                deadline = time.time() + duration_seconds if action == "pause" and not gpu_condition else None
                supervisor.set_manual_override(True, persist=False, until=deadline)
                await self._persist_supervisor_state(supervisor, was_stopped_by_coordinator=True)
                stopped = await adapter.pause(timeout=timeout_seconds, origin="manual")
                verified = await adapter.status()
                if not stopped or verified.state != ProcessState.STOPPED:
                    supervisor.set_manual_override(False, persist=False)
                    await self._persist_supervisor_state(supervisor)
                    if gpu_condition:
                        StateCodec.record_gpu_idle_condition(state_path)
                    raise RuntimeError("Miner stop was not verified; manual hold cleared")
                await self._persist_supervisor_state(supervisor, was_stopped_by_coordinator=True)
                if gpu_condition:
                    StateCodec.record_gpu_idle_condition(
                        state_path, threshold_pct=threshold_pct, window_seconds=window_seconds, samples=[]
                    )
                result.update(status="paused" if action == "pause" else "stopped", manual_override_until=deadline)
                if gpu_condition:
                    result["gpu_idle_condition"] = {"threshold_pct": threshold_pct, "window_seconds": window_seconds}
                return
            if action in {"start", "resume"}:
                previous_override = supervisor.is_manual_override
                previous_deadline = supervisor.manual_override_until
                supervisor.set_manual_override(False, persist=False)
                await self._persist_supervisor_state(supervisor)
                StateCodec.record_gpu_idle_condition(state_path)
                started = await adapter.resume(
                    origin="manual", only_if_stopped_by_coordinator=(action == "resume")
                )
                verified = await adapter.status()
                if not started or verified.state != ProcessState.RUNNING or not verified.is_coordinator_owned:
                    if previous_override:
                        supervisor.set_manual_override(True, persist=False, until=previous_deadline)
                        await self._persist_supervisor_state(supervisor)
                    raise RuntimeError("Coordinator-owned miner start was not verified")
                await self._persist_supervisor_state(supervisor)
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

    async def gaming_control(self, action: str) -> Dict[str, Any]:
        """Unload and later restore LM Studio models under the GPU arbitration gate."""
        if action == "status":
            path = getattr(self.system.config.service, "state_persistence_path", "")
            if not path:
                return {"status": "unavailable", "reason": "Durable state persistence is required"}
            state = StateCodec.load(path).gaming_mode
            miner = await self.system.miner_adapter.status() if self.system.miner_adapter else None
            return {**state, "miner_state": miner.state.value if miner else "unconfigured"}
        if action not in {"start", "stop"}:
            return {"status": "invalid", "reason": "Unsupported gaming action"}
        path = getattr(self.system.config.service, "state_persistence_path", "")
        if not path:
            return {"status": "unavailable", "reason": "Durable state persistence is required"}
        if not self.is_ready:
            return {"status": "blocked", "reason": "Coordinator is not ready"}
        current = StateCodec.load(path).gaming_mode
        if action == "start" and current.get("state") == "active":
            return {**current, "status": "active"}
        if action == "start" and current.get("state") != "inactive":
            return {**current, "status": "blocked", "reason": "Gaming transition requires operator reconciliation"}
        if action == "stop" and current.get("state") == "inactive":
            return {"state": "inactive", "status": "inactive"}

        async def transition() -> None:
            if not self.is_ready:
                raise RuntimeError("Coordinator stopped admitting work")
            import httpx
            from resource_coordinator.adapters.lmstudio.models import NativeModelController

            base_url = self.system.config.service.upstream_url.rstrip("/")
            if base_url.endswith("/v1"):
                base_url = base_url[:-3]
            headers = {}
            token = os.environ.get("LM_STUDIO_API_TOKEN") or os.environ.get("LM_API_TOKEN")
            if token:
                headers["Authorization"] = f"Bearer {token}"
            client_factory = self._lmstudio_client_factory or httpx.AsyncClient
            async with client_factory(base_url=base_url, headers=headers, timeout=120.0) as client:
                controller = NativeModelController(client)
                if action == "start":
                    miner_info = await self.system.miner_adapter.status() if self.system.miner_adapter else None
                    miner_supervisor = self.system.miner_adapter.supervisor if self.system.miner_adapter else None
                    miner_was_running = bool(
                        miner_info and miner_info.state == ProcessState.RUNNING
                        and miner_info.is_coordinator_owned
                    )
                    loaded = await controller.snapshot_loaded()
                    snapshot = [{"model": item["model"], "type": item["type"], "config": item["config"]}
                                for item in loaded]
                    StateCodec.record_gaming_mode(path, "stopping", models=snapshot,
                                                  miner_was_running=miner_was_running,
                                                  miner_override_before=(miner_supervisor.is_manual_override
                                                                         if miner_supervisor else False),
                                                  miner_override_until_before=(miner_supervisor.manual_override_until
                                                                               if miner_supervisor else None))
                    if self.system.miner_adapter is not None:
                        supervisor = self.system.miner_adapter.supervisor
                        supervisor.set_manual_override(True, persist=False)
                        await self._persist_supervisor_state(
                            supervisor, was_stopped_by_coordinator=miner_was_running
                        )
                        if miner_info and miner_info.state == ProcessState.RUNNING:
                            stopped = await self.system.miner_adapter.pause(timeout=10.0, origin="gaming")
                            verified = await self.system.miner_adapter.status()
                            if not stopped or verified.state != ProcessState.STOPPED:
                                raise RuntimeError("Miner stop was not verified; gaming mode remains held")
                            await self._persist_supervisor_state(supervisor, was_stopped_by_coordinator=True)
                    await controller.unload(loaded)
                    StateCodec.record_gaming_mode(path, "active")
                    result.update(status="active", state="active", unloaded_models=len(snapshot))
                else:
                    snapshot = current.get("models", [])
                    StateCodec.record_gaming_mode(path, "restoring")
                    await controller.restore(snapshot)
                    cooldown = max(
                        self.system.lease_mgr.get_resource_cooldown("gpu.inference"),
                        self.system.lease_mgr.get_resource_cooldown("gpu.model_loading"),
                    )
                    if cooldown > 0:
                        await asyncio.sleep(cooldown)
                    if current.get("miner_was_running") and self.system.miner_adapter is not None:
                        supervisor = self.system.miner_adapter.supervisor
                        supervisor.set_manual_override(False, persist=False)
                        await self._persist_supervisor_state(supervisor)
                        try:
                            started = await self.system.miner_adapter.resume(origin="gaming_restore")
                            verified = await self.system.miner_adapter.status()
                            if not started or verified.state != ProcessState.RUNNING or not verified.is_coordinator_owned:
                                raise RuntimeError("Model restored but prior coordinator-owned miner did not restart")
                            await self._persist_supervisor_state(supervisor)
                        except Exception:
                            supervisor.set_manual_override(True, persist=False)
                            await self._persist_supervisor_state(supervisor)
                            raise
                    elif self.system.miner_adapter is not None:
                        supervisor = self.system.miner_adapter.supervisor
                        supervisor.set_manual_override(
                            bool(current.get("miner_override_before", False)),
                            persist=False,
                            until=current.get("miner_override_until_before"),
                        )
                        await self._persist_supervisor_state(supervisor)
                    StateCodec.record_gaming_mode(path, "inactive")
                    result.update(status="inactive", state="inactive", restored_models=len(snapshot))

        result: Dict[str, Any] = {}
        try:
            allowed = await self.system.lease_mgr.run_if_idle(
                "gpu.inference", transition,
                additionally_guarded_resources={"gpu.model_loading"},
                check_self_cooldown=True,
            )
        except Exception as exc:
            try:
                StateCodec.record_gaming_mode(path, "failed")
            except Exception:
                logger.exception("Could not persist failed gaming transition")
            return {"status": "failed", "state": "failed", "reason": str(exc)}
        if not allowed:
            return {"status": "blocked", "reason": "GPU claims, cooldown, inhibition, or safety gate is active"}
        return result

    async def _sample_gpu_idle_condition(self, condition: Dict[str, Any], state_path: str, adapter: Any) -> None:
        """Sample only while mining is verified stopped; resume after a complete valid low-util window."""
        info = await adapter.status()
        if info.state != ProcessState.STOPPED:
            return
        try:
            if self._gpu_monitor is None:
                from resource_coordinator.monitors.gpu import NvidiaGpuMonitor

                self._gpu_monitor = NvidiaGpuMonitor()
            metrics = await self._gpu_monitor.get_metrics()
            values = [float(item.utilization_pct) for item in metrics]
            if not values or not all(math.isfinite(value) and 0 <= value <= 100 for value in values):
                return
        except Exception as exc:
            logger.debug("GPU-idle sampling unavailable; keeping miner paused: %s", exc)
            return

        now = time.time()
        window = float(condition["window_seconds"])
        threshold = float(condition["threshold_pct"])
        cutoff = now - window
        previous = list(condition.get("samples", []))
        samples_in_window = [item for item in previous if item["at"] >= cutoff]
        boundary = [item for item in previous if item["at"] < cutoff]
        samples = ([boundary[-1]] if boundary else []) + samples_in_window
        samples.append({"at": now, "utilization_pct": max(values)})
        samples = samples[-4000:]
        StateCodec.record_gpu_idle_condition(
            state_path, threshold_pct=threshold, window_seconds=window, samples=samples
        )
        condition["samples"] = samples

        poll = max(0.01, self.supervision_poll_interval)
        max_gap = max(2.5 * poll, min(5.0, window / 4.0))
        complete = (
            len(samples) >= 2
            and samples[0]["at"] <= cutoff
            and samples[-1]["at"] >= now - 2.0 * poll
            and all(right["at"] - left["at"] <= max_gap for left, right in zip(samples, samples[1:]))
        )
        window_samples = [item for item in samples if item["at"] >= cutoff]
        if not complete or not window_samples or (
            sum(item["utilization_pct"] for item in window_samples) / len(window_samples) > threshold
        ):
            return

        supervisor = adapter.supervisor

        async def resume_after_window() -> None:
            supervisor.set_manual_override(False, persist=False)
            StateCodec.record_gpu_idle_condition(state_path)
            try:
                await self._persist_supervisor_state(supervisor)
                started = await adapter.resume(origin="gpu_idle_window")
                verified = await adapter.status()
                if not started or verified.state != ProcessState.RUNNING or not verified.is_coordinator_owned:
                    raise RuntimeError("Coordinator-owned miner restart was not verified")
                await self._persist_supervisor_state(supervisor)
            except Exception:
                supervisor.set_manual_override(True, persist=False)
                await self._persist_supervisor_state(supervisor)
                StateCodec.record_gpu_idle_condition(
                    state_path, threshold_pct=threshold, window_seconds=window, samples=samples
                )
                logger.error("GPU-idle condition passed but coordinator-owned miner restart was not verified")

        resumed = await self.system.lease_mgr.run_if_idle(
            "gpu.inference", resume_after_window,
            additionally_guarded_resources={"gpu.model_loading"},
            check_self_cooldown=True,
        )
        if resumed:
            logger.info("GPU-idle pause condition satisfied; miner resumed after safety gates cleared")

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
                    state_path = getattr(self.system.config.service, "state_persistence_path", "")
                    durable_state = StateCodec.load(state_path) if state_path else None
                    condition = durable_state.gpu_idle_condition if durable_state else {}
                    gaming_mode = durable_state.gaming_mode if durable_state else {}
                    if _gpu_idle_sampling_allowed(
                        condition, gaming_mode, manual_override=supervisor.is_manual_override
                    ):
                        await self._sample_gpu_idle_condition(condition, state_path, adapter)
                    deadline = supervisor.manual_override_until
                    if supervisor.is_manual_override and deadline is not None and deadline <= time.time():
                        async def resume_expired_hold() -> None:
                            supervisor.set_manual_override(False, persist=False)
                            if supervisor.was_stopped_by_coordinator:
                                try:
                                    await self._persist_supervisor_state(supervisor)
                                    started = await adapter.resume(origin="manual_deadline")
                                    info = await adapter.status()
                                    if not started or info.state != ProcessState.RUNNING or not info.is_coordinator_owned:
                                        raise RuntimeError("Coordinator-owned miner restart was not verified")
                                    await self._persist_supervisor_state(supervisor)
                                except Exception:
                                    supervisor.set_manual_override(True, persist=False, until=deadline)
                                    await self._persist_supervisor_state(supervisor)
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
