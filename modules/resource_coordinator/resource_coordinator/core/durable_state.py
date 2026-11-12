"""
Durable state persistence, atomic serialization, and PID reconciliation for crash recovery.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import psutil

from .leases import LeaseManager
from .processes import ProcessLifecycleOwner

logger = logging.getLogger(__name__)


class ReconciliationOutcome(str, Enum):
    """The outcome of verifying a persisted process identity against the live OS process table."""

    VERIFIED_RUNNING = "verified_running"  # PID exists and creation time matches
    PID_RECYCLED = "pid_recycled"  # PID exists in OS, but creation time differs (different process!)
    NOT_RUNNING = "not_running"  # PID does not exist in OS process table
    UNVERIFIABLE = "unverifiable"  # Missing, invalid or unreadable identity is not evidence of absence
    ACCESS_DENIED = "access_denied"  # Insufficient permissions to inspect PID


class RequestPhase(str, Enum):
    """Lifecycle phase of an in-flight or completed inference request."""

    RESERVED = "reserved"  # Lease reserved, not yet forwarded upstream
    POSSIBLY_FORWARDED = "possibly_forwarded"  # Bytes committed to upstream dispatch
    TERMINAL_VERIFIED = "terminal_verified"  # Stream completed with [DONE] or non-stream completed
    UNCERTAIN = "uncertain"  # Stream ended abruptly, network failure, or error
    OPERATOR_RESOLVED = "operator_resolved"  # Explicitly overridden by authenticated operator recovery


def _valid_time(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _mapping(value: Any, label: str) -> Dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(k, str) or not k for k in value):
        raise ValueError(f"{label} must be a mapping with nonempty string keys")
    return value


def _remove_inhibition_holder(state: CoordinatorState, resource: str, holder_id: str) -> bool:
    """Remove one exact inhibition owner, promoting another unresolved owner if present."""
    current = state.inhibitions.get(resource)
    if current is None:
        return False
    current = dict(current)
    details = dict(current.get("details", {}))
    additional = list(details.get("additional_uncertain_holders", []))
    if current.get("holder_id") == holder_id:
        if not additional:
            state.inhibitions.pop(resource, None)
            return True
        promoted = dict(additional.pop(0))
        promoted_details = dict(promoted.get("details", {}))
        remaining = list(promoted_details.get("additional_uncertain_holders", [])) + additional
        if remaining:
            promoted_details["additional_uncertain_holders"] = remaining
        else:
            promoted_details.pop("additional_uncertain_holders", None)
        promoted["details"] = promoted_details
        state.inhibitions[resource] = promoted
        return True
    retained = [item for item in additional if item.get("holder_id") != holder_id]
    if len(retained) == len(additional):
        return False
    if retained:
        details["additional_uncertain_holders"] = retained
    else:
        details.pop("additional_uncertain_holders", None)
    current["details"] = details
    state.inhibitions[resource] = current
    return True


@dataclass
class PersistedRequest:
    """Persistent snapshot of an inference request across coordinator restarts."""

    request_id: str
    resource: str
    phase: str
    model: Optional[str] = None
    path: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PersistedRequest:
        data = _mapping(data, "request")
        allowed = set(cls.__dataclass_fields__)
        if set(data) - allowed:
            raise ValueError("Unknown request fields")
        for req_field in ("request_id", "resource", "phase"):
            if not isinstance(data.get(req_field), str) or not data[req_field]:
                raise ValueError(f"Persisted request requires non-empty {req_field}")
        RequestPhase(data["phase"])
        for time_field in ("created_at", "updated_at"):
            if data.get(time_field) is not None and not _valid_time(data[time_field]):
                raise ValueError(f"Invalid timestamp {time_field}")
        if "details" in data:
            _mapping(data["details"], "request details")
        return cls(**data)


@dataclass
class PersistedProcess:
    """Persistent snapshot of a managed process's state across restarts."""

    name: str
    pid: Optional[int] = None
    create_time: Optional[float] = None
    lifecycle_owner: str = ProcessLifecycleOwner.UNMANAGED.value
    was_stopped_by_coordinator: bool = False
    is_manual_override: bool = False
    manual_override_until: Optional[float] = None
    last_stopped_at: Optional[float] = None
    last_started_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PersistedProcess:
        data = _mapping(data, "process")
        allowed = set(cls.__dataclass_fields__)
        if set(data) - allowed or not isinstance(data.get("name"), str) or not data["name"]:
            raise ValueError("Unknown process fields or missing process name")
        if type(data.get("was_stopped_by_coordinator", False)) is not bool:
            raise ValueError("Restart ownership must be a boolean")
        if type(data.get("is_manual_override", False)) is not bool:
            raise ValueError("Manual override must be a boolean")
        hold_until = data.get("manual_override_until")
        if hold_until is not None and not _valid_time(hold_until):
            raise ValueError("Invalid manual override deadline")
        pid, created = data.get("pid"), data.get("create_time")
        if pid is not None and (type(pid) is not int or pid <= 0 or not _valid_time(created)):
            raise ValueError("A persisted PID requires a valid exact creation time")
        for key in ("create_time", "last_stopped_at", "last_started_at"):
            if data.get(key) is not None and not _valid_time(data[key]):
                raise ValueError(f"Invalid {key}")
        owner = data.get("lifecycle_owner", ProcessLifecycleOwner.UNMANAGED.value)
        ProcessLifecycleOwner(owner)
        return cls(**data)


@dataclass
class CoordinatorState:
    """The aggregate durable state of the Resource Coordinator."""

    version: str = "1.0"
    updated_at: float = field(default_factory=time.time)
    inhibitions: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    processes: Dict[str, PersistedProcess] = field(default_factory=dict)
    requests: Dict[str, PersistedRequest] = field(default_factory=dict)
    gaming_mode: Dict[str, Any] = field(default_factory=lambda: {"state": "inactive"})
    gpu_idle_condition: Dict[str, Any] = field(default_factory=dict)
    maintenance: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {
            "version": self.version,
            "updated_at": self.updated_at,
            "inhibitions": dict(self.inhibitions),
            "processes": {k: v.to_dict() for k, v in self.processes.items()},
        }
        if self.requests:
            res["requests"] = {k: v.to_dict() for k, v in self.requests.items()}
        if self.gaming_mode.get("state", "inactive") != "inactive":
            res["gaming_mode"] = dict(self.gaming_mode)
        if self.gpu_idle_condition:
            res["gpu_idle_condition"] = dict(self.gpu_idle_condition)
        if self.maintenance:
            res["maintenance"] = dict(self.maintenance)
        return res

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CoordinatorState:
        data = _mapping(data, "state")
        required = {"version", "updated_at", "inhibitions", "processes"}
        allowed = required | {"requests", "gaming_mode", "gpu_idle_condition", "maintenance"}
        if not (required.issubset(set(data)) and set(data).issubset(allowed)):
            raise ValueError("Incomplete or unsupported durable state schema")
        if data["version"] != "1.0" or not _valid_time(data["updated_at"]):
            raise ValueError("Incomplete or unsupported durable state schema")
        holds = _mapping(data["inhibitions"], "inhibitions")
        for resource, raw in holds.items():
            hold = _mapping(raw, "inhibition")
            if hold.get("resource", resource) != resource:
                raise ValueError("Inhibition resource identity mismatch")
            for key in ("reason", "holder_id"):
                if not isinstance(hold.get(key), str) or not hold[key]:
                    raise ValueError(f"Inhibition requires {key}")
            _mapping(hold.get("details", {}), "inhibition details")
            if "inhibited_at" in hold and not _valid_time(hold["inhibited_at"]):
                raise ValueError("Invalid inhibition timestamp")
        procs = {}
        for key, raw in _mapping(data["processes"], "processes").items():
            process = PersistedProcess.from_dict(raw)
            if process.name != key:
                raise ValueError("Persisted process key/name mismatch")
            procs[key] = process
        reqs = {}
        if "requests" in data:
            for key, raw in _mapping(data["requests"], "requests").items():
                request = PersistedRequest.from_dict(raw)
                if request.request_id != key:
                    raise ValueError("Persisted request key/request_id mismatch")
                reqs[key] = request
        gaming = data.get("gaming_mode", {"state": "inactive"})
        if not isinstance(gaming, dict) or gaming.get("state") not in {
            "inactive", "stopping", "active", "restoring", "failed"
        }:
            raise ValueError("Invalid gaming mode state")
        if gaming.get("state") != "inactive":
            models = gaming.get("models")
            if not isinstance(models, list) or type(gaming.get("miner_was_running")) is not bool:
                raise ValueError("Invalid durable gaming mode snapshot")
            if type(gaming.get("miner_override_before", False)) is not bool:
                raise ValueError("Invalid prior miner override in gaming mode snapshot")
            if gaming.get("miner_override_until_before") is not None and not _valid_time(
                gaming["miner_override_until_before"]
            ):
                raise ValueError("Invalid prior miner override deadline in gaming mode snapshot")
            for model in models:
                if (not isinstance(model, dict) or not isinstance(model.get("model"), str)
                        or not model["model"] or not isinstance(model.get("config", {}), dict)):
                    raise ValueError("Invalid model in durable gaming mode snapshot")
        gpu_condition = data.get("gpu_idle_condition", {})
        if not isinstance(gpu_condition, dict):
            raise ValueError("Invalid GPU-idle condition")
        if gpu_condition:
            threshold, window = gpu_condition.get("threshold_pct"), gpu_condition.get("window_seconds")
            samples = gpu_condition.get("samples")
            if (not _valid_time(threshold) or threshold > 100 or not _valid_time(window) or window <= 0
                    or not isinstance(samples, list) or len(samples) > 4000):
                raise ValueError("Invalid persisted GPU-idle condition settings")
            for sample in samples:
                if (not isinstance(sample, dict) or not _valid_time(sample.get("at"))
                        or not _valid_time(sample.get("utilization_pct")) or sample["utilization_pct"] > 100):
                    raise ValueError("Invalid persisted GPU-idle sample")
        maintenance = data.get("maintenance", {})
        if not isinstance(maintenance, dict):
            raise ValueError("Invalid maintenance record")
        if maintenance:
            allowed_maintenance = {
                "state", "operation_id", "session_id", "operator", "reason", "requested_at", "updated_at",
                "lease_seconds", "expires_at", "last_renewed_at", "miner_was_running",
                "miner_stopped_by_coordinator", "manual_override_before", "restoration", "recovery_reason",
                "last_disposition", "restart_not_before",
                "completed_operations",
                "tuning_scope", "gpu_baseline", "registered_processes",
            }
            if set(maintenance) - allowed_maintenance:
                raise ValueError("Unknown maintenance record fields")
            if maintenance.get("state") not in {
                "idle", "acquiring", "active", "releasing", "recovery_required"
            }:
                raise ValueError("Invalid maintenance state")
            if maintenance["state"] != "idle":
                for key in ("operation_id", "operator", "reason"):
                    if not isinstance(maintenance.get(key), str) or not maintenance[key]:
                        raise ValueError(f"Maintenance record requires {key}")
                for key in ("requested_at", "updated_at"):
                    if not _valid_time(maintenance.get(key)):
                        raise ValueError(f"Invalid maintenance timestamp {key}")
                for key in ("miner_was_running", "miner_stopped_by_coordinator", "manual_override_before"):
                    if type(maintenance.get(key, False)) is not bool:
                        raise ValueError(f"Invalid maintenance flag {key}")
            if maintenance.get("state") == "active":
                if not isinstance(maintenance.get("session_id"), str) or not maintenance["session_id"]:
                    raise ValueError("Active maintenance requires session_id")
                if not _valid_time(maintenance.get("expires_at")):
                    raise ValueError("Active maintenance requires a valid expiration")
            if "lease_seconds" in maintenance and (
                type(maintenance["lease_seconds"]) is not int or not 30 <= maintenance["lease_seconds"] <= 3600
            ):
                raise ValueError("Invalid maintenance lease duration")
            for key in ("expires_at", "last_renewed_at", "restart_not_before"):
                if maintenance.get(key) is not None and not _valid_time(maintenance[key]):
                    raise ValueError(f"Invalid maintenance timestamp {key}")
            for key in ("restoration", "last_disposition"):
                if key in maintenance:
                    _mapping(maintenance[key], f"maintenance {key}")
            scope = maintenance.get("tuning_scope")
            if scope is not None:
                if (
                    not isinstance(scope, dict)
                    or set(scope) != {"mode", "dimensions"}
                    or scope.get("mode") not in {"power", "offsets", "power_offsets", "fixed_clocks"}
                    or not isinstance(scope.get("dimensions"), list)
                    or len(scope["dimensions"]) > 3
                    or any(not isinstance(item, str) for item in scope["dimensions"])
                ):
                    raise ValueError("Invalid maintenance tuning scope")
            baseline = maintenance.get("gpu_baseline")
            if baseline is not None:
                if (
                    not isinstance(baseline, dict)
                    or set(baseline) != {
                        "schema_version", "operation_id", "observed_at", "gpu_uuid", "pci_bus_id",
                        "driver_version", "values", "gpu_processes",
                    }
                    or baseline.get("schema_version") != 1
                    or not _valid_time(baseline.get("observed_at"))
                    or not isinstance(baseline.get("operation_id"), str)
                    or not baseline.get("operation_id")
                    or not isinstance(baseline.get("gpu_uuid"), str)
                    or not baseline.get("gpu_uuid")
                    or not isinstance(baseline.get("pci_bus_id"), str)
                    or not isinstance(baseline.get("driver_version"), str)
                    or not isinstance(baseline.get("values"), dict)
                    or len(baseline["values"]) > 3
                ):
                    raise ValueError("Invalid maintenance GPU baseline")
                for dimension, observation in baseline["values"].items():
                    if dimension not in {
                        "power_limit_mw", "graphics_clock_offset_mhz", "memory_clock_offset_mhz"
                    } or not isinstance(observation, dict) or set(observation) - {"status", "value", "reason"}:
                        raise ValueError("Invalid maintenance GPU baseline setting")
                    if observation.get("status") == "available":
                        if type(observation.get("value")) not in (int, float) or not math.isfinite(
                            float(observation["value"])
                        ):
                            raise ValueError("Invalid maintenance GPU baseline value")
                    elif observation.get("status") != "unsupported":
                        raise ValueError("Invalid maintenance GPU baseline capability")
                attribution = baseline.get("gpu_processes")
                if not isinstance(attribution, dict) or attribution.get("status") != "available" \
                        or not isinstance(attribution.get("identities"), list) \
                        or len(attribution["identities"]) > 256:
                    raise ValueError("Invalid maintenance GPU-process baseline")
                for process in attribution["identities"]:
                    if (
                        not isinstance(process, dict)
                        or set(process) != {"pid", "create_time", "executable_path", "executable_name"}
                        or type(process.get("pid")) is not int or process["pid"] <= 0
                        or not _valid_time(process.get("create_time"))
                        or not isinstance(process.get("executable_path"), str)
                        or not process["executable_path"] or len(process["executable_path"]) > 2048
                        or not isinstance(process.get("executable_name"), str)
                        or not process["executable_name"] or len(process["executable_name"]) > 256
                    ):
                        raise ValueError("Invalid maintenance GPU-process baseline identity")
            registered = maintenance.get("registered_processes", [])
            if not isinstance(registered, list) or len(registered) > 64:
                raise ValueError("Invalid maintenance process registration list")
            for process in registered:
                if (
                    not isinstance(process, dict)
                    or set(process) != {"pid", "create_time", "executable_path", "executable_name"}
                    or type(process.get("pid")) is not int or process["pid"] <= 0
                    or not _valid_time(process.get("create_time"))
                    or not isinstance(process.get("executable_path"), str)
                    or not process["executable_path"] or len(process["executable_path"]) > 2048
                    or not isinstance(process.get("executable_name"), str)
                    or not process["executable_name"] or len(process["executable_name"]) > 256
                ):
                    raise ValueError("Invalid maintenance process identity")
            completed_operations = maintenance.get("completed_operations", [])
            if not isinstance(completed_operations, list) or len(completed_operations) > 64:
                raise ValueError("Invalid maintenance completed-operation history")
            for disposition in completed_operations:
                if not isinstance(disposition, dict) or any(
                    not isinstance(disposition.get(key), str) or not disposition[key]
                    for key in ("operation_id", "operator")
                ):
                    raise ValueError("Completed maintenance disposition requires operation and operator")
                if disposition.get("session_id") is not None and (
                    not isinstance(disposition["session_id"], str) or not disposition["session_id"]
                ):
                    raise ValueError("Completed maintenance session_id must be a nonempty string when present")
                if not _valid_time(disposition.get("released_at")):
                    raise ValueError("Completed maintenance disposition requires released_at")
                if any(type(disposition.get(key)) is not bool for key in (
                    "resume_miner_requested", "miner_restart_eligible"
                )):
                    raise ValueError("Completed maintenance disposition requires boolean release flags")
                if not isinstance(disposition.get("restoration", {}), dict):
                    raise ValueError("Completed maintenance restoration disposition must be a mapping")
            if maintenance.get("recovery_reason") is not None and not isinstance(maintenance["recovery_reason"], str):
                raise ValueError("Invalid maintenance recovery reason")
        return cls(
            version=data["version"],
            updated_at=data["updated_at"],
            inhibitions=dict(holds),
            processes=procs,
            requests=reqs,
            gaming_mode=dict(gaming),
            gpu_idle_condition=dict(gpu_condition),
            maintenance=dict(maintenance),
        )


def reconcile_pid(
    persisted_pid: Optional[int],
    persisted_create_time: Optional[float],
    query_fn: Callable[[int], Optional[float]],
    create_time_tolerance_seconds: float = 0.0,
) -> ReconciliationOutcome:
    """
    Safely reconcile a persisted PID against the live OS process table.

    Uses a pluggable `query_fn(pid) -> Optional[create_time]` for deterministic testing
    without touching the real OS process table. The query may return None only
    for confirmed absence, never for access denial or an unknown execution state.
    Matching time establishes a candidate identity, not permission to control it;
    executable, boot/instance context and lifecycle authority still require verification.
    """
    if create_time_tolerance_seconds != 0.0:
        raise ValueError("Process identity requires exact creation time; tolerance must be zero")
    if type(persisted_pid) is not int or persisted_pid <= 0 or not _valid_time(persisted_create_time):
        return ReconciliationOutcome.UNVERIFIABLE
    try:
        actual_create_time = query_fn(persisted_pid)
    except psutil.AccessDenied:
        return ReconciliationOutcome.ACCESS_DENIED
    except psutil.NoSuchProcess:
        return ReconciliationOutcome.NOT_RUNNING
    except (psutil.Error, OSError):
        return ReconciliationOutcome.UNVERIFIABLE
    if actual_create_time is None:
        return ReconciliationOutcome.NOT_RUNNING
    if not _valid_time(actual_create_time):
        return ReconciliationOutcome.UNVERIFIABLE
    if actual_create_time == persisted_create_time:
        return ReconciliationOutcome.VERIFIED_RUNNING
    logger.warning("PID %d creation time differs; persisted identity is stale", persisted_pid)
    return ReconciliationOutcome.PID_RECYCLED


class StateCodec:
    """Atomic file persistence and recovery codec for CoordinatorState."""

    @staticmethod
    def serialize(state: CoordinatorState) -> str:
        """Serialize CoordinatorState to formatted JSON string."""
        validated = CoordinatorState.from_dict(state.to_dict())
        return json.dumps(validated.to_dict(), indent=2, sort_keys=True, allow_nan=False)

    @staticmethod
    def deserialize(json_str: str) -> CoordinatorState:
        """Deserialize JSON string into CoordinatorState."""

        def unique_object(pairs: list[tuple[str, Any]]) -> Dict[str, Any]:
            result: Dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"Duplicate durable state key: {key}")
                result[key] = value
            return result

        data = json.loads(json_str, object_pairs_hook=unique_object)
        return CoordinatorState.from_dict(data)

    @classmethod
    def save_atomic(cls, state: CoordinatorState, target_path: Path | str) -> None:
        """
        Atomically write state to disk via sibling temporary file and replacement.

        Fsync the temporary file before replacement. This is not a crash-recovery
        transaction or a guarantee of directory/rename durability after power loss.
        """
        path = Path(target_path)
        payload = cls.serialize(state).encode("utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f"{path.name}.tmp.{uuid.uuid4().hex}")

        try:
            with open(tmp_path, "wb") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    @classmethod
    def initialize(
        cls,
        target_path: Path | str,
        force: bool = False,
    ) -> CoordinatorState:
        """
        Explicitly initialize a new, clean durable state journal.

        Fails if the journal already exists unless force=True.
        """
        path = Path(target_path)
        if path.exists() and not force:
            raise FileExistsError(
                f"Cannot initialize durable state journal at '{path}': file already exists"
            )
        state = CoordinatorState(
            version="1.0",
            updated_at=time.time(),
            inhibitions={},
            processes={},
            requests={},
        )
        cls.save_atomic(state, path)
        logger.info("Initialized new durable state journal at '%s'", path)
        return state

    @classmethod
    def load(cls, target_path: Path | str) -> CoordinatorState:
        """Load validated state. Missing, unreadable or corrupt state must block recovery.

        First-boot initialization requires a separate explicit caller decision;
        a missing file cannot distinguish first boot from loss of prior holds.
        """
        return cls.deserialize(Path(target_path).read_text(encoding="utf-8"))

    @classmethod
    def record_maintenance(
        cls,
        target_path: Path | str,
        maintenance: Dict[str, Any],
        *,
        set_inhibition: Optional[Dict[str, Any]] = None,
        clear_inhibition_holder: Optional[str] = None,
    ) -> CoordinatorState:
        """Atomically update maintenance metadata and its matching GPU hold."""
        target = Path(target_path)
        state = cls.load(target)
        state.maintenance = dict(maintenance)
        if set_inhibition is not None:
            resource = set_inhibition.get("resource")
            holder_id = set_inhibition.get("holder_id")
            if not isinstance(resource, str) or not resource or not isinstance(holder_id, str) or not holder_id:
                raise ValueError("Maintenance inhibition requires resource and holder identity")
            current = state.inhibitions.get(resource)
            if current and current.get("holder_id") != holder_id:
                current = dict(current)
                current_details = dict(current.get("details", {}))
                additional = list(current_details.get("additional_uncertain_holders", []))
                if not any(item.get("holder_id") == holder_id for item in additional):
                    additional.append(dict(set_inhibition))
                current_details["additional_uncertain_holders"] = additional
                current["details"] = current_details
                state.inhibitions[resource] = current
                set_inhibition = None
            if set_inhibition is not None and current:
                current_details = dict(current.get("details", {}))
                new_details = dict(set_inhibition.get("details", {}))
                additional = list(current_details.get("additional_uncertain_holders", []))
                if additional:
                    new_details["additional_uncertain_holders"] = additional
                set_inhibition = {**set_inhibition, "details": new_details}
            if set_inhibition is not None:
                state.inhibitions[resource] = dict(set_inhibition)
        if clear_inhibition_holder is not None:
            if not _remove_inhibition_holder(state, "gpu.inference", clear_inhibition_holder):
                raise ValueError("Maintenance inhibition identity changed before release")
        state.updated_at = time.time()
        cls.save_atomic(state, target)
        return state

    @classmethod
    def mark_maintenance_recovery_required(cls, target_path: Path | str) -> Optional[CoordinatorState]:
        """Revoke process-local ownership on restart and durably preserve the hold."""
        target = Path(target_path)
        state = cls.load(target)
        record = dict(state.maintenance)
        if not record or record.get("state", "idle") == "idle":
            return state
        now = time.time()
        record["state"] = "recovery_required"
        record["updated_at"] = now
        record["recovery_reason"] = "Coordinator restarted; the prior fencing token was revoked"
        state.maintenance = record
        holder_id = f"maintenance:{record['operation_id']}"
        existing = state.inhibitions.get("gpu.inference")
        maintenance_hold = {
                "resource": "gpu.inference",
                "reason": "maintenance session interrupted by Coordinator restart",
                "holder_id": holder_id,
                "inhibited_at": now,
                "details": {"maintenance_operation_id": record["operation_id"]},
        }
        if existing is None:
            state.inhibitions["gpu.inference"] = maintenance_hold
        elif existing.get("holder_id") != holder_id:
            existing = dict(existing)
            details = dict(existing.get("details", {}))
            additional = list(details.get("additional_uncertain_holders", []))
            if not any(item.get("holder_id") == holder_id for item in additional):
                additional.append(maintenance_hold)
            details["additional_uncertain_holders"] = additional
            existing["details"] = details
            state.inhibitions["gpu.inference"] = existing
        state.updated_at = now
        cls.save_atomic(state, target)
        return state

    @classmethod
    async def restore_into_leases(cls, state: CoordinatorState, lease_manager: LeaseManager) -> int:
        """
        Restore persisted restart inhibitions into an active LeaseManager.

        Returns the number of restored inhibitions.
        """
        # Validate the entire snapshot before exposing any partial restoration.
        validated = CoordinatorState.from_dict(state.to_dict())
        count = 0
        for resource, data in validated.inhibitions.items():
            await lease_manager.inhibit_restart(
                resource=resource,
                reason=data.get("reason", "restored_from_durable_state"),
                holder_id=data.get("holder_id", "persisted_holder"),
                details={
                    **data.get("details", {}),
                    "restored_inhibited_at": data.get("inhibited_at"),
                    "snapshot_updated_at": validated.updated_at,
                },
            )
            count += 1
        return count

    @classmethod
    def record_request_phase(
        cls,
        target_path: Path | str,
        request_id: str,
        resource: str,
        phase: RequestPhase | str,
        model: Optional[str] = None,
        path: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> CoordinatorState:
        """
        Atomically record or update a request's lifecycle phase in the durable state journal.
        Fails closed if writing to disk fails.
        """
        target = Path(target_path)
        phase_str = phase.value if isinstance(phase, RequestPhase) else str(phase)
        now = time.time()
        state = cls.load(target)

        existing = state.requests.get(request_id)
        if existing:
            existing.phase = phase_str
            existing.updated_at = now
            if model:
                existing.model = model
            if path:
                existing.path = path
            if details:
                existing.details.update(details)
        else:
            state.requests[request_id] = PersistedRequest(
                request_id=request_id,
                resource=resource,
                phase=phase_str,
                model=model,
                path=path,
                created_at=now,
                updated_at=now,
                details=details or {},
            )
        state.updated_at = now
        cls.save_atomic(state, target)
        return state

    @classmethod
    def record_process_state(
        cls,
        target_path: Path | str,
        name: str,
        pid: Optional[int],
        create_time: Optional[float],
        lifecycle_owner: str,
        was_stopped_by_coordinator: bool,
        is_manual_override: Optional[bool] = None,
        manual_override_until: Optional[float] = None,
    ) -> CoordinatorState:
        target = Path(target_path)
        now = time.time()
        state = cls.load(target)
        proc = state.processes.get(name) or PersistedProcess(name=name)
        proc.pid = pid
        proc.create_time = create_time
        proc.lifecycle_owner = lifecycle_owner
        proc.was_stopped_by_coordinator = was_stopped_by_coordinator
        if is_manual_override is not None:
            proc.is_manual_override = is_manual_override
        proc.manual_override_until = manual_override_until if proc.is_manual_override else None
        if was_stopped_by_coordinator:
            proc.last_stopped_at = now
        elif pid is not None:
            proc.last_started_at = now
        state.processes[name] = proc
        state.updated_at = now
        cls.save_atomic(state, target)
        return state

    @classmethod
    def record_gaming_mode(
        cls,
        target_path: Path | str,
        state_name: str,
        *,
        models: Optional[list[Dict[str, Any]]] = None,
        miner_was_running: Optional[bool] = None,
        miner_override_before: Optional[bool] = None,
        miner_override_until_before: Optional[float] = None,
    ) -> CoordinatorState:
        if state_name not in {"inactive", "stopping", "active", "restoring", "failed"}:
            raise ValueError("Invalid gaming mode state")
        target = Path(target_path)
        state = cls.load(target)
        if state_name == "inactive":
            state.gaming_mode = {"state": "inactive"}
        else:
            previous = state.gaming_mode
            state.gaming_mode = {
                "state": state_name,
                "models": models if models is not None else previous.get("models", []),
                "miner_was_running": (
                    miner_was_running if miner_was_running is not None
                    else previous.get("miner_was_running", False)
                ),
                "miner_override_before": (
                    miner_override_before if miner_override_before is not None
                    else previous.get("miner_override_before", False)
                ),
                "miner_override_until_before": (
                    miner_override_until_before if miner_override_before is not None
                    else previous.get("miner_override_until_before")
                ),
            }
        state.updated_at = time.time()
        cls.save_atomic(state, target)
        return state

    @classmethod
    def record_gpu_idle_condition(
        cls,
        target_path: Path | str,
        *,
        threshold_pct: Optional[float] = None,
        window_seconds: Optional[float] = None,
        samples: Optional[list[Dict[str, float]]] = None,
    ) -> CoordinatorState:
        target = Path(target_path)
        state = cls.load(target)
        if threshold_pct is None or window_seconds is None:
            state.gpu_idle_condition = {}
        else:
            state.gpu_idle_condition = {
                "threshold_pct": float(threshold_pct),
                "window_seconds": float(window_seconds),
                "samples": list(samples or []),
            }
        state.updated_at = time.time()
        cls.save_atomic(state, target)
        return state

    @classmethod
    def record_inhibition(
        cls,
        target_path: Path | str,
        resource: str,
        reason: str,
        holder_id: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> CoordinatorState:
        target = Path(target_path)
        now = time.time()
        state = cls.load(target)
        updated = {
            "resource": resource,
            "reason": reason,
            "holder_id": holder_id,
            "inhibited_at": now,
            "details": details or {},
        }
        existing = state.inhibitions.get(resource)
        if existing and existing.get("holder_id") != holder_id:
            existing = dict(existing)
            existing_details = dict(existing.get("details", {}))
            additional = list(existing_details.get("additional_uncertain_holders", []))
            additional.append(updated)
            existing_details["additional_uncertain_holders"] = additional
            existing["details"] = existing_details
            state.inhibitions[resource] = existing
        else:
            state.inhibitions[resource] = updated
        state.updated_at = now
        cls.save_atomic(state, target)
        return state

    @classmethod
    def clear_inhibition(
        cls,
        target_path: Path | str,
        resource: str,
    ) -> CoordinatorState:
        target = Path(target_path)
        now = time.time()
        state = cls.load(target)
        state.inhibitions.pop(resource, None)
        state.updated_at = now
        cls.save_atomic(state, target)
        return state

    @classmethod
    def resolve_unresolved_requests(
        cls,
        target_path: Path | str,
        resource: str,
        operator: str,
        reason: str,
    ) -> tuple[CoordinatorState, list[str]]:
        """
        Durably resolve in-flight and uncertain requests for a resource upon operator override.
        Transitions unresolved requests to OPERATOR_RESOLVED with attribution metadata and
        clears the resource inhibition.
        """
        target = Path(target_path)
        now = time.time()
        state = cls.load(target)
        resolved_ids: list[str] = []
        UNRESOLVED_PHASES = {
            RequestPhase.RESERVED.value,
            RequestPhase.POSSIBLY_FORWARDED.value,
            RequestPhase.UNCERTAIN.value,
        }
        for req_id, req in list(state.requests.items()):
            if req.resource == resource and req.phase in UNRESOLVED_PHASES:
                req.details["previous_phase"] = req.phase
                req.phase = RequestPhase.OPERATOR_RESOLVED.value
                req.updated_at = now
                req.details["resolved_by"] = f"operator_override:{operator}:{reason}"
                req.details["resolved_at"] = now
                resolved_ids.append(req_id)
        state.inhibitions.pop(resource, None)
        state.updated_at = now
        cls.save_atomic(state, target)
        logger.info(
            "Resolved %d requests and cleared inhibition for resource '%s' (operator=%s, reason=%s)",
            len(resolved_ids),
            resource,
            operator,
            reason,
        )
        return state, resolved_ids


async def reconcile_startup_state(
    state: CoordinatorState,
    lease_manager: LeaseManager,
    supervisors: Optional[Dict[str, Any]] = None,
    query_fn: Optional[Callable[[int], Optional[float]]] = None,
) -> Dict[str, Any]:
    """
    Reconcile loaded durable state during coordinator startup.
    - Restores persisted inhibitions.
    - Replays unresolved requests (reserved, possibly_forwarded, uncertain) into restart inhibitions.
    - Reconciles persisted process identities against live OS process table.
    Returns audit dictionary of actions taken.
    """
    audit: Dict[str, Any] = {
        "restored_inhibitions": [],
        "unresolved_request_holds": [],
        "reconciled_processes": {},
    }
    # 1. Restore prior inhibitions
    for resource, data in state.inhibitions.items():
        await lease_manager.inhibit_restart(
            resource=resource,
            reason=data.get("reason", "restored_from_durable_state"),
            holder_id=data.get("holder_id", "persisted_holder"),
            details={
                **data.get("details", {}),
                "restored_inhibited_at": data.get("inhibited_at"),
                "snapshot_updated_at": state.updated_at,
            },
        )
        audit["restored_inhibitions"].append(resource)

    # 2. Replay unresolved requests
    UNRESOLVED_PHASES = {
        RequestPhase.RESERVED.value,
        RequestPhase.POSSIBLY_FORWARDED.value,
        RequestPhase.UNCERTAIN.value,
    }
    for req_id, req in state.requests.items():
        if req.phase in UNRESOLVED_PHASES:
            logger.warning(
                "Unresolved request %s in phase %s on resource %s; imposing restart inhibition",
                req_id,
                req.phase,
                req.resource,
            )
            await lease_manager.inhibit_restart(
                resource=req.resource,
                reason=f"unresolved_request:{req.phase}",
                holder_id=f"crash_recovery:{req_id}",
                details={
                    "request_id": req.request_id,
                    "phase": req.phase,
                    "model": req.model,
                    "path": req.path,
                    "persisted_at": req.updated_at,
                },
            )
            audit["unresolved_request_holds"].append(
                {"request_id": req_id, "phase": req.phase, "resource": req.resource}
            )

    # 3. Reconcile persisted process table
    if query_fn is None:

        def _default_query(pid: int) -> Optional[float]:
            try:
                p = psutil.Process(pid)
                return p.create_time()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return None

        query_fn = _default_query

    for proc_name, proc in state.processes.items():
        if supervisors and proc_name in supervisors:
            sup = supervisors[proc_name]
            sup.was_stopped_by_coordinator = proc.was_stopped_by_coordinator
            if proc.is_manual_override:
                sup.set_manual_override(True, persist=False, until=proc.manual_override_until)
        outcome = reconcile_pid(proc.pid, proc.create_time, query_fn)
        audit["reconciled_processes"][proc_name] = {
            "pid": proc.pid,
            "outcome": outcome.value,
        }
        if outcome == ReconciliationOutcome.PID_RECYCLED:
            logger.warning(
                "Persisted process %s PID %s recycled by unrelated process; refusing adoption",
                proc_name,
                proc.pid,
            )
        elif outcome == ReconciliationOutcome.NOT_RUNNING:
            logger.info("Persisted process %s PID %s is not running", proc_name, proc.pid)

    return audit

