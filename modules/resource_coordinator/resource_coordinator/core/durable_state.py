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


def _valid_time(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _mapping(value: Any, label: str) -> Dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(k, str) or not k for k in value):
        raise ValueError(f"{label} must be a mapping with nonempty string keys")
    return value


@dataclass
class PersistedProcess:
    """Persistent snapshot of a managed process's state across restarts."""

    name: str
    pid: Optional[int] = None
    create_time: Optional[float] = None
    lifecycle_owner: str = ProcessLifecycleOwner.UNMANAGED.value
    was_stopped_by_coordinator: bool = False
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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "updated_at": self.updated_at,
            "inhibitions": dict(self.inhibitions),
            "processes": {k: v.to_dict() for k, v in self.processes.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CoordinatorState:
        data = _mapping(data, "state")
        required = {"version", "updated_at", "inhibitions", "processes"}
        if set(data) != required or data["version"] != "1.0" or not _valid_time(data["updated_at"]):
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
        return cls(version=data["version"], updated_at=data["updated_at"], inhibitions=dict(holds), processes=procs)


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
    def load(cls, target_path: Path | str) -> CoordinatorState:
        """Load validated state. Missing, unreadable or corrupt state must block recovery.

        First-boot initialization requires a separate explicit caller decision;
        a missing file cannot distinguish first boot from loss of prior holds.
        """
        return cls.deserialize(Path(target_path).read_text(encoding="utf-8"))

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
