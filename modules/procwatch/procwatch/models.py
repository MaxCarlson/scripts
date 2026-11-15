"""Typed event, identity, window, guard, and correlation models for ProcWatch."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


def utc_now_iso() -> str:
    """Return current UTC timestamp formatted to millisecond precision with Z suffix."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class MissingMetadataReason(StrEnum):
    """Explicit reasons why process or window metadata could not be captured."""

    NOT_EMITTED = "not_emitted"
    EXITED_BEFORE_ENRICHMENT = "exited_before_enrichment"
    ACCESS_DENIED = "access_denied"
    SOURCE_UNAVAILABLE = "source_unavailable"
    QUEUE_OVERFLOW = "queue_overflow"
    UNKNOWN = "unknown"


class WindowState(StrEnum):
    """Lifecycle states for an observed HWND instance."""

    FIRST_SEEN = "first_seen"
    PENDING = "pending"
    ALLOWED = "allowed"
    SUPPRESSED = "suppressed"
    RESTORED = "restored"
    DESTROYED = "destroyed"


class ConfidenceLevel(StrEnum):
    """Confidence levels for provisional causal correlation."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class CapabilityFlags:
    """Boolean capability flags indicating what telemetry was observed."""

    process_created: bool = False
    process_terminated: bool = False
    exit_code_known: bool = False
    window_observed: bool = False
    command_line_captured: bool = False
    ancestry_complete: bool = False


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    """Durable or provisional identity for a process lifetime (never PID alone)."""

    proc_key: str
    boot_id: str
    pid: int
    is_provisional: bool = True
    kernel_create_100ns: int | None = None
    sysmon_guid: str | None = None

    @classmethod
    def provisional(cls, boot_id: str, pid: int, monotonic_ns: int) -> ProcessIdentity:
        """Create a provisional identity keyed by boot, PID, and monotonic timestamp."""
        bucket_ms = monotonic_ns // 1_000_000
        return cls(
            proc_key=f"prov:{boot_id}:{pid}:{bucket_ms}",
            boot_id=boot_id,
            pid=pid,
            is_provisional=True,
        )

    @classmethod
    def canonical_kernel(cls, boot_id: str, pid: int, create_time_100ns: int) -> ProcessIdentity:
        """Create a canonical identity from verified kernel process creation time."""
        return cls(
            proc_key=f"canon:{boot_id}:{pid}:{create_time_100ns}",
            boot_id=boot_id,
            pid=pid,
            is_provisional=False,
            kernel_create_100ns=create_time_100ns,
        )


@dataclass(slots=True)
class ProcessObservation:
    """Observed lifecycle and metadata for a single process lifetime."""

    identity: ProcessIdentity
    ppid: int | None = None
    image_name: str = ""
    image_path: str | None = None
    command_line_redacted: str | None = None
    decoded_payload_redacted: str | None = None
    session_id: int | None = None
    start_ts_utc: str | None = None
    start_monotonic_ns: int | None = None
    exit_ts_utc: str | None = None
    exit_monotonic_ns: int | None = None
    exit_code: int | None = None
    exit_reason: str | None = None
    source: str = "unknown"
    capabilities: CapabilityFlags = field(default_factory=CapabilityFlags)
    missing_reasons: list[MissingMetadataReason] = field(default_factory=list)

    def add_missing_reason(self, reason: MissingMetadataReason) -> None:
        if reason not in self.missing_reasons:
            self.missing_reasons.append(reason)

    @property
    def is_alive(self) -> bool:
        return self.exit_ts_utc is None and self.exit_reason is None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ApiAttempt:
    """Result of a single Win32 API call during guard action or restoration."""

    api: str
    success: bool
    error_code: int = 0
    detail: str = ""


@dataclass(slots=True)
class GuardDecision:
    """Audit record for a guard classification and suppression/restoration attempt."""

    window_instance_id: str
    hwnd: int
    mode: str
    matched_rule: str
    reason: str
    intended_action: str
    observed_outcome: str
    attempted_apis: list[ApiAttempt] = field(default_factory=list)
    callback_latency_ms: float | None = None
    action_latency_ms: float | None = None
    timestamp_utc: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class WindowObservation:
    """Observed state and history of a single HWND lifetime instance."""

    window_instance_id: str
    hwnd: int
    owner_pid: int
    owner_tid: int
    window_class: str
    initial_title: str
    current_title: str
    title_history: list[str] = field(default_factory=list)
    became_visible: bool = False
    stole_foreground: bool = False
    first_seen_ts_utc: str = field(default_factory=utc_now_iso)
    first_seen_monotonic_ns: int = 0
    callback_arrival_ns: int = 0
    win_event: int = 0
    state: WindowState = WindowState.FIRST_SEEN
    destroy_ts_utc: str | None = None
    destroy_monotonic_ns: int | None = None
    foreground_target_hwnd: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CandidateInitiator:
    """Candidate initiating process correlated with a window observation."""

    proc_key: str
    pid: int
    image_name: str
    command_line_redacted: str | None
    confidence: ConfidenceLevel
    reasons: list[str] = field(default_factory=list)
    time_delta_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class LiveIncidentEvent:
    """Unified Phase 1 output event emitted by the correlator to renderers/JSONL."""

    event_type: str  # "window" | "process_start" | "process_stop" | "guard_decision"
    timestamp_utc: str
    monotonic_ns: int
    window: WindowObservation | None = None
    process: ProcessObservation | None = None
    guard_decision: GuardDecision | None = None
    candidate_initiators: list[CandidateInitiator] = field(default_factory=list)
    ancestry_chain: list[ProcessObservation] = field(default_factory=list)
    collapsed_ancestry_chain: list[ProcessObservation] = field(default_factory=list)
    missing_reasons: list[MissingMetadataReason] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CollectorStats:
    """Runtime telemetry counters for collectors and guard."""

    win_events_received: int = 0
    win_events_dropped: int = 0
    wmi_starts_received: int = 0
    wmi_stops_received: int = 0
    wmi_events_dropped: int = 0
    wmi_status: str = "uninitialized"
    guard_suppressed_count: int = 0
    guard_allowed_count: int = 0
    guard_pending_count: int = 0
    guard_errors: int = 0
