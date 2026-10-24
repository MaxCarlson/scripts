"""Centralized invocation persistence and schema management."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

from .models import InvocationRecord
from .redaction import compute_pattern_id, normalize_argv_json, redact_argv


def resolve_invocation_db_path(*, create: bool = False) -> Path:
    """Resolve the platform-appropriate path to the invocations SQLite database."""
    env_override = os.environ.get("SCRIPT_LOGGING_INVOCATION_DB")
    if env_override:
        path = Path(env_override).resolve()
        if create:
            path.parent.mkdir(parents=True, exist_ok=True)
        return path

    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA")
        base = Path(local_appdata) if local_appdata else Path.home() / "AppData" / "Local"
        path = (base / "ScriptsToolkit" / "invocations.sqlite3").resolve()
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
        path = (base / "ScriptsToolkit" / "invocations.sqlite3").resolve()
    else:
        xdg_state = os.environ.get("XDG_STATE_HOME")
        base = Path(xdg_state) if xdg_state else Path.home() / ".local" / "state"
        path = (base / "scripts-toolkit" / "invocations.sqlite3").resolve()

    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


class InvocationStore:
    """Persistent SQLite store for command invocations and execution counters."""

    def __init__(self, path: Optional[Path | str] = None) -> None:
        if path is None:
            self.path = resolve_invocation_db_path(create=True)
        else:
            self.path = Path(path).resolve()
            self.path.parent.mkdir(parents=True, exist_ok=True)

        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        """Create and configure a SQLite connection with WAL mode and busy timeout."""
        conn = sqlite3.connect(str(self.path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 15000;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self) -> None:
        """Initialize database tables, indices, and schema version."""
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                INSERT OR IGNORE INTO schema_meta (key, value) VALUES ('schema_version', '1');

                CREATE TABLE IF NOT EXISTS invocations (
                    invocation_id TEXT PRIMARY KEY,
                    program_id TEXT NOT NULL,
                    invoked_name TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    pattern_id TEXT NOT NULL,
                    raw_argv_json TEXT NOT NULL,
                    redacted_argv_json TEXT NOT NULL,
                    is_redacted INTEGER NOT NULL,
                    cwd TEXT NOT NULL,
                    started_at_utc TEXT NOT NULL,
                    started_epoch_ms INTEGER NOT NULL,
                    finished_at_utc TEXT,
                    duration_ms INTEGER,
                    exit_code INTEGER,
                    status TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_invocations_order ON invocations(started_epoch_ms DESC, invocation_id DESC);
                CREATE INDEX IF NOT EXISTS idx_invocations_program ON invocations(program_id, started_epoch_ms DESC);
                CREATE INDEX IF NOT EXISTS idx_invocations_alias ON invocations(invoked_name, started_epoch_ms DESC);
                CREATE INDEX IF NOT EXISTS idx_invocations_pattern ON invocations(pattern_id, started_epoch_ms DESC);

                CREATE TABLE IF NOT EXISTS command_patterns (
                    pattern_id TEXT PRIMARY KEY,
                    program_id TEXT NOT NULL,
                    pattern_argv_json TEXT NOT NULL,
                    invocation_count INTEGER NOT NULL DEFAULT 0,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    unknown_count INTEGER NOT NULL DEFAULT 0,
                    first_seen_utc TEXT NOT NULL,
                    last_seen_utc TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_command_patterns_prog ON command_patterns(program_id);
                CREATE INDEX IF NOT EXISTS idx_command_patterns_seen ON command_patterns(last_seen_utc DESC);

                CREATE TABLE IF NOT EXISTS program_usage (
                    program_id TEXT PRIMARY KEY,
                    total_starts INTEGER NOT NULL DEFAULT 0,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    unknown_count INTEGER NOT NULL DEFAULT 0,
                    first_seen_utc TEXT NOT NULL,
                    last_seen_utc TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS alias_usage (
                    invoked_name TEXT NOT NULL,
                    program_id TEXT NOT NULL,
                    total_starts INTEGER NOT NULL DEFAULT 0,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    unknown_count INTEGER NOT NULL DEFAULT 0,
                    first_seen_utc TEXT NOT NULL,
                    last_seen_utc TEXT NOT NULL,
                    PRIMARY KEY (invoked_name, program_id)
                );
                """
            )

    def start_invocation(
        self,
        program_id: str,
        invoked_name: str,
        argv: Tuple[str, ...],
        cwd: Path | str,
        origin: str = "launcher",
        *,
        invocation_id: Optional[str] = None,
        started_at_utc: Optional[str] = None,
        fail_open: bool = True,
    ) -> str:
        """Record the start of a command invocation and atomically increment start counters."""
        inv_id = invocation_id or uuid.uuid4().hex
        try:
            if started_at_utc is None:
                now = datetime.now(timezone.utc)
                started_at_utc = now.isoformat()
                started_epoch_ms = int(now.timestamp() * 1000)
            else:
                dt = datetime.fromisoformat(started_at_utc)
                started_epoch_ms = int(dt.timestamp() * 1000)

            redacted_argv, is_redacted = redact_argv(argv)
            pattern_id = compute_pattern_id(program_id, redacted_argv)
            raw_argv_json = normalize_argv_json(argv)
            redacted_argv_json = normalize_argv_json(redacted_argv)
            cwd_str = str(cwd)
            created_at_utc = started_at_utc

            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    INSERT INTO invocations (
                        invocation_id, program_id, invoked_name, origin, pattern_id,
                        raw_argv_json, redacted_argv_json, is_redacted, cwd,
                        started_at_utc, started_epoch_ms, status, created_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'started', ?)
                    """,
                    (
                        inv_id,
                        program_id,
                        invoked_name,
                        origin,
                        pattern_id,
                        raw_argv_json,
                        redacted_argv_json,
                        1 if is_redacted else 0,
                        cwd_str,
                        started_at_utc,
                        started_epoch_ms,
                        created_at_utc,
                    ),
                )

                # Atomically update command_patterns
                conn.execute(
                    """
                    INSERT INTO command_patterns (
                        pattern_id, program_id, pattern_argv_json,
                        invocation_count, success_count, failure_count, unknown_count,
                        first_seen_utc, last_seen_utc
                    ) VALUES (?, ?, ?, 1, 0, 0, 0, ?, ?)
                    ON CONFLICT(pattern_id) DO UPDATE SET
                        invocation_count = invocation_count + 1,
                        last_seen_utc = excluded.last_seen_utc
                    """,
                    (pattern_id, program_id, redacted_argv_json, started_at_utc, started_at_utc),
                )

                # Atomically update program_usage
                conn.execute(
                    """
                    INSERT INTO program_usage (
                        program_id, total_starts, success_count, failure_count, unknown_count,
                        first_seen_utc, last_seen_utc
                    ) VALUES (?, 1, 0, 0, 0, ?, ?)
                    ON CONFLICT(program_id) DO UPDATE SET
                        total_starts = total_starts + 1,
                        last_seen_utc = excluded.last_seen_utc
                    """,
                    (program_id, started_at_utc, started_at_utc),
                )

                # Atomically update alias_usage
                conn.execute(
                    """
                    INSERT INTO alias_usage (
                        invoked_name, program_id, total_starts, success_count, failure_count, unknown_count,
                        first_seen_utc, last_seen_utc
                    ) VALUES (?, ?, 1, 0, 0, 0, ?, ?)
                    ON CONFLICT(invoked_name, program_id) DO UPDATE SET
                        total_starts = total_starts + 1,
                        last_seen_utc = excluded.last_seen_utc
                    """,
                    (invoked_name, program_id, started_at_utc, started_at_utc),
                )

            return inv_id
        except (sqlite3.Error, OSError) as err:
            if not fail_open:
                raise
            if os.environ.get("SCRIPT_LOGGING_DEBUG") == "1":
                sys.stderr.write(f"[script_logging] Database error during start_invocation: {err}\n")
            return f"fallback-{uuid.uuid4().hex}"

    def finish_invocation(
        self,
        invocation_id: str,
        exit_code: Optional[int] = None,
        status: str = "exited",
        *,
        finished_at_utc: Optional[str] = None,
        fail_open: bool = True,
    ) -> None:
        """Record process completion, duration, exit code, and atomically maintain success/failure counters."""
        if fail_open and invocation_id.startswith("fallback-"):
            return

        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    """
                    SELECT invocation_id, program_id, invoked_name, pattern_id,
                           started_at_utc, started_epoch_ms, status
                    FROM invocations WHERE invocation_id = ?
                    """,
                    (invocation_id,),
                ).fetchone()

                if not row:
                    return

                # Terminal status transitions are idempotent; only update counters once
                if row["status"] in ("exited", "launch_failed", "interrupted"):
                    return

                if finished_at_utc is None:
                    now = datetime.now(timezone.utc)
                    finished_at_utc = now.isoformat()
                    finished_epoch_ms = int(now.timestamp() * 1000)
                else:
                    dt = datetime.fromisoformat(finished_at_utc)
                    finished_epoch_ms = int(dt.timestamp() * 1000)

                duration_ms = max(0, finished_epoch_ms - row["started_epoch_ms"])

                conn.execute(
                    """
                    UPDATE invocations
                    SET finished_at_utc = ?, duration_ms = ?, exit_code = ?, status = ?
                    WHERE invocation_id = ?
                    """,
                    (finished_at_utc, duration_ms, exit_code, status, invocation_id),
                )

                # Determine outcome category
                is_success = (status == "exited" and exit_code == 0)
                is_failure = (exit_code is not None and exit_code != 0) or status in (
                    "launch_failed",
                    "interrupted",
                )

                if is_success:
                    counter_col = "success_count"
                elif is_failure:
                    counter_col = "failure_count"
                else:
                    counter_col = "unknown_count"

                conn.execute(
                    f"UPDATE command_patterns SET {counter_col} = {counter_col} + 1, last_seen_utc = ? WHERE pattern_id = ?",
                    (finished_at_utc, row["pattern_id"]),
                )
                conn.execute(
                    f"UPDATE program_usage SET {counter_col} = {counter_col} + 1, last_seen_utc = ? WHERE program_id = ?",
                    (finished_at_utc, row["program_id"]),
                )
                conn.execute(
                    f"UPDATE alias_usage SET {counter_col} = {counter_col} + 1, last_seen_utc = ? WHERE invoked_name = ? AND program_id = ?",
                    (finished_at_utc, row["invoked_name"], row["program_id"]),
                )
        except (sqlite3.Error, OSError) as err:
            if not fail_open:
                raise
            if os.environ.get("SCRIPT_LOGGING_DEBUG") == "1":
                sys.stderr.write(f"[script_logging] Database error during finish_invocation: {err}\n")

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
