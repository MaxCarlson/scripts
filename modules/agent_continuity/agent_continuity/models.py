"""Domain models and enumerations for GUI-agent session continuity."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Provider(StrEnum):
    """Supported coding-agent providers."""

    CODEX = "codex"
    AGY = "agy"
    CLAUDE = "claude"


class RuntimeKind(StrEnum):
    """Supported execution environment categories."""

    WINDOWS = "windows"
    WSL = "wsl"
    LINUX = "linux"
    MACOS = "macos"


class EvidenceLevel(StrEnum):
    """Discrete association evidence levels (Master Plan §9.1)."""

    CONFIRMED = "confirmed"
    STRONG = "strong"
    CANDIDATE = "candidate"
    UNKNOWN = "unknown"
    REJECTED = "rejected"


class AssociationStatus(StrEnum):
    """Lifecycle states of a workflow-session association."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    UNLINKED = "unlinked"
    REJECTED = "rejected"
    CONFLICT = "conflict"


class WorkflowStatus(StrEnum):
    """Workflow lifecycle status."""

    ACTIVE = "active"
    ARCHIVED = "archived"


class SessionLifecycleStatus(StrEnum):
    """Session lifecycle status tracked independently of provider state."""

    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class EventType(StrEnum):
    """Durable event types persisted in the environment-isolated event spool."""

    WORKFLOW_REGISTERED = "workflow.registered"
    WORKFLOW_UPDATED = "workflow.updated"
    WORKFLOW_ARCHIVED = "workflow.archived"
    WORKFLOW_UNARCHIVED = "workflow.unarchived"
    WORKFLOW_GUI_LINKED = "workflow.gui_linked"
    WORKFLOW_GUI_UNLINKED = "workflow.gui_unlinked"
    ENVIRONMENT_REGISTERED = "environment.registered"
    SESSION_REGISTERED = "session.registered"
    SESSION_OBSERVED = "session.observed"
    SESSION_STATUS_CHANGED = "session.status_changed"
    ASSOCIATION_CREATED = "association.created"
    ASSOCIATION_UPDATED = "association.updated"
    ASSOCIATION_SUPERSEDED = "association.superseded"
    ASSOCIATION_UNLINKED = "association.unlinked"
    ASSOCIATION_CONFLICT_FLAGGED = "association.conflict_flagged"
    ASSOCIATION_CANDIDATE_REJECTED = "association.candidate_rejected"
    HOOK_EVENT = "hook.event"
    CHECKPOINT_RECORDED = "checkpoint.recorded"
    DISPATCHER_GUI_REGISTERED = "dispatcher.gui_registered"
    DISPATCHER_GUI_RENAMED = "dispatcher.gui_renamed"
    DISPATCHER_SLOT_CREATED = "dispatcher.slot_created"
    DISPATCHER_SLOT_STATE_CHANGED = "dispatcher.slot_state_changed"
    DISPATCHER_SESSION_ACTIVATED = "dispatcher.session_activated"
    DISPATCHER_LAUNCH_REQUESTED = "dispatcher.launch_requested"
    DISPATCHER_LAUNCH_RESOLVED = "dispatcher.launch_resolved"
    DISPATCHER_LAUNCH_FAILED = "dispatcher.launch_failed"
    DISPATCHER_PROCESS_OBSERVED = "dispatcher.process_observed"
    DISPATCHER_SLOTS_TRANSITIONED = "dispatcher.slots_transitioned"
    DISPATCHER_AGENT_TRANSITION_COMPLETED = "dispatcher.agent_transition_completed"
    DISPATCHER_TERMINAL_LAUNCH_RECORDED = "dispatcher.terminal_launch_recorded"
    DISPATCHER_LAUNCH_PROFILE_CREATED = "dispatcher.launch_profile_created"
    DISPATCHER_LAUNCH_PROFILE_UPDATED = "dispatcher.launch_profile_updated"
    DISPATCHER_LAUNCH_PROFILE_RETIRED = "dispatcher.launch_profile_retired"
    DISPATCHER_SLOT_PROFILE_ASSIGNED = "dispatcher.slot_profile_assigned"
    DISPATCHER_SLOT_WORKFLOW_TYPE_CHANGED = "dispatcher.slot_workflow_type_changed"
    DISPATCHER_AGENT_NUMBER_ASSIGNED = "dispatcher.agent_number_assigned"


@dataclass(slots=True)
class EventEnvelope:
    """Immutable durable event record."""

    event_id: str
    event_schema_version: int
    event_type: str
    provider: str | None
    environment_id: str
    native_session_id: str | None
    source_timestamp: str
    observed_timestamp: str
    source_adapter_version: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EventEnvelope:
        return cls(
            event_id=str(data["event_id"]),
            event_schema_version=int(data["event_schema_version"]),
            event_type=str(data["event_type"]),
            provider=data.get("provider"),
            environment_id=str(data["environment_id"]),
            native_session_id=data.get("native_session_id"),
            source_timestamp=str(data["source_timestamp"]),
            observed_timestamp=str(data["observed_timestamp"]),
            source_adapter_version=str(data.get("source_adapter_version", "0.1.0")),
            payload=dict(data.get("payload") or {}),
        )


@dataclass(slots=True)
class EnvironmentInfo:
    """Persistent runtime environment identity."""

    environment_id: str
    runtime_kind: str
    distro: str | None
    hostname: str
    label: str
    created_at: str
    last_seen_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class GuiConversation:
    """Consumer ChatGPT GUI conversation linked to a workflow."""

    gui_ref_id: str
    workflow_id: str
    url: str
    canonical_url: str
    title: str | None
    relationship: str
    status: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Workflow:
    """Persistent GUI workflow record."""

    workflow_id: str
    slug: str
    title: str
    repo_paths: list[str]
    status: str
    created_at: str
    updated_at: str
    gui_conversations: list[GuiConversation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["gui_conversations"] = [g.to_dict() for g in self.gui_conversations]
        return data


@dataclass(slots=True)
class SessionRecord:
    """Provider-neutral native session keyed by (provider, environment_id, native_session_id)."""

    provider: str
    environment_id: str
    native_session_id: str
    native_root_id: str | None = None
    parent_session_id: str | None = None
    surface: str | None = None
    native_version: str | None = None
    cwd_native: str | None = None
    cwd_canonical: str | None = None
    repository_identity: str | None = None
    native_title: str | None = None
    transcript_reference: str | None = None
    created_at: str | None = None
    first_observed_at: str = ""
    last_seen_at: str | None = None
    last_turn_at: str | None = None
    last_completed_turn_at: str | None = None
    lifecycle_status: str = SessionLifecycleStatus.ACTIVE.value
    metadata_source: str = "manual"
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AssociationRecord:
    """Workflow-to-session association with provenance and conflict status."""

    association_id: str
    workflow_id: str
    provider: str
    environment_id: str
    native_session_id: str
    evidence_level: str
    association_method: str
    evidence_summary: str | None
    evidence_reference: str | None
    status: str
    first_turn_id: str | None
    last_turn_id: str | None
    confirmed_at: str | None
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
