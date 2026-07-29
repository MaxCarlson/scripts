"""Shared execution and run-state models for the merged backup engine."""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional

UTC = timezone.utc


def utc_now() -> datetime:
    """Return an aware UTC timestamp."""

    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Normalize an aware or naive timestamp to UTC."""

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def datetime_to_text(value: Optional[datetime]) -> Optional[str]:
    """Serialize an optional datetime as an ISO-8601 UTC string."""

    if value is None:
        return None
    return ensure_utc(value).isoformat()


def datetime_from_text(value: Optional[str]) -> Optional[datetime]:
    """Parse an optional ISO-8601 timestamp."""

    if not value:
        return None
    return ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


class ExecutionMode(str, Enum):
    """How a command should be handled by the execution boundary."""

    RUN = "run"
    DRY_RUN = "dry-run"
    PREVIEW = "preview"


class RunState(str, Enum):
    """Persisted lifecycle state for a backup attempt."""

    QUEUED = "queued"
    WAITING = "waiting"
    SKIPPED = "skipped"
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"
    INTERRUPTED = "interrupted"
    DRY_RUN = "dry-run"


TERMINAL_RUN_STATES = frozenset(
    {
        RunState.SKIPPED,
        RunState.SUCCESS,
        RunState.FAILURE,
        RunState.INTERRUPTED,
        RunState.DRY_RUN,
    }
)

_ALLOWED_TRANSITIONS = {
    RunState.QUEUED: {
        RunState.WAITING,
        RunState.SKIPPED,
        RunState.RUNNING,
        RunState.FAILURE,
        RunState.INTERRUPTED,
        RunState.DRY_RUN,
    },
    RunState.WAITING: {
        RunState.SKIPPED,
        RunState.RUNNING,
        RunState.FAILURE,
        RunState.INTERRUPTED,
        RunState.DRY_RUN,
    },
    RunState.RUNNING: {
        RunState.SUCCESS,
        RunState.FAILURE,
        RunState.INTERRUPTED,
        RunState.DRY_RUN,
    },
    RunState.SKIPPED: set(),
    RunState.SUCCESS: set(),
    RunState.FAILURE: set(),
    RunState.INTERRUPTED: set(),
    RunState.DRY_RUN: set(),
}


class InvalidRunTransition(ValueError):
    """Raised when a persisted run is moved through an invalid lifecycle edge."""


@dataclass
class RunRecord:
    """Structured state for one backup attempt."""

    run_id: str
    profile: str
    backup_set: str
    state: RunState
    created_utc: datetime
    started_utc: Optional[datetime] = None
    finished_utc: Optional[datetime] = None
    exit_code: Optional[int] = None
    reason: Optional[str] = None
    command: List[str] = field(default_factory=list)
    redacted_command: Optional[str] = None
    snapshot_id: Optional[str] = None
    pid: Optional[int] = None
    process_start_time: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        profile: str,
        backup_set: str,
        state: RunState = RunState.QUEUED,
        now: Optional[datetime] = None,
        run_id: Optional[str] = None,
    ) -> "RunRecord":
        """Create a new run record with a stable UUID identifier."""

        return cls(
            run_id=run_id or uuid.uuid4().hex,
            profile=profile,
            backup_set=backup_set,
            state=state,
            created_utc=ensure_utc(now or utc_now()),
        )

    @property
    def is_terminal(self) -> bool:
        """Whether the run has reached a terminal state."""

        return self.state in TERMINAL_RUN_STATES

    def transition(
        self,
        state: RunState,
        *,
        now: Optional[datetime] = None,
        exit_code: Optional[int] = None,
        reason: Optional[str] = None,
        snapshot_id: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> "RunRecord":
        """Return a validated copy in the requested lifecycle state."""

        if state == self.state:
            raise InvalidRunTransition(
                "Run is already in state '{0}'.".format(self.state.value)
            )

        allowed = _ALLOWED_TRANSITIONS[self.state]
        if state not in allowed:
            raise InvalidRunTransition(
                "Cannot transition run from '{0}' to '{1}'.".format(
                    self.state.value,
                    state.value,
                )
            )

        transition_time = ensure_utc(now or utc_now())
        started_utc = self.started_utc
        finished_utc = self.finished_utc

        if state == RunState.RUNNING and started_utc is None:
            started_utc = transition_time
        if state in TERMINAL_RUN_STATES:
            finished_utc = transition_time

        merged_metadata = copy.deepcopy(self.metadata)
        if metadata:
            merged_metadata.update(copy.deepcopy(dict(metadata)))

        return replace(
            self,
            state=state,
            started_utc=started_utc,
            finished_utc=finished_utc,
            exit_code=exit_code,
            reason=reason if reason is not None else self.reason,
            snapshot_id=snapshot_id if snapshot_id is not None else self.snapshot_id,
            metadata=merged_metadata,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the run to a JSON-compatible mapping."""

        return {
            "schema_version": 1,
            "run_id": self.run_id,
            "profile": self.profile,
            "backup_set": self.backup_set,
            "state": self.state.value,
            "created_utc": datetime_to_text(self.created_utc),
            "started_utc": datetime_to_text(self.started_utc),
            "finished_utc": datetime_to_text(self.finished_utc),
            "exit_code": self.exit_code,
            "reason": self.reason,
            "command": list(self.command),
            "redacted_command": self.redacted_command,
            "snapshot_id": self.snapshot_id,
            "pid": self.pid,
            "process_start_time": self.process_start_time,
            "metadata": copy.deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RunRecord":
        """Deserialize a run record from persisted JSON data."""

        created_utc = datetime_from_text(payload.get("created_utc"))
        if created_utc is None:
            raise ValueError("Run record is missing created_utc.")

        return cls(
            run_id=str(payload["run_id"]),
            profile=str(payload.get("profile", "default")),
            backup_set=str(payload.get("backup_set", "default")),
            state=RunState(str(payload["state"])),
            created_utc=created_utc,
            started_utc=datetime_from_text(payload.get("started_utc")),
            finished_utc=datetime_from_text(payload.get("finished_utc")),
            exit_code=(
                None
                if payload.get("exit_code") is None
                else int(payload["exit_code"])
            ),
            reason=(
                None if payload.get("reason") is None else str(payload["reason"])
            ),
            command=[str(value) for value in payload.get("command", [])],
            redacted_command=(
                None
                if payload.get("redacted_command") is None
                else str(payload["redacted_command"])
            ),
            snapshot_id=(
                None
                if payload.get("snapshot_id") is None
                else str(payload["snapshot_id"])
            ),
            pid=None if payload.get("pid") is None else int(payload["pid"]),
            process_start_time=(
                None
                if payload.get("process_start_time") is None
                else float(payload["process_start_time"])
            ),
            metadata=copy.deepcopy(dict(payload.get("metadata", {}))),
        )
