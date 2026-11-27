"""Read-only runtime observations for exact native agent sessions.

Raw process arguments are inspected only in memory by exact-session matchers. They
are never included in observations, evidence details, reprs, logs, or persistence.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol

__all__ = [
    "AgySessionStore",
    "AttachmentState",
    "CodexSessionStore",
    "EvidenceAvailability",
    "EvidenceConfidence",
    "ManagedPaneReference",
    "ManagedLaunchAssociation",
    "ManagedReceiptSnapshot",
    "ManagedReceiptSource",
    "ManagementState",
    "MatchStatus",
    "ObservedProcess",
    "ProcessAncestry",
    "ProcessEnumerator",
    "ProcessIdentity",
    "ProcessInventory",
    "ProcessLiveness",
    "ProcessRecord",
    "ProcessSessionMatcher",
    "ProviderActivity",
    "PsutilProcessEnumerator",
    "RuntimeDiscovery",
    "RuntimeEvidence",
    "SessionKey",
    "SessionRuntimeObservation",
    "TerminalLauncherManagedReceiptSource",
    "TerminalLauncherStore",
    "managed_pane_reference_from_terminal_launcher_record",
    "match_agy_invocation",
    "match_claude_invocation",
    "match_codex_invocation",
    "process_identity_from_windows_filetime",
]


class EvidenceAvailability(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class EvidenceConfidence(StrEnum):
    EXACT = "exact"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class ProcessLiveness(StrEnum):
    RUNNING = "running"
    EXITED = "exited"
    NOT_OBSERVED = "not_observed"
    UNKNOWN = "unknown"
    AMBIGUOUS = "ambiguous"


class AttachmentState(StrEnum):
    ATTACHED = "attached"
    DETACHED = "detached"
    UNKNOWN = "unknown"


class ManagementState(StrEnum):
    MANAGED = "managed"
    UNMANAGED = "unmanaged"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"


class MatchStatus(StrEnum):
    EXACT = "exact"
    NOT_OBSERVED = "not_observed"
    UNKNOWN = "unknown"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class SessionKey:
    provider: str
    native_session_id: str
    environment_id: str | None = None
    runtime_kind: str = "local"

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.native_session_id.strip() or not self.runtime_kind.strip():
            raise ValueError("provider, native_session_id, and runtime_kind must be non-empty")


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    pid: int
    creation_time_ns: int

    def __post_init__(self) -> None:
        if self.pid <= 0 or self.creation_time_ns <= 0:
            raise ValueError("process identity requires positive PID and creation time")


@dataclass(frozen=True, slots=True, repr=False)
class ProcessRecord:
    """Transient process row. The private argv field is omitted from repr and output."""

    identity: ProcessIdentity | None
    parent_pid: int | None
    image_name: str | None
    argv: tuple[str, ...] | None = field(default=None, repr=False, compare=False)

    def __repr__(self) -> str:
        return (
            f"ProcessRecord(identity={self.identity!r}, parent_pid={self.parent_pid!r}, "
            f"image_name={self.image_name!r}, argv=<redacted>)"
        )


@dataclass(frozen=True, slots=True)
class ProcessInventory:
    records: tuple[ProcessRecord, ...]
    availability: EvidenceAvailability
    captured_at: datetime
    inaccessible_count: int = 0
    error_code: str | None = None

    def __repr__(self) -> str:
        return (
            f"ProcessInventory(records={self.records!r}, availability={self.availability.value!r}, "
            f"captured_at={self.captured_at!r}, inaccessible_count={self.inaccessible_count}, "
            f"error_code={self.error_code!r})"
        )


class ProcessEnumerator(Protocol):
    def enumerate_processes(self) -> ProcessInventory:
        """Return a read-only point-in-time inventory."""


class PsutilProcessEnumerator:
    """Optional psutil-backed process inventory; access gaps are reported, never guessed."""

    def enumerate_processes(self) -> ProcessInventory:
        started = datetime.now(UTC)
        try:
            import psutil
        except ImportError:
            return ProcessInventory((), EvidenceAvailability.UNAVAILABLE, started, error_code="psutil_unavailable")
        rows: list[ProcessRecord] = []
        inaccessible = 0
        try:
            iterator = psutil.process_iter(
                attrs=("pid", "ppid", "name", "create_time", "cmdline"), ad_value=None
            )
            for process in iterator:
                try:
                    info = process.info
                    pid, created, argv_value = info.get("pid"), info.get("create_time"), info.get("cmdline")
                    identity = (
                        ProcessIdentity(int(pid), int(round(float(created) * 1_000_000_000)))
                        if pid and created else None
                    )
                    rows.append(ProcessRecord(
                        identity=identity,
                        parent_pid=int(info["ppid"]) if info.get("ppid") is not None else None,
                        image_name=Path(str(info.get("name") or "")).name or None,
                        argv=tuple(str(part) for part in argv_value) if argv_value is not None else None,
                    ))
                    if identity is None or argv_value is None:
                        inaccessible += 1
                except (psutil.NoSuchProcess, psutil.ZombieProcess, psutil.AccessDenied):
                    inaccessible += 1
        except (OSError, psutil.Error):
            return ProcessInventory(
                tuple(rows), EvidenceAvailability.PARTIAL if rows else EvidenceAvailability.UNAVAILABLE,
                datetime.now(UTC), inaccessible + 1, "process_enumeration_failed",
            )
        state = EvidenceAvailability.PARTIAL if inaccessible else EvidenceAvailability.COMPLETE
        return ProcessInventory(tuple(rows), state, datetime.now(UTC), inaccessible)


@dataclass(frozen=True, slots=True)
class ProviderActivity:
    availability: EvidenceAvailability
    found: bool | None
    last_activity_at: datetime | None
    source: str
    captured_at: datetime
    last_turn_at: datetime | None = None
    error_code: str | None = None


class SessionStore(Protocol):
    def observe(self, key: SessionKey) -> ProviderActivity:
        """Read metadata for this exact ID, never by recency ordering."""


class ProcessSessionMatcher(Protocol):
    def __call__(self, argv: Sequence[str] | None, native_session_id: str) -> bool:
        """Return whether transient argv identifies this exact provider session."""


class CodexSessionStore:
    """Exact-ID, read-only lookup in Codex state_5.sqlite."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or Path.home() / ".codex" / "state_5.sqlite"

    def observe(self, key: SessionKey) -> ProviderActivity:
        if key.provider != "codex":
            return _unavailable_store("codex_state_sqlite", "unsupported_provider")
        captured = datetime.now(UTC)
        if not self.db_path.exists():
            return _unavailable_store("codex_state_sqlite", "store_missing", captured)
        try:
            connection = _open_readonly(self.db_path)
            try:
                row = connection.execute(
                    "SELECT updated_at FROM threads WHERE id = ?", (key.native_session_id,)
                ).fetchone()
            finally:
                connection.close()
        except (OSError, sqlite3.Error):
            return ProviderActivity(
                EvidenceAvailability.PARTIAL, None, None, "codex_state_sqlite", captured,
                error_code="store_unavailable",
            )
        return ProviderActivity(
            EvidenceAvailability.COMPLETE, row is not None,
            _parse_timestamp(row[0]) if row else None, "codex_state_sqlite", captured,
        )


class AgySessionStore:
    """Exact-ID, read-only lookup in AGY conversation_summaries.db."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or (
            Path.home() / ".gemini" / "antigravity-cli" / "conversation_summaries.db"
        )

    def observe(self, key: SessionKey) -> ProviderActivity:
        if key.provider != "agy":
            return _unavailable_store("agy_summary_sqlite", "unsupported_provider")
        captured = datetime.now(UTC)
        if not self.db_path.exists():
            return _unavailable_store("agy_summary_sqlite", "store_missing", captured)
        try:
            connection = _open_readonly(self.db_path)
            try:
                row = connection.execute(
                    "SELECT last_modified_time, last_user_input_time "
                    "FROM conversation_summaries WHERE conversation_id = ?",
                    (key.native_session_id,),
                ).fetchone()
            finally:
                connection.close()
        except (OSError, sqlite3.Error):
            return ProviderActivity(
                EvidenceAvailability.PARTIAL, None, None, "agy_summary_sqlite", captured,
                error_code="store_unavailable",
            )
        return ProviderActivity(
            EvidenceAvailability.COMPLETE, row is not None,
            _parse_timestamp(row[0]) if row else None, "agy_summary_sqlite", captured,
            last_turn_at=_parse_timestamp(row[1]) if row else None,
        )


def _open_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=0.5)


def _parse_timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        seconds = float(value)
        if abs(seconds) > 100_000_000_000:
            seconds /= 1000
        try:
            return datetime.fromtimestamp(seconds, UTC)
        except (OverflowError, OSError, ValueError):
            return None
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            try:
                return _parse_timestamp(float(value))
            except ValueError:
                return None
    else:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _unavailable_store(source: str, code: str, captured: datetime | None = None) -> ProviderActivity:
    return ProviderActivity(
        EvidenceAvailability.UNAVAILABLE, None, None, source, captured or datetime.now(UTC),
        error_code=code,
    )


def match_codex_invocation(argv: Sequence[str] | None, native_session_id: str) -> bool:
    """Match only codex resume with the exact next positional ID."""
    if not argv or not _has_provider_executable(argv, "codex"):
        return False
    for index, token in enumerate(argv):
        if str(token).casefold() == "resume":
            candidate = next(
                (str(part) for part in argv[index + 1 :] if not str(part).startswith("-")), None
            )
            return candidate == native_session_id
    return False


def match_agy_invocation(argv: Sequence[str] | None, native_session_id: str) -> bool:
    """Match AGY's exact --conversation ID form."""
    if not argv or not _has_provider_executable(argv, "agy"):
        return False
    for index, token in enumerate(argv):
        text = str(token)
        if text == "--conversation" and index + 1 < len(argv):
            return str(argv[index + 1]) == native_session_id
        if text.startswith("--conversation="):
            return text.partition("=")[2] == native_session_id
    return False


def match_claude_invocation(argv: Sequence[str] | None, native_session_id: str) -> bool:
    """Match Claude Code's exact ``--resume <session-id>`` invocation."""
    if not argv or not _has_provider_executable(argv, "claude"):
        return False
    for index, token in enumerate(argv):
        if str(token).casefold() == "--resume" and index + 1 < len(argv):
            return str(argv[index + 1]) == native_session_id
    return False


def _has_provider_executable(argv: Sequence[str], provider: str) -> bool:
    names = {provider, f"{provider}.exe", f"{provider}.cmd", f"{provider}.ps1"}
    if provider == "codex":
        names.update({"codex.js", "codex.mjs", "codex-cli", "codex-cli.js"})
    elif provider == "agy":
        names.update({"agy.js", "agy.mjs", "agy-cli.js"})
    elif provider == "claude":
        names.update({"claude.js", "claude.mjs", "claude-cli.js"})
    return any(Path(str(token).strip('"')).name.casefold() in names for token in argv[:4])


_DEFAULT_PROCESS_MATCHERS: Mapping[str, ProcessSessionMatcher] = {
    "codex": match_codex_invocation,
    "agy": match_agy_invocation,
    "claude": match_claude_invocation,
}


@dataclass(frozen=True, slots=True)
class ManagedPaneReference:
    provider: str
    native_session_id: str
    environment_id: str | None
    process_identity: ProcessIdentity
    launch_id: str
    pane_id: str
    terminal_session_id: str


_WINDOWS_FILETIME_UNIX_EPOCH_100NS = 116_444_736_000_000_000


def process_identity_from_windows_filetime(pid: int, creation_filetime: int) -> ProcessIdentity:
    """Normalize Terminal Launcher's FILETIME into Unix-nanosecond process identity."""
    created_ns = (int(creation_filetime) - _WINDOWS_FILETIME_UNIX_EPOCH_100NS) * 100
    return ProcessIdentity(pid=pid, creation_time_ns=created_ns)


def managed_pane_reference_from_terminal_launcher_record(
    key: SessionKey,
    record: object,
    *,
    terminal_session_id: str,
) -> ManagedPaneReference | None:
    """Adapt a 0.2.0 receipt by duck typing, without importing Terminal Launcher."""
    if not bool(getattr(record, "spawn_acknowledged", False)):
        return None
    pid = getattr(record, "pid", None)
    created = getattr(record, "process_created", None)
    launch_id = getattr(record, "launch_id", None)
    pane_id = getattr(record, "pane_id", None)
    if not all((pid, created, launch_id, pane_id, terminal_session_id)):
        return None
    try:
        process_identity = process_identity_from_windows_filetime(int(pid), int(created))
    except (TypeError, ValueError):
        return None
    return ManagedPaneReference(
        provider=key.provider,
        native_session_id=key.native_session_id,
        environment_id=key.environment_id,
        process_identity=process_identity,
        launch_id=str(launch_id),
        pane_id=str(pane_id),
        terminal_session_id=terminal_session_id,
    )


@dataclass(frozen=True, slots=True)
class ManagedReceiptSnapshot:
    references: tuple[ManagedPaneReference, ...]
    availability: EvidenceAvailability
    captured_at: datetime
    error_code: str | None = None


class ManagedReceiptSource(Protocol):
    def observe(self, key: SessionKey) -> ManagedReceiptSnapshot:
        """Return joined registry/terminal receipts; this protocol has no package dependency."""


@dataclass(frozen=True, slots=True)
class ManagedLaunchAssociation:
    launch_id: str
    terminal_session_id: str


class TerminalLauncherStore(Protocol):
    def enumerate_processes(self, *, launch_id: str | None = None) -> Sequence[object]:
        """Structural subset implemented by Terminal Launcher 0.2.0 ManagedProcessStore."""


class TerminalLauncherManagedReceiptSource:
    """Optional duck-typed bridge from exact LLMD links to Terminal Launcher 0.2.0 receipts."""

    def __init__(
        self,
        store: TerminalLauncherStore,
        associations_for_session: Callable[[SessionKey], Sequence[ManagedLaunchAssociation]],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.associations_for_session = associations_for_session
        self.clock = clock or (lambda: datetime.now(UTC))

    def observe(self, key: SessionKey) -> ManagedReceiptSnapshot:
        captured = self.clock()
        try:
            associations = tuple(self.associations_for_session(key))
        except Exception:
            return ManagedReceiptSnapshot(
                (), EvidenceAvailability.PARTIAL, captured, "association_lookup_failed"
            )
        references: list[ManagedPaneReference] = []
        failed = False
        seen: set[tuple[str, str]] = set()
        for association in associations:
            association_key = (association.launch_id, association.terminal_session_id)
            if association_key in seen:
                continue
            seen.add(association_key)
            try:
                records = self.store.enumerate_processes(launch_id=association.launch_id)
            except Exception:
                failed = True
                continue
            for record in records:
                reference = managed_pane_reference_from_terminal_launcher_record(
                    key, record, terminal_session_id=association.terminal_session_id
                )
                if reference is not None:
                    references.append(reference)
        return ManagedReceiptSnapshot(
            tuple(references),
            EvidenceAvailability.PARTIAL if failed else EvidenceAvailability.COMPLETE,
            captured,
            "receipt_query_failed" if failed else None,
        )


@dataclass(frozen=True, slots=True)
class RuntimeEvidence:
    source: str
    code: str
    availability: EvidenceAvailability
    confidence: EvidenceConfidence
    captured_at: datetime
    process_identity: ProcessIdentity | None = None
    safe_values: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ProcessAncestry:
    identities: tuple[ProcessIdentity, ...]
    image_names: tuple[str, ...]
    complete: bool
    ambiguous: bool


@dataclass(frozen=True, slots=True)
class ObservedProcess:
    """Safe process identity exposed by the high-level observation API."""

    identity: ProcessIdentity | None
    parent_pid: int | None
    image_name: str | None


@dataclass(frozen=True, slots=True)
class SessionRuntimeObservation:
    key: SessionKey
    captured_at: datetime
    process_liveness: ProcessLiveness
    known_process_liveness: ProcessLiveness
    process_session_match: MatchStatus
    interactive_attachment: AttachmentState
    attachment_confidence: EvidenceConfidence
    management: ManagementState
    availability: EvidenceAvailability
    process_availability: EvidenceAvailability
    provider_store_availability: EvidenceAvailability
    managed_receipt_availability: EvidenceAvailability
    confidence: EvidenceConfidence
    provider_session_found: bool | None
    provider_activity_at: datetime | None
    provider_last_turn_at: datetime | None
    registry_association: bool | None
    processes: tuple[ObservedProcess, ...]
    ancestry: tuple[ProcessAncestry, ...]
    managed_pane: ManagedPaneReference | None
    identity_conflict: bool
    evidence_conflict: bool
    evidence: tuple[RuntimeEvidence, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.key.provider,
            "native_session_id": self.key.native_session_id,
            "environment_id": self.key.environment_id,
            "runtime_kind": self.key.runtime_kind,
            "captured_at": self.captured_at.isoformat(),
            "process_liveness": self.process_liveness.value,
            "known_process_liveness": self.known_process_liveness.value,
            "process_session_match": self.process_session_match.value,
            "interactive_attachment": self.interactive_attachment.value,
            "attachment_confidence": self.attachment_confidence.value,
            "management": self.management.value,
            "availability": self.availability.value,
            "process_availability": self.process_availability.value,
            "provider_store_availability": self.provider_store_availability.value,
            "managed_receipt_availability": self.managed_receipt_availability.value,
            "confidence": self.confidence.value,
            "provider_session_found": self.provider_session_found,
            "provider_activity_at": self.provider_activity_at.isoformat() if self.provider_activity_at else None,
            "provider_last_turn_at": self.provider_last_turn_at.isoformat() if self.provider_last_turn_at else None,
            "registry_association": self.registry_association,
            "processes": [
                {
                    "pid": item.identity.pid if item.identity else None,
                    "creation_time_ns": item.identity.creation_time_ns if item.identity else None,
                    "image_name": item.image_name,
                    "parent_pid": item.parent_pid,
                }
                for item in self.processes
            ],
            "ancestry": [
                {
                    "identities": [
                        {"pid": identity.pid, "creation_time_ns": identity.creation_time_ns}
                        for identity in item.identities
                    ],
                    "image_names": list(item.image_names),
                    "complete": item.complete,
                    "ambiguous": item.ambiguous,
                }
                for item in self.ancestry
            ],
            "managed_pane": (
                {
                    "launch_id": self.managed_pane.launch_id,
                    "pane_id": self.managed_pane.pane_id,
                    "terminal_session_id": self.managed_pane.terminal_session_id,
                    "process_pid": self.managed_pane.process_identity.pid,
                    "process_creation_time_ns": self.managed_pane.process_identity.creation_time_ns,
                }
                if self.managed_pane else None
            ),
            "identity_conflict": self.identity_conflict,
            "evidence_conflict": self.evidence_conflict,
            "evidence": [
                {
                    "source": item.source,
                    "code": item.code,
                    "availability": item.availability.value,
                    "confidence": item.confidence.value,
                    "captured_at": item.captured_at.isoformat(),
                    "process_pid": item.process_identity.pid if item.process_identity else None,
                    "process_creation_time_ns": (
                        item.process_identity.creation_time_ns if item.process_identity else None
                    ),
                    "safe_values": dict(item.safe_values),
                }
                for item in self.evidence
            ],
        }


class RuntimeDiscovery:
    """Read-only exact-session observer scoped to one environment.

    To observe WSL or a remote runtime, construct another instance with explicit
    sources for that runtime. This class never starts a runtime or provider.
    """

    def __init__(
        self,
        *,
        process_enumerator: ProcessEnumerator | None = None,
        provider_stores: Mapping[str, SessionStore] | None = None,
        process_matchers: Mapping[str, ProcessSessionMatcher] | None = None,
        managed_receipt_source: ManagedReceiptSource | None = None,
        runtime_kind: str = "local",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.runtime_kind = runtime_kind
        self.process_enumerator = process_enumerator or (
            PsutilProcessEnumerator() if runtime_kind == "local" else _UnavailableProcessEnumerator()
        )
        if provider_stores is not None:
            self.provider_stores = dict(provider_stores)
        elif runtime_kind == "local":
            home = Path.home()
            self.provider_stores = {
                "codex": CodexSessionStore(home / ".codex" / "state_5.sqlite"),
                "agy": AgySessionStore(home / ".gemini" / "antigravity-cli" / "conversation_summaries.db"),
            }
        else:
            self.provider_stores = {}
        self.managed_receipt_source = managed_receipt_source
        self.process_matchers = dict(_DEFAULT_PROCESS_MATCHERS)
        if process_matchers is not None:
            self.process_matchers.update(process_matchers)
        self.clock = clock or (lambda: datetime.now(UTC))

    def observe(
        self,
        key: SessionKey,
        *,
        registry_association: bool | None = None,
        known_process: ProcessIdentity | None = None,
    ) -> SessionRuntimeObservation:
        captured = self.clock()
        if key.runtime_kind != self.runtime_kind:
            inventory = ProcessInventory((), EvidenceAvailability.UNAVAILABLE, captured, error_code="runtime_mismatch")
            activity = _unavailable_store("provider_store", "runtime_mismatch", captured)
            receipt_snapshot = ManagedReceiptSnapshot((), EvidenceAvailability.UNAVAILABLE, captured, "runtime_mismatch")
        else:
            try:
                inventory = self.process_enumerator.enumerate_processes()
            except Exception:
                inventory = ProcessInventory((), EvidenceAvailability.UNAVAILABLE, self.clock(), error_code="process_source_error")
            store = self.provider_stores.get(key.provider)
            if store is None:
                activity = _unavailable_store("provider_store", "provider_store_unconfigured", self.clock())
            else:
                try:
                    activity = store.observe(key)
                except Exception:
                    activity = ProviderActivity(
                        EvidenceAvailability.PARTIAL, None, None, "provider_store", self.clock(),
                        error_code="provider_store_error",
                    )
            if self.managed_receipt_source is None:
                receipt_snapshot = ManagedReceiptSnapshot(
                    (), EvidenceAvailability.UNAVAILABLE, self.clock(), "receipt_source_unconfigured"
                )
            else:
                try:
                    receipt_snapshot = self.managed_receipt_source.observe(key)
                except Exception:
                    receipt_snapshot = ManagedReceiptSnapshot(
                        (), EvidenceAvailability.PARTIAL, self.clock(), "receipt_source_error"
                    )

        matching_records = tuple(
            row for row in inventory.records
            if row.argv is not None and _matches_provider_invocation(
                key.provider, row.argv, key.native_session_id, self.process_matchers
            )
        )
        matching_refs = tuple(ref for ref in receipt_snapshot.references if _reference_matches(ref, key))
        evidence: list[RuntimeEvidence] = [
            RuntimeEvidence(
                "process_enumeration",
                inventory.error_code or "process_snapshot",
                inventory.availability,
                EvidenceConfidence.HIGH if inventory.availability is EvidenceAvailability.COMPLETE else EvidenceConfidence.NONE,
                inventory.captured_at,
                safe_values=(("inaccessible_count", str(inventory.inaccessible_count)),),
            )
        ]
        if matching_records:
            evidence.extend(
                RuntimeEvidence(
                    "process_arguments", "exact_session_argument_match", inventory.availability,
                    EvidenceConfidence.EXACT, inventory.captured_at, row.identity,
                )
                for row in matching_records
            )
        if activity.found is True:
            evidence.append(RuntimeEvidence(
                activity.source, "provider_session_found", activity.availability,
                EvidenceConfidence.MEDIUM, activity.captured_at,
            ))
        elif activity.found is False:
            evidence.append(RuntimeEvidence(
                activity.source, "provider_session_not_found", activity.availability,
                EvidenceConfidence.MEDIUM, activity.captured_at,
            ))
        else:
            evidence.append(RuntimeEvidence(
                activity.source, activity.error_code or "provider_store_unavailable",
                activity.availability, EvidenceConfidence.NONE, activity.captured_at,
            ))
        if self.managed_receipt_source is not None:
            evidence.append(RuntimeEvidence(
                "managed_receipt", "managed_receipt_found" if matching_refs else "managed_receipt_not_found",
                receipt_snapshot.availability,
                EvidenceConfidence.HIGH if matching_refs else EvidenceConfidence.LOW,
                receipt_snapshot.captured_at,
            ))
        if registry_association is not None:
            evidence.append(RuntimeEvidence(
                "registry_association",
                "exact_registry_association" if registry_association else "no_registry_association",
                EvidenceAvailability.COMPLETE, EvidenceConfidence.HIGH, captured,
            ))

        if len(matching_records) > 1:
            process_match, process_state = MatchStatus.AMBIGUOUS, ProcessLiveness.AMBIGUOUS
        elif matching_records:
            process_match = MatchStatus.EXACT
            process_state = ProcessLiveness.RUNNING if matching_records[0].identity else ProcessLiveness.UNKNOWN
        elif len(matching_refs) > 1:
            process_match, process_state = MatchStatus.AMBIGUOUS, ProcessLiveness.AMBIGUOUS
        elif matching_refs:
            process_match = MatchStatus.EXACT
            process_state = _known_process_state(inventory, matching_refs[0].process_identity)
        elif known_process is not None:
            process_state = _known_process_state(inventory, known_process)
            process_match = (
                MatchStatus.EXACT if process_state is ProcessLiveness.RUNNING
                else MatchStatus.NOT_OBSERVED if process_state is ProcessLiveness.EXITED
                else MatchStatus.UNKNOWN
            )
        elif inventory.availability is EvidenceAvailability.COMPLETE:
            process_match, process_state = MatchStatus.NOT_OBSERVED, ProcessLiveness.NOT_OBSERVED
        else:
            process_match, process_state = MatchStatus.UNKNOWN, ProcessLiveness.UNKNOWN

        known_state = _known_process_state(inventory, known_process) if known_process else ProcessLiveness.UNKNOWN
        identity_conflict = False
        evidence_conflict = len(matching_refs) > 1
        if len(matching_refs) > 1:
            evidence.append(RuntimeEvidence(
                "managed_receipt", "multiple_managed_session_references",
                receipt_snapshot.availability, EvidenceConfidence.NONE, receipt_snapshot.captured_at,
            ))
        for ref in matching_refs:
            same_pid = [row for row in inventory.records if row.identity and row.identity.pid == ref.process_identity.pid]
            if same_pid and not any(row.identity == ref.process_identity for row in same_pid):
                identity_conflict = True
                evidence_conflict = True
                evidence.append(RuntimeEvidence(
                    "process_identity", "pid_creation_time_mismatch", inventory.availability,
                    EvidenceConfidence.HIGH, inventory.captured_at, ref.process_identity,
                ))
        if known_process:
            same_pid = [row for row in inventory.records if row.identity and row.identity.pid == known_process.pid]
            if same_pid and not any(row.identity == known_process for row in same_pid):
                identity_conflict = True
                evidence_conflict = True
            if known_state is ProcessLiveness.RUNNING:
                evidence.append(RuntimeEvidence(
                    "process_identity", "known_process_identity_live", inventory.availability,
                    EvidenceConfidence.HIGH, inventory.captured_at, known_process,
                ))
            elif known_state is ProcessLiveness.EXITED:
                evidence.append(RuntimeEvidence(
                    "process_identity", "known_process_identity_exited", inventory.availability,
                    EvidenceConfidence.HIGH, inventory.captured_at, known_process,
                ))
        if matching_records and activity.found is False:
            evidence_conflict = True
            evidence.append(RuntimeEvidence(
                "cross_source", "process_match_missing_from_provider_store",
                activity.availability, EvidenceConfidence.MEDIUM, activity.captured_at,
                matching_records[0].identity,
            ))

        ancestry: list[ProcessAncestry] = []
        attachment, attachment_confidence = AttachmentState.UNKNOWN, EvidenceConfidence.NONE
        for row in matching_records:
            chain, chain_evidence, complete, ambiguous = _process_ancestry(row, inventory)
            ancestry.append(chain)
            evidence.extend(chain_evidence)
            if ambiguous:
                continue
            if any(_is_terminal_host(name) for name in chain.image_names):
                attachment = AttachmentState.ATTACHED
                attachment_confidence = EvidenceConfidence.HIGH if complete else EvidenceConfidence.MEDIUM
            elif complete and any(_is_background_host(name) for name in chain.image_names):
                attachment = AttachmentState.DETACHED
                attachment_confidence = EvidenceConfidence.MEDIUM
        if not matching_records and matching_refs:
            for ref in matching_refs:
                if any(row.identity == ref.process_identity for row in inventory.records):
                    attachment, attachment_confidence = AttachmentState.ATTACHED, EvidenceConfidence.EXACT
        if process_state is ProcessLiveness.AMBIGUOUS:
            attachment, attachment_confidence = AttachmentState.UNKNOWN, EvidenceConfidence.NONE
        if identity_conflict or len(matching_refs) > 1:
            attachment, attachment_confidence = AttachmentState.UNKNOWN, EvidenceConfidence.NONE

        if matching_refs and not identity_conflict and len(matching_refs) == 1:
            management = ManagementState.MANAGED
        elif matching_refs and (identity_conflict or len(matching_refs) > 1):
            management = ManagementState.CONFLICT
        elif self.managed_receipt_source is None or receipt_snapshot.availability is not EvidenceAvailability.COMPLETE:
            management = ManagementState.UNKNOWN
        else:
            management = ManagementState.UNMANAGED
        confidence = (
            EvidenceConfidence.EXACT
            if process_match is MatchStatus.EXACT and matching_records and matching_records[0].identity
            else EvidenceConfidence.LOW if process_match is MatchStatus.AMBIGUOUS
            else EvidenceConfidence.HIGH
            if process_match is MatchStatus.EXACT and known_state is ProcessLiveness.RUNNING
            else EvidenceConfidence.HIGH if matching_refs
            else EvidenceConfidence.MEDIUM if activity.found is True
            else EvidenceConfidence.LOW if registry_association is True
            else EvidenceConfidence.NONE
        )
        availability = _combined_availability(
            inventory.availability, activity.availability,
            receipt_snapshot.availability if self.managed_receipt_source is not None else None,
        )
        return SessionRuntimeObservation(
            key, captured, process_state, known_state, process_match, attachment,
            attachment_confidence, management, availability, inventory.availability,
            activity.availability, receipt_snapshot.availability, confidence,
            activity.found, activity.last_activity_at, activity.last_turn_at,
            registry_association,
            tuple(ObservedProcess(row.identity, row.parent_pid, row.image_name) for row in matching_records),
            tuple(ancestry),
            matching_refs[0] if len(matching_refs) == 1 else None,
            identity_conflict, evidence_conflict, tuple(evidence),
        )


class _UnavailableProcessEnumerator:
    def enumerate_processes(self) -> ProcessInventory:
        return ProcessInventory(
            (), EvidenceAvailability.UNAVAILABLE, datetime.now(UTC),
            error_code="process_source_unconfigured",
        )


def _known_process_state(inventory: ProcessInventory, identity: ProcessIdentity) -> ProcessLiveness:
    same_pid = [row for row in inventory.records if row.identity and row.identity.pid == identity.pid]
    if any(row.identity == identity for row in same_pid):
        return ProcessLiveness.RUNNING
    if same_pid:
        return ProcessLiveness.EXITED
    return (
        ProcessLiveness.EXITED
        if inventory.availability is EvidenceAvailability.COMPLETE else ProcessLiveness.UNKNOWN
    )


def _matches_provider_invocation(
    provider: str,
    argv: Sequence[str],
    session_id: str,
    matchers: Mapping[str, ProcessSessionMatcher] | None = None,
) -> bool:
    matcher = (matchers or _DEFAULT_PROCESS_MATCHERS).get(provider)
    return matcher(argv, session_id) if matcher is not None else False


def _reference_matches(ref: ManagedPaneReference, key: SessionKey) -> bool:
    if ref.provider != key.provider or ref.native_session_id != key.native_session_id:
        return False
    return ref.environment_id == key.environment_id


def _process_ancestry(
    record: ProcessRecord, inventory: ProcessInventory
) -> tuple[ProcessAncestry, list[RuntimeEvidence], bool, bool]:
    by_pid: dict[int, list[ProcessRecord]] = defaultdict(list)
    for row in inventory.records:
        if row.identity:
            by_pid[row.identity.pid].append(row)
    identities: list[ProcessIdentity] = []
    names: list[str] = []
    evidence: list[RuntimeEvidence] = []
    current, complete, ambiguous = record, True, False
    seen = {record.identity.pid} if record.identity else set()
    for _ in range(64):
        parent_pid = current.parent_pid
        if parent_pid is None:
            complete = False
            break
        if parent_pid == 0:
            break
        if parent_pid in seen:
            complete, ambiguous = False, True
            break
        candidates = by_pid.get(parent_pid, [])
        if len(candidates) != 1:
            complete, ambiguous = False, len(candidates) > 1
            break
        parent = candidates[0]
        if (
            parent.identity is None or current.identity is None
            or parent.identity.creation_time_ns > current.identity.creation_time_ns
        ):
            complete, ambiguous = False, True
            break
        identities.append(parent.identity)
        if parent.image_name:
            names.append(Path(parent.image_name).name.casefold())
        seen.add(parent_pid)
        current = parent
    else:
        complete, ambiguous = False, True
    if ambiguous or not complete:
        evidence.append(RuntimeEvidence(
            "process_ancestry",
            "ambiguous_ancestry" if ambiguous else "ancestry_incomplete",
            inventory.availability, EvidenceConfidence.NONE, inventory.captured_at,
        ))
    return ProcessAncestry(tuple(identities), tuple(names), complete, ambiguous), evidence, complete, ambiguous


def _is_terminal_host(name: str) -> bool:
    return name.casefold() in {"windowsterminal.exe", "openconsole.exe"}


def _is_background_host(name: str) -> bool:
    return name.casefold() in {"taskhostw.exe", "taskeng.exe", "services.exe"}


def _combined_availability(*values: EvidenceAvailability | None) -> EvidenceAvailability:
    present = [value for value in values if value is not None]
    if not present or all(value is EvidenceAvailability.UNAVAILABLE for value in present):
        return EvidenceAvailability.UNAVAILABLE
    if any(value is not EvidenceAvailability.COMPLETE for value in present):
        return EvidenceAvailability.PARTIAL
    return EvidenceAvailability.COMPLETE
