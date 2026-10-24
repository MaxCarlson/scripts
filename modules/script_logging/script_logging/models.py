"""Domain models for command invocation recording and query statistics."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, Optional, Tuple, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class InvocationRecord:
    """Immutable record representing a single program invocation lifecycle."""

    invocation_id: str
    program_id: str
    invoked_name: str
    origin: str
    pattern_id: str
    raw_argv: Tuple[str, ...]
    redacted_argv: Tuple[str, ...]
    is_redacted: bool
    cwd: str
    started_at_utc: str
    started_epoch_ms: int
    status: str
    exit_code: Optional[int] = None
    finished_at_utc: Optional[str] = None
    duration_ms: Optional[int] = None


@dataclass(frozen=True)
class CommandPattern:
    """Aggregated command argument pattern and execution metrics."""

    pattern_id: str
    program_id: str
    pattern_argv: Tuple[str, ...]
    pattern_argv_json: str
    invocation_count: int
    success_count: int
    failure_count: int
    first_seen_utc: str
    last_seen_utc: str
    unknown_count: int = 0


@dataclass(frozen=True)
class CommandStatistics:
    """Summary statistics for a command pattern."""

    pattern_id: str
    program_id: str
    pattern_argv: Tuple[str, ...]
    invocation_count: int
    success_count: int
    failure_count: int
    first_seen_utc: Optional[str] = None
    last_seen_utc: Optional[str] = None
    unknown_count: int = 0


@dataclass(frozen=True)
class ProgramStatistics:
    """Aggregated invocation statistics for a specific program ID."""

    program_id: str
    total_starts: int
    success_count: int
    failure_count: int
    unknown_count: int = 0
    first_seen_utc: Optional[str] = None
    last_seen_utc: Optional[str] = None


@dataclass(frozen=True)
class AliasStatistics:
    """Aggregated invocation statistics for an alias / invoked executable name."""

    invoked_name: str
    program_id: str
    total_starts: int
    success_count: int
    failure_count: int
    unknown_count: int = 0
    first_seen_utc: Optional[str] = None
    last_seen_utc: Optional[str] = None


@dataclass(frozen=True)
class Page(Generic[T]):
    """Cursor-paginated container for query results."""

    items: list[T]
    next_cursor: Optional[str] = None
    has_more: bool = False


@dataclass(frozen=True)
class ReconciliationReport:
    """Diagnostic outcome of counter reconciliation against invocation truth."""

    mismatches_found: int = 0
    corrections_applied: int = 0
    details: Tuple[str, ...] = field(default_factory=tuple)
