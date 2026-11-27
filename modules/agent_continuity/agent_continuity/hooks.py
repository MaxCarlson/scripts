"""Normalized hook event contract for Phase 2 provider shims."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from .identifiers import generate_id, normalize_path_canonical, normalize_repo_identity, now_utc_iso
from .models import EventEnvelope, EventType


class NormalizedHookType(StrEnum):
    """Provider-neutral hook lifecycle event types."""

    SESSION_CREATED = "session.created"
    SESSION_OBSERVED = "session.observed"
    TURN_SUBMITTED = "turn.submitted"
    TURN_COMPLETED = "turn.completed"
    SESSION_ENDED = "session.ended"


@dataclass(slots=True)
class NormalizedHookEvent:
    """Normalized provider hook payload (no raw prompt text retained)."""

    provider: str
    environment_id: str
    native_session_id: str
    native_event_type: str
    normalized_event_type: str
    event_id: str
    event_schema_version: int
    source_timestamp: str | None
    observed_timestamp: str
    source_adapter_version: str
    workflow_marker: str | None = None
    workflow_markers_conflict: list[str] = field(default_factory=list)
    turn_id: str | None = None
    cwd: str | None = None
    transcript_path: str | None = None
    source: str | None = None
    parent_session_id: str | None = None
    surface: str | None = None
    lifecycle_status: str = "active"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalized_hook_to_event_envelope(hook: NormalizedHookEvent) -> EventEnvelope:
    """Convert a NormalizedHookEvent into a durable EventEnvelope for spool persistence."""
    observed = hook.observed_timestamp or now_utc_iso()
    source_ts = hook.source_timestamp or observed
    cwd_canon = normalize_path_canonical(hook.cwd)
    repo_id = normalize_repo_identity(hook.cwd)
    return EventEnvelope(
        event_id=hook.event_id or generate_id("evt"),
        event_schema_version=hook.event_schema_version,
        event_type=EventType.HOOK_EVENT.value,
        provider=hook.provider,
        environment_id=hook.environment_id,
        native_session_id=hook.native_session_id,
        source_timestamp=source_ts,
        observed_timestamp=observed,
        source_adapter_version=hook.source_adapter_version,
        payload={
            "native_event_type": hook.native_event_type,
            "normalized_event_type": hook.normalized_event_type,
            "workflow_marker": hook.workflow_marker,
            "workflow_markers_conflict": list(hook.workflow_markers_conflict),
            "turn_id": hook.turn_id,
            "cwd_native": hook.cwd,
            "cwd_canonical": cwd_canon,
            "repository_identity": repo_id,
            "transcript_reference": hook.transcript_path,
            "source": hook.source,
            "parent_session_id": hook.parent_session_id,
            "surface": hook.surface,
            "lifecycle_status": hook.lifecycle_status,
            "metadata": dict(hook.metadata),
        },
    )
