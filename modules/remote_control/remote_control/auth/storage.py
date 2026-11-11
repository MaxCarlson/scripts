"""SQLite persistence engine for operator credentials, sessions, and audit logging."""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from notifications.config import _secure_path
from remote_control.models import AuditEvent, DeviceModel, OperatorModel, SessionModel

logger = logging.getLogger(__name__)

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS operators (
    operator_id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    totp_secret TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    operator_id TEXT NOT NULL,
    device_name TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    is_revoked INTEGER NOT NULL DEFAULT 0,
    revoked_at TEXT,
    FOREIGN KEY(operator_id) REFERENCES operators(operator_id)
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    session_id_hash TEXT UNIQUE NOT NULL,
    operator_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    csrf_token TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    revoked_at TEXT,
    user_agent TEXT NOT NULL DEFAULT '',
    ip_address TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(operator_id) REFERENCES operators(operator_id),
    FOREIGN KEY(device_id) REFERENCES devices(device_id)
);

CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip_address TEXT NOT NULL,
    attempt_time REAL NOT NULL,
    success INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS used_totp_timesteps (
    operator_id TEXT NOT NULL,
    timestep INTEGER NOT NULL,
    used_at REAL NOT NULL,
    PRIMARY KEY(operator_id, timestep)
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    device_id TEXT,
    action TEXT NOT NULL,
    decision TEXT NOT NULL,
    ip_address TEXT NOT NULL DEFAULT '',
    details TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_sessions_hash ON sessions(session_id_hash);
CREATE INDEX IF NOT EXISTS idx_login_ip_time ON login_attempts(ip_address, attempt_time);
"""


class AuthStorage:
    """Manages the isolated authentication and session SQLite database."""

    def __init__(self, db_path: Path, read_only: bool = False) -> None:
        self.db_path = db_path.resolve()
        self.read_only = read_only
        self.exists = self.db_path.is_file()
        if not self.read_only:
            self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self.read_only:
            if not self.db_path.is_file():
                raise FileNotFoundError(f"Auth database does not exist: {self.db_path}")
            conn = sqlite3.connect(
                f"file:{self.db_path.as_posix()}?mode=ro",
                uri=True,
                timeout=5.0,
            )
            conn.row_factory = sqlite3.Row
            return conn

        conn = sqlite3.connect(
            str(self.db_path),
            timeout=5.0,
            isolation_level="DEFERRED",
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        return conn

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        _secure_path(self.db_path.parent)

        with self._get_connection() as conn:
            conn.executescript(SCHEMA_V1)
            row = conn.execute("SELECT version FROM schema_version").fetchone()
            if not row:
                conn.execute("INSERT INTO schema_version (version) VALUES (1)")
            conn.commit()

        _secure_path(self.db_path)

    # ── Operator Methods ─────────────────────────────────────────────────────────

    def get_operator(self) -> Optional[Dict[str, Any]]:
        if self.read_only and not self.db_path.is_file():
            return None
        try:
            with self._get_connection() as conn:
                row = conn.execute("SELECT * FROM operators LIMIT 1").fetchone()
                return dict(row) if row else None
        except (sqlite3.OperationalError, FileNotFoundError):
            return None

    def create_operator(
        self,
        operator_id: str,
        username: str,
        password_hash: str,
        totp_secret: str,
    ) -> OperatorModel:
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO operators (operator_id, username, password_hash, totp_secret, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (operator_id, username, password_hash, totp_secret, now_iso, now_iso),
            )
            conn.commit()
        return OperatorModel(
            operator_id=operator_id,
            username=username,
            created_at=now_iso,
            updated_at=now_iso,
        )

    def update_operator_password(self, operator_id: str, password_hash: str) -> bool:
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        with self._get_connection() as conn:
            cur = conn.execute(
                "UPDATE operators SET password_hash = ?, updated_at = ? WHERE operator_id = ?",
                (password_hash, now_iso, operator_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def update_operator_totp(self, operator_id: str, totp_secret: str) -> bool:
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        with self._get_connection() as conn:
            cur = conn.execute(
                "UPDATE operators SET totp_secret = ?, updated_at = ? WHERE operator_id = ?",
                (totp_secret, now_iso, operator_id),
            )
            conn.commit()
            return cur.rowcount > 0

    # ── Device Methods ───────────────────────────────────────────────────────────

    def register_or_touch_device(
        self,
        device_id: str,
        operator_id: str,
        device_name: str,
    ) -> DeviceModel:
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM devices WHERE device_id = ?", (device_id,)).fetchone()
            if row:
                conn.execute(
                    "UPDATE devices SET last_seen_at = ?, device_name = ? WHERE device_id = ?",
                    (now_iso, device_name, device_id),
                )
                conn.commit()
                return DeviceModel(
                    device_id=device_id,
                    operator_id=row["operator_id"],
                    device_name=device_name,
                    first_seen_at=row["first_seen_at"],
                    last_seen_at=now_iso,
                    is_revoked=bool(row["is_revoked"]),
                    revoked_at=row["revoked_at"],
                )
            else:
                conn.execute(
                    """
                    INSERT INTO devices (device_id, operator_id, device_name, first_seen_at, last_seen_at, is_revoked)
                    VALUES (?, ?, ?, ?, ?, 0)
                    """,
                    (device_id, operator_id, device_name, now_iso, now_iso),
                )
                conn.commit()
                return DeviceModel(
                    device_id=device_id,
                    operator_id=operator_id,
                    device_name=device_name,
                    first_seen_at=now_iso,
                    last_seen_at=now_iso,
                    is_revoked=False,
                )

    def get_device(self, device_id: str) -> Optional[DeviceModel]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM devices WHERE device_id = ?", (device_id,)).fetchone()
            if not row:
                return None
            return DeviceModel(
                device_id=row["device_id"],
                operator_id=row["operator_id"],
                device_name=row["device_name"],
                first_seen_at=row["first_seen_at"],
                last_seen_at=row["last_seen_at"],
                is_revoked=bool(row["is_revoked"]),
                revoked_at=row["revoked_at"],
            )

    def list_devices(self) -> List[DeviceModel]:
        if self.read_only and not self.db_path.is_file():
            return []
        try:
            with self._get_connection() as conn:
                rows = conn.execute("SELECT * FROM devices ORDER BY last_seen_at DESC").fetchall()
                return [
                    DeviceModel(
                        device_id=r["device_id"],
                        operator_id=r["operator_id"],
                        device_name=r["device_name"],
                        first_seen_at=r["first_seen_at"],
                        last_seen_at=r["last_seen_at"],
                        is_revoked=bool(r["is_revoked"]),
                        revoked_at=r["revoked_at"],
                    )
                    for r in rows
                ]
        except (sqlite3.OperationalError, FileNotFoundError):
            return []

    def revoke_device(self, device_id: str) -> bool:
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        with self._get_connection() as conn:
            cur = conn.execute(
                "UPDATE devices SET is_revoked = 1, revoked_at = ? WHERE device_id = ?",
                (now_iso, device_id),
            )
            # Also revoke all active sessions for this device immediately
            conn.execute(
                "UPDATE sessions SET revoked_at = ? WHERE device_id = ? AND revoked_at IS NULL",
                (now_iso, device_id),
            )
            conn.commit()
            return cur.rowcount > 0

    # ── Session Methods ──────────────────────────────────────────────────────────

    def create_session(
        self,
        session_id: str,
        session_id_hash: str,
        operator_id: str,
        device_id: str,
        csrf_token: str,
        expires_at: str,
        user_agent: str = "",
        ip_address: str = "",
    ) -> SessionModel:
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    session_id, session_id_hash, operator_id, device_id, csrf_token,
                    created_at, expires_at, last_seen_at, user_agent, ip_address
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    session_id_hash,
                    operator_id,
                    device_id,
                    csrf_token,
                    now_iso,
                    expires_at,
                    now_iso,
                    user_agent,
                    ip_address,
                ),
            )
            conn.commit()

        return SessionModel(
            session_id=session_id,
            operator_id=operator_id,
            device_id=device_id,
            csrf_token=csrf_token,
            created_at=now_iso,
            expires_at=expires_at,
            last_seen_at=now_iso,
            user_agent=user_agent,
            ip_address=ip_address,
        )

    def get_session_by_hash(self, token_hash: str) -> Optional[SessionModel]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE session_id_hash = ?", (token_hash,)
            ).fetchone()
            if not row:
                return None
            return SessionModel(
                session_id=row["session_id"],
                operator_id=row["operator_id"],
                device_id=row["device_id"],
                csrf_token=row["csrf_token"],
                created_at=row["created_at"],
                expires_at=row["expires_at"],
                last_seen_at=row["last_seen_at"],
                revoked_at=row["revoked_at"],
                user_agent=row["user_agent"],
                ip_address=row["ip_address"],
            )

    def touch_session(self, session_id: str, expires_at: str, ip_address: str = "") -> None:
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE sessions
                SET last_seen_at = ?, expires_at = ?, ip_address = CASE WHEN ? != '' THEN ? ELSE ip_address END
                WHERE session_id = ?
                """,
                (now_iso, expires_at, ip_address, ip_address, session_id),
            )
            conn.commit()

    def revoke_session(self, session_id: str) -> bool:
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        with self._get_connection() as conn:
            cur = conn.execute(
                "UPDATE sessions SET revoked_at = ? WHERE session_id = ? AND revoked_at IS NULL",
                (now_iso, session_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def revoke_all_sessions_for_device(self, device_id: str) -> int:
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        with self._get_connection() as conn:
            cur = conn.execute(
                "UPDATE sessions SET revoked_at = ? WHERE device_id = ? AND revoked_at IS NULL",
                (now_iso, device_id),
            )
            conn.commit()
            return cur.rowcount

    def revoke_all_sessions_for_operator(self, operator_id: str) -> int:
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        with self._get_connection() as conn:
            cur = conn.execute(
                "UPDATE sessions SET revoked_at = ? WHERE operator_id = ? AND revoked_at IS NULL",
                (now_iso, operator_id),
            )
            conn.commit()
            return cur.rowcount

    def list_active_sessions(self) -> List[SessionModel]:
        if self.read_only and not self.db_path.is_file():
            return []
        try:
            now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            with self._get_connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM sessions WHERE revoked_at IS NULL AND expires_at > ? ORDER BY last_seen_at DESC",
                    (now_iso,),
                ).fetchall()
                return [
                    SessionModel(
                        session_id=r["session_id"],
                        operator_id=r["operator_id"],
                        device_id=r["device_id"],
                        csrf_token=r["csrf_token"],
                        created_at=r["created_at"],
                        expires_at=r["expires_at"],
                        last_seen_at=r["last_seen_at"],
                        revoked_at=r["revoked_at"],
                        user_agent=r["user_agent"],
                        ip_address=r["ip_address"],
                    )
                    for r in rows
                ]
        except (sqlite3.OperationalError, FileNotFoundError):
            return []

    # ── Rate Limiting & Replay Defense ───────────────────────────────────────────

    def record_login_attempt(self, ip_address: str, success: bool) -> None:
        with self._get_connection() as conn:
            conn.execute(
                "INSERT INTO login_attempts (ip_address, attempt_time, success) VALUES (?, ?, ?)",
                (ip_address, time.time(), 1 if success else 0),
            )
            conn.commit()

    def get_recent_failed_attempts(self, ip_address: str, window_seconds: int = 900) -> int:
        cutoff = time.time() - window_seconds
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) as count FROM login_attempts
                WHERE ip_address = ? AND attempt_time >= ? AND success = 0
                """,
                (ip_address, cutoff),
            ).fetchone()
            return int(row["count"]) if row else 0

    def clean_old_login_attempts(self, max_age_seconds: int = 86400) -> None:
        cutoff = time.time() - max_age_seconds
        with self._get_connection() as conn:
            conn.execute("DELETE FROM login_attempts WHERE attempt_time < ?", (cutoff,))
            conn.commit()

    def is_totp_timestep_used(self, operator_id: str, timestep: int) -> bool:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM used_totp_timesteps WHERE operator_id = ? AND timestep = ?",
                (operator_id, timestep),
            ).fetchone()
            return row is not None

    def consume_totp_timestep(
        self,
        operator_id: str,
        candidate_timesteps: List[int],
    ) -> Optional[int]:
        """
        Atomically find the first unconsumed candidate timestep and mark it used.
        Returns the consumed timestep if successful, or None if all candidate timesteps were already used.
        Enforces atomic check-and-insert using SQLite transactions.
        """
        if not candidate_timesteps:
            return None

        now = time.time()
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                placeholders = ",".join("?" for _ in candidate_timesteps)
                rows = conn.execute(
                    f"SELECT timestep FROM used_totp_timesteps WHERE operator_id = ? AND timestep IN ({placeholders})",
                    [operator_id] + candidate_timesteps,
                ).fetchall()
                consumed_steps = {r["timestep"] for r in rows}

                for step in candidate_timesteps:
                    if step not in consumed_steps:
                        try:
                            conn.execute(
                                "INSERT INTO used_totp_timesteps (operator_id, timestep, used_at) VALUES (?, ?, ?)",
                                (operator_id, step, now),
                            )
                            conn.commit()
                            return step
                        except sqlite3.IntegrityError:
                            continue

                conn.commit()
                return None
            except Exception:
                conn.rollback()
                raise

    def mark_totp_timestep_used(self, operator_id: str, timestep: int) -> None:
        with self._get_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO used_totp_timesteps (operator_id, timestep, used_at) VALUES (?, ?, ?)",
                (operator_id, timestep, time.time()),
            )
            conn.commit()

    # ── Audit Logging ────────────────────────────────────────────────────────────

    def record_audit_event(self, event: AuditEvent) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO audit_events (timestamp, actor_id, device_id, action, decision, ip_address, details)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.timestamp,
                    event.actor_id,
                    event.device_id,
                    event.action,
                    event.decision,
                    event.ip_address,
                    event.details,
                ),
            )
            conn.commit()

    def list_audit_events(self, limit: int = 50) -> List[AuditEvent]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [
                AuditEvent(
                    timestamp=r["timestamp"],
                    actor_id=r["actor_id"],
                    device_id=r["device_id"],
                    action=r["action"],
                    decision=r["decision"],
                    ip_address=r["ip_address"],
                    details=r["details"],
                )
                for r in rows
            ]
