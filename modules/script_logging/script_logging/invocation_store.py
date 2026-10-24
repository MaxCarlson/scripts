"""Centralized invocation persistence and schema management."""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from typing import Optional


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
