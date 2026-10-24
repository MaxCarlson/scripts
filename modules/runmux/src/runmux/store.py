"""SQLite-backed run registry for runmux."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from runmux.constants import DEFAULT_LEASE_TIMEOUT_SECONDS, STATUS_FINISHED, TERMINAL_STATUSES
from runmux.models import (
    AttachmentSummary,
    RunLineageNode,
    RunLineageSummary,
    RunPage,
    RunRecord,
    utc_now_iso,
)
from runmux.platform_paths import ensure_state_tree, get_state_dir

SCHEMA_VERSION = 3
MAX_QUERY_VM_STEPS = 5_000_000


class RegistryError(RuntimeError):
    """Base error for registry operations."""


class RunNotFoundError(RegistryError):
    """Raised when a run ID cannot be resolved."""


class AmbiguousRunIdError(RegistryError):
    """Raised when a run ID prefix matches multiple records."""


class RunStore:
    """Persistent store for run records."""

    def __init__(self, state_dir: Path | None = None) -> None:
        self.state_dir = ensure_state_tree(state_dir or get_state_dir())
        self.db_path = self.state_dir / "registry.sqlite3"
        self.init_db()

    @property
    def runs_dir(self) -> Path:
        """Return the root directory for per-run artifacts."""

        return self.state_dir / "runs"

    def connect(self) -> sqlite3.Connection:
        """Open a SQLite connection with runmux defaults."""

        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def init_db(self) -> None:
        """Create the registry schema if needed."""

        with sqlite3.connect(self.db_path, timeout=30) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    numeric_id INTEGER UNIQUE,
                    name TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    ended_at TEXT,
                    exit_code INTEGER,
                    pid INTEGER,
                    supervisor_pid INTEGER,
                    program TEXT NOT NULL,
                    argv_json TEXT NOT NULL,
                    cwd TEXT NOT NULL,
                    env_overrides_json TEXT NOT NULL,
                    port INTEGER,
                    auth_token TEXT NOT NULL,
                    log_path TEXT NOT NULL,
                    command_line TEXT NOT NULL,
                    restart_of TEXT,
                    duplicate_of TEXT,
                    rows INTEGER,
                    columns INTEGER,
                    lifetime_view_count INTEGER NOT NULL DEFAULT 0,
                    lifetime_interact_count INTEGER NOT NULL DEFAULT 0
                )
                """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS attachment_sessions (
                    session_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    mode TEXT NOT NULL CHECK(mode IN ('view', 'interact')),
                    connected_at TEXT NOT NULL,
                    last_heartbeat TEXT NOT NULL,
                    disconnected_at TEXT,
                    holds_lock INTEGER NOT NULL DEFAULT 0,
                    lock_requested_at TEXT,
                    FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
                )
                """)
            self.migrate_db(connection)
            connection.execute(
                """
                INSERT INTO metadata(key, value)
                VALUES('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(SCHEMA_VERSION),),
            )

    def migrate_db(self, connection: sqlite3.Connection) -> None:
        """Apply lightweight schema migrations for existing runmux registries."""

        columns = {str(row["name"]) for row in connection.execute("PRAGMA table_info(runs)").fetchall()}
        if "numeric_id" not in columns:
            connection.execute("ALTER TABLE runs ADD COLUMN numeric_id INTEGER")
            rows = connection.execute("SELECT id FROM runs ORDER BY created_at ASC").fetchall()
            for numeric_id, row in enumerate(rows):
                connection.execute(
                    "UPDATE runs SET numeric_id = ? WHERE id = ?",
                    (numeric_id, str(row["id"])),
                )
        if "lifetime_view_count" not in columns:
            connection.execute("ALTER TABLE runs ADD COLUMN lifetime_view_count INTEGER NOT NULL DEFAULT 0")
        if "lifetime_interact_count" not in columns:
            connection.execute("ALTER TABLE runs ADD COLUMN lifetime_interact_count INTEGER NOT NULL DEFAULT 0")
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_numeric_id ON runs(numeric_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_runs_created_at_id ON runs(created_at, id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_runs_status_created_at ON runs(status, created_at, id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_runs_started_at_id ON runs(started_at, id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_runs_ended_at_id ON runs(ended_at, id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_runs_name_created_at ON runs(name, created_at, id)")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_runs_name_nocase_created_at ON runs(name COLLATE NOCASE, created_at, id)"
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_runs_restart_of ON runs(restart_of, created_at, id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_runs_duplicate_of ON runs(duplicate_of, created_at, id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_attachment_sessions_run_id ON attachment_sessions(run_id)")

    def create_run(
        self,
        *,
        run_id: str,
        name: str | None,
        status: str,
        program: str,
        argv_json: str,
        cwd: str,
        env_overrides_json: str,
        auth_token: str,
        log_path: Path,
        command_line: str,
        restart_of: str | None = None,
        duplicate_of: str | None = None,
        rows: int | None = None,
        columns: int | None = None,
    ) -> RunRecord:
        """Insert and return a new run record."""

        now = utc_now_iso()
        with self.connect() as connection:
            # Reserve the SQLite writer before selecting the next reusable ID.
            # A deferred transaction lets concurrent launchers observe the same
            # maximum numeric ID before either insert commits.
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO runs(
                    id, numeric_id, name, status, created_at, updated_at, started_at, ended_at,
                    exit_code, pid, supervisor_pid, program, argv_json, cwd,
                    env_overrides_json, port, auth_token, log_path, command_line,
                    restart_of, duplicate_of, rows, columns
                )
                VALUES(?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, ?, ?, ?, ?, NULL,
                       ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    self.next_numeric_id(connection),
                    name,
                    status,
                    now,
                    now,
                    program,
                    argv_json,
                    cwd,
                    env_overrides_json,
                    auth_token,
                    str(log_path),
                    command_line,
                    restart_of,
                    duplicate_of,
                    rows,
                    columns,
                ),
            )
        return self.get_run(run_id)

    def register_attachment(self, *, run_id: str, session_id: str, mode: str) -> None:
        """Register a new view or interact attachment and increment lifetime counts."""

        if mode not in {"view", "interact"}:
            raise RegistryError(f"Unsupported attachment mode: {mode}")
        now = utc_now_iso()
        counter = "lifetime_view_count" if mode == "view" else "lifetime_interact_count"
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT session_id FROM attachment_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if existing is not None:
                connection.execute(
                    """
                    UPDATE attachment_sessions
                    SET last_heartbeat = ?, disconnected_at = NULL
                    WHERE session_id = ?
                    """,
                    (now, session_id),
                )
                return
            connection.execute(
                """
                INSERT INTO attachment_sessions(
                    session_id, run_id, mode, connected_at, last_heartbeat
                )
                VALUES(?, ?, ?, ?, ?)
                """,
                (session_id, run_id, mode, now, now),
            )
            connection.execute(
                f"UPDATE runs SET {counter} = {counter} + 1, updated_at = ? WHERE id = ?",
                (now, run_id),
            )

    def heartbeat_attachment(self, session_id: str) -> None:
        """Refresh an attachment lease."""

        with self.connect() as connection:
            connection.execute(
                """
                UPDATE attachment_sessions
                SET last_heartbeat = ?
                WHERE session_id = ? AND disconnected_at IS NULL
                """,
                (utc_now_iso(), session_id),
            )

    def disconnect_attachment(self, session_id: str) -> None:
        """Mark an attachment disconnected."""

        with self.connect() as connection:
            connection.execute(
                """
                UPDATE attachment_sessions
                SET disconnected_at = ?, holds_lock = 0, lock_requested_at = NULL
                WHERE session_id = ? AND disconnected_at IS NULL
                """,
                (utc_now_iso(), session_id),
            )

    def set_attachment_lock_state(
        self,
        *,
        run_id: str,
        holder_id: str | None,
        queued_ids: list[str],
    ) -> None:
        """Persist lock ownership and queue membership for list/status readers."""

        now = utc_now_iso()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE attachment_sessions
                SET holds_lock = 0, lock_requested_at = NULL
                WHERE run_id = ? AND disconnected_at IS NULL
                """,
                (run_id,),
            )
            if holder_id is not None:
                connection.execute(
                    "UPDATE attachment_sessions SET holds_lock = 1 WHERE session_id = ?",
                    (holder_id,),
                )
            for session_id in queued_ids:
                connection.execute(
                    "UPDATE attachment_sessions SET lock_requested_at = ? WHERE session_id = ?",
                    (now, session_id),
                )

    def attachment_summary(
        self,
        run_id: str,
        *,
        lease_timeout_seconds: float = DEFAULT_LEASE_TIMEOUT_SECONDS,
    ) -> AttachmentSummary:
        """Return current lease-filtered and lifetime attachment counts."""

        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=max(0.0, lease_timeout_seconds))).isoformat(
            timespec="seconds"
        )
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    SUM(CASE WHEN mode = 'view' AND disconnected_at IS NULL
                             AND last_heartbeat >= ? THEN 1 ELSE 0 END) AS current_viewers,
                    SUM(CASE WHEN mode = 'interact' AND disconnected_at IS NULL
                             AND last_heartbeat >= ? THEN 1 ELSE 0 END) AS current_interactors,
                    SUM(CASE WHEN holds_lock = 1 AND disconnected_at IS NULL
                             AND last_heartbeat >= ? THEN 1 ELSE 0 END) AS lock_holders,
                    SUM(CASE WHEN lock_requested_at IS NOT NULL AND disconnected_at IS NULL
                             AND last_heartbeat >= ? THEN 1 ELSE 0 END) AS lock_queue
                FROM attachment_sessions
                WHERE run_id = ?
                """,
                (cutoff, cutoff, cutoff, cutoff, run_id),
            ).fetchone()
            run = connection.execute(
                """
                SELECT lifetime_view_count, lifetime_interact_count
                FROM runs WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
        if run is None:
            raise RunNotFoundError(f"No run found with ID '{run_id}'.")
        return AttachmentSummary(
            current_viewers=int(row["current_viewers"] or 0),
            current_interactors=int(row["current_interactors"] or 0),
            lifetime_viewers=int(run["lifetime_view_count"] or 0),
            lifetime_interactors=int(run["lifetime_interact_count"] or 0),
            lock_held=bool(row["lock_holders"]),
            lock_queue_count=int(row["lock_queue"] or 0),
        )

    def next_numeric_id(self, connection: sqlite3.Connection) -> int:
        """Return the lowest available user-facing numeric run ID."""

        rows = connection.execute("SELECT numeric_id FROM runs ORDER BY numeric_id ASC").fetchall()
        expected = 0
        for row in rows:
            value = row["numeric_id"]
            if value is None:
                continue
            numeric_id = int(value)
            if numeric_id > expected:
                return expected
            if numeric_id == expected:
                expected += 1
        return expected

    def get_run(self, run_id_or_prefix: str) -> RunRecord:
        """Return a run by exact ID or unambiguous ID prefix."""

        resolved = self.resolve_run_id(run_id_or_prefix)
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (resolved,)).fetchone()
        if row is None:
            raise RunNotFoundError(f"No run found with ID '{run_id_or_prefix}'.")
        return RunRecord.from_row(row)

    def resolve_run_id(self, run_id_or_prefix: str) -> str:
        """Resolve an exact ID or unambiguous prefix to a full run ID."""

        with self.connect() as connection:
            exact = connection.execute(
                "SELECT id FROM runs WHERE id = ?",
                (run_id_or_prefix,),
            ).fetchone()
            if exact is not None:
                return str(exact["id"])

            if run_id_or_prefix.isdigit():
                numeric = connection.execute(
                    "SELECT id FROM runs WHERE numeric_id = ?",
                    (int(run_id_or_prefix),),
                ).fetchone()
                if numeric is not None:
                    return str(numeric["id"])

            rows = connection.execute(
                "SELECT id FROM runs WHERE id LIKE ? ORDER BY created_at DESC LIMIT 10",
                (f"{escape_like(run_id_or_prefix)}%",),
            ).fetchall()

        if not rows:
            raise RunNotFoundError(f"No run found with ID prefix '{run_id_or_prefix}'.")
        if len(rows) > 1:
            matches = ", ".join(str(row["id"]) for row in rows)
            raise AmbiguousRunIdError(f"Run ID prefix '{run_id_or_prefix}' is ambiguous. Matches: {matches}")
        return str(rows[0]["id"])

    def list_runs(
        self,
        *,
        include_all: bool = True,
        limit: int | None = None,
        statuses: list[str] | None = None,
    ) -> list[RunRecord]:
        """List runs ordered by newest first."""

        normalized_statuses = list(statuses or [])
        if "active" in normalized_statuses:
            normalized_statuses = [status for status in normalized_statuses if status != "active"]
            normalized_statuses.extend(["pending", "running", "paused"])
        if normalized_statuses:
            placeholders = ",".join("?" for _ in normalized_statuses)
            where = f"WHERE status IN ({placeholders})"
            where_params: tuple[Any, ...] = tuple(dict.fromkeys(normalized_statuses))
        elif include_all:
            where = ""
            where_params = ()
        else:
            where = "WHERE status IN ('pending', 'running', 'paused')"
            where_params = ()
        limit_sql = "" if limit is None else "LIMIT ?"
        params = where_params if limit is None else (*where_params, limit)
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM runs {where} "
                "ORDER BY CASE WHEN status IN ('pending', 'running', 'paused') THEN 0 ELSE 1 END, created_at DESC "
                f"{limit_sql}",
                params,
            ).fetchall()
        return [RunRecord.from_row(row) for row in rows]

    def query_runs(
        self,
        *,
        cursor: str | None = None,
        limit: int = 50,
        sort_by: str = "created_at",
        sort_dir: str = "desc",
        status: str | list[str] | None = None,
        state: str | None = None,
        name: str | None = None,
        name_exact: bool = False,
        since: str | float | int | None = None,
        until: str | float | int | None = None,
        time_field: str = "created_at",
        exit_code: int | None = None,
        failed_only: bool = False,
        lost_only: bool = False,
        restart_of: str | None = None,
        duplicate_of: str | None = None,
        has_restarts: bool = False,
        include_total: bool = False,
    ) -> RunPage:
        """Query a bounded page of runs using SQL filters and keyset pagination."""

        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200.")
        sort_columns = {
            "created_at": "COALESCE(created_at, '')",
            "started_at": "COALESCE(started_at, '')",
            "ended_at": "COALESCE(ended_at, '')",
            "name": "COALESCE(name, '')",
            "numeric_id": "COALESCE(numeric_id, -1)",
        }
        if sort_by not in sort_columns:
            raise ValueError("sort_by must be one of: created_at, started_at, ended_at, name, numeric_id.")
        direction = sort_dir.casefold()
        if direction not in {"asc", "desc"}:
            raise ValueError("sort_dir must be 'asc' or 'desc'.")
        if time_field not in {"created_at", "started_at", "ended_at"}:
            raise ValueError("time_field must be created_at, started_at, or ended_at.")
        if state is not None and state not in {"active", "terminal"}:
            raise ValueError("state must be 'active' or 'terminal'.")
        if failed_only and lost_only:
            raise ValueError("failed_only and lost_only cannot both be true.")

        statuses = _normalize_status_filter(status)
        since_value = _normalize_query_timestamp(since)
        until_value = _normalize_query_timestamp(until)
        if since_value is not None and until_value is not None and since_value > until_value:
            raise ValueError("since must be less than or equal to until.")
        normalized_filters = {
            "status": statuses,
            "state": state,
            "name": name,
            "name_exact": bool(name_exact),
            "since": since_value,
            "until": until_value,
            "time_field": time_field,
            "exit_code": exit_code,
            "failed_only": bool(failed_only),
            "lost_only": bool(lost_only),
            "restart_of": restart_of,
            "duplicate_of": duplicate_of,
            "has_restarts": bool(has_restarts),
        }
        filter_hash = hashlib.sha256(
            json.dumps(normalized_filters, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:16]

        where: list[str] = []
        params: list[Any] = []
        if statuses:
            where.append(f"status IN ({','.join('?' for _ in statuses)})")
            params.extend(statuses)
        if state == "active":
            where.append("status IN ('pending', 'running', 'paused')")
        elif state == "terminal":
            where.append("status IN ('finished', 'failed', 'killed', 'lost')")
        if name is not None:
            if name_exact:
                where.append("name = ? COLLATE NOCASE")
                params.append(name)
            else:
                where.append("name LIKE ? ESCAPE '\\' COLLATE NOCASE")
                params.append(f"%{escape_like(name)}%")
        if since_value is not None:
            where.append(f"{time_field} IS NOT NULL AND {time_field} >= ?")
            params.append(since_value)
        if until_value is not None:
            where.append(f"{time_field} IS NOT NULL AND {time_field} <= ?")
            params.append(until_value)
        if exit_code is not None:
            where.append("exit_code = ?")
            params.append(exit_code)
        if failed_only:
            where.append("(status = 'failed' OR (status = 'finished' AND exit_code IS NOT NULL AND exit_code != 0))")
        if lost_only:
            where.append("status = 'lost'")
        if restart_of is not None:
            where.append("restart_of = ?")
            params.append(restart_of)
        if duplicate_of is not None:
            where.append("duplicate_of = ?")
            params.append(duplicate_of)
        if has_restarts:
            where.append("EXISTS (SELECT 1 FROM runs AS child WHERE child.restart_of = runs.id)")

        sort_expr = sort_columns[sort_by]
        order = direction.upper()
        cursor_data: dict[str, Any] | None = None
        if cursor is not None:
            cursor_data = _decode_run_cursor(cursor)
            if cursor_data.get("sort_by") != sort_by or cursor_data.get("sort_dir") != direction:
                raise ValueError("cursor sort does not match this query.")
            if cursor_data.get("filters") != filter_hash:
                raise ValueError("cursor filters do not match this query.")
            last_value = cursor_data.get("value")
            last_id = cursor_data.get("id")
            if not isinstance(last_id, str) or not isinstance(last_value, (str, int, float)):
                raise ValueError("cursor is invalid.")

        with self.connect() as connection:
            connection.set_progress_handler(lambda: 1, MAX_QUERY_VM_STEPS)
            if cursor_data is None:
                snapshot = connection.execute(
                    "SELECT created_at, id FROM runs ORDER BY created_at DESC, id DESC LIMIT 1"
                ).fetchone()
                snapshot_created_at = str(snapshot["created_at"]) if snapshot is not None else None
                snapshot_id = str(snapshot["id"]) if snapshot is not None else None
            else:
                snapshot_created_at = cursor_data.get("snapshot_created_at")
                snapshot_id = cursor_data.get("snapshot_id")
                if snapshot_created_at is not None and not isinstance(snapshot_id, str):
                    raise ValueError("cursor is invalid.")

            query_where = list(where)
            query_params = list(params)
            if snapshot_created_at is not None:
                query_where.append("(created_at < ? OR (created_at = ? AND id <= ?))")
                query_params.extend((snapshot_created_at, snapshot_created_at, snapshot_id))
            if cursor_data is not None:
                comparator = ">" if direction == "asc" else "<"
                query_where.append(f"({sort_expr}, id) {comparator} (?, ?)")
                query_params.extend((last_value, last_id))
            where_sql = f"WHERE {' AND '.join(query_where)}" if query_where else ""
            rows = connection.execute(
                f"SELECT * FROM runs {where_sql} ORDER BY {sort_expr} {order}, id {order} LIMIT ?",
                (*query_params, limit + 1),
            ).fetchall()
            total_count = None
            if include_total:
                count_where = list(where)
                count_params = list(params)
                if snapshot_created_at is not None:
                    count_where.append("(created_at < ? OR (created_at = ? AND id <= ?))")
                    count_params.extend((snapshot_created_at, snapshot_created_at, snapshot_id))
                count_sql = f"WHERE {' AND '.join(count_where)}" if count_where else ""
                total_count = int(
                    connection.execute(f"SELECT COUNT(*) FROM runs {count_sql}", count_params).fetchone()[0]
                )

        has_more = len(rows) > limit
        page_rows = rows[:limit]
        records = [RunRecord.from_row(row) for row in page_rows]
        next_cursor = None
        if has_more and page_rows:
            last = page_rows[-1]
            value = last[sort_by]
            if value is None:
                value = -1 if sort_by == "numeric_id" else ""
            next_cursor = _encode_run_cursor(
                {
                    "v": 1,
                    "sort_by": sort_by,
                    "sort_dir": direction,
                    "value": value,
                    "id": str(last["id"]),
                    "snapshot_created_at": snapshot_created_at,
                    "snapshot_id": snapshot_id,
                    "filters": filter_hash,
                }
            )
        return RunPage(
            items=records,
            next_cursor=next_cursor,
            has_more=has_more,
            page_size=len(records),
            total_count=total_count,
        )

    def get_run_lineage(self, run_id: str, *, max_nodes: int = 200) -> RunLineageSummary:
        """Return explicit restart/duplicate ancestors and descendants for a run."""

        if not 1 <= max_nodes <= 1000:
            raise ValueError("max_nodes must be between 1 and 1000.")
        record = self.get_run(run_id)
        ancestors: list[RunLineageNode] = []
        ancestor_ids = {record.id}
        pending_ancestors = [(record.restart_of, "restart"), (record.duplicate_of, "duplicate")]
        truncated = False
        while pending_ancestors:
            parent_id, relation = pending_ancestors.pop(0)
            if not parent_id or parent_id in ancestor_ids:
                continue
            if len(ancestors) >= max_nodes:
                truncated = True
                break
            try:
                parent = self.get_run(parent_id)
            except RunNotFoundError:
                continue
            ancestor_ids.add(parent.id)
            ancestors.append(_lineage_node(parent, f"parent_{relation}"))
            pending_ancestors.extend(((parent.restart_of, "restart"), (parent.duplicate_of, "duplicate")))
        descendants: list[RunLineageNode] = []
        pending = [(record.id, 0)]
        descendant_seen = {record.id}
        while pending and len(descendants) < max_nodes:
            parent_id, depth = pending.pop(0)
            with self.connect() as connection:
                connection.set_progress_handler(lambda: 1, MAX_QUERY_VM_STEPS)
                rows = connection.execute(
                    "SELECT * FROM runs WHERE restart_of = ? OR duplicate_of = ? "
                    "ORDER BY created_at ASC, id ASC LIMIT ?",
                    (parent_id, parent_id, max_nodes - len(descendants) + 1),
                ).fetchall()
            for row in rows:
                child = RunRecord.from_row(row)
                if child.id in descendant_seen:
                    continue
                descendant_seen.add(child.id)
                relation = "restart" if child.restart_of == parent_id else "duplicate"
                descendants.append(_lineage_node(child, f"child_{relation}"))
                pending.append((child.id, depth + 1))
                if len(descendants) >= max_nodes:
                    break
        if pending:
            truncated = True
        with self.connect() as connection:
            connection.set_progress_handler(lambda: 1, MAX_QUERY_VM_STEPS)
            totals = connection.execute(
                "SELECT (SELECT COUNT(*) FROM runs WHERE restart_of = ?) AS restarts, "
                "(SELECT COUNT(*) FROM runs WHERE duplicate_of = ?) AS duplicates",
                (record.id, record.id),
            ).fetchone()

        return RunLineageSummary(
            run_id=record.id,
            root_run_id=next(
                (node.id for node in reversed(ancestors) if node.relationship == "parent_restart"),
                ancestors[-1].id if ancestors else record.id,
            ),
            ancestors=ancestors,
            descendants=descendants,
            total_restarts=int(totals["restarts"] or 0),
            total_duplicates=int(totals["duplicates"] or 0),
            truncated=truncated,
        )

    def remove_run(self, run_id_or_prefix: str) -> RunRecord:
        """Remove a terminal run from the registry and return the removed record."""

        record = self.get_run(run_id_or_prefix)
        if record.is_active:
            raise RegistryError(f"Run '{record.numeric_id}' is still active; kill it before removing it.")
        with self.connect() as connection:
            connection.execute("DELETE FROM runs WHERE id = ?", (record.id,))
        return record

    def remove_finished_runs(self, *, clean_only: bool = False) -> list[RunRecord]:
        """Remove finished run records and return the removed records."""

        statuses = {STATUS_FINISHED} if clean_only else TERMINAL_STATUSES
        placeholders = ",".join("?" for _ in statuses)
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM runs WHERE status IN ({placeholders}) ORDER BY numeric_id ASC",
                tuple(sorted(statuses)),
            ).fetchall()
            records = [RunRecord.from_row(row) for row in rows]
            if records:
                connection.executemany(
                    "DELETE FROM runs WHERE id = ?",
                    [(record.id,) for record in records],
                )
        return records

    def prune_terminal_runs(self, *, limit: int) -> list[RunRecord]:
        """Retain only the newest configured number of terminal run records."""

        if limit < 0:
            raise RegistryError("Terminal record limit must be non-negative.")
        statuses = tuple(sorted(TERMINAL_STATUSES))
        placeholders = ",".join("?" for _ in statuses)
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM runs WHERE status IN ({placeholders}) "
                "ORDER BY created_at DESC",
                statuses,
            ).fetchall()
            removed = [RunRecord.from_row(row) for row in rows[limit:]]
            if removed:
                connection.executemany("DELETE FROM runs WHERE id = ?", [(record.id,) for record in removed])
        return removed

    def update_run(self, run_id: str, **fields: Any) -> RunRecord:
        """Update selected fields for a run and return the updated record."""

        if not fields:
            return self.get_run(run_id)
        fields["updated_at"] = utc_now_iso()
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = tuple(fields.values()) + (run_id,)
        with self.connect() as connection:
            connection.execute(f"UPDATE runs SET {assignments} WHERE id = ?", values)
        return self.get_run(run_id)

    def mark_started(
        self,
        *,
        run_id: str,
        pid: int,
        supervisor_pid: int,
        port: int,
    ) -> RunRecord:
        """Mark a run as started."""

        now = utc_now_iso()
        return self.update_run(
            run_id,
            status="running",
            started_at=now,
            pid=pid,
            supervisor_pid=supervisor_pid,
            port=port,
        )

    def mark_finished(self, *, run_id: str, status: str, exit_code: int | None) -> RunRecord:
        """Mark a run as finished, failed, killed, or lost."""

        return self.update_run(
            run_id,
            status=status,
            ended_at=utc_now_iso(),
            exit_code=exit_code,
            port=None,
        )

    def ids_exist(self, run_ids: Iterable[str]) -> set[str]:
        """Return the subset of IDs present in the registry."""

        ids = list(run_ids)
        if not ids:
            return set()
        placeholders = ",".join("?" for _ in ids)
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT id FROM runs WHERE id IN ({placeholders})",
                tuple(ids),
            ).fetchall()
        return {str(row["id"]) for row in rows}


def escape_like(value: str) -> str:
    """Escape LIKE wildcard characters for prefix matching."""

    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _normalize_status_filter(status: str | list[str] | None) -> list[str]:
    if status is None:
        return []
    values = status if isinstance(status, list) else status.split(",")
    allowed = {"pending", "running", "paused", "finished", "failed", "killed", "lost"}
    normalized = list(dict.fromkeys(value.strip().casefold() for value in values if value.strip()))
    invalid = sorted(set(normalized) - allowed)
    if invalid:
        raise ValueError(f"Unsupported status value(s): {', '.join(invalid)}.")
    return normalized


def _normalize_query_timestamp(value: str | float | int | None) -> str | None:
    if value is None:
        return None
    try:
        timestamp = str(value).strip()
        try:
            epoch = float(value)
        except (TypeError, ValueError):
            epoch = None
        if epoch is not None:
            parsed = datetime.fromtimestamp(epoch, tz=timezone.utc)
        else:
            if timestamp.endswith("Z"):
                timestamp = f"{timestamp[:-1]}+00:00"
            parsed = datetime.fromisoformat(timestamp)
            if parsed.tzinfo is None:
                raise ValueError("Timestamp must include a timezone.")
            parsed = parsed.astimezone(timezone.utc)
    except (OverflowError, OSError, TypeError) as error:
        raise ValueError(f"Invalid timestamp: {value!r}.") from error
    except ValueError as error:
        if "timezone" in str(error):
            raise
        raise ValueError(f"Invalid timestamp: {value!r}.") from error
    # Registry timestamps are persisted at second precision; use that exact format
    # so indexed lexical range comparisons remain aligned with stored values.
    return parsed.isoformat(timespec="seconds")


def _encode_run_cursor(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_run_cursor(cursor: str) -> dict[str, Any]:
    if not cursor or len(cursor) > 4096:
        raise ValueError("cursor is invalid.")
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        payload = json.loads(raw.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError("cursor is invalid.") from error
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise ValueError("cursor version is unsupported or invalid.")
    return payload


def _lineage_node(record: RunRecord, relationship: str) -> RunLineageNode:
    return RunLineageNode(
        id=record.id,
        numeric_id=record.numeric_id,
        name=record.name,
        status=record.status,
        created_at=record.created_at,
        relationship=relationship,
        exit_code=record.exit_code,
    )
