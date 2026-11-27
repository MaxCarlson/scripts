"""Read-only runtime observations for exact native agent sessions.

Raw process arguments are inspected only in memory by exact-session matchers. They
are never included in observations, evidence details, reprs, logs, or persistence.
"""

from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
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
    "ManagedAssociationState",
    "ManagedLaunchAssociation",
    "ManagedReceiptSnapshot",
    "ManagedReceiptSource",
    "ManagementState",
    "MatchStatus",
    "ObservedProcess",
    "ProcessAncestry",
    "ProcessEnumerator",
    "ProcessIdentity",
    "IdentityComparison",
    "ProcessInventory",
    "ProcessSnapshot",
    "ProcessLiveness",
    "ProcessRecord",
    "ProcessSessionMatcher",
    "ProviderActivity",
    "PsutilProcessEnumerator",
    "RuntimeDiscovery",
    "RuntimeEvidence",
    "SessionKey",
    "SessionIdentityState",
    "SessionRuntimeObservation",
    "TerminalLauncherManagedReceiptSource",
    "TerminalLauncherStore",
    "managed_pane_reference_from_terminal_launcher_record",
    "match_agy_invocation",
    "match_claude_invocation",
    "match_codex_invocation",
    "process_identity_from_windows_filetime",
    "process_identity_from_psutil",
    "compare_process_identities",
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
    HISTORICAL = "historical"
    UNMANAGED = "unmanaged"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"


class MatchStatus(StrEnum):
    EXACT = "exact"
    NOT_OBSERVED = "not_observed"
    UNKNOWN = "unknown"
    AMBIGUOUS = "ambiguous"


class IdentityComparison(StrEnum):
    SAME = "same"
    DIFFERENT = "different"
    AMBIGUOUS = "ambiguous"


class SessionIdentityState(StrEnum):
    UNKNOWN = "unknown"
    EXACT = "exact"
    RESERVED = "reserved"


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
    precision_ns: int = 0

    def __post_init__(self) -> None:
        if self.pid <= 0 or self.creation_time_ns <= 0 or self.precision_ns < 0:
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


@dataclass(frozen=True, slots=True)
class ProcessSnapshot:
    """Transient process inventory bound to one exact runtime environment."""

    runtime_kind: str
    environment_id: str | None
    inventory: ProcessInventory

    @property
    def captured_at(self) -> datetime:
        return self.inventory.captured_at


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
            ppid_map = psutil.ppid_map() if hasattr(psutil, "ppid_map") else None
            attrs = (
                ("pid", "name", "create_time", "cmdline")
                if ppid_map is not None
                else ("pid", "ppid", "name", "create_time", "cmdline")
            )
            iterator = psutil.process_iter(attrs=attrs, ad_value=None)
            for process in iterator:
                try:
                    info = process.info
                    pid, created, argv_value = info.get("pid"), info.get("create_time"), info.get("cmdline")
                    identity = (
                        process_identity_from_psutil(int(pid), float(created))
                        if pid and created else None
                    )
                    raw_ppid = ppid_map.get(int(pid)) if (ppid_map is not None and pid is not None) else info.get("ppid")
                    rows.append(ProcessRecord(
                        identity=identity,
                        parent_pid=int(raw_ppid) if raw_ppid is not None else None,
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
    """Match a supported Codex resume form with one unambiguous exact ID."""
    args = _provider_arguments(argv, "codex")
    if args is None:
        return False
    if not args or args[0].casefold() != "resume":
        return False
    positionals: list[str] = []
    value_options = {
        "-c", "--cd", "--model", "-m", "--sandbox", "-s", "--ask-for-approval", "-a",
        "--profile", "--enable", "--disable",
    }
    flags = {
        "--full-auto", "--yolo", "--no-alt-screen", "--oss", "--search", "--no-daemon",
    }
    index = 1
    while index < len(args):
        token = args[index]
        if token == "--":
            return False
        option = token.casefold()
        option_name, separator, _ = option.partition("=")
        if separator and option_name in value_options:
            index += 1
            continue
        if option in value_options:
            if index + 1 >= len(args) or args[index + 1].startswith("-"):
                return False
            index += 2
            continue
        if option in flags:
            index += 1
            continue
        if token.startswith("-"):
            return False
        positionals.append(token)
        index += 1
    return positionals == [native_session_id]


def match_agy_invocation(argv: Sequence[str] | None, native_session_id: str) -> bool:
    """Match AGY's exact --conversation ID form."""
    args = _provider_arguments(argv, "agy")
    if args is None:
        return False
    if any(token.casefold() in {"--help", "-h", "--version"} for token in args):
        return False
    selectors: list[str] = []
    index = 0
    value_options = {"--profile", "--model", "--effort", "--cwd", "-c"}
    flags = {"--verbose", "--debug", "--help", "--version", "--yolo", "--no-color", "--sandbox"}
    while index < len(args):
        token = args[index]
        if token == "--":
            return False
        option, separator, _ = token.casefold().partition("=")
        if option == "--conversation" and separator:
            selectors.append(token.partition("=")[2])
            index += 1
        elif token == "--conversation":
            if index + 1 >= len(args) or args[index + 1].startswith("-"):
                return False
            selectors.append(args[index + 1])
            index += 2
        elif option in value_options and separator:
            index += 1
        elif option in value_options:
            if index + 1 >= len(args):
                return False
            index += 2
        elif option in flags:
            index += 1
        elif token.startswith("-"):
            return False
        else:
            index += 1
    return len(selectors) == 1 and selectors[0] == native_session_id


def match_claude_invocation(argv: Sequence[str] | None, native_session_id: str) -> bool:
    """Match one exact Claude ``--resume`` or reserved ``--session-id`` selector."""
    selector = _claude_session_selector(argv)
    return selector is not None and selector[1] == native_session_id


def _claude_session_selector(argv: Sequence[str] | None) -> tuple[str, str] | None:
    args = _provider_arguments(argv, "claude")
    if args is None:
        return None
    disallowed_modes = {"--continue", "-c", "--help", "-h", "--version", "--print", "-p"}
    if any(token.casefold() in disallowed_modes for token in args):
        return None
    selectors: list[tuple[str, str]] = []
    value_options = {
        "--model", "--effort", "--add-dir", "--permission-mode", "--output-format", "--permission-prompt-tool",
        "--settings", "--mcp-config", "--betas", "--fallback-model", "--max-budget-usd", "--agent",
        "--append-system-prompt",
    }
    flags = {
        "--verbose", "--debug", "--dangerously-skip-permissions", "--continue", "-c", "--print",
        "--help", "--version", "--ide", "--no-session-persistence",
    }
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--":
            return None
        if token in {"--resume", "--session-id"}:
            if index + 1 >= len(args) or args[index + 1].startswith("-"):
                return None
            selectors.append((token, args[index + 1]))
            index += 2
        elif token.casefold().partition("=")[0] in value_options and "=" in token:
            index += 1
        elif token.casefold() in value_options:
            if index + 1 >= len(args):
                return None
            index += 2
        elif token.casefold() in flags:
            index += 1
        elif token.startswith("-"):
            return None
        else:
            index += 1
    return selectors[0] if len(selectors) == 1 else None


def _has_provider_executable(argv: Sequence[str], provider: str) -> bool:
    names = {provider, f"{provider}.exe", f"{provider}.cmd", f"{provider}.ps1"}
    if provider == "codex":
        names.update({"codex.js", "codex.mjs", "codex-cli", "codex-cli.js"})
    elif provider == "agy":
        names.update({"agy.js", "agy.mjs", "agy-cli.js"})
    elif provider == "claude":
        names.update({"claude.js", "claude.mjs", "claude-cli.js"})
    first = Path(str(argv[0]).strip('"')).name.casefold() if argv else ""
    if first in names:
        return True
    # npm-installed Node entry points are supported, but only at argv[1].
    if first in {"node", "node.exe"} and len(argv) > 1:
        return Path(str(argv[1]).strip('"')).name.casefold() in names
    return False


def _provider_arguments(argv: Sequence[str] | None, provider: str) -> tuple[str, ...] | None:
    if not argv or not _has_provider_executable(argv, provider):
        return None
    executable = Path(str(argv[0]).strip('"')).name.casefold()
    offset = 2 if executable in {"node", "node.exe"} else 1
    return tuple(str(token) for token in argv[offset:])


_DEFAULT_PROCESS_MATCHERS: Mapping[str, ProcessSessionMatcher] = {
    "codex": match_codex_invocation,
    "agy": match_agy_invocation,
    "claude": match_claude_invocation,
}


class ManagedAssociationState(StrEnum):
    CURRENT = "current"
    HISTORICAL = "historical"


@dataclass(frozen=True, slots=True)
class ManagedPaneReference:
    provider: str
    native_session_id: str
    environment_id: str | None
    process_identity: ProcessIdentity
    launch_id: str
    pane_id: str
    terminal_session_id: str
    runtime_kind: str = "local"
    association_state: ManagedAssociationState = ManagedAssociationState.CURRENT
    receipt_state: str = "unknown"
    receipt_liveness: ProcessLiveness = ProcessLiveness.UNKNOWN


_WINDOWS_FILETIME_UNIX_EPOCH_100NS = 116_444_736_000_000_000


def process_identity_from_windows_filetime(pid: int, creation_filetime: int) -> ProcessIdentity:
    """Normalize Terminal Launcher's FILETIME into Unix-nanosecond process identity."""
    created_ns = (int(creation_filetime) - _WINDOWS_FILETIME_UNIX_EPOCH_100NS) * 100
    return ProcessIdentity(pid=pid, creation_time_ns=created_ns)


def process_identity_from_psutil(pid: int, creation_time_seconds: float) -> ProcessIdentity:
    """Normalize psutil's float seconds, preserving input quantization uncertainty.

    The seconds float already includes the platform's FILETIME-to-float rounding.
    Convert that binary float to nanoseconds with integer arithmetic so multiplying
    by 1e9 cannot introduce a second, untracked floating-point rounding.
    """
    seconds = float(creation_time_seconds)
    if not math.isfinite(seconds):
        raise ValueError("process creation time must be finite")
    numerator, denominator = seconds.as_integer_ratio()
    scaled_numerator = numerator * 1_000_000_000
    created_ns, remainder = divmod(scaled_numerator, denominator)
    doubled_remainder = remainder * 2
    if doubled_remainder > denominator or (doubled_remainder == denominator and created_ns % 2):
        created_ns += 1
    precision_ns = math.ceil(math.ulp(seconds) * 500_000_000 + 0.5)
    return ProcessIdentity(pid=int(pid), creation_time_ns=created_ns, precision_ns=precision_ns)


def compare_process_identities(left: ProcessIdentity, right: ProcessIdentity) -> IdentityComparison:
    """Compare PID/creation times without treating rounded timestamps as exact."""
    if left.pid != right.pid:
        return IdentityComparison.DIFFERENT
    left_low, left_high = left.creation_time_ns - left.precision_ns, left.creation_time_ns + left.precision_ns
    right_low, right_high = right.creation_time_ns - right.precision_ns, right.creation_time_ns + right.precision_ns
    if left_high < right_low or right_high < left_low:
        return IdentityComparison.DIFFERENT
    if left.precision_ns == right.precision_ns == 0 and left.creation_time_ns == right.creation_time_ns:
        return IdentityComparison.SAME
    return IdentityComparison.AMBIGUOUS


def managed_pane_reference_from_terminal_launcher_record(
    key: SessionKey,
    record: object,
    *,
    terminal_session_id: str,
    association_state: ManagedAssociationState = ManagedAssociationState.CURRENT,
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
        runtime_kind=key.runtime_kind,
        association_state=association_state,
        receipt_state=_record_value(record, "state", "unknown"),
        receipt_liveness=_record_liveness(record),
    )


@dataclass(frozen=True, slots=True)
class ManagedReceiptSnapshot:
    references: tuple[ManagedPaneReference, ...]
    availability: EvidenceAvailability
    captured_at: datetime
    error_code: str | None = None
    historical_references: tuple[ManagedPaneReference, ...] = ()


class ManagedReceiptSource(Protocol):
    def observe(self, key: SessionKey) -> ManagedReceiptSnapshot:
        """Return joined registry/terminal receipts; this protocol has no package dependency."""


@dataclass(frozen=True, slots=True)
class ManagedLaunchAssociation:
    launch_id: str
    terminal_session_id: str
    pane_id: str
    session_key: SessionKey
    association_state: ManagedAssociationState = ManagedAssociationState.CURRENT


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
        historical_references: list[ManagedPaneReference] = []
        failed = False
        seen: set[tuple[str, str, str, ManagedAssociationState]] = set()
        for association in associations:
            if association.session_key != key or not association.pane_id:
                failed = True
                continue
            try:
                association_state = ManagedAssociationState(association.association_state)
            except ValueError:
                failed = True
                continue
            association_key = (
                association.launch_id, association.terminal_session_id,
                association.pane_id, association_state,
            )
            if association_key in seen:
                continue
            seen.add(association_key)
            try:
                records = self.store.enumerate_processes(launch_id=association.launch_id)
            except Exception:
                failed = True
                continue
            pane_records = tuple(
                record for record in records
                if getattr(record, "launch_id", None) == association.launch_id
                and getattr(record, "pane_id", None) == association.pane_id
            )
            if len(pane_records) != 1:
                failed = True
                continue
            for record in pane_records:
                reference = managed_pane_reference_from_terminal_launcher_record(
                    key, record, terminal_session_id=association.terminal_session_id,
                    association_state=association_state,
                )
                if reference is not None:
                    if (
                        association_state is ManagedAssociationState.HISTORICAL
                        or reference.receipt_state in {"exited", "failed", "stale"}
                        or reference.receipt_liveness is ProcessLiveness.EXITED
                    ):
                        historical_references.append(reference)
                    else:
                        references.append(reference)
                else:
                    failed = True
        return ManagedReceiptSnapshot(
            references=tuple(references),
            availability=EvidenceAvailability.PARTIAL if failed else EvidenceAvailability.COMPLETE,
            captured_at=captured,
            error_code="receipt_query_incomplete" if failed else None,
            historical_references=tuple(historical_references),
        )


def _record_value(record: object, field_name: str, default: str) -> str:
    value = getattr(record, field_name, default)
    return str(getattr(value, "value", value))


def _record_liveness(record: object) -> ProcessLiveness:
    value = _record_value(record, "liveness", ProcessLiveness.UNKNOWN.value).casefold()
    if value == "alive":
        value = ProcessLiveness.RUNNING.value
    try:
        return ProcessLiveness(value)
    except ValueError:
        return ProcessLiveness.UNKNOWN


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
    session_identity_state: SessionIdentityState
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
    historical_managed_panes: tuple[ManagedPaneReference, ...]
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
            "session_identity_state": self.session_identity_state.value,
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
                    "creation_time_precision_ns": item.identity.precision_ns if item.identity else None,
                    "image_name": item.image_name,
                    "parent_pid": item.parent_pid,
                }
                for item in self.processes
            ],
            "ancestry": [
                {
                    "identities": [
                        {
                            "pid": identity.pid,
                            "creation_time_ns": identity.creation_time_ns,
                            "creation_time_precision_ns": identity.precision_ns,
                        }
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
                    "process_creation_time_precision_ns": self.managed_pane.process_identity.precision_ns,
                }
                if self.managed_pane else None
            ),
            "historical_managed_panes": [
                {
                    "provider": item.provider,
                    "native_session_id": item.native_session_id,
                    "environment_id": item.environment_id,
                    "runtime_kind": item.runtime_kind,
                    "process_pid": item.process_identity.pid,
                    "process_creation_time_ns": item.process_identity.creation_time_ns,
                    "process_creation_time_precision_ns": item.process_identity.precision_ns,
                    "launch_id": item.launch_id,
                    "pane_id": item.pane_id,
                    "terminal_session_id": item.terminal_session_id,
                    "receipt_state": item.receipt_state,
                    "receipt_liveness": item.receipt_liveness.value,
                }
                for item in self.historical_managed_panes
            ],
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
                    "process_creation_time_precision_ns": (
                        item.process_identity.precision_ns if item.process_identity else None
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
        environment_id: str | None = None,
        snapshot_max_age: timedelta = timedelta(seconds=2),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if snapshot_max_age <= timedelta(0):
            raise ValueError("snapshot_max_age must be positive")
        self.runtime_kind = runtime_kind
        self.environment_id = environment_id
        self.snapshot_max_age = snapshot_max_age
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

    def capture_snapshot(self) -> ProcessSnapshot:
        """Capture one bounded process inventory for reuse in a single observation batch."""
        try:
            inventory = self.process_enumerator.enumerate_processes()
        except Exception:
            inventory = ProcessInventory(
                (), EvidenceAvailability.UNAVAILABLE, self.clock(), error_code="process_source_error"
            )
        return ProcessSnapshot(self.runtime_kind, self.environment_id, inventory)

    def observe(
        self,
        key: SessionKey,
        *,
        registry_association: bool | None = None,
        known_process: ProcessIdentity | None = None,
    ) -> SessionRuntimeObservation:
        return self.observe_many(
            (key,),
            registry_associations={key: registry_association} if registry_association is not None else None,
            known_processes={key: known_process} if known_process is not None else None,
        )[0]

    def observe_many(
        self,
        keys: Sequence[SessionKey],
        *,
        snapshot: ProcessSnapshot | None = None,
        registry_associations: Mapping[SessionKey, bool] | None = None,
        known_processes: Mapping[SessionKey, ProcessIdentity] | None = None,
    ) -> tuple[SessionRuntimeObservation, ...]:
        """Observe up to 256 sessions using one fresh, exactly scoped process snapshot."""
        requested = tuple(keys)
        if len(requested) > 256:
            raise ValueError("observe_many is limited to 256 sessions per batch")
        needs_snapshot = any(
            key.runtime_kind == self.runtime_kind and key.environment_id == self.environment_id
            for key in requested
        )
        process_snapshot = snapshot or (
            self.capture_snapshot() if needs_snapshot else ProcessSnapshot(
                self.runtime_kind,
                self.environment_id,
                ProcessInventory(
                    (), EvidenceAvailability.UNAVAILABLE, self.clock(), error_code="environment_mismatch"
                ),
            )
        )
        age = self.clock() - process_snapshot.captured_at
        scope_matches = (
            process_snapshot.runtime_kind == self.runtime_kind
            and process_snapshot.environment_id == self.environment_id
        )
        fresh = timedelta(0) <= age <= self.snapshot_max_age
        if not scope_matches:
            inventory = ProcessInventory(
                (), EvidenceAvailability.UNAVAILABLE, self.clock(), error_code="process_snapshot_scope_mismatch"
            )
        elif not fresh:
            inventory = ProcessInventory(
                (), EvidenceAvailability.UNAVAILABLE, self.clock(), error_code="process_snapshot_stale"
            )
        else:
            inventory = process_snapshot.inventory
        return tuple(
            self._observe_one(
                key,
                inventory,
                registry_association=(registry_associations or {}).get(key),
                known_process=(known_processes or {}).get(key),
            )
            for key in requested
        )

    def _observe_one(
        self,
        key: SessionKey,
        inventory: ProcessInventory,
        *,
        registry_association: bool | None,
        known_process: ProcessIdentity | None,
    ) -> SessionRuntimeObservation:
        captured = self.clock()
        if key.runtime_kind != self.runtime_kind or key.environment_id != self.environment_id:
            mismatch = "runtime_mismatch" if key.runtime_kind != self.runtime_kind else "environment_mismatch"
            inventory = ProcessInventory((), EvidenceAvailability.UNAVAILABLE, captured, error_code=mismatch)
            activity = _unavailable_store("provider_store", mismatch, captured)
            receipt_snapshot = ManagedReceiptSnapshot((), EvidenceAvailability.UNAVAILABLE, captured, mismatch)
        else:
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
        matching_historical_refs = tuple(
            ref for ref in receipt_snapshot.historical_references if _reference_matches(ref, key)
        )
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
            if matching_historical_refs:
                evidence.append(RuntimeEvidence(
                    "managed_receipt", "historical_managed_session_reference",
                    receipt_snapshot.availability, EvidenceConfidence.MEDIUM,
                    receipt_snapshot.captured_at,
                    safe_values=(("reference_count", str(len(matching_historical_refs))),),
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

        session_identity_state = SessionIdentityState.UNKNOWN
        if matching_records:
            session_identity_state = SessionIdentityState.EXACT
            if key.provider == "claude" and {
                _claude_session_selector(row.argv) for row in matching_records
            } == {("--session-id", key.native_session_id)}:
                session_identity_state = SessionIdentityState.RESERVED

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
            if same_pid and all(
                compare_process_identities(row.identity, ref.process_identity) is IdentityComparison.DIFFERENT
                for row in same_pid
            ):
                identity_conflict = True
                evidence_conflict = True
                evidence.append(RuntimeEvidence(
                    "process_identity", "pid_creation_time_mismatch", inventory.availability,
                    EvidenceConfidence.HIGH, inventory.captured_at, ref.process_identity,
                ))
        if known_process:
            same_pid = [row for row in inventory.records if row.identity and row.identity.pid == known_process.pid]
            if same_pid and all(
                compare_process_identities(row.identity, known_process) is IdentityComparison.DIFFERENT
                for row in same_pid
            ):
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
        if (
            matching_records and activity.found is False
            and session_identity_state is not SessionIdentityState.RESERVED
        ):
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
                if any(
                    row.identity
                    and compare_process_identities(row.identity, ref.process_identity) is IdentityComparison.SAME
                    for row in inventory.records
                ):
                    attachment, attachment_confidence = AttachmentState.ATTACHED, EvidenceConfidence.EXACT
        if process_state is ProcessLiveness.AMBIGUOUS:
            attachment, attachment_confidence = AttachmentState.UNKNOWN, EvidenceConfidence.NONE
        if identity_conflict or len(matching_refs) > 1:
            attachment, attachment_confidence = AttachmentState.UNKNOWN, EvidenceConfidence.NONE

        if matching_refs and not identity_conflict and len(matching_refs) == 1:
            management = ManagementState.MANAGED
        elif matching_refs and (identity_conflict or len(matching_refs) > 1):
            management = ManagementState.CONFLICT
        elif matching_historical_refs:
            management = ManagementState.HISTORICAL
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
            else EvidenceConfidence.MEDIUM if matching_historical_refs
            else EvidenceConfidence.MEDIUM if activity.found is True
            else EvidenceConfidence.LOW if registry_association is True
            else EvidenceConfidence.NONE
        )
        availability = _combined_availability(
            inventory.availability, activity.availability,
            receipt_snapshot.availability if self.managed_receipt_source is not None else None,
        )
        return SessionRuntimeObservation(
            key, captured, process_state, known_state, process_match, session_identity_state, attachment,
            attachment_confidence, management, availability, inventory.availability,
            activity.availability, receipt_snapshot.availability, confidence,
            activity.found, activity.last_activity_at, activity.last_turn_at,
            registry_association,
            tuple(ObservedProcess(row.identity, row.parent_pid, row.image_name) for row in matching_records),
            tuple(ancestry),
            matching_refs[0] if len(matching_refs) == 1 else None,
            matching_historical_refs,
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
    comparisons = [compare_process_identities(row.identity, identity) for row in same_pid]
    if IdentityComparison.SAME in comparisons:
        return ProcessLiveness.RUNNING
    if same_pid and all(result is IdentityComparison.DIFFERENT for result in comparisons):
        return ProcessLiveness.EXITED
    if same_pid:
        return ProcessLiveness.UNKNOWN
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
    return ref.environment_id == key.environment_id and ref.runtime_kind == key.runtime_kind


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
            or parent.identity.creation_time_ns - parent.identity.precision_ns
            > current.identity.creation_time_ns + current.identity.precision_ns
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
