"""Durable, fail-closed GPU maintenance ownership for external optimizers."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import secrets
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

from resource_coordinator.core.durable_state import StateCodec
from resource_coordinator.core.leases import LeaseManager
from resource_coordinator.core.processes import ProcessState

if TYPE_CHECKING:
    from resource_coordinator.core.service import CoordinatorService

logger = logging.getLogger(__name__)

MIN_LEASE_SECONDS = 30
MAX_LEASE_SECONDS = 3600
_STATES = {"idle", "acquiring", "active", "releasing", "recovery_required"}
_MAX_COMPLETED_OPERATIONS = 64


class MaintenanceSessionManager:
    """Owns one durable maintenance operation and its process-local fencing secret."""

    def __init__(
        self,
        service: CoordinatorService,
        *,
        response_wait_seconds: float = 2.0,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], Any] = asyncio.sleep,
        restoration_verifier: Optional[Callable[[Dict[str, Any], Dict[str, Any]], bool]] = None,
        observation_timeout_seconds: float = 5.0,
    ) -> None:
        self.service = service
        self.lease_manager: LeaseManager = service.system.lease_mgr
        self.state_path = Path(service.system.config.service.state_persistence_path) if (
            service.system.config.service.state_persistence_path
        ) else None
        self.response_wait_seconds = float(response_wait_seconds)
        self.clock = clock
        self.sleep = sleep
        self.restoration_verifier = restoration_verifier
        self.observation_timeout_seconds = float(observation_timeout_seconds)
        self._lock = asyncio.Lock()
        self._observer_admission = asyncio.Lock()
        self._observer_worker_active = False
        self._record: Dict[str, Any] = {"state": "idle"}
        self._operation_task: Optional[asyncio.Task] = None
        self._expiry_task: Optional[asyncio.Task] = None
        self._token_digest: Optional[bytes] = None
        self._token_for_idempotent_retry: Optional[str] = None
        self._last_released_session_id: Optional[str] = None
        self._last_released_token_digest: Optional[bytes] = None

    async def _run_observer(self, callback: Callable[..., Any], *args: Any) -> Any:
        """Bound observer waiting and reject retries while a timed-out worker is still active."""
        async with self._observer_admission:
            if self._observer_worker_active:
                raise RuntimeError("A previous read-only hardware/process observation is still running")
            self._observer_worker_active = True
            try:
                task = asyncio.create_task(asyncio.to_thread(callback, *args))
            except Exception:
                self._observer_worker_active = False
                raise
            task.add_done_callback(self._observer_finished)
        return await asyncio.wait_for(asyncio.shield(task), timeout=self.observation_timeout_seconds)

    def _observer_finished(self, task: asyncio.Task) -> None:
        self._observer_worker_active = False
        if not task.cancelled():
            # Retrieve late worker failures after the caller timed out, avoiding unhandled-task warnings.
            task.exception()

    @property
    def enabled(self) -> bool:
        return self.state_path is not None

    @property
    def state(self) -> str:
        return str(self._record.get("state", "idle"))

    def _require_state_path(self) -> Optional[Dict[str, Any]]:
        if self.state_path is None:
            return {"status": "unavailable", "error": "Durable state persistence is required"}
        return None

    @staticmethod
    def _validate_request(payload: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(payload, dict):
            return {"status": "invalid", "error": "A JSON object is required"}
        for name in ("operator", "reason"):
            value = payload.get(name)
            if not isinstance(value, str) or not value.strip() or len(value) > 256:
                return {"status": "invalid", "error": f"A nonempty bounded {name} is required"}
        lease_seconds = payload.get("lease_seconds", 3600)
        if type(lease_seconds) is not int or not MIN_LEASE_SECONDS <= lease_seconds <= MAX_LEASE_SECONDS:
            return {
                "status": "invalid",
                "error": f"lease_seconds must be an integer in {MIN_LEASE_SECONDS}..{MAX_LEASE_SECONDS}",
            }
        if payload.get("inhibit_restarts") is not True:
            return {"status": "invalid", "error": "inhibit_restarts must be true"}
        operation_id = payload.get("request_id", payload.get("idempotency_key"))
        if operation_id is not None and (
            not isinstance(operation_id, str)
            or not operation_id
            or len(operation_id) > 128
            or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-" for ch in operation_id)
        ):
            return {"status": "invalid", "error": "request_id must be a bounded URL-safe identifier"}
        tuning_scope = payload.get("tuning_scope")
        if tuning_scope is not None:
            if (
                not isinstance(tuning_scope, dict)
                or set(tuning_scope) != {"mode", "dimensions"}
                or not isinstance(tuning_scope.get("mode"), str)
                or not isinstance(tuning_scope.get("dimensions"), list)
                or len(tuning_scope["dimensions"]) > 3
                or any(not isinstance(item, str) for item in tuning_scope["dimensions"])
            ):
                return {"status": "invalid", "error": "tuning_scope must declare a bounded mode and dimensions"}
            tuning_scope = {"mode": tuning_scope["mode"], "dimensions": list(tuning_scope["dimensions"])}
        return {
            "operator": payload["operator"].strip(),
            "reason": payload["reason"].strip(),
            "lease_seconds": lease_seconds,
            "operation_id": operation_id or uuid.uuid4().hex,
            "client_supplied_operation_id": operation_id is not None,
            "tuning_scope": tuning_scope,
        }

    def _load_record(self) -> Dict[str, Any]:
        assert self.state_path is not None
        state = StateCodec.load(self.state_path)
        return dict(state.maintenance or {"state": "idle"})

    @staticmethod
    def _completed_dispositions(record: Dict[str, Any]) -> list[Dict[str, Any]]:
        history = list(record.get("completed_operations", []))
        last = record.get("last_disposition")
        if isinstance(last, dict) and last.get("operation_id") and not any(
            item.get("operation_id") == last["operation_id"] for item in history
        ):
            history.append(last)
        return history

    def _inhibition(self, record: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "resource": "gpu.inference",
            "reason": "exclusive GPU maintenance session",
            "holder_id": f"maintenance:{record['operation_id']}",
            "inhibited_at": self.clock(),
            "details": {"maintenance_operation_id": record["operation_id"]},
        }

    def _persist(
        self,
        record: Dict[str, Any],
        *,
        set_inhibition: bool = False,
        clear_inhibition_holder: Optional[str] = None,
    ) -> None:
        assert self.state_path is not None
        StateCodec.record_maintenance(
            self.state_path,
            record,
            set_inhibition=self._inhibition(record) if set_inhibition else None,
            clear_inhibition_holder=clear_inhibition_holder,
        )
        self._record = dict(record)

    async def restore_before_startup(self) -> None:
        """Revoke previous-process token authority and restore admission/restart holds."""
        if self.state_path is None:
            return
        state = StateCodec.mark_maintenance_recovery_required(self.state_path)
        assert state is not None
        self._record = dict(state.maintenance or {"state": "idle"})
        if self.state == "idle":
            restart_not_before = self._record.get("restart_not_before")
            if restart_not_before is not None:
                await self.lease_manager.restore_cooldown(
                    "gpu.inference", max(0.0, float(restart_not_before) - self.clock())
                )
                disposition = self._record.get("last_disposition", {})
                supervisor = self._miner_supervisor()
                if disposition.get("miner_restart_eligible") and supervisor is not None:
                    # The durable process record owns the coordinator-stop bit. Startup
                    # has not reconciled that record into the supervisor yet, so writing
                    # a snapshot here would replace the correct bit with the supervisor's
                    # default False value and strand the miner after cooldown. The absolute
                    # maintenance deadline is already durable and recreates this temporary
                    # in-memory hold after any further restart.
                    supervisor.set_manual_override(True, persist=False, until=float(restart_not_before))
            return
        holder = f"maintenance:{self._record['operation_id']}"
        await self.lease_manager.restore_gpu_maintenance_fence(holder)
        await self.lease_manager.inhibit_restart(
            "gpu.inference", "maintenance session requires startup reconciliation", holder,
            {"maintenance_operation_id": self._record["operation_id"]},
        )
        supervisor = self._miner_supervisor()
        if supervisor is not None:
            supervisor.set_manual_override(True, persist=False)
            await self.service._persist_supervisor_state(supervisor)
        await self._emit("resource_coordinator.maintenance_recovery_required", self._record)

    async def prepare_shutdown(self) -> None:
        """Revoke owner authority on service shutdown without implying restoration."""
        if self.state == "idle":
            return
        async with self._lock:
            if self.state == "idle":
                return
            record = dict(self._record)
            record.update(
                state="recovery_required",
                updated_at=self.clock(),
                recovery_reason="Coordinator is shutting down; external restoration must be reconciled",
            )
            self._token_digest = None
            self._token_for_idempotent_retry = None
            if self._expiry_task is not None:
                self._expiry_task.cancel()
                self._expiry_task = None
            self._persist(record)

    async def acquire(self, payload: Any) -> Dict[str, Any]:
        unavailable = self._require_state_path()
        if unavailable:
            return unavailable
        request = self._validate_request(payload)
        if request and request.get("status") == "invalid":
            return request
        assert request is not None
        if getattr(self.restoration_verifier, "validate_scope", None):
            if not request.get("tuning_scope") or not self.restoration_verifier.validate_scope(request["tuning_scope"]):
                return {"status": "invalid", "error": "A verifier-supported tuning_scope is required"}
        preflight = getattr(self.restoration_verifier, "preflight", None)
        if callable(preflight):
            try:
                await self._run_observer(preflight, request["tuning_scope"])
            except asyncio.TimeoutError:
                return {"status": "unavailable", "error": "Restoration-verifier preflight timed out; miner was not stopped"}
            except Exception as exc:
                logger.info("Maintenance observer preflight rejected acquisition (%s)", type(exc).__name__)
                return {"status": "unavailable", "error": "Restoration-verifier preflight failed; miner was not stopped"}
        operation_id = request["operation_id"]
        task: Optional[asyncio.Task] = None
        async with self._lock:
            current = self._load_record()
            current_state = current.get("state", "idle")
            if current_state == "idle" and any(
                item.get("operation_id") == operation_id for item in self._completed_dispositions(current)
            ):
                return {
                    "status": "conflict",
                    "error": "request_id already identifies a completed maintenance operation",
                    "operation_id": operation_id,
                }
            if current_state != "idle":
                if current.get("operation_id") == operation_id:
                    if any(
                        current.get(key) != request[key]
                        for key in ("operator", "reason", "lease_seconds", "tuning_scope")
                    ):
                        return {
                            "status": "conflict",
                            "error": "request_id is already bound to a different maintenance request",
                            "operation_id": operation_id,
                        }
                    if current_state == "active" and self._token_for_idempotent_retry:
                        return self._granted_result(current, self._token_for_idempotent_retry)
                    return self.operation_status(operation_id)
                return {
                    "status": "recovery_required" if current_state == "recovery_required" else "conflict",
                    "error": "Another GPU maintenance operation owns or inhibits the resource",
                    "maintenance": self.status(),
                }
            if self._miner_supervisor() is None:
                return {"status": "unavailable", "error": "A managed miner is required for maintenance ownership"}
            operation_id = request["operation_id"]
            holder = f"maintenance:{operation_id}"

            def precondition() -> bool:
                try:
                    return StateCodec.load(self.state_path).gaming_mode.get("state", "inactive") == "inactive"
                except (OSError, ValueError):
                    return False

            if not await self.lease_manager.begin_gpu_maintenance(holder, precondition=precondition):
                return {
                    "status": "conflict",
                    "error": "GPU claims, cooldown, recovery holds, gaming, or another transition blocks maintenance",
                    "maintenance": self.status(),
                }

            miner_info = await self.service.system.miner_adapter.status()
            if miner_info.state not in {ProcessState.RUNNING, ProcessState.STOPPED}:
                # The admission fence is retained because process identity is ambiguous.
                record = self._new_record(request, state="recovery_required")
                record["recovery_reason"] = "Managed miner process identity is not verifiable"
                try:
                    self._persist(record, set_inhibition=True)
                    await self.lease_manager.inhibit_restart(
                        "gpu.inference", "maintenance acquisition process identity is uncertain", holder,
                        {"maintenance_operation_id": operation_id},
                    )
                except Exception:
                    self.service._state = type(self.service.state).RECONCILIATION_REQUIRED
                    self.service._failure_reason = "Could not persist maintenance recovery hold"
                    self.service._freeze(self.service._failure_reason)
                return {"status": "recovery_required", "operation_id": operation_id,
                        "error": record["recovery_reason"]}
            if miner_info.state == ProcessState.RUNNING and not miner_info.is_coordinator_owned:
                # Never stop or adopt an external process. Keep admission closed for operator reconciliation.
                record = self._new_record(request, state="recovery_required")
                record["recovery_reason"] = "A running miner is not coordinator-owned; no process was stopped"
                try:
                    self._persist(record, set_inhibition=True)
                    await self.lease_manager.inhibit_restart(
                        "gpu.inference", "external miner conflicts with maintenance", holder,
                        {"maintenance_operation_id": operation_id},
                    )
                except Exception:
                    self.service._state = type(self.service.state).RECONCILIATION_REQUIRED
                    self.service._failure_reason = "Could not persist maintenance recovery hold"
                    self.service._freeze(self.service._failure_reason)
                return {"status": "recovery_required", "operation_id": operation_id,
                        "error": record["recovery_reason"]}

            record = self._new_record(request, state="acquiring")
            record["completed_operations"] = self._completed_dispositions(current)[-_MAX_COMPLETED_OPERATIONS:]
            record["miner_was_running"] = miner_info.state == ProcessState.RUNNING
            record["manual_override_before"] = self._miner_supervisor().is_manual_override
            try:
                self._persist(record, set_inhibition=True)
                await self.lease_manager.inhibit_restart(
                    "gpu.inference", "exclusive GPU maintenance session", holder,
                    {"maintenance_operation_id": operation_id},
                )
            except Exception as exc:
                # Keep the in-memory fence and terminalize service admission. No miner stop has begun.
                self._record = {**record, "state": "recovery_required",
                                "recovery_reason": "Durable maintenance intent could not be confirmed"}
                self.service._state = type(self.service.state).RECONCILIATION_REQUIRED
                self.service._failure_reason = "Durable maintenance intent could not be confirmed"
                self.service._freeze(self.service._failure_reason)
                logger.error("Could not persist maintenance intent for operation %s: %s", operation_id, exc)
                return {"status": "persistence_failed", "operation_id": operation_id,
                        "error": "Durable maintenance intent could not be confirmed"}
            await self._emit("resource_coordinator.maintenance_acquiring", record)
            self._operation_task = asyncio.create_task(self._complete_acquisition(record))
            task = self._operation_task

        assert task is not None
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=self.response_wait_seconds)
        except asyncio.TimeoutError:
            return self.operation_status(operation_id)
        except asyncio.CancelledError:
            # Client disconnect never cancels the process-stop transaction.
            raise

    def _new_record(self, request: Dict[str, Any], *, state: str) -> Dict[str, Any]:
        now = self.clock()
        return {
            "state": state,
            "operation_id": request["operation_id"],
            "operator": request["operator"],
            "reason": request["reason"],
            "requested_at": now,
            "updated_at": now,
            "lease_seconds": request["lease_seconds"],
            "miner_was_running": False,
            "miner_stopped_by_coordinator": False,
            "manual_override_before": False,
            "restoration": {},
            **({"tuning_scope": dict(request["tuning_scope"])} if request.get("tuning_scope") else {}),
            "registered_processes": [],
        }

    async def _complete_acquisition(self, record: Dict[str, Any]) -> Dict[str, Any]:
        operation_id = record["operation_id"]
        async with self._lock:
            if self._record.get("operation_id") != operation_id or self.state != "acquiring":
                return self.operation_status(operation_id)
            supervisor = self._miner_supervisor()
            assert supervisor is not None
            try:
                supervisor.set_manual_override(True, persist=False)
                await self.service._persist_supervisor_state(supervisor)
                info = await self.service.system.miner_adapter.status()
                if info.state == ProcessState.RUNNING:
                    if not info.is_coordinator_owned:
                        raise RuntimeError("Miner became externally owned before maintenance stop")
                    cfg = self.service.system.config.processes[supervisor.name]
                    stopped = await self.service.system.miner_adapter.pause(
                        timeout=cfg.stop_timeout_seconds, origin="maintenance"
                    )
                    verified = await self.service.system.miner_adapter.status()
                    if not stopped or verified.state != ProcessState.STOPPED or not supervisor.was_stopped_by_coordinator:
                        raise RuntimeError("Coordinator-owned miner stop could not be verified")
                    record["miner_stopped_by_coordinator"] = True
                    await self.service._persist_supervisor_state(supervisor, was_stopped_by_coordinator=True)
                elif info.state != ProcessState.STOPPED:
                    raise RuntimeError("Miner state became unverifiable during acquisition")

                capture_baseline = getattr(self.restoration_verifier, "capture_baseline", None)
                if callable(capture_baseline):
                    if not record.get("tuning_scope"):
                        raise RuntimeError("Maintenance tuning scope is unavailable")
                    baseline = await self._run_observer(capture_baseline, record["tuning_scope"])
                    from resource_coordinator.core.restoration import evaluate_gpu_restoration
                    baseline_check = evaluate_gpu_restoration(
                        record["tuning_scope"], baseline, baseline,
                        expected_gpu_uuid=self.restoration_verifier.gpu_uuid,
                        max_age_seconds=self.restoration_verifier.max_age_seconds,
                    )
                    if not baseline_check.verified:
                        raise RuntimeError(f"Maintenance baseline rejected: {baseline_check.reason_code}")
                    record["gpu_baseline"] = {**baseline, "operation_id": operation_id}

                token = secrets.token_urlsafe(32)
                session_id = uuid.uuid4().hex
                now = self.clock()
                record = dict(record)
                record.update(
                    state="active",
                    session_id=session_id,
                    updated_at=now,
                    expires_at=now + record["lease_seconds"],
                )
                self._persist(record)
                self._token_digest = hashlib.sha256(token.encode("utf-8")).digest()
                self._token_for_idempotent_retry = token
                self._schedule_expiry(session_id, record["expires_at"])
                await self._emit("resource_coordinator.maintenance_granted", record)
                return self._granted_result(record, token)
            except asyncio.CancelledError:
                await asyncio.shield(self._mark_recovery_locked(record, "Acquisition interrupted during process transition"))
                raise
            except Exception as exc:
                await self._mark_recovery_locked(record, f"Acquisition could not verify a safe miner stop: {type(exc).__name__}")
                logger.warning("Maintenance acquisition %s requires reconciliation (%s)", operation_id, type(exc).__name__)
                return {"status": "recovery_required", "operation_id": operation_id,
                        "error": "Miner stop or durable acquisition could not be verified"}

    def _miner_supervisor(self):
        adapter = self.service.system.miner_adapter
        return adapter.supervisor if adapter is not None else None

    @staticmethod
    def _granted_result(record: Dict[str, Any], token: str) -> Dict[str, Any]:
        return {
            "status": "granted",
            "session_id": record["session_id"],
            "token": token,
            "lease_seconds": record["lease_seconds"],
            "expires_at": record["expires_at"],
            "operation_id": record["operation_id"],
        }

    async def heartbeat(self, payload: Any) -> Dict[str, Any]:
        unavailable = self._require_state_path()
        if unavailable:
            return unavailable
        if not isinstance(payload, dict):
            return {"status": "invalid", "error": "A JSON object is required"}
        token = payload.get("token")
        duration = payload.get("lease_seconds", 3600)
        if not isinstance(token, str) or not token or type(duration) is not int or not MIN_LEASE_SECONDS <= duration <= MAX_LEASE_SECONDS:
            return {"status": "invalid", "error": "A token and bounded integer lease_seconds are required"}
        async with self._lock:
            if self.state != "active" or not self._token_matches(token):
                return {"status": "stale", "error": "Maintenance fencing token is invalid or revoked"}
            if self.clock() >= float(self._record["expires_at"]):
                await self._mark_recovery_locked(self._record, "Maintenance lease expired without reconciliation")
                return {"status": "expired", "error": "Expired ownership cannot be renewed"}
            record = dict(self._record)
            now = self.clock()
            record.update(last_renewed_at=now, expires_at=now + duration, lease_seconds=duration, updated_at=now)
            try:
                self._persist(record)
            except Exception:
                await self._mark_recovery_locked(record, "Heartbeat could not be durably recorded")
                return {"status": "unavailable", "error": "Heartbeat persistence failed; recovery hold remains active"}
            self._schedule_expiry(record["session_id"], record["expires_at"])
            return {"status": "renewed", "session_id": record["session_id"], "expires_at": record["expires_at"],
                    "lease_seconds": duration}

    async def register_process(self, payload: Any) -> Dict[str, Any]:
        """Register a trial process after independently verifying its current OS identity."""
        unavailable = self._require_state_path()
        if unavailable:
            return unavailable
        if not isinstance(payload, dict):
            return {"status": "invalid", "error": "A JSON object is required"}
        token, session_id, pid = payload.get("token"), payload.get("session_id"), payload.get("pid")
        if not isinstance(token, str) or not token or not isinstance(session_id, str) or not session_id \
                or type(pid) is not int or pid <= 0:
            return {"status": "invalid", "error": "token, session_id, and positive integer pid are required"}
        inspector = getattr(self.restoration_verifier, "inspect_process", None)
        if not callable(inspector):
            return {"status": "unavailable", "error": "Trusted process observation is not configured"}
        async with self._lock:
            if self.state != "active" or self._record.get("session_id") != session_id \
                    or not self._token_matches(token):
                return {"status": "stale", "error": "Maintenance ownership is invalid or revoked"}
            if self.clock() >= float(self._record.get("expires_at", 0)):
                await self._mark_recovery_locked(self._record, "Maintenance lease expired during process registration")
                return {"status": "expired", "error": "Expired maintenance ownership cannot register a process"}
            operation_id = self._record.get("operation_id")
        try:
            identity = await self._run_observer(inspector, pid)
        except asyncio.TimeoutError:
            return {"status": "unavailable", "error": "Process identity observation timed out"}
        except Exception as exc:
            return {"status": "invalid", "error": f"Process identity could not be verified ({type(exc).__name__})"}
        async with self._lock:
            if self.state != "active" or self._record.get("operation_id") != operation_id \
                    or self._record.get("session_id") != session_id or not self._token_matches(token):
                return {"status": "stale", "error": "Maintenance ownership changed during process inspection"}
            if self.clock() >= float(self._record.get("expires_at", 0)):
                await self._mark_recovery_locked(self._record, "Maintenance lease expired during process registration")
                return {"status": "expired", "error": "Expired maintenance ownership cannot register a process"}
            processes = list(self._record.get("registered_processes", []))
            if any(item.get("pid") == identity["pid"] and item.get("create_time") == identity["create_time"]
                   for item in processes):
                return {"status": "registered", "session_id": session_id, "process_count": len(processes),
                        "idempotent": True}
            if len(processes) >= 64:
                return {"status": "invalid", "error": "Maintenance process registration limit reached"}
            record = dict(self._record)
            record["registered_processes"] = processes + [identity]
            record["updated_at"] = self.clock()
            try:
                self._persist(record)
            except Exception:
                await self._mark_recovery_locked(self._record, "Process registration could not be durably recorded")
                return {"status": "persistence_failed", "error": "Process registration persistence failed"}
            return {"status": "registered", "session_id": session_id, "process_count": len(record["registered_processes"])}

    async def release(self, payload: Any) -> Dict[str, Any]:
        unavailable = self._require_state_path()
        if unavailable:
            return unavailable
        if not isinstance(payload, dict):
            return {"status": "invalid", "error": "A JSON object is required"}
        token = payload.get("token")
        session_id = payload.get("session_id")
        operation_id = payload.get("operation_id")
        operator = payload.get("operator")
        if not isinstance(operator, str) or not operator or (
            session_id is not None and (not isinstance(session_id, str) or not session_id)
        ):
            return {"status": "invalid", "error": "operator and a valid session_id are required"}
        if type(payload.get("restoration_verified")) is not bool or type(payload.get("resume_miner", True)) is not bool:
            return {"status": "invalid", "error": "restoration_verified and resume_miner must be booleans"}
        override = payload.get("operator_override") is True
        override_reason = payload.get("override_reason")
        if override and (not isinstance(override_reason, str) or not override_reason.strip() or len(override_reason) > 512):
            return {"status": "invalid", "error": "Explicit operator override requires a bounded reason"}

        evidence = payload.get("restoration_evidence", {})
        if not isinstance(evidence, dict) or len(evidence) > 32:
            return {"status": "invalid", "error": "restoration_evidence must be a bounded object"}
        preverified = False
        verification_summary: Optional[Dict[str, Any]] = None
        verifier = self.restoration_verifier
        verify_method = getattr(verifier, "verify", None)
        if not callable(verify_method) and callable(verifier):
            verify_method = verifier
        verify_snapshot: Optional[Dict[str, Any]] = None

        if payload["restoration_verified"] and not override and callable(verify_method):
            async with self._lock:
                if self.state == "releasing" and self._record.get("session_id") == session_id \
                        and isinstance(token, str) and self._token_matches(token):
                    return {"status": "pending", "session_id": session_id,
                            "operation_id": self._record.get("operation_id"),
                            "error": "Restoration verification is already in progress"}
                if self.state != "active" or self._record.get("session_id") != session_id \
                        or not isinstance(token, str) or not self._token_matches(token):
                    # Operator recovery continues through the existing audited override path.
                    if not (self.state == "recovery_required" and override):
                        return {"status": "stale", "error": "Maintenance session or fencing token is invalid"}
                elif self._record.get("operator") != operator and not override:
                    return {"status": "stale", "error": "Maintenance session belongs to another operator"}
                elif self.clock() >= float(self._record.get("expires_at", 0)):
                    await self._mark_recovery_locked(self._record,
                        "Maintenance lease expired before restoration verification")
                    return {"status": "expired", "error": "Expired ownership requires operator reconciliation"}
                else:
                    verify_snapshot = dict(self._record)
                    verify_snapshot.update(state="releasing", updated_at=self.clock())
                    self._persist(verify_snapshot)
            if verify_snapshot is not None:
                try:
                    result = await self._run_observer(verify_method, verify_snapshot, dict(evidence))
                    if isinstance(result, bool):
                        preverified = result
                        verification_summary = {"verified": result,
                                                "reason_code": "legacy_verifier" if result else "verification_failed"}
                    elif callable(getattr(result, "to_dict", None)):
                        verification_summary = result.to_dict()
                        preverified = result.verified is True
                    else:
                        verification_summary = {"verified": False, "reason_code": "invalid_verifier_result"}
                except asyncio.TimeoutError:
                    verification_summary = {"verified": False, "reason_code": "verification_timeout"}
                except asyncio.CancelledError:
                    async with self._lock:
                        if self.state == "releasing" and self._record.get("session_id") == session_id:
                            await asyncio.shield(self._mark_recovery_locked(
                                self._record, "Restoration verification was cancelled"))
                    raise
                except Exception as exc:
                    verification_summary = {"verified": False,
                                             "reason_code": f"verification_error:{type(exc).__name__}"}
                async with self._lock:
                    if self.state != "releasing" or self._record.get("session_id") != session_id \
                            or self._record.get("operation_id") != verify_snapshot.get("operation_id"):
                        return {"status": "stale", "error": "Maintenance ownership changed during verification"}
                    if self.clock() >= float(self._record.get("expires_at", 0)):
                        await self._mark_recovery_locked(self._record,
                            "Maintenance lease expired while restoration was being verified")
                        return {"status": "expired", "error": "Expired ownership requires operator reconciliation"}
                    if not preverified:
                        failed = dict(self._record)
                        failed["restoration"] = {
                            "client_asserted_verified": True,
                            "independently_verified": False,
                            "operator_override": False,
                            "evidence_received": bool(evidence),
                            "attempted_at": self.clock(),
                            "verification": verification_summary,
                        }
                        await self._mark_recovery_locked(
                            failed, "Independent restoration verification did not establish safe release")
                        return {"status": "recovery_required", "session_id": session_id,
                                "error": "Independent restoration verification failed; GPU admission remains inhibited",
                                "maintenance": self.status()}
                    record = dict(self._record)
                    record["restoration"] = {
                        "client_asserted_verified": True,
                        "independently_verified": True,
                        "operator_override": False,
                        "evidence_received": bool(evidence),
                        "verified_at": self.clock(),
                        "verification": verification_summary,
                    }
                    record["updated_at"] = self.clock()
                    self._persist(record)

        async with self._lock:
            completed = self._completed_dispositions(self._record)
            replay = next((item for item in reversed(completed) if (
                (isinstance(session_id, str) and session_id == item.get("session_id"))
                or (isinstance(operation_id, str) and operation_id == item.get("operation_id"))
            )), None)
            if self.state == "idle" and replay is not None:
                # The authenticated route already proves operator authority. A completed
                # durable disposition is safe to replay without reviving the old token.
                return {"status": "released", "session_id": replay.get("session_id"),
                        "disposition": dict(replay), "idempotent_replay": True}
            operator_recovery = (
                self.state == "recovery_required"
                and override
                and (
                    (isinstance(session_id, str) and session_id == self._record.get("session_id"))
                    or (isinstance(operation_id, str) and operation_id == self._record.get("operation_id"))
                )
            )
            token_owner = (
                self.state in {"active", "releasing"}
                and self._record.get("session_id") == session_id
                and isinstance(token, str)
                and self._token_matches(token)
            )
            active_owner = token_owner and (
                self._record.get("operator") == operator or override
            )
            if not (active_owner or operator_recovery):
                return {"status": "stale", "error": "Maintenance session or fencing token is invalid"}
            if active_owner and self.clock() >= float(self._record["expires_at"]):
                await self._mark_recovery_locked(self._record, "Maintenance lease expired before release reconciliation")
                return {"status": "expired", "error": "Expired ownership requires operator reconciliation"}

            independent = preverified
            if not operator_recovery and not override and not (payload["restoration_verified"] and independent):
                record = dict(self._record)
                record["restoration"] = {
                    "client_asserted_verified": payload["restoration_verified"],
                    "independently_verified": independent,
                    "operator_override": override,
                    "evidence_received": bool(evidence),
                    "attempted_at": self.clock(),
                    **({"verification": verification_summary} if verification_summary else {}),
                }
                record["updated_at"] = self.clock()
                self._persist(record)
                return {"status": "recovery_required", "error": "Client assertion alone does not prove hardware restoration",
                        "session_id": session_id, "maintenance": self.status()}

            record = dict(self._record)
            record.update(state="releasing", updated_at=self.clock())
            record["restoration"] = {
                "client_asserted_verified": payload["restoration_verified"],
                "independently_verified": independent,
                "operator_override": override,
                "override_reason": override_reason.strip() if override else None,
                "evidence_received": bool(evidence),
                "verified_at": self.clock(),
                **({"verification": verification_summary} if verification_summary else {}),
            }
            try:
                release_committed = False
                self._persist(record)
                supervisor = self._miner_supervisor()
                if supervisor is None:
                    raise RuntimeError("Managed miner is unavailable during release")
                miner = await self.service.system.miner_adapter.status()
                if miner.state != ProcessState.STOPPED:
                    raise RuntimeError("Managed miner is not independently verified stopped")
                restore_override = bool(record.get("manual_override_before") or not payload.get("resume_miner", True))
                supervisor.set_manual_override(restore_override, persist=False)
                await self.service._persist_supervisor_state(supervisor)
                disposition = {
                    "operation_id": record["operation_id"],
                    "session_id": session_id,
                    "operator": operator,
                    "released_at": self.clock(),
                    "resume_miner_requested": payload.get("resume_miner", True),
                    "restoration": dict(record["restoration"]),
                    "miner_restart_eligible": bool(record.get("miner_stopped_by_coordinator") and not restore_override),
                }
                completed_operations = [
                    item for item in self._completed_dispositions(record)
                    if item.get("operation_id") != record["operation_id"]
                ]
                completed_operations = (completed_operations + [disposition])[-_MAX_COMPLETED_OPERATIONS:]
                idle_record = {
                    "state": "idle",
                    "updated_at": self.clock(),
                    "restart_not_before": self.clock() + self.lease_manager.get_resource_cooldown("gpu.inference"),
                    "last_disposition": disposition,
                    "completed_operations": completed_operations,
                }
                holder = f"maintenance:{record['operation_id']}"

                def persist_release() -> None:
                    self._persist(idle_record, clear_inhibition_holder=holder)

                cleared = await self.lease_manager.clear_inhibition_holder(
                    "gpu.inference",
                    holder,
                    before_change=persist_release,
                    start_cooldown=False,
                )
                if cleared is None:
                    raise RuntimeError("Maintenance restart inhibition changed before release")
                self._last_released_session_id = session_id
                self._last_released_token_digest = self._token_digest
                self._token_digest = None
                self._token_for_idempotent_retry = None
                if self._expiry_task is not None:
                    self._expiry_task.cancel()
                    self._expiry_task = None
                await self.lease_manager.end_gpu_maintenance(holder, cooldown_resource="gpu.inference")
                release_committed = True
                await self._emit("resource_coordinator.maintenance_released", idle_record)
                return {"status": "released", "session_id": session_id,
                        "disposition": dict(disposition)}
            except asyncio.CancelledError:
                if not release_committed:
                    await asyncio.shield(
                        self._mark_recovery_locked(record, "Release interrupted during restoration transition")
                    )
                raise
            except Exception as exc:
                if release_committed:
                    logger.warning(
                        "Maintenance release %s committed but its observational event failed (%s)",
                        record.get("operation_id"), type(exc).__name__,
                    )
                    return {
                        "status": "released",
                        "session_id": session_id,
                        "disposition": dict(disposition),
                    }
                await self._mark_recovery_locked(record, f"Release could not be safely reconciled: {type(exc).__name__}")
                logger.warning("Maintenance release %s requires reconciliation (%s)",
                               record.get("operation_id"), type(exc).__name__)
                return {"status": "recovery_required", "session_id": session_id,
                        "error": "Release could not be verified; GPU admission remains inhibited"}

    def _token_matches(self, token: str) -> bool:
        return self._token_digest is not None and self._matches_digest(token, self._token_digest)

    @staticmethod
    def _matches_digest(token: str, expected: bytes) -> bool:
        return hmac.compare_digest(hashlib.sha256(token.encode("utf-8")).digest(), expected)

    async def _mark_recovery_locked(self, record: Dict[str, Any], reason: str) -> None:
        recovery = dict(record)
        recovery.update(state="recovery_required", updated_at=self.clock(), recovery_reason=reason)
        self._token_digest = None
        self._token_for_idempotent_retry = None
        try:
            self._persist(recovery, set_inhibition=True)
        except Exception as exc:
            self._record = recovery
            self.service._state = self.service.state.RECONCILIATION_REQUIRED
            self.service._failure_reason = "Maintenance recovery state could not be persisted"
            self.service._freeze(self.service._failure_reason)
            logger.error("Maintenance recovery persistence failed (%s)", type(exc).__name__)
        holder = f"maintenance:{recovery['operation_id']}"
        try:
            await self.lease_manager.restore_gpu_maintenance_fence(holder)
            await self.lease_manager.inhibit_restart(
                "gpu.inference", "maintenance requires recovery", holder,
                {"maintenance_operation_id": recovery["operation_id"]},
            )
        except Exception as exc:
            self.service._state = type(self.service.state).RECONCILIATION_REQUIRED
            self.service._failure_reason = "Maintenance admission fence could not be restored"
            self.service._freeze(self.service._failure_reason)
            logger.error("Could not restore in-memory maintenance fence (%s)", type(exc).__name__)
        supervisor = self._miner_supervisor()
        if supervisor is not None:
            supervisor.set_manual_override(True, persist=False)
            try:
                await self.service._persist_supervisor_state(supervisor)
            except Exception as exc:
                logger.error("Could not persist miner hold after maintenance failure (%s)", type(exc).__name__)
        await self._emit("resource_coordinator.maintenance_recovery_required", recovery)

    def _schedule_expiry(self, session_id: str, expires_at: float) -> None:
        if self._expiry_task is not None:
            self._expiry_task.cancel()

        async def expire() -> None:
            try:
                await self.sleep(max(0.0, expires_at - self.clock()))
                async with self._lock:
                    if self.state == "active" and self._record.get("session_id") == session_id \
                            and self.clock() >= float(self._record.get("expires_at", float("inf"))):
                        await self._mark_recovery_locked(
                            self._record, "Maintenance lease expired; external execution termination is unverified"
                        )
                        await self._emit("resource_coordinator.maintenance_expired", self._record)
            except asyncio.CancelledError:
                return

        self._expiry_task = asyncio.create_task(expire())

    def status(self) -> Dict[str, Any]:
        record = self._record
        state = record.get("state", "idle")
        disposition = record.get("last_disposition", {})
        safe_disposition = {
            key: disposition[key]
            for key in (
                "operation_id", "session_id", "operator", "released_at", "resume_miner_requested",
                "miner_restart_eligible",
            )
            if key in disposition
        }
        safe_restoration = disposition.get("restoration", {})
        if isinstance(safe_restoration, dict):
            safe_disposition["restoration"] = {
                key: safe_restoration[key]
                for key in (
                    "client_asserted_verified", "independently_verified", "operator_override",
                    "evidence_received", "verified_at",
                )
                if key in safe_restoration
            }
            if isinstance(safe_restoration.get("verification"), dict):
                safe_disposition["restoration"]["verification"] = self._safe_verification(
                    safe_restoration["verification"]
                )
        another_hold = any(
            self.lease_manager.is_restart_inhibited(resource)
            for resource in self.lease_manager.tracked_resources()
            if resource.startswith("gpu.")
        )
        current_restoration = {
            key: value for key, value in record.get("restoration", {}).items()
            if key in {"client_asserted_verified", "independently_verified", "operator_override",
                       "evidence_received", "verified_at", "attempted_at"}
        }
        if isinstance(record.get("restoration", {}).get("verification"), dict):
            current_restoration["verification"] = self._safe_verification(
                record["restoration"]["verification"]
            )
        return {
            "state": state,
            "owner": record.get("operator"),
            "operation_id": record.get("operation_id"),
            "session_id": record.get("session_id"),
            "reason": record.get("reason"),
            "requested_at": record.get("requested_at"),
            "expires_at": record.get("expires_at"),
            "restart_not_before": record.get("restart_not_before"),
            "last_renewed_at": record.get("last_renewed_at"),
            "acquisition_pending": state == "acquiring",
            "restart_inhibited": state != "idle" or another_hold or self.lease_manager.restarts_blocked,
            "gpu_admission_permitted": (
                state == "idle"
                and self.lease_manager.gpu_maintenance_owner is None
                and not another_hold
                and not self.lease_manager.restarts_blocked
            ),
            "recovery_required_reason": record.get("recovery_reason"),
            "restoration": current_restoration,
            "last_disposition": safe_disposition,
            "registered_process_count": len(record.get("registered_processes", [])),
        }

    @staticmethod
    def _safe_verification(summary: Dict[str, Any]) -> Dict[str, Any]:
        comparisons = summary.get("comparisons", {})
        safe_comparisons = {}
        if isinstance(comparisons, dict):
            for key, comparison in comparisons.items():
                if key in {"power_limit_mw", "graphics_clock_offset_mhz", "memory_clock_offset_mhz"} \
                        and isinstance(comparison, dict):
                    safe_comparisons[key] = {
                        field: comparison[field] for field in ("match", "baseline", "current", "unit", "status")
                        if field in comparison
                    }
        process_result = summary.get("process_termination", {})
        safe_process_result = {
            "registered_processes": process_result.get("registered_processes")
        } if isinstance(process_result, dict) else {}
        return {
            key: summary[key] for key in ("verified", "reason_code", "gpu_uuid", "observed_at")
            if key in summary
        } | {"comparisons": safe_comparisons, "process_termination": safe_process_result}

    def operation_status(self, operation_id: str) -> Dict[str, Any]:
        if operation_id != self._record.get("operation_id"):
            completed = next((item for item in reversed(self._completed_dispositions(self._record))
                              if item.get("operation_id") == operation_id), None)
            if completed is not None:
                return {"status": "released", "operation_id": operation_id,
                        "session_id": completed.get("session_id"), "disposition": dict(completed)}
            return {"status": "not_found", "operation_id": operation_id}
        return {
            "status": "pending" if self.state in {"acquiring", "releasing"} else self.state,
            "operation_id": operation_id,
            "session_id": self._record.get("session_id"),
            "maintenance": self.status(),
        }

    async def _emit(self, event_name: str, record: Dict[str, Any]) -> None:
        restoration = record.get("restoration", {})
        verification = restoration.get("verification") if isinstance(restoration, dict) else None
        safe_verification = self._safe_verification(verification) if isinstance(verification, dict) else None
        await self.service.system.dispatcher.emit(
            event_name,
            {
                "event_key": f"{event_name}:{record.get('operation_id', 'none')}:{record.get('updated_at', self.clock())}",
                "occurred_at": record.get("updated_at", self.clock()),
                "severity": "warning" if event_name.endswith(("expired", "recovery_required")) else "info",
                "operation_id": record.get("operation_id"),
                "session_id": record.get("session_id"),
                "owner": record.get("operator"),
                "state": record.get("state"),
                "recovery_reason": record.get("recovery_reason"),
                "miner_stopped_by_coordinator": record.get("miner_stopped_by_coordinator", False),
                "restoration_verification": safe_verification,
            },
        )
