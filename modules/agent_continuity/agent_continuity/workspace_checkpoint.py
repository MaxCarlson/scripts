"""Durable workspace checkpoints and minimal integration contracts (LLMD-42)."""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import shutil
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .errors import ContinuityError, ErrorCode
from .events import atomic_write_json
from .identifiers import generate_id, normalize_path_canonical, now_utc_iso
from .runtime_discovery import (
    AttachmentState,
    EvidenceAvailability,
    EvidenceConfidence,
    IdentityComparison,
    ManagementState,
    MatchStatus,
    ProcessIdentity,
    ProcessLiveness,
    ProcessSnapshot,
    RuntimeDiscovery,
    SessionIdentityState,
    SessionKey,
    SessionRuntimeObservation,
    compare_process_identities,
)

CHECKPOINT_SCHEMA_VERSION = 1

_EFFORT_VALUES = frozenset({"low", "medium", "high", "xhigh", "max"})
_SANDBOX_SAFE_VALUES = frozenset({"read-only", "workspace-write", "default", "true", "false"})
_APPROVAL_SAFE_VALUES = frozenset({"untrusted", "on-failure", "on-request", "auto-review"})
_PERMISSION_MODE_SAFE_VALUES = frozenset({"default", "manual", "acceptEdits", "plan", "auto"})

ALLOWED_LAUNCH_SETTINGS: frozenset[str] = frozenset(
    {
        "model",
        "sandbox",
        "approval_policy",
        "permission_mode",
        "reasoning_effort",
        "effort",
        "search",
        "add_dirs",
        "profile",
    }
)


@dataclass(frozen=True, slots=True)
class WorkspaceSlotMetadata:
    """Minimal integration contract for v2.3.0 profile, workflow, and numbering metadata."""

    workflow_type: str | None = None
    profile_id: str | None = None
    profile_revision: int | None = None
    agent_number: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_type": self.workflow_type,
            "profile_id": self.profile_id,
            "profile_revision": self.profile_revision,
            "agent_number": self.agent_number,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> WorkspaceSlotMetadata:
        if not data:
            return cls()
        rev = data.get("profile_revision")
        num = data.get("agent_number")
        return cls(
            workflow_type=str(data["workflow_type"]) if data.get("workflow_type") is not None else None,
            profile_id=str(data["profile_id"]) if data.get("profile_id") is not None else None,
            profile_revision=int(rev) if rev is not None else None,
            agent_number=int(num) if num is not None else None,
        )


@dataclass(frozen=True, slots=True)
class WorkspaceTopologyRequest:
    """Requested terminal/pane layout captured separately from observed runtime receipts."""

    launch_id: str | None = None
    pane_id: str | None = None
    terminal_session_id: str | None = None
    target_window: str | None = None
    requested_layout: str | None = None
    requested_tab_index: int | None = None
    requested_pane_index: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "launch_id": self.launch_id,
            "pane_id": self.pane_id,
            "terminal_session_id": self.terminal_session_id,
            "target_window": self.target_window,
            "requested_layout": self.requested_layout,
            "requested_tab_index": self.requested_tab_index,
            "requested_pane_index": self.requested_pane_index,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> WorkspaceTopologyRequest | None:
        if not data:
            return None
        tab_idx = data.get("requested_tab_index")
        pane_idx = data.get("requested_pane_index")
        return cls(
            launch_id=str(data["launch_id"]) if data.get("launch_id") is not None else None,
            pane_id=str(data["pane_id"]) if data.get("pane_id") is not None else None,
            terminal_session_id=(
                str(data["terminal_session_id"]) if data.get("terminal_session_id") is not None else None
            ),
            target_window=str(data["target_window"]) if data.get("target_window") is not None else None,
            requested_layout=str(data["requested_layout"]) if data.get("requested_layout") is not None else None,
            requested_tab_index=int(tab_idx) if tab_idx is not None else None,
            requested_pane_index=int(pane_idx) if pane_idx is not None else None,
        )


@dataclass(frozen=True, slots=True)
class WorkspaceWorktreeEvidence:
    """Captured working directory and Git worktree/revision evidence for a slot."""

    requested_cwd: str | None = None
    effective_cwd: str | None = None
    native_cwd: str | None = None
    git_repository: str | None = None
    git_worktree: str | None = None
    git_branch: str | None = None
    git_commit: str | None = None

    def primary_cwd(self) -> str | None:
        return self.effective_cwd or self.native_cwd or self.requested_cwd or self.git_worktree

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_cwd": self.requested_cwd,
            "effective_cwd": self.effective_cwd,
            "native_cwd": self.native_cwd,
            "git_repository": self.git_repository,
            "git_worktree": self.git_worktree,
            "git_branch": self.git_branch,
            "git_commit": self.git_commit,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> WorkspaceWorktreeEvidence:
        if not data:
            return cls()
        return cls(
            requested_cwd=str(data["requested_cwd"]) if data.get("requested_cwd") is not None else None,
            effective_cwd=str(data["effective_cwd"]) if data.get("effective_cwd") is not None else None,
            native_cwd=str(data["native_cwd"]) if data.get("native_cwd") is not None else None,
            git_repository=str(data["git_repository"]) if data.get("git_repository") is not None else None,
            git_worktree=str(data["git_worktree"]) if data.get("git_worktree") is not None else None,
            git_branch=str(data["git_branch"]) if data.get("git_branch") is not None else None,
            git_commit=str(data["git_commit"]) if data.get("git_commit") is not None else None,
        )


@dataclass(frozen=True, slots=True)
class WorkspaceSlotInput:
    """Candidate session/slot input supplied by dispatcher or caller for checkpointing."""

    slot_id: str
    gui_id: str
    provider: str
    native_session_id: str
    environment_id: str
    runtime_kind: str = "windows"
    lifecycle_state: str = "active"
    registry_association: bool = True
    gui_alias: str | None = None
    slot_name: str | None = None
    known_process_identity: ProcessIdentity | None = None
    launch_settings: Mapping[str, Any] = field(default_factory=dict)
    worktree: WorkspaceWorktreeEvidence | None = None
    requested_topology: WorkspaceTopologyRequest | None = None
    metadata: WorkspaceSlotMetadata = field(default_factory=WorkspaceSlotMetadata)

    def session_key(self) -> SessionKey:
        return SessionKey(
            provider=self.provider,
            native_session_id=self.native_session_id,
            environment_id=self.environment_id,
            runtime_kind=self.runtime_kind,
        )


class WorkspaceSnapshotSource(Protocol):
    """Read-only source of candidate slots for workspace checkpointing."""

    def list_candidate_slots(self) -> Sequence[WorkspaceSlotInput]: ...


@dataclass(frozen=True, slots=True)
class ObservedProcessEvidence:
    """Serializable process identity captured from runtime discovery."""

    pid: int | None
    creation_time_ns: int | None
    precision_ns: int | None
    image_name: str | None
    parent_pid: int | None

    def to_process_identity(self) -> ProcessIdentity | None:
        if self.pid is None or self.creation_time_ns is None or self.precision_ns is None:
            return None
        return ProcessIdentity(
            pid=self.pid,
            creation_time_ns=self.creation_time_ns,
            precision_ns=self.precision_ns,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "creation_time_ns": self.creation_time_ns,
            "precision_ns": self.precision_ns,
            "image_name": self.image_name,
            "parent_pid": self.parent_pid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ObservedProcessEvidence:
        return cls(
            pid=int(data["pid"]) if data.get("pid") is not None else None,
            creation_time_ns=(
                int(data["creation_time_ns"]) if data.get("creation_time_ns") is not None else None
            ),
            precision_ns=int(data["precision_ns"]) if data.get("precision_ns") is not None else None,
            image_name=str(data["image_name"]) if data.get("image_name") is not None else None,
            parent_pid=int(data["parent_pid"]) if data.get("parent_pid") is not None else None,
        )


@dataclass(frozen=True, slots=True)
class ObservedManagedPaneEvidence:
    """Serializable exact managed-pane receipt captured from runtime discovery."""

    launch_id: str
    pane_id: str
    terminal_session_id: str | None
    process_pid: int
    process_creation_time_ns: int
    process_creation_time_precision_ns: int

    def to_process_identity(self) -> ProcessIdentity:
        return ProcessIdentity(
            pid=self.process_pid,
            creation_time_ns=self.process_creation_time_ns,
            precision_ns=self.process_creation_time_precision_ns,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "launch_id": self.launch_id,
            "pane_id": self.pane_id,
            "terminal_session_id": self.terminal_session_id,
            "process_pid": self.process_pid,
            "process_creation_time_ns": self.process_creation_time_ns,
            "process_creation_time_precision_ns": self.process_creation_time_precision_ns,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> ObservedManagedPaneEvidence | None:
        if not data:
            return None
        return cls(
            launch_id=str(data["launch_id"]),
            pane_id=str(data["pane_id"]),
            terminal_session_id=(
                str(data["terminal_session_id"]) if data.get("terminal_session_id") is not None else None
            ),
            process_pid=int(data["process_pid"]),
            process_creation_time_ns=int(data["process_creation_time_ns"]),
            process_creation_time_precision_ns=int(data["process_creation_time_precision_ns"]),
        )


@dataclass(frozen=True, slots=True)
class ObservedTopologyEvidence:
    """Actually observed attachment/management evidence; never infers window/pane geometry."""

    interactive_attachment: str
    attachment_confidence: str
    management: str
    managed_pane: ObservedManagedPaneEvidence | None = None
    observed_processes: tuple[ObservedProcessEvidence, ...] = ()
    window_ownership_inferred: bool = False
    pane_geometry_inferred: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "interactive_attachment": self.interactive_attachment,
            "attachment_confidence": self.attachment_confidence,
            "management": self.management,
            "managed_pane": self.managed_pane.to_dict() if self.managed_pane else None,
            "observed_processes": [proc.to_dict() for proc in self.observed_processes],
            "window_ownership_inferred": self.window_ownership_inferred,
            "pane_geometry_inferred": self.pane_geometry_inferred,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ObservedTopologyEvidence:
        return cls(
            interactive_attachment=str(data.get("interactive_attachment", AttachmentState.UNKNOWN.value)),
            attachment_confidence=str(data.get("attachment_confidence", EvidenceConfidence.NONE.value)),
            management=str(data.get("management", ManagementState.UNKNOWN.value)),
            managed_pane=ObservedManagedPaneEvidence.from_dict(data.get("managed_pane")),
            observed_processes=tuple(
                ObservedProcessEvidence.from_dict(item) for item in data.get("observed_processes", ())
            ),
            window_ownership_inferred=bool(data.get("window_ownership_inferred", False)),
            pane_geometry_inferred=bool(data.get("pane_geometry_inferred", False)),
        )


@dataclass(frozen=True, slots=True)
class CheckpointSessionEntry:
    """Immutable checkpointed session envelope tied to a durable slot_id."""

    slot_id: str
    gui_id: str
    provider: str
    native_session_id: str
    environment_id: str
    runtime_kind: str
    lifecycle_state: str
    process_liveness: str
    known_process_liveness: str
    process_session_match: str
    session_identity_state: str
    resumability_state: str
    availability: str
    confidence: str
    observed_at: str
    capture_reason: str
    gui_alias: str | None = None
    slot_name: str | None = None
    provider_session_found: bool | None = None
    provider_activity_at: str | None = None
    identity_conflict: bool = False
    evidence_conflict: bool = False
    worktree: WorkspaceWorktreeEvidence = field(default_factory=WorkspaceWorktreeEvidence)
    launch_settings: dict[str, Any] = field(default_factory=dict)
    requested_topology: WorkspaceTopologyRequest | None = None
    observed_topology: ObservedTopologyEvidence = field(
        default_factory=lambda: ObservedTopologyEvidence(
            interactive_attachment=AttachmentState.UNKNOWN.value,
            attachment_confidence=EvidenceConfidence.NONE.value,
            management=ManagementState.UNKNOWN.value,
        )
    )
    metadata: WorkspaceSlotMetadata = field(default_factory=WorkspaceSlotMetadata)
    stale: bool = False
    stale_reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "gui_id": self.gui_id,
            "provider": self.provider,
            "native_session_id": self.native_session_id,
            "environment_id": self.environment_id,
            "runtime_kind": self.runtime_kind,
            "lifecycle_state": self.lifecycle_state,
            "process_liveness": self.process_liveness,
            "known_process_liveness": self.known_process_liveness,
            "process_session_match": self.process_session_match,
            "session_identity_state": self.session_identity_state,
            "resumability_state": self.resumability_state,
            "availability": self.availability,
            "confidence": self.confidence,
            "observed_at": self.observed_at,
            "capture_reason": self.capture_reason,
            "gui_alias": self.gui_alias,
            "slot_name": self.slot_name,
            "provider_session_found": self.provider_session_found,
            "provider_activity_at": self.provider_activity_at,
            "identity_conflict": self.identity_conflict,
            "evidence_conflict": self.evidence_conflict,
            "worktree": self.worktree.to_dict(),
            "launch_settings": dict(self.launch_settings),
            "requested_topology": self.requested_topology.to_dict() if self.requested_topology else None,
            "observed_topology": self.observed_topology.to_dict(),
            "metadata": self.metadata.to_dict(),
            "stale": self.stale,
            "stale_reasons": list(self.stale_reasons),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CheckpointSessionEntry:
        return cls(
            slot_id=str(data["slot_id"]),
            gui_id=str(data["gui_id"]),
            provider=str(data["provider"]),
            native_session_id=str(data["native_session_id"]),
            environment_id=str(data["environment_id"]),
            runtime_kind=str(data["runtime_kind"]),
            lifecycle_state=str(data["lifecycle_state"]),
            process_liveness=str(data["process_liveness"]),
            known_process_liveness=str(data["known_process_liveness"]),
            process_session_match=str(data["process_session_match"]),
            session_identity_state=str(data["session_identity_state"]),
            resumability_state=str(data["resumability_state"]),
            availability=str(data["availability"]),
            confidence=str(data["confidence"]),
            observed_at=str(data["observed_at"]),
            capture_reason=str(data["capture_reason"]),
            gui_alias=str(data["gui_alias"]) if data.get("gui_alias") is not None else None,
            slot_name=str(data["slot_name"]) if data.get("slot_name") is not None else None,
            provider_session_found=data.get("provider_session_found"),
            provider_activity_at=(
                str(data["provider_activity_at"]) if data.get("provider_activity_at") is not None else None
            ),
            identity_conflict=bool(data.get("identity_conflict", False)),
            evidence_conflict=bool(data.get("evidence_conflict", False)),
            worktree=WorkspaceWorktreeEvidence.from_dict(data.get("worktree")),
            launch_settings=dict(data.get("launch_settings") or {}),
            requested_topology=WorkspaceTopologyRequest.from_dict(data.get("requested_topology")),
            observed_topology=ObservedTopologyEvidence.from_dict(data.get("observed_topology") or {}),
            metadata=WorkspaceSlotMetadata.from_dict(data.get("metadata")),
            stale=bool(data.get("stale", False)),
            stale_reasons=tuple(str(item) for item in data.get("stale_reasons", ())),
        )


@dataclass(frozen=True, slots=True)
class SkippedSlotEvidence:
    """Candidate slot excluded from checkpoint capture because it was not observed."""

    slot_id: str
    gui_id: str
    provider: str
    native_session_id: str
    environment_id: str
    lifecycle_state: str
    process_liveness: str
    availability: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SkippedSlotEvidence:
        return cls(
            slot_id=str(data["slot_id"]),
            gui_id=str(data["gui_id"]),
            provider=str(data["provider"]),
            native_session_id=str(data["native_session_id"]),
            environment_id=str(data["environment_id"]),
            lifecycle_state=str(data["lifecycle_state"]),
            process_liveness=str(data["process_liveness"]),
            availability=str(data["availability"]),
            reason=str(data["reason"]),
        )


@dataclass(frozen=True, slots=True)
class WorkspaceCheckpoint:
    """Atomic durable workspace checkpoint envelope."""

    checkpoint_id: str
    schema_version: int
    created_at: str
    label: str | None
    environment_ids: tuple[str, ...]
    sessions: tuple[CheckpointSessionEntry, ...]
    skipped_slots: tuple[SkippedSlotEvidence, ...] = ()
    stale: bool = False
    stale_reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "label": self.label,
            "environment_ids": list(self.environment_ids),
            "sessions": [entry.to_dict() for entry in self.sessions],
            "skipped_slots": [item.to_dict() for item in self.skipped_slots],
            "stale": self.stale,
            "stale_reasons": list(self.stale_reasons),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> WorkspaceCheckpoint:
        version = int(data.get("schema_version", 0))
        if version != CHECKPOINT_SCHEMA_VERSION:
            raise ContinuityError(
                ErrorCode.INVALID_INPUT,
                f"Unsupported checkpoint schema_version {version}; expected {CHECKPOINT_SCHEMA_VERSION}.",
                {"schema_version": version},
            )
        return cls(
            checkpoint_id=str(data["checkpoint_id"]),
            schema_version=version,
            created_at=str(data["created_at"]),
            label=str(data["label"]) if data.get("label") is not None else None,
            environment_ids=tuple(str(item) for item in data.get("environment_ids", ())),
            sessions=tuple(CheckpointSessionEntry.from_dict(item) for item in data.get("sessions", ())),
            skipped_slots=tuple(SkippedSlotEvidence.from_dict(item) for item in data.get("skipped_slots", ())),
            stale=bool(data.get("stale", False)),
            stale_reasons=tuple(str(item) for item in data.get("stale_reasons", ())),
        )


@dataclass(frozen=True, slots=True)
class CheckpointPreview:
    """Read-only preview of what a workspace checkpoint would capture."""

    label: str | None
    captured_at: str
    sessions: tuple[CheckpointSessionEntry, ...]
    skipped_slots: tuple[SkippedSlotEvidence, ...]
    environment_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "captured_at": self.captured_at,
            "environment_ids": list(self.environment_ids),
            "sessions": [entry.to_dict() for entry in self.sessions],
            "skipped_slots": [item.to_dict() for item in self.skipped_slots],
        }


@dataclass(frozen=True, slots=True)
class EntryRevalidationResult:
    """Revalidation outcome for one checkpointed session."""

    slot_id: str
    checkpoint_gui_id: str
    current_gui_id: str | None
    native_session_id: str
    stale: bool
    reasons: tuple[str, ...]
    can_restore: bool
    cross_gui_transferred: bool = False
    already_running: bool = False


@dataclass(frozen=True, slots=True)
class CheckpointRevalidationReport:
    """Aggregate revalidation report for a checkpoint."""

    checkpoint_id: str
    checked_at: str
    stale: bool
    stale_reasons: tuple[str, ...]
    entries: tuple[EntryRevalidationResult, ...]


@dataclass(frozen=True, slots=True)
class CorruptCheckpointRecord:
    """Record of an unreadable or corrupt checkpoint file encountered during listing."""

    path: str
    error: str


def _validate_nonempty_str(key: str, value: Any, *, max_len: int = 256) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_len or "\0" in value or "\n" in value or "\r" in value:
        raise ContinuityError(
            ErrorCode.INVALID_INPUT,
            f"Launch setting {key!r} must be a non-empty single-line string (<= {max_len} chars).",
            {"key": key},
        )
    return value.strip()


def sanitize_launch_settings(settings: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate and return a JSON-safe copy of explicitly permitted non-secret launch settings."""
    if not settings:
        return {}
    sanitized: dict[str, Any] = {}
    for raw_key, value in settings.items():
        key = str(raw_key).strip()
        if key not in ALLOWED_LAUNCH_SETTINGS:
            raise ContinuityError(
                ErrorCode.INVALID_INPUT,
                f"Launch setting {key!r} is not in the permitted non-secret allowlist.",
                {"key": key, "allowed_keys": sorted(ALLOWED_LAUNCH_SETTINGS)},
            )
        if value is None:
            continue
        if key == "model" or key == "profile":
            sanitized[key] = _validate_nonempty_str(key, value, max_len=128)
        elif key == "sandbox":
            text = _validate_nonempty_str(key, value, max_len=64)
            if text not in _SANDBOX_SAFE_VALUES:
                raise ContinuityError(
                    ErrorCode.INVALID_INPUT,
                    f"Launch setting 'sandbox' value {text!r} is not permitted.",
                    {"key": key, "value": text},
                )
            sanitized[key] = text
        elif key == "approval_policy":
            text = _validate_nonempty_str(key, value, max_len=64)
            if text not in _APPROVAL_SAFE_VALUES:
                raise ContinuityError(
                    ErrorCode.INVALID_INPUT,
                    f"Launch setting 'approval_policy' value {text!r} is not permitted.",
                    {"key": key, "value": text},
                )
            sanitized[key] = text
        elif key == "permission_mode":
            text = _validate_nonempty_str(key, value, max_len=64)
            if text not in _PERMISSION_MODE_SAFE_VALUES:
                raise ContinuityError(
                    ErrorCode.INVALID_INPUT,
                    f"Launch setting 'permission_mode' value {text!r} is not permitted.",
                    {"key": key, "value": text},
                )
            sanitized[key] = text
        elif key in {"reasoning_effort", "effort"}:
            text = _validate_nonempty_str(key, value, max_len=32)
            if text not in _EFFORT_VALUES:
                raise ContinuityError(
                    ErrorCode.INVALID_INPUT,
                    f"Launch setting {key!r} value {text!r} is not permitted.",
                    {"key": key, "value": text},
                )
            sanitized[key] = text
        elif key == "search":
            if not isinstance(value, bool):
                raise ContinuityError(
                    ErrorCode.INVALID_INPUT,
                    "Launch setting 'search' must be a boolean.",
                    {"key": key},
                )
            sanitized[key] = value
        elif key == "add_dirs":
            if not isinstance(value, (list, tuple)):
                raise ContinuityError(
                    ErrorCode.INVALID_INPUT,
                    "Launch setting 'add_dirs' must be a sequence of directory strings.",
                    {"key": key},
                )
            sanitized[key] = [_validate_nonempty_str(key, item, max_len=1024) for item in value]
    return sanitized


def _resumability_state(observation: SessionRuntimeObservation) -> str:
    if observation.session_identity_state is SessionIdentityState.RESERVED:
        if observation.provider_session_found is True:
            return "confirmed_resumable"
        return "reserved_unconfirmed"
    if observation.provider_session_found is True:
        return "confirmed_resumable"
    if observation.session_identity_state is SessionIdentityState.EXACT:
        return "exact_process_unverified_store"
    return "unverified"


def _is_actually_observed(observation: SessionRuntimeObservation) -> tuple[bool, str]:
    if observation.process_liveness is ProcessLiveness.RUNNING:
        return True, "observed_running"
    if observation.process_session_match is MatchStatus.EXACT:
        return True, "observed_exact_match"
    if (
        observation.management is ManagementState.MANAGED
        and observation.managed_pane is not None
        and observation.known_process_liveness is ProcessLiveness.RUNNING
    ):
        return True, "observed_managed_pane"
    return False, f"not_observed:{observation.process_liveness.value}:{observation.availability.value}"


def _entry_from_observation(
    slot: WorkspaceSlotInput,
    observation: SessionRuntimeObservation,
    *,
    capture_reason: str,
) -> CheckpointSessionEntry:
    managed_pane = None
    if observation.managed_pane is not None:
        pane = observation.managed_pane
        managed_pane = ObservedManagedPaneEvidence(
            launch_id=pane.launch_id,
            pane_id=pane.pane_id,
            terminal_session_id=pane.terminal_session_id,
            process_pid=pane.process_identity.pid,
            process_creation_time_ns=pane.process_identity.creation_time_ns,
            process_creation_time_precision_ns=pane.process_identity.precision_ns,
        )
    observed_procs = tuple(
        ObservedProcessEvidence(
            pid=proc.identity.pid if proc.identity else None,
            creation_time_ns=proc.identity.creation_time_ns if proc.identity else None,
            precision_ns=proc.identity.precision_ns if proc.identity else None,
            image_name=proc.image_name,
            parent_pid=proc.parent_pid,
        )
        for proc in observation.processes
    )
    return CheckpointSessionEntry(
        slot_id=slot.slot_id,
        gui_id=slot.gui_id,
        provider=slot.provider,
        native_session_id=slot.native_session_id,
        environment_id=slot.environment_id,
        runtime_kind=slot.runtime_kind,
        lifecycle_state=slot.lifecycle_state,
        process_liveness=observation.process_liveness.value,
        known_process_liveness=observation.known_process_liveness.value,
        process_session_match=observation.process_session_match.value,
        session_identity_state=observation.session_identity_state.value,
        resumability_state=_resumability_state(observation),
        availability=observation.availability.value,
        confidence=observation.confidence.value,
        observed_at=observation.captured_at.isoformat(),
        capture_reason=capture_reason,
        gui_alias=slot.gui_alias,
        slot_name=slot.slot_name,
        provider_session_found=observation.provider_session_found,
        provider_activity_at=(
            observation.provider_activity_at.isoformat() if observation.provider_activity_at else None
        ),
        identity_conflict=observation.identity_conflict,
        evidence_conflict=observation.evidence_conflict,
        worktree=slot.worktree or WorkspaceWorktreeEvidence(),
        launch_settings=sanitize_launch_settings(slot.launch_settings),
        requested_topology=slot.requested_topology,
        observed_topology=ObservedTopologyEvidence(
            interactive_attachment=observation.interactive_attachment.value,
            attachment_confidence=observation.attachment_confidence.value,
            management=observation.management.value,
            managed_pane=managed_pane,
            observed_processes=observed_procs,
            window_ownership_inferred=False,
            pane_geometry_inferred=False,
        ),
        metadata=slot.metadata,
    )


def observe_slots_batched(
    slots: Sequence[WorkspaceSlotInput],
    *,
    observers: Mapping[tuple[str, str], RuntimeDiscovery] | RuntimeDiscovery | None = None,
    snapshots: Mapping[tuple[str, str], ProcessSnapshot] | ProcessSnapshot | None = None,
) -> dict[str, SessionRuntimeObservation]:
    """Observe candidate slots using one fresh batched snapshot per (runtime_kind, environment_id)."""
    if not slots:
        return {}
    grouped: dict[tuple[str, str], list[WorkspaceSlotInput]] = {}
    for slot in slots:
        grouped.setdefault((slot.runtime_kind, slot.environment_id), []).append(slot)

    results: dict[str, SessionRuntimeObservation] = {}
    for env_key, env_slots in grouped.items():
        runtime_kind, environment_id = env_key
        if isinstance(observers, RuntimeDiscovery):
            observer = observers
        elif observers is not None and env_key in observers:
            observer = observers[env_key]
        else:
            observer = RuntimeDiscovery(environment_id=environment_id, runtime_kind=runtime_kind)

        if isinstance(snapshots, ProcessSnapshot):
            snapshot = snapshots
        elif snapshots is not None and env_key in snapshots:
            snapshot = snapshots[env_key]
        else:
            snapshot = observer.capture_snapshot()

        keys = [slot.session_key() for slot in env_slots]
        reg_assoc = {slot.session_key(): slot.registry_association for slot in env_slots}
        known_ids = {
            slot.session_key(): slot.known_process_identity
            for slot in env_slots
            if slot.known_process_identity is not None
        }
        observations = observer.observe_many(
            keys,
            snapshot=snapshot,
            registry_associations=reg_assoc,
            known_processes=known_ids,
        )
        for slot, observation in zip(env_slots, observations, strict=True):
            results[slot.slot_id] = observation
    return results


def preview_checkpoint(
    slots: Sequence[WorkspaceSlotInput],
    *,
    label: str | None = None,
    observers: Mapping[tuple[str, str], RuntimeDiscovery] | RuntimeDiscovery | None = None,
    snapshots: Mapping[tuple[str, str], ProcessSnapshot] | ProcessSnapshot | None = None,
    include_unobserved: bool = False,
) -> CheckpointPreview:
    """Preview what a workspace checkpoint would capture without writing to disk."""
    for slot in slots:
        sanitize_launch_settings(slot.launch_settings)
    observations = observe_slots_batched(slots, observers=observers, snapshots=snapshots)
    captured_entries: list[CheckpointSessionEntry] = []
    skipped: list[SkippedSlotEvidence] = []
    env_ids: set[str] = set()

    for slot in slots:
        obs = observations[slot.slot_id]
        observed, reason = _is_actually_observed(obs)
        if observed or include_unobserved:
            capture_reason = reason if observed else f"explicit_unobserved:{reason}"
            captured_entries.append(_entry_from_observation(slot, obs, capture_reason=capture_reason))
            env_ids.add(slot.environment_id)
        else:
            skipped.append(
                SkippedSlotEvidence(
                    slot_id=slot.slot_id,
                    gui_id=slot.gui_id,
                    provider=slot.provider,
                    native_session_id=slot.native_session_id,
                    environment_id=slot.environment_id,
                    lifecycle_state=slot.lifecycle_state,
                    process_liveness=obs.process_liveness.value,
                    availability=obs.availability.value,
                    reason=reason,
                )
            )

    return CheckpointPreview(
        label=label,
        captured_at=now_utc_iso(),
        sessions=tuple(captured_entries),
        skipped_slots=tuple(skipped),
        environment_ids=tuple(sorted(env_ids)),
    )


def revalidate_checkpoint(
    checkpoint: WorkspaceCheckpoint,
    *,
    current_slots: Sequence[WorkspaceSlotInput] | None = None,
    observers: Mapping[tuple[str, str], RuntimeDiscovery] | RuntimeDiscovery | None = None,
    snapshots: Mapping[tuple[str, str], ProcessSnapshot] | ProcessSnapshot | None = None,
    path_exists: Callable[[str], bool] | None = None,
    allow_unknown_runtime: bool = False,
    has_slot_exclusion: bool = False,
) -> CheckpointRevalidationReport:
    """Revalidate a checkpoint against current registry slots, worktrees, and fresh observations."""
    exists_fn = path_exists or (lambda raw: Path(raw).exists())
    slots_by_id = {slot.slot_id: slot for slot in (current_slots or ())}

    observations: dict[str, SessionRuntimeObservation] = {}
    if observers is not None or snapshots is not None:
        synthetic_slots = [
            WorkspaceSlotInput(
                slot_id=entry.slot_id,
                gui_id=entry.gui_id,
                provider=entry.provider,
                native_session_id=entry.native_session_id,
                environment_id=entry.environment_id,
                runtime_kind=entry.runtime_kind,
                lifecycle_state=entry.lifecycle_state,
                known_process_identity=(
                    entry.observed_topology.managed_pane.to_process_identity()
                    if entry.observed_topology.managed_pane is not None
                    else (
                        entry.observed_topology.observed_processes[0].to_process_identity()
                        if entry.observed_topology.observed_processes
                        else None
                    )
                ),
            )
            for entry in checkpoint.sessions
        ]
        observations = observe_slots_batched(synthetic_slots, observers=observers, snapshots=snapshots)

    results: list[EntryRevalidationResult] = []
    any_stale = False
    aggregate_reasons: list[str] = []

    for entry in checkpoint.sessions:
        reasons: list[str] = list(entry.stale_reasons)
        current_slot = slots_by_id.get(entry.slot_id)
        cross_gui_transferred = False
        already_running = False

        if current_slots is not None:
            if current_slot is None:
                reasons.append("stale_slot_missing")
            else:
                if current_slot.gui_id != entry.gui_id:
                    cross_gui_transferred = True
                    reasons.append("cross_gui_transferred")
                if (
                    current_slot.native_session_id != entry.native_session_id
                    or current_slot.provider != entry.provider
                    or current_slot.environment_id != entry.environment_id
                ):
                    reasons.append("stale_session_superseded")
                if (
                    entry.worktree.git_commit
                    and current_slot.worktree is not None
                    and current_slot.worktree.git_commit
                    and current_slot.worktree.git_commit != entry.worktree.git_commit
                ):
                    reasons.append("stale_workspace_revision_changed")

        cwd = entry.worktree.primary_cwd()
        if cwd is not None and not exists_fn(cwd):
            reasons.append("stale_worktree_missing")
        elif (
            current_slot is not None
            and current_slot.worktree is not None
            and cwd is not None
            and current_slot.worktree.primary_cwd() is not None
            and normalize_path_canonical(current_slot.worktree.primary_cwd()) != normalize_path_canonical(cwd)
        ):
            reasons.append("stale_worktree_changed")

        if entry.resumability_state == "reserved_unconfirmed":
            reasons.append("reserved_unconfirmed")

        obs = observations.get(entry.slot_id)
        if obs is not None:
            if obs.identity_conflict:
                reasons.append("identity_conflict")
            if obs.evidence_conflict:
                reasons.append("evidence_conflict")
            if obs.process_liveness is ProcessLiveness.RUNNING:
                already_running = True
                reasons.append("already_running")
            elif obs.process_liveness is ProcessLiveness.AMBIGUOUS or (
                obs.process_availability is EvidenceAvailability.UNAVAILABLE
            ):
                reasons.append("unknown_runtime_evidence")
            elif obs.process_liveness is ProcessLiveness.UNKNOWN or (
                obs.process_availability is EvidenceAvailability.PARTIAL
            ):
                # Absence of a managed receipt never implies verified exit; cooperating
                # dispatcher slot exclusion does not exclude external unmanaged processes.
                managed_exited = (
                    obs.managed_pane is None
                    and any(
                        ref.receipt_state in {"exited", "failed", "stale"}
                        or ref.receipt_liveness is ProcessLiveness.EXITED
                        for ref in obs.historical_managed_panes
                    )
                    and obs.known_process_liveness is not ProcessLiveness.RUNNING
                )
                exact_identity = (
                    entry.resumability_state in {"confirmed_resumable", "exact_process_unverified_store"}
                    or obs.session_identity_state is SessionIdentityState.EXACT
                )
                if (
                    has_slot_exclusion
                    and not obs.identity_conflict
                    and not obs.evidence_conflict
                    and exact_identity
                    and managed_exited
                ):
                    reasons.append("partial_enum_safe_via_guard_and_receipts")
                else:
                    if obs.managed_pane is None and not obs.historical_managed_panes:
                        reasons.append("unmanaged_partial_enum_unverified")
                    reasons.append("unknown_runtime_evidence")
            elif entry.observed_topology.observed_processes and obs.processes:
                prior = entry.observed_topology.observed_processes[0].to_process_identity()
                curr = obs.processes[0].identity
                if prior is not None and curr is not None:
                    cmp_result = compare_process_identities(prior, curr)
                    if cmp_result is IdentityComparison.DIFFERENT:
                        reasons.append("process_identity_changed")

        deduped = tuple(dict.fromkeys(reasons))
        blocking_reasons = {
            "stale_slot_missing",
            "stale_session_superseded",
            "stale_worktree_missing",
            "stale_worktree_changed",
            "reserved_unconfirmed",
            "identity_conflict",
            "evidence_conflict",
            "already_running",
        }
        if not allow_unknown_runtime:
            blocking_reasons.add("unknown_runtime_evidence")
        entry_stale = bool(entry.stale or any(r.startswith("stale_") for r in deduped))
        can_restore = not any(r in blocking_reasons for r in deduped)
        if entry_stale:
            any_stale = True
            for r in deduped:
                if r.startswith("stale_") and r not in aggregate_reasons:
                    aggregate_reasons.append(r)

        results.append(
            EntryRevalidationResult(
                slot_id=entry.slot_id,
                checkpoint_gui_id=entry.gui_id,
                current_gui_id=current_slot.gui_id if current_slot else None,
                native_session_id=entry.native_session_id,
                stale=entry_stale,
                reasons=deduped,
                can_restore=can_restore,
                cross_gui_transferred=cross_gui_transferred,
                already_running=already_running,
            )
        )

    return CheckpointRevalidationReport(
        checkpoint_id=checkpoint.checkpoint_id,
        checked_at=now_utc_iso(),
        stale=checkpoint.stale or any_stale,
        stale_reasons=tuple(dict.fromkeys([*checkpoint.stale_reasons, *aggregate_reasons])),
        entries=tuple(results),
    )


@contextlib.contextmanager
def _checkpoint_lock(lock_path: Path, *, timeout_seconds: float = 10.0) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    with lock_path.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt

            while True:
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise ContinuityError(
                            ErrorCode.EVENT_SPOOL_UNAVAILABLE,
                            f"Timed out waiting for checkpoint lock {lock_path}.",
                        ) from exc
                    time.sleep(0.02)
            try:
                yield
            finally:
                with contextlib.suppress(OSError):
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            while True:
                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise ContinuityError(
                            ErrorCode.EVENT_SPOOL_UNAVAILABLE,
                            f"Timed out waiting for checkpoint lock {lock_path}.",
                        ) from exc
                    time.sleep(0.02)
            try:
                yield
            finally:
                with contextlib.suppress(OSError):
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class CheckpointStore:
    """Atomic, crash-safe file store for durable workspace checkpoints."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.checkpoints_dir = self.root_dir / "checkpoints"
        self.quarantine_dir = self.checkpoints_dir / "corrupt"
        self.index_path = self.checkpoints_dir / "index.json"
        self.lock_path = self.checkpoints_dir / ".checkpoint.lock"

    def create_checkpoint(
        self,
        slots: Sequence[WorkspaceSlotInput],
        *,
        label: str | None = None,
        observers: Mapping[tuple[str, str], RuntimeDiscovery] | RuntimeDiscovery | None = None,
        snapshots: Mapping[tuple[str, str], ProcessSnapshot] | ProcessSnapshot | None = None,
        include_unobserved: bool = False,
        checkpoint_id: str | None = None,
    ) -> WorkspaceCheckpoint:
        """Capture fresh batched observations and persist a durable checkpoint atomically."""
        preview = preview_checkpoint(
            slots,
            label=label,
            observers=observers,
            snapshots=snapshots,
            include_unobserved=include_unobserved,
        )
        cid = checkpoint_id or generate_id("chk")
        checkpoint = WorkspaceCheckpoint(
            checkpoint_id=cid,
            schema_version=CHECKPOINT_SCHEMA_VERSION,
            created_at=preview.captured_at,
            label=label,
            environment_ids=preview.environment_ids,
            sessions=preview.sessions,
            skipped_slots=preview.skipped_slots,
        )
        self.save_checkpoint(checkpoint)
        return checkpoint

    def save_checkpoint(self, checkpoint: WorkspaceCheckpoint) -> Path:
        """Persist a WorkspaceCheckpoint atomically and update the checkpoint index."""
        self.checkpoints_dir.mkdir(parents=True, exist_ok=True)
        target = self.checkpoints_dir / f"{checkpoint.checkpoint_id}.json"
        with _checkpoint_lock(self.lock_path):
            self._cleanup_stale_temps()
            atomic_write_json(target, checkpoint.to_dict())
            self._update_index_locked(checkpoint)
        return target

    def get_checkpoint(self, checkpoint_id: str) -> WorkspaceCheckpoint:
        """Load one checkpoint by ID, raising ContinuityError if missing or corrupt."""
        target = self.checkpoints_dir / f"{checkpoint_id}.json"
        if not target.exists():
            raise ContinuityError(
                ErrorCode.SESSION_NOT_FOUND,
                f"Workspace checkpoint {checkpoint_id!r} was not found.",
                {"checkpoint_id": checkpoint_id},
            )
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
            return WorkspaceCheckpoint.from_dict(payload)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ContinuityError(
                ErrorCode.MATERIALIZER_FAILED,
                f"Workspace checkpoint {checkpoint_id!r} is corrupt or unreadable: {exc}",
                {"checkpoint_id": checkpoint_id, "path": str(target)},
            ) from exc

    def list_checkpoints(
        self,
        *,
        quarantine_corrupt: bool = False,
    ) -> tuple[tuple[WorkspaceCheckpoint, ...], tuple[CorruptCheckpointRecord, ...]]:
        """List valid checkpoints newest-first while isolating corrupt/partial files."""
        if not self.checkpoints_dir.exists():
            return (), ()
        checkpoints: list[WorkspaceCheckpoint] = []
        corrupt: list[CorruptCheckpointRecord] = []
        for path in sorted(self.checkpoints_dir.glob("*.json")):
            if path.name == "index.json" or path.name.startswith(".tmp."):
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                checkpoints.append(WorkspaceCheckpoint.from_dict(payload))
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError, ContinuityError) as exc:
                corrupt.append(CorruptCheckpointRecord(path=str(path), error=str(exc)))
                if quarantine_corrupt:
                    with _checkpoint_lock(self.lock_path):
                        self.quarantine_dir.mkdir(parents=True, exist_ok=True)
                        dest = self.quarantine_dir / f"{path.stem}.{secrets.token_hex(3)}{path.suffix}"
                        with contextlib.suppress(OSError):
                            shutil.move(str(path), str(dest))
        checkpoints.sort(key=lambda item: (item.created_at, item.checkpoint_id), reverse=True)
        return tuple(checkpoints), tuple(corrupt)

    def mark_stale(self, checkpoint_id: str, reasons: Sequence[str]) -> WorkspaceCheckpoint:
        """Mark a persisted checkpoint stale with explicit reason codes."""
        with _checkpoint_lock(self.lock_path):
            existing = self.get_checkpoint(checkpoint_id)
            merged_reasons = tuple(dict.fromkeys([*existing.stale_reasons, *(str(r) for r in reasons)]))
            updated = WorkspaceCheckpoint(
                checkpoint_id=existing.checkpoint_id,
                schema_version=existing.schema_version,
                created_at=existing.created_at,
                label=existing.label,
                environment_ids=existing.environment_ids,
                sessions=existing.sessions,
                skipped_slots=existing.skipped_slots,
                stale=True,
                stale_reasons=merged_reasons,
            )
            atomic_write_json(self.checkpoints_dir / f"{checkpoint_id}.json", updated.to_dict())
            self._update_index_locked(updated)
            return updated

    def _cleanup_stale_temps(self) -> None:
        cutoff = time.time() - 60.0
        for tmp in self.checkpoints_dir.glob(".tmp.*.json"):
            with contextlib.suppress(OSError):
                if tmp.stat().st_mtime < cutoff:
                    tmp.unlink(missing_ok=True)

    def _update_index_locked(self, checkpoint: WorkspaceCheckpoint) -> None:
        entries: dict[str, dict[str, Any]] = {}
        if self.index_path.exists():
            with contextlib.suppress(OSError, json.JSONDecodeError, TypeError):
                raw = json.loads(self.index_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and isinstance(raw.get("checkpoints"), dict):
                    entries = dict(raw["checkpoints"])
        entries[checkpoint.checkpoint_id] = {
            "checkpoint_id": checkpoint.checkpoint_id,
            "created_at": checkpoint.created_at,
            "label": checkpoint.label,
            "session_count": len(checkpoint.sessions),
            "slot_ids": [item.slot_id for item in checkpoint.sessions],
            "stale": checkpoint.stale,
            "stale_reasons": list(checkpoint.stale_reasons),
        }
        atomic_write_json(
            self.index_path,
            {
                "schema_version": CHECKPOINT_SCHEMA_VERSION,
                "updated_at": datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"),
                "checkpoints": entries,
            },
        )
