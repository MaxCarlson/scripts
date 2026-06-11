"""SQLite-backed run registry for runmux."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from runmux.constants import STATUS_FINISHED, TERMINAL_STATUSES
from runmux.models import RunRecord, utc_now_iso
from runmux.platform_paths import ensure_state_tree, get_state_dir

SCHEMA_VERSION = 2


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
                    columns INTEGER
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

        columns = {
            str(row["name"]) for row in connection.execute("PRAGMA table_info(runs)").fetchall()
        }
        if "numeric_id" not in columns:
            connection.execute("ALTER TABLE runs ADD COLUMN numeric_id INTEGER")
            rows = connection.execute("SELECT id FROM runs ORDER BY created_at ASC").fetchall()
            for numeric_id, row in enumerate(rows):
                connection.execute(
                    "UPDATE runs SET numeric_id = ? WHERE id = ?",
                    (numeric_id, str(row["id"])),
                )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_numeric_id ON runs(numeric_id)"
        )

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
            raise AmbiguousRunIdError(
                f"Run ID prefix '{run_id_or_prefix}' is ambiguous. Matches: {matches}"
            )
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
            raise RegistryError(
                f"Run '{record.numeric_id}' is still active; kill it before removing it."
            )
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
