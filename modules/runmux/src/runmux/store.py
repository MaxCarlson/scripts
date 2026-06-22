"""SQLite-backed run registry for runmux."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from runmux.constants import DEFAULT_LEASE_TIMEOUT_SECONDS, STATUS_FINISHED, TERMINAL_STATUSES
from runmux.models import AttachmentSummary, RunRecord, utc_now_iso
from runmux.platform_paths import ensure_state_tree, get_state_dir

SCHEMA_VERSION = 3


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

    def list_runs(self, *, include_all: bool = True, limit: int | None = None) -> list[RunRecord]:
        """List runs ordered by newest first."""

        where = "" if include_all else "WHERE status IN ('pending', 'running', 'paused')"
        limit_sql = "" if limit is None else "LIMIT ?"
        params: tuple[Any, ...] = () if limit is None else (limit,)
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM runs {where} ORDER BY created_at DESC {limit_sql}",
                params,
            ).fetchall()
        return [RunRecord.from_row(row) for row in rows]

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

    return value.replace("%", "\\%").replace("_", "\\_")
