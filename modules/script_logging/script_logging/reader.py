"""Read-only SQLite query interface for command invocation history."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Optional, Tuple, Union

from .invocation_store import resolve_invocation_db_path
from .models import (
    AliasStatistics,
    CommandPattern,
    CommandStatistics,
    InvocationRecord,
    Page,
    ProgramStatistics,
)


def _encode_cursor(epoch_ms: int, invocation_id: str) -> str:
    raw = f"{epoch_ms}:{invocation_id}"
    return base64.urlsafe_b64encode(raw.encode("ascii")).decode("ascii")


def _decode_cursor(cursor: str) -> Tuple[int, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("ascii")
        parts = raw.split(":", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid pagination cursor: {cursor}")
        epoch_ms = int(parts[0])
        inv_id = parts[1]
        return epoch_ms, inv_id
    except Exception as exc:
        raise ValueError(f"Invalid pagination cursor: {cursor}") from exc


def _encode_commands_cursor(sort_metric: Union[str, int], pattern_id: str) -> str:
    raw = f"{sort_metric}|{pattern_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def _decode_commands_cursor(cursor: str) -> Tuple[str, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        parts = raw.split("|", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid pagination cursor: {cursor}")
        return parts[0], parts[1]
    except Exception as exc:
        raise ValueError(f"Invalid pagination cursor: {cursor}") from exc


def _to_epoch_ms(val: Optional[Union[datetime, str, int]]) -> Optional[int]:
    if val is None:
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, datetime):
        if val.tzinfo is None:
            val = val.replace(tzinfo=timezone.utc)
        return int(val.timestamp() * 1000)
    if isinstance(val, str):
        dt = datetime.fromisoformat(val)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    raise TypeError(f"Unsupported timestamp format: {type(val)}")


class ReadOnlyHistoryReader:
    """Read-only reader for querying invocation history and statistics.

    Uses SQLite URI read-only mode (mode=ro) to guarantee no write locks, journal files,
    or database mutations can occur during queries.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).resolve()
        if not self.path.is_file():
            raise FileNotFoundError(f"Invocation database not found at {self.path}")

    def _connect(self) -> sqlite3.Connection:
        """Create a read-only SQLite connection using URI mode=ro."""
        uri = f"file:{self.path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 15000;")
        return conn

    def list_invocations(
        self,
        *,
        program_id: Optional[str] = None,
        invoked_name: Optional[str] = None,
        status: Optional[str] = None,
        since: Optional[Union[datetime, str, int]] = None,
        before: Optional[Union[datetime, str, int]] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> Page[InvocationRecord]:
        """Query invocations in deterministic reverse-chronological order with keyset cursor pagination."""
        if limit <= 0:
            raise ValueError("limit must be positive")

        conditions = []
        params: list[Any] = []

        if program_id is not None:
            conditions.append("program_id = ?")
            params.append(program_id)

        if invoked_name is not None:
            conditions.append("invoked_name = ?")
            params.append(invoked_name)

        if status is not None:
            conditions.append("status = ?")
            params.append(status)

        since_ms = _to_epoch_ms(since)
        if since_ms is not None:
            conditions.append("started_epoch_ms >= ?")
            params.append(since_ms)

        before_ms = _to_epoch_ms(before)
        if before_ms is not None:
            conditions.append("started_epoch_ms < ?")
            params.append(before_ms)

        if cursor:
            cursor_epoch, cursor_id = _decode_cursor(cursor)
            conditions.append("((started_epoch_ms < ?) OR (started_epoch_ms = ? AND invocation_id < ?))")
            params.extend([cursor_epoch, cursor_epoch, cursor_id])

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        fetch_limit = limit + 1

        sql = f"""
            SELECT invocation_id, program_id, invoked_name, origin, pattern_id,
                   raw_argv_json, redacted_argv_json, is_redacted, cwd,
                   started_at_utc, started_epoch_ms, finished_at_utc, duration_ms,
                   exit_code, status
            FROM invocations
            {where_clause}
            ORDER BY started_epoch_ms DESC, invocation_id DESC
            LIMIT ?
        """
        params.append(fetch_limit)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        items = [
            InvocationRecord(
                invocation_id=row["invocation_id"],
                program_id=row["program_id"],
                invoked_name=row["invoked_name"],
                origin=row["origin"],
                pattern_id=row["pattern_id"],
                raw_argv=tuple(json.loads(row["raw_argv_json"])),
                redacted_argv=tuple(json.loads(row["redacted_argv_json"])),
                is_redacted=bool(row["is_redacted"]),
                cwd=row["cwd"],
                started_at_utc=row["started_at_utc"],
                started_epoch_ms=row["started_epoch_ms"],
                status=row["status"],
                exit_code=row["exit_code"],
                finished_at_utc=row["finished_at_utc"],
                duration_ms=row["duration_ms"],
            )
            for row in rows
        ]

        has_more = len(items) > limit
        if has_more:
            items = items[:limit]
            last = items[-1]
            next_cursor = _encode_cursor(last.started_epoch_ms, last.invocation_id)
        else:
            next_cursor = None

        return Page(items=items, next_cursor=next_cursor, has_more=has_more)

    def list_unique_commands(
        self,
        *,
        program_id: Optional[str] = None,
        order_by: str = "last_seen",
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> Page[CommandPattern]:
        """Query unique aggregated command patterns with cursor pagination."""
        if limit <= 0:
            raise ValueError("limit must be positive")
        if order_by not in ("last_seen", "invocations"):
            raise ValueError("order_by must be 'last_seen' or 'invocations'")

        conditions = []
        params: list[Any] = []

        if program_id is not None:
            conditions.append("program_id = ?")
            params.append(program_id)

        if cursor:
            c_metric, c_id = _decode_commands_cursor(cursor)
            if order_by == "last_seen":
                conditions.append("((last_seen_utc < ?) OR (last_seen_utc = ? AND pattern_id < ?))")
                params.extend([c_metric, c_id])
            else:
                c_count = int(c_metric)
                conditions.append("((invocation_count < ?) OR (invocation_count = ? AND pattern_id < ?))")
                params.extend([c_count, c_count, c_id])

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        if order_by == "last_seen":
            order_clause = "ORDER BY last_seen_utc DESC, pattern_id DESC"
        else:
            order_clause = "ORDER BY invocation_count DESC, pattern_id DESC"

        fetch_limit = limit + 1
        sql = f"""
            SELECT pattern_id, program_id, pattern_argv_json,
                   invocation_count, success_count, failure_count, unknown_count,
                   first_seen_utc, last_seen_utc
            FROM command_patterns
            {where_clause}
            {order_clause}
            LIMIT ?
        """
        params.append(fetch_limit)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        items = [
            CommandPattern(
                pattern_id=row["pattern_id"],
                program_id=row["program_id"],
                pattern_argv=tuple(json.loads(row["pattern_argv_json"])),
                pattern_argv_json=row["pattern_argv_json"],
                invocation_count=row["invocation_count"],
                success_count=row["success_count"],
                failure_count=row["failure_count"],
                unknown_count=row["unknown_count"],
                first_seen_utc=row["first_seen_utc"],
                last_seen_utc=row["last_seen_utc"],
            )
            for row in rows
        ]

        has_more = len(items) > limit
        if has_more:
            items = items[:limit]
            last = items[-1]
            metric_val = last.last_seen_utc if order_by == "last_seen" else last.invocation_count
            next_cursor = _encode_commands_cursor(metric_val, last.pattern_id)
        else:
            next_cursor = None

        return Page(items=items, next_cursor=next_cursor, has_more=has_more)

    def get_invocation(self, invocation_id: str) -> Optional[InvocationRecord]:
        """Fetch a single invocation record by ID."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM invocations WHERE invocation_id = ?",
                (invocation_id,),
            ).fetchone()
            if not row:
                return None
            return InvocationRecord(
                invocation_id=row["invocation_id"],
                program_id=row["program_id"],
                invoked_name=row["invoked_name"],
                origin=row["origin"],
                pattern_id=row["pattern_id"],
                raw_argv=tuple(json.loads(row["raw_argv_json"])),
                redacted_argv=tuple(json.loads(row["redacted_argv_json"])),
                is_redacted=bool(row["is_redacted"]),
                cwd=row["cwd"],
                started_at_utc=row["started_at_utc"],
                started_epoch_ms=row["started_epoch_ms"],
                status=row["status"],
                exit_code=row["exit_code"],
                finished_at_utc=row["finished_at_utc"],
                duration_ms=row["duration_ms"],
            )

    def get_program_statistics(self, program_id: str) -> ProgramStatistics:
        """Fetch cumulative execution statistics for a program ID."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT program_id, total_starts, success_count, failure_count, unknown_count,
                       first_seen_utc, last_seen_utc
                FROM program_usage
                WHERE program_id = ?
                """,
                (program_id,),
            ).fetchone()

            if not row:
                return ProgramStatistics(
                    program_id=program_id,
                    total_starts=0,
                    success_count=0,
                    failure_count=0,
                    unknown_count=0,
                    first_seen_utc=None,
                    last_seen_utc=None,
                )

            return ProgramStatistics(
                program_id=row["program_id"],
                total_starts=row["total_starts"],
                success_count=row["success_count"],
                failure_count=row["failure_count"],
                unknown_count=row["unknown_count"],
                first_seen_utc=row["first_seen_utc"],
                last_seen_utc=row["last_seen_utc"],
            )

    def get_command_statistics(self, pattern_id: str) -> Optional[CommandStatistics]:
        """Fetch execution statistics for a specific command pattern fingerprint."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT pattern_id, program_id, pattern_argv_json,
                       invocation_count, success_count, failure_count, unknown_count,
                       first_seen_utc, last_seen_utc
                FROM command_patterns
                WHERE pattern_id = ?
                """,
                (pattern_id,),
            ).fetchone()

            if not row:
                return None

            return CommandStatistics(
                pattern_id=row["pattern_id"],
                program_id=row["program_id"],
                pattern_argv=tuple(json.loads(row["pattern_argv_json"])),
                invocation_count=row["invocation_count"],
                success_count=row["success_count"],
                failure_count=row["failure_count"],
                unknown_count=row["unknown_count"],
                first_seen_utc=row["first_seen_utc"],
                last_seen_utc=row["last_seen_utc"],
            )

    def get_alias_statistics(
        self, invoked_name: str, program_id: Optional[str] = None
    ) -> list[AliasStatistics]:
        """Fetch execution statistics for an alias / invoked executable name."""
        with self._connect() as conn:
            if program_id:
                rows = conn.execute(
                    """
                    SELECT invoked_name, program_id, total_starts, success_count, failure_count,
                           unknown_count, first_seen_utc, last_seen_utc
                    FROM alias_usage
                    WHERE invoked_name = ? AND program_id = ?
                    """,
                    (invoked_name, program_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT invoked_name, program_id, total_starts, success_count, failure_count,
                           unknown_count, first_seen_utc, last_seen_utc
                    FROM alias_usage
                    WHERE invoked_name = ?
                    ORDER BY total_starts DESC
                    """,
                    (invoked_name,),
                ).fetchall()

            return [
                AliasStatistics(
                    invoked_name=r["invoked_name"],
                    program_id=r["program_id"],
                    total_starts=r["total_starts"],
                    success_count=r["success_count"],
                    failure_count=r["failure_count"],
                    unknown_count=r["unknown_count"],
                    first_seen_utc=r["first_seen_utc"],
                    last_seen_utc=r["last_seen_utc"],
                )
                for r in rows
            ]


def open_invocation_reader(path: Optional[Path | str] = None) -> ReadOnlyHistoryReader:
    """Open a read-only reader for the invocation database.

    Args:
        path: Path to invocations SQLite file. If None, resolves default platform path.

    Returns:
        ReadOnlyHistoryReader instance.

    Raises:
        FileNotFoundError: If the database file does not exist.
    """
    if path is None:
        target_path = resolve_invocation_db_path(create=False)
    else:
        target_path = Path(path).resolve()

    return ReadOnlyHistoryReader(target_path)
