"""Reusable event/run history, invocation recording, and configurable text logging."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional, Union

from .formatting import EventFormatter, StoreHandler, text_file_handler
from .invocation_store import InvocationStore, resolve_invocation_db_path
from .launcher import launch_target
from .models import (
    AliasStatistics,
    CommandPattern,
    CommandStatistics,
    InvocationRecord,
    Page,
    ProgramStatistics,
    ReconciliationReport,
)
from .reader import (
    ReadOnlyHistoryReader,
    open_invocation_reader,
)
from .reconciliation import reconcile_invocation_summaries
from .redaction import compute_pattern_id, redact_argv
from .store import EventRecord, HistoryStore, RunRecord

__version__ = "0.2.0"


def list_invocations(
    *,
    path: Optional[Path | str] = None,
    program_id: Optional[str] = None,
    invoked_name: Optional[str] = None,
    status: Optional[str] = None,
    since: Optional[Union[datetime, str, int]] = None,
    before: Optional[Union[datetime, str, int]] = None,
    limit: int = 50,
    cursor: Optional[str] = None,
) -> Page[InvocationRecord]:
    """Query invocations in deterministic reverse-chronological order with keyset cursor pagination."""
    reader = open_invocation_reader(path)
    return reader.list_invocations(
        program_id=program_id,
        invoked_name=invoked_name,
        status=status,
        since=since,
        before=before,
        limit=limit,
        cursor=cursor,
    )


def list_unique_commands(
    *,
    path: Optional[Path | str] = None,
    program_id: Optional[str] = None,
    order_by: str = "last_seen",
    limit: int = 50,
    cursor: Optional[str] = None,
) -> Page[CommandPattern]:
    """Query unique aggregated command patterns with cursor pagination."""
    reader = open_invocation_reader(path)
    return reader.list_unique_commands(
        program_id=program_id,
        order_by=order_by,
        limit=limit,
        cursor=cursor,
    )


def get_program_statistics(
    program_id: str, *, path: Optional[Path | str] = None
) -> ProgramStatistics:
    """Fetch cumulative execution statistics for a program ID."""
    reader = open_invocation_reader(path)
    return reader.get_program_statistics(program_id)


def get_command_statistics(
    pattern_id: str, *, path: Optional[Path | str] = None
) -> Optional[CommandStatistics]:
    """Fetch execution statistics for a specific command pattern fingerprint."""
    reader = open_invocation_reader(path)
    return reader.get_command_statistics(pattern_id)


__all__ = [
    "AliasStatistics",
    "CommandPattern",
    "CommandStatistics",
    "EventFormatter",
    "EventRecord",
    "HistoryStore",
    "InvocationRecord",
    "InvocationStore",
    "Page",
    "ProgramStatistics",
    "ReadOnlyHistoryReader",
    "ReconciliationReport",
    "RunRecord",
    "StoreHandler",
    "compute_pattern_id",
    "get_command_statistics",
    "get_program_statistics",
    "launch_target",
    "list_invocations",
    "list_unique_commands",
    "open_invocation_reader",
    "reconcile_invocation_summaries",
    "redact_argv",
    "resolve_invocation_db_path",
    "text_file_handler",
]
