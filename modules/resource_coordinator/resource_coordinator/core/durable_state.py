"""
Durable state persistence, atomic serialization, and PID reconciliation for crash recovery.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .leases import LeaseManager
from .processes import ProcessLifecycleOwner

logger = logging.getLogger(__name__)


class ReconciliationOutcome(str, Enum):
    """The outcome of verifying a persisted process identity against the live OS process table."""

    VERIFIED_RUNNING = "verified_running"  # PID exists and creation time matches
    PID_RECYCLED = "pid_recycled"  # PID exists in OS, but creation time differs (different process!)
    NOT_RUNNING = "not_running"  # PID does not exist in OS process table
    ACCESS_DENIED = "access_denied"  # Insufficient permissions to inspect PID


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
        return cls(
            name=data["name"],
            pid=data.get("pid"),
            create_time=data.get("create_time"),
            lifecycle_owner=data.get(
                "lifecycle_owner", ProcessLifecycleOwner.UNMANAGED.value
            ),
            was_stopped_by_coordinator=bool(
                data.get("was_stopped_by_coordinator", False)
            ),
            last_stopped_at=data.get("last_stopped_at"),
            last_started_at=data.get("last_started_at"),
        )


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
        procs = {}
        for k, v in data.get("processes", {}).items():
            procs[k] = PersistedProcess.from_dict(v)
        return cls(
            version=data.get("version", "1.0"),
            updated_at=data.get("updated_at", time.time()),
            inhibitions=dict(data.get("inhibitions", {})),
            processes=procs,
        )


def reconcile_pid(
    persisted_pid: Optional[int],
    persisted_create_time: Optional[float],
    query_fn: Callable[[int], Optional[float]],
    create_time_tolerance_seconds: float = 1.0,
) -> ReconciliationOutcome:
    """
    Safely reconcile a persisted PID against the live OS process table.

    Uses a pluggable `query_fn(pid) -> Optional[create_time]` for deterministic testing
    without touching the real OS process table.
    """
    if persisted_pid is None or persisted_create_time is None:
        return ReconciliationOutcome.NOT_RUNNING

    actual_create_time = query_fn(persisted_pid)
    if actual_create_time is None:
        return ReconciliationOutcome.NOT_RUNNING

    if abs(actual_create_time - persisted_create_time) <= create_time_tolerance_seconds:
        return ReconciliationOutcome.VERIFIED_RUNNING
    else:
        logger.warning(
            "PID recycling detected! Persisted PID %d has create_time %.3f, but current process has %.3f",
            persisted_pid,
            persisted_create_time,
            actual_create_time,
        )
        return ReconciliationOutcome.PID_RECYCLED


class StateCodec:
    """Atomic file persistence and recovery codec for CoordinatorState."""

    @staticmethod
    def serialize(state: CoordinatorState) -> str:
        """Serialize CoordinatorState to formatted JSON string."""
        return json.dumps(state.to_dict(), indent=2, sort_keys=True)

    @staticmethod
    def deserialize(json_str: str) -> CoordinatorState:
        """Deserialize JSON string into CoordinatorState."""
        data = json.loads(json_str)
        return CoordinatorState.from_dict(data)

    @classmethod
    def save_atomic(cls, state: CoordinatorState, target_path: Path | str) -> None:
        """
        Atomically write state to disk via sibling temporary file and replacement.

        Guarantees that state is never partially written or corrupted by sudden crash.
        """
        path = Path(target_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        payload = cls.serialize(state).encode("utf-8")
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
        """Load state from file, returning clean empty state if file does not exist."""
        path = Path(target_path)
        if not path.exists():
            return CoordinatorState()

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            return cls.deserialize(content)
        except Exception as e:
            logger.error(
                "Failed to load durable state from '%s': %s; falling back to clean state",
                path,
                e,
            )
            return CoordinatorState()

    @classmethod
    async def restore_into_leases(
        cls, state: CoordinatorState, lease_manager: LeaseManager
    ) -> int:
        """
        Restore persisted restart inhibitions into an active LeaseManager.

        Returns the number of restored inhibitions.
        """
        count = 0
        for resource, data in state.inhibitions.items():
            await lease_manager.inhibit_restart(
                resource=resource,
                reason=data.get("reason", "restored_from_durable_state"),
                holder_id=data.get("holder_id", "persisted_holder"),
                details=data.get("details", {}),
            )
            count += 1
        return count
