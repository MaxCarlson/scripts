"""Durable persistence for confirmation challenges, execution journal, and action audit."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from notifications.config import _secure_path
from remote_control.actions.models import (
    ActionExecutionRecord,
    ConfirmationChallenge,
    ExecutionState,
)
from remote_control.actions.state_fingerprint import redact_sensitive_data

logger = logging.getLogger(__name__)

SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS action_challenges (
    challenge_id TEXT PRIMARY KEY,
    operator_id TEXT NOT NULL,
    session_id_hash TEXT NOT NULL,
    device_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    action_version TEXT NOT NULL,
    arguments_digest TEXT NOT NULL,
    state_fingerprint TEXT NOT NULL,
    rc_request_id TEXT,
    prepared_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    rejection_reason TEXT
);

CREATE TABLE IF NOT EXISTS action_executions (
    execution_id TEXT PRIMARY KEY,
    action_id TEXT NOT NULL,
    action_version TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    session_id_hash TEXT NOT NULL,
    device_id TEXT NOT NULL,
    idempotency_key_hash TEXT NOT NULL,
    arguments_digest TEXT NOT NULL,
    state_fingerprint TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    result_category TEXT,
    error_code TEXT,
    postcondition_verified INTEGER NOT NULL DEFAULT 0,
    summary TEXT NOT NULL DEFAULT '',
    details_json TEXT,
    dispatch_phase TEXT NOT NULL DEFAULT 'reserved_not_dispatched'
);

CREATE TABLE IF NOT EXISTS action_resource_locks (
    resource_key TEXT PRIMARY KEY,
    holder_execution_id TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    device_id TEXT,
    action TEXT NOT NULL,
    decision TEXT NOT NULL,
    ip_address TEXT,
    details TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_exec_idempotency ON action_executions(action_id, idempotency_key_hash);
CREATE INDEX IF NOT EXISTS idx_challenges_lookup ON action_challenges(challenge_id, status);
CREATE INDEX IF NOT EXISTS idx_executions_action_time ON action_executions(action_id, started_at);
"""

SCHEMA_V3 = SCHEMA_V2 + """
CREATE TABLE IF NOT EXISTS action_resource_barriers (
    resource_key TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL,
    barrier_status TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    cleared_at TEXT,
    cleared_by TEXT,
    evidence TEXT
);
CREATE INDEX IF NOT EXISTS idx_barriers_active ON action_resource_barriers(resource_key, cleared_at);
"""


class ActionStorage:
    """Manages persistent confirmation challenges, execution journal, and action audit."""

    def __init__(self, db_path: Path, read_only: bool = False) -> None:
        self.db_path = db_path.resolve()
        self.read_only = read_only
        self.exists = self.db_path.is_file()
        if not self.read_only:
            self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self.read_only:
            if not self.db_path.is_file():
                raise FileNotFoundError(f"Database does not exist: {self.db_path}")
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
            isolation_level=None,  # Autocommit mode; transactions managed explicitly via BEGIN
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        return conn

    def get_schema_version(self) -> Optional[int]:
        """Read-only check of schema version without running migrations."""
        if not self.db_path.is_file():
            return None
        try:
            with self._get_connection() as conn:
                row = conn.execute("SELECT version FROM schema_version").fetchone()
                return int(row["version"]) if row else None
        except Exception:
            return None

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        _secure_path(self.db_path.parent)

        with self._get_connection() as conn:
            conn.executescript(SCHEMA_V3)
            conn.execute("BEGIN IMMEDIATE;")
            try:
                # Add dispatch_phase column if missing from existing database
                cols = [r["name"] for r in conn.execute("PRAGMA table_info(action_executions)").fetchall()]
                if "dispatch_phase" not in cols:
                    conn.execute("ALTER TABLE action_executions ADD COLUMN dispatch_phase TEXT NOT NULL DEFAULT 'reserved_not_dispatched';")

                # Ensure schema_version table exists and record v3
                conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY);")
                row = conn.execute("SELECT version FROM schema_version").fetchone()
                if not row:
                    conn.execute("INSERT INTO schema_version (version) VALUES (3);")
                elif row["version"] < 3:
                    conn.execute("UPDATE schema_version SET version = 3;")
                conn.execute("COMMIT;")
            except Exception:
                conn.execute("ROLLBACK;")
                raise

        _secure_path(self.db_path)

    # ── Challenge Management ──────────────────────────────────────────────────

    def save_challenge(self, challenge: ConfirmationChallenge) -> None:
        """Persist a new confirmation challenge."""
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                conn.execute(
                    """
                    INSERT INTO action_challenges (
                        challenge_id, operator_id, session_id_hash, device_id,
                        action_id, action_version, arguments_digest, state_fingerprint,
                        rc_request_id, prepared_at, expires_at, status, rejection_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        challenge.challenge_id,
                        challenge.operator_id,
                        challenge.session_id_hash,
                        challenge.device_id,
                        challenge.action_id,
                        challenge.action_version,
                        challenge.arguments_digest,
                        challenge.state_fingerprint,
                        challenge.rc_request_id,
                        challenge.prepared_at,
                        challenge.expires_at,
                        challenge.status,
                        challenge.rejection_reason,
                    ),
                )
                conn.execute("COMMIT;")
            except Exception:
                conn.execute("ROLLBACK;")
                raise

    def get_challenge(self, challenge_id: str) -> Optional[ConfirmationChallenge]:
        """Retrieve a confirmation challenge by ID."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM action_challenges WHERE challenge_id = ?", (challenge_id,)
            ).fetchone()
            if not row:
                return None
            return ConfirmationChallenge(
                challenge_id=row["challenge_id"],
                operator_id=row["operator_id"],
                session_id_hash=row["session_id_hash"],
                device_id=row["device_id"],
                action_id=row["action_id"],
                action_version=row["action_version"],
                arguments_digest=row["arguments_digest"],
                state_fingerprint=row["state_fingerprint"],
                rc_request_id=row["rc_request_id"],
                prepared_at=row["prepared_at"],
                expires_at=row["expires_at"],
                status=row["status"],
                rejection_reason=row["rejection_reason"],
            )

    def consume_challenge(
        self,
        challenge_id: str,
        operator_id: str,
        device_id: str,
        session_id_hash: str,
        action_id: str,
        arguments_digest: str,
        now_iso: str,
    ) -> bool:
        """Atomically consume a confirmation challenge. Returns True if successfully consumed."""
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                cur = conn.execute(
                    """
                    UPDATE action_challenges
                    SET status = 'consumed'
                    WHERE challenge_id = ?
                      AND operator_id = ?
                      AND device_id = ?
                      AND session_id_hash = ?
                      AND action_id = ?
                      AND arguments_digest = ?
                      AND status = 'pending'
                      AND expires_at >= ?
                    """,
                    (
                        challenge_id,
                        operator_id,
                        device_id,
                        session_id_hash,
                        action_id,
                        arguments_digest,
                        now_iso,
                    ),
                )
                consumed = (cur.rowcount == 1)
                conn.execute("COMMIT;")
                return consumed
            except Exception:
                conn.execute("ROLLBACK;")
                raise

    def reject_challenge(self, challenge_id: str, reason: str) -> None:
        """Mark a challenge as rejected with a reason."""
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                conn.execute(
                    "UPDATE action_challenges SET status = 'rejected', rejection_reason = ? WHERE challenge_id = ?",
                    (reason, challenge_id),
                )
                conn.execute("COMMIT;")
            except Exception:
                conn.execute("ROLLBACK;")
                raise

    # ── Execution Journal and Idempotency ──────────────────────────────────────

    def reserve_execution(
        self, execution: ActionExecutionRecord
    ) -> Tuple[bool, ActionExecutionRecord]:
        """Atomically reserve an idempotency key before calling external mutations.

        Returns:
            (True, execution) if the reservation was newly created.
            (False, existing_record) if the idempotency key was already reserved or executed.
        """
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                # Check for existing execution under the same action and idempotency key hash
                existing = conn.execute(
                    "SELECT * FROM action_executions WHERE action_id = ? AND idempotency_key_hash = ?",
                    (execution.action_id, execution.idempotency_key_hash),
                ).fetchone()

                if existing:
                    conn.execute("COMMIT;")
                    return (
                        False,
                        ActionExecutionRecord(
                            execution_id=existing["execution_id"],
                            action_id=existing["action_id"],
                            action_version=existing["action_version"],
                            actor_id=existing["actor_id"],
                            session_id_hash=existing["session_id_hash"],
                            device_id=existing["device_id"],
                            idempotency_key_hash=existing["idempotency_key_hash"],
                            arguments_digest=existing["arguments_digest"],
                            state_fingerprint=existing["state_fingerprint"],
                            started_at=existing["started_at"],
                            finished_at=existing["finished_at"],
                            status=ExecutionState(existing["status"]),
                            result_category=existing["result_category"],
                            error_code=existing["error_code"],
                            postcondition_verified=bool(existing["postcondition_verified"]),
                            summary=existing["summary"],
                            details_json=existing["details_json"],
                            dispatch_phase=existing["dispatch_phase"] if "dispatch_phase" in existing.keys() else "reserved_not_dispatched",
                        ),
                    )

                conn.execute(
                    """
                    INSERT INTO action_executions (
                        execution_id, action_id, action_version, actor_id,
                        session_id_hash, device_id, idempotency_key_hash,
                        arguments_digest, state_fingerprint, started_at,
                        status, summary, dispatch_phase
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        execution.execution_id,
                        execution.action_id,
                        execution.action_version,
                        execution.actor_id,
                        execution.session_id_hash,
                        execution.device_id,
                        execution.idempotency_key_hash,
                        execution.arguments_digest,
                        execution.state_fingerprint,
                        execution.started_at,
                        execution.status.value,
                        execution.summary[:256] if execution.summary else "",
                        getattr(execution, "dispatch_phase", "reserved_not_dispatched"),
                    ),
                )
                conn.execute("COMMIT;")
                return (True, execution)
            except sqlite3.IntegrityError:
                conn.execute("ROLLBACK;")
                existing_rec = self.get_execution_by_idempotency_key(execution.action_id, execution.idempotency_key_hash)
                if existing_rec:
                    return (False, existing_rec)
                raise
            except Exception:
                conn.execute("ROLLBACK;")
                raise

    def update_execution(
        self,
        execution_id: str,
        status: ExecutionState,
        finished_at: str,
        result_category: Optional[str] = None,
        error_code: Optional[str] = None,
        postcondition_verified: bool = False,
        summary: str = "",
        details: Optional[Dict[str, Any]] = None,
        dispatch_phase: Optional[str] = None,
    ) -> None:
        """Update an execution record upon outcome determination."""
        if self.read_only:
            raise PermissionError("ActionStorage is in read-only mode")
        # Sanitize and bound details payload (64KB max of valid JSON)
        sanitized_details = redact_sensitive_data(details) if details else None
        details_str = json.dumps(sanitized_details) if sanitized_details else None
        if details_str and len(details_str) > 65536:
            truncated_obj = {
                "truncated": True,
                "original_size": len(details_str),
                "preview": details_str[:60000],
            }
            details_str = json.dumps(truncated_obj)

        bounded_summary = (summary or "")[:256]

        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                conn.execute(
                    """
                    UPDATE action_executions
                    SET status = ?,
                        finished_at = ?,
                        result_category = ?,
                        error_code = ?,
                        postcondition_verified = ?,
                        summary = ?,
                        details_json = ?,
                        dispatch_phase = COALESCE(?, dispatch_phase)
                    WHERE execution_id = ?
                    """,
                    (
                        status.value,
                        finished_at,
                        result_category,
                        error_code,
                        1 if postcondition_verified else 0,
                        bounded_summary,
                        details_str,
                        dispatch_phase,
                        execution_id,
                    ),
                )
                conn.execute("COMMIT;")
            except Exception:
                conn.execute("ROLLBACK;")
                raise

    def update_execution_dispatch_phase(self, execution_id: str, dispatch_phase: str) -> None:
        """Atomically transition the dispatch phase before/during external dispatch."""
        if self.read_only:
            raise PermissionError("ActionStorage is in read-only mode")
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                conn.execute(
                    "UPDATE action_executions SET dispatch_phase = ? WHERE execution_id = ?",
                    (dispatch_phase, execution_id),
                )
                conn.execute("COMMIT;")
            except Exception:
                conn.execute("ROLLBACK;")
                raise

    def reconcile_dangling_executions(
        self,
        concurrency_key: Optional[str] = None,
        exclude_execution_id: Optional[str] = None,
        only_expired: bool = False,
    ) -> List[Dict[str, Any]]:
        """Detect and reconcile dangling executions left by terminated or crashed processes.

        Stage D & Mandatory Amendment 1 Invariants:
        - If an execution was in 'dispatch_started' when the process terminated:
          The external mutation may have reached the subsystem. It must be sealed as
          status='outcome_unknown', dispatch_phase='outcome_unknown', and an explicit
          durable barrier ('locked_unresolved') must be placed on the resource key.
        - If an execution was in ('reserved_not_dispatched', 'dispatch_possible') when terminated:
          It was guaranteed never dispatched. It is transitioned to status='failed',
          dispatch_phase='terminal_without_dispatch' (no barrier).
        - Active executions (matching exclude_execution_id or with unexpired leases when
          only_expired=True) are preserved and never prematurely terminated.
        """
        if self.read_only or not self.db_path.is_file():
            return []

        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        reconciled = []

        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                # Find all executions with finished_at IS NULL
                rows = conn.execute("SELECT * FROM action_executions WHERE finished_at IS NULL").fetchall()
                for r in rows:
                    exec_id = r["execution_id"]
                    if exclude_execution_id and exec_id == exclude_execution_id:
                        continue

                    phase = r["dispatch_phase"] if "dispatch_phase" in r.keys() else "reserved_not_dispatched"
                    act_id = r["action_id"]

                    # Find associated lock and resource key
                    lock_row = conn.execute(
                        "SELECT resource_key, expires_at FROM action_resource_locks WHERE holder_execution_id = ?",
                        (exec_id,),
                    ).fetchone()

                    res_key = concurrency_key
                    if not res_key:
                        if lock_row:
                            res_key = lock_row["resource_key"]
                        else:
                            res_key = f"action:{act_id}"

                    # If concurrency_key was passed, filter to matching executions
                    if concurrency_key and res_key != concurrency_key:
                        continue

                    # If only_expired is True and an active lock lease exists, do not reconcile
                    if only_expired and lock_row and lock_row["expires_at"] > now_iso:
                        continue

                    if phase == "dispatch_started":
                        conn.execute(
                            """
                            UPDATE action_executions
                            SET status = 'outcome_unknown',
                                dispatch_phase = 'outcome_unknown',
                                finished_at = ?,
                                result_category = 'crash_recovery',
                                error_code = 'process_terminated_during_dispatch',
                                summary = 'Process terminated during or immediately after mutation dispatch. Outcome uncertain.'
                            WHERE execution_id = ?
                            """,
                            (now_iso, exec_id),
                        )
                        # Set durable barrier if not already active
                        b_row = conn.execute(
                            "SELECT resource_key FROM action_resource_barriers WHERE resource_key = ? AND cleared_at IS NULL",
                            (res_key,),
                        ).fetchone()
                        if not b_row:
                            conn.execute(
                                """
                                INSERT OR REPLACE INTO action_resource_barriers (
                                    resource_key, execution_id, barrier_status, reason, created_at, cleared_at
                                )
                                VALUES (?, ?, 'locked_unresolved', ?, ?, NULL)
                                """,
                                (
                                    res_key,
                                    exec_id,
                                    f"Dangling execution {exec_id} terminated during dispatch. Durable barrier established.",
                                    now_iso,
                                ),
                            )
                        reconciled.append({"execution_id": exec_id, "action": "barrier_established", "resource_key": res_key})
                    else:
                        conn.execute(
                            """
                            UPDATE action_executions
                            SET status = 'failed',
                                dispatch_phase = 'terminal_without_dispatch',
                                finished_at = ?,
                                result_category = 'crash_recovery',
                                error_code = 'process_terminated_before_dispatch',
                                summary = 'Process terminated before external dispatch. No mutation occurred.'
                            WHERE execution_id = ?
                            """,
                            (now_iso, exec_id),
                        )
                        reconciled.append({"execution_id": exec_id, "action": "terminated_without_dispatch", "resource_key": res_key})

                # Clear any expired leases in action_resource_locks held by reconciled executions
                conn.execute(
                    """
                    DELETE FROM action_resource_locks
                    WHERE holder_execution_id IN (
                        SELECT execution_id FROM action_executions WHERE finished_at IS NOT NULL
                    )
                    """
                )
                conn.execute("COMMIT;")
            except Exception:
                conn.execute("ROLLBACK;")
                raise

        return reconciled

    def get_execution(self, execution_id: str) -> Optional[ActionExecutionRecord]:
        """Retrieve an execution record by ID."""
        if self.read_only and not self.db_path.is_file():
            return None
        try:
            with self._get_connection() as conn:
                row = conn.execute(
                    "SELECT * FROM action_executions WHERE execution_id = ?", (execution_id,)
                ).fetchone()
                if not row:
                    return None
                return ActionExecutionRecord(
                    execution_id=row["execution_id"],
                    action_id=row["action_id"],
                    action_version=row["action_version"],
                    actor_id=row["actor_id"],
                    session_id_hash=row["session_id_hash"],
                    device_id=row["device_id"],
                    idempotency_key_hash=row["idempotency_key_hash"],
                    arguments_digest=row["arguments_digest"],
                    state_fingerprint=row["state_fingerprint"],
                    started_at=row["started_at"],
                    finished_at=row["finished_at"],
                    status=ExecutionState(row["status"]),
                    result_category=row["result_category"],
                    error_code=row["error_code"],
                    postcondition_verified=bool(row["postcondition_verified"]),
                    summary=row["summary"],
                    details_json=row["details_json"],
                    dispatch_phase=row["dispatch_phase"] if "dispatch_phase" in row.keys() else "reserved_not_dispatched",
                )
        except (sqlite3.OperationalError, FileNotFoundError):
            return None

    def get_execution_by_idempotency_key(
        self, action_id: str, idempotency_key_hash: str
    ) -> Optional[ActionExecutionRecord]:
        """Retrieve an execution record by action ID and idempotency key hash."""
        if self.read_only and not self.db_path.is_file():
            return None
        try:
            with self._get_connection() as conn:
                row = conn.execute(
                    "SELECT * FROM action_executions WHERE action_id = ? AND idempotency_key_hash = ?",
                    (action_id, idempotency_key_hash),
                ).fetchone()
                if not row:
                    return None
                return ActionExecutionRecord(
                    execution_id=row["execution_id"],
                    action_id=row["action_id"],
                    action_version=row["action_version"],
                    actor_id=row["actor_id"],
                    session_id_hash=row["session_id_hash"],
                    device_id=row["device_id"],
                    idempotency_key_hash=row["idempotency_key_hash"],
                    arguments_digest=row["arguments_digest"],
                    state_fingerprint=row["state_fingerprint"],
                    started_at=row["started_at"],
                    finished_at=row["finished_at"],
                    status=ExecutionState(row["status"]),
                    result_category=row["result_category"],
                    error_code=row["error_code"],
                    postcondition_verified=bool(row["postcondition_verified"]),
                    summary=row["summary"],
                    details_json=row["details_json"],
                    dispatch_phase=row["dispatch_phase"] if "dispatch_phase" in row.keys() else "reserved_not_dispatched",
                )
        except (sqlite3.OperationalError, FileNotFoundError):
            return None

    def list_executions(self, action_id: Optional[str] = None, limit: int = 50) -> List[ActionExecutionRecord]:
        """List recent execution journal records."""
        eff_limit = min(max(1, limit), 100)
        if self.read_only and not self.db_path.is_file():
            return []
        try:
            with self._get_connection() as conn:
                if action_id:
                    rows = conn.execute(
                        "SELECT * FROM action_executions WHERE action_id = ? ORDER BY started_at DESC LIMIT ?",
                        (action_id, eff_limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM action_executions ORDER BY started_at DESC LIMIT ?",
                        (eff_limit,),
                    ).fetchall()

                return [
                    ActionExecutionRecord(
                        execution_id=r["execution_id"],
                        action_id=r["action_id"],
                        action_version=r["action_version"],
                        actor_id=r["actor_id"],
                        session_id_hash=r["session_id_hash"],
                        device_id=r["device_id"],
                        idempotency_key_hash=r["idempotency_key_hash"],
                        arguments_digest=r["arguments_digest"],
                        state_fingerprint=r["state_fingerprint"],
                        started_at=r["started_at"],
                        finished_at=r["finished_at"],
                        status=ExecutionState(r["status"]),
                        result_category=r["result_category"],
                        error_code=r["error_code"],
                        postcondition_verified=bool(r["postcondition_verified"]),
                        summary=r["summary"],
                        details_json=r["details_json"],
                        dispatch_phase=r["dispatch_phase"] if "dispatch_phase" in r.keys() else "reserved_not_dispatched",
                    )
                    for r in rows
                ]
        except (sqlite3.OperationalError, FileNotFoundError):
            return []

    # ── Resource Barriers & Durable Safety (Amendment 1) ──────────────────────

    def set_resource_barrier(
        self,
        resource_key: str,
        execution_id: str,
        reason: str,
        barrier_status: str = "locked_unresolved",
    ) -> None:
        """Set a durable safety barrier on a resource key.

        Subsequent mutations on this resource will be blocked fail-closed
        until authoritatively cleared via clear_resource_barrier.
        """
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        cleaned_reason = redact_sensitive_data(reason)[:512]
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                conn.execute(
                    """
                    INSERT INTO action_resource_barriers (
                        resource_key, execution_id, barrier_status, reason, created_at, cleared_at, cleared_by, evidence
                    ) VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL)
                    ON CONFLICT(resource_key) DO UPDATE SET
                        execution_id = excluded.execution_id,
                        barrier_status = excluded.barrier_status,
                        reason = excluded.reason,
                        created_at = excluded.created_at,
                        cleared_at = NULL,
                        cleared_by = NULL,
                        evidence = NULL
                    """,
                    (resource_key, execution_id, barrier_status, cleaned_reason, now_iso),
                )
                conn.execute("COMMIT;")
            except Exception:
                conn.execute("ROLLBACK;")
                raise

    def clear_resource_barrier(
        self,
        resource_key: str,
        cleared_by: str,
        evidence: str,
        execution_id: Optional[str] = None,
    ) -> bool:
        """Clear an active barrier with authoritative source evidence.

        Optionally binds atomically to execution_id to prevent clearing a newly established barrier.
        Returns True if an active barrier was found and cleared, False otherwise.
        """
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        cleaned_evidence = redact_sensitive_data(evidence)[:2048]
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                query = "SELECT resource_key FROM action_resource_barriers WHERE resource_key = ? AND cleared_at IS NULL"
                params: List[Any] = [resource_key]
                if execution_id:
                    query += " AND execution_id = ?"
                    params.append(execution_id)

                row = conn.execute(query, tuple(params)).fetchone()
                if not row:
                    conn.execute("COMMIT;")
                    return False

                update_query = """
                    UPDATE action_resource_barriers
                    SET cleared_at = ?, cleared_by = ?, evidence = ?
                    WHERE resource_key = ? AND cleared_at IS NULL
                """
                update_params: List[Any] = [now_iso, cleared_by, cleaned_evidence, resource_key]
                if execution_id:
                    update_query += " AND execution_id = ?"
                    update_params.append(execution_id)

                conn.execute(update_query, tuple(update_params))
                conn.execute("COMMIT;")
                return True
            except Exception:
                conn.execute("ROLLBACK;")
                raise

    def get_active_barrier(self, resource_key: str) -> Optional[Dict[str, Any]]:
        """Retrieve active barrier for a resource key if present."""
        if self.read_only and not self.db_path.is_file():
            return None
        try:
            with self._get_connection() as conn:
                row = conn.execute(
                    "SELECT * FROM action_resource_barriers WHERE resource_key = ? AND cleared_at IS NULL",
                    (resource_key,),
                ).fetchone()
                if not row:
                    return None
                return {
                    "resource_key": row["resource_key"],
                    "execution_id": row["execution_id"],
                    "barrier_status": row["barrier_status"],
                    "reason": row["reason"],
                    "created_at": row["created_at"],
                    "cleared_at": row["cleared_at"],
                    "cleared_by": row["cleared_by"],
                    "evidence": row["evidence"],
                }
        except (sqlite3.OperationalError, FileNotFoundError):
            return None

    def list_active_barriers(self) -> List[Dict[str, Any]]:
        """List all active resource barriers."""
        if self.read_only and not self.db_path.is_file():
            return []
        try:
            with self._get_connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM action_resource_barriers WHERE cleared_at IS NULL ORDER BY created_at DESC"
                ).fetchall()
                return [
                    {
                        "resource_key": r["resource_key"],
                        "execution_id": r["execution_id"],
                        "barrier_status": r["barrier_status"],
                        "reason": r["reason"],
                        "created_at": r["created_at"],
                        "cleared_at": r["cleared_at"],
                        "cleared_by": r["cleared_by"],
                        "evidence": r["evidence"],
                    }
                    for r in rows
                ]
        except (sqlite3.OperationalError, FileNotFoundError):
            return []

    # ── Concurrency & Resource Locks ──────────────────────────────────────────

    def acquire_resource_lock_detailed(
        self,
        resource_key: str,
        execution_id: str,
        ttl_seconds: float = 30.0,
    ) -> Tuple[bool, Optional[str]]:
        """Atomically acquire an exclusive resource lease across processes.

        Stage D & Mandatory Amendment 1 Invariants:
        - Reconciles any dangling/terminated executions for this resource before lease evaluation.
        - Returns (True, None) if acquired.
        - Returns (False, 'barrier_active') if protected by an active unresolved barrier.
        - Returns (False, 'lock_contention') if held by another active execution lease.
        """
        if self.read_only:
            raise PermissionError("ActionStorage is in read-only mode")

        # Reconcile dangling executions targeting this resource before lock evaluation
        self.reconcile_dangling_executions(
            concurrency_key=resource_key,
            exclude_execution_id=execution_id,
            only_expired=True,
        )

        now = datetime.now(timezone.utc)
        now_iso = now.isoformat().replace("+00:00", "Z")
        expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat().replace("+00:00", "Z")

        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                # 1. Check if resource is guarded by an active barrier
                barrier = conn.execute(
                    "SELECT 1 FROM action_resource_barriers WHERE resource_key = ? AND cleared_at IS NULL",
                    (resource_key,),
                ).fetchone()
                if barrier:
                    conn.execute("COMMIT;")
                    return False, "barrier_active"

                # 2. Check transient resource lock
                row = conn.execute(
                    "SELECT * FROM action_resource_locks WHERE resource_key = ?",
                    (resource_key,),
                ).fetchone()

                if row:
                    if row["expires_at"] > now_iso and row["holder_execution_id"] != execution_id:
                        conn.execute("COMMIT;")
                        return False, "lock_contention"

                    conn.execute(
                        """
                        UPDATE action_resource_locks
                        SET holder_execution_id = ?, acquired_at = ?, expires_at = ?
                        WHERE resource_key = ?
                        """,
                        (execution_id, now_iso, expires_at, resource_key),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO action_resource_locks (
                            resource_key, holder_execution_id, acquired_at, expires_at
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (resource_key, execution_id, now_iso, expires_at),
                    )

                conn.execute("COMMIT;")
                return True, None
            except Exception:
                conn.execute("ROLLBACK;")
                raise

    def acquire_resource_lock(
        self, resource_key: str, execution_id: str, ttl_seconds: float = 30.0
    ) -> bool:
        """Atomically acquire an exclusive resource lease across processes.

        Returns True if the lock was acquired, False if currently held by another execution
        or blocked by an active barrier.
        """
        acquired, _ = self.acquire_resource_lock_detailed(resource_key, execution_id, ttl_seconds=ttl_seconds)
        return acquired

    def renew_resource_lock(
        self, resource_key: str, execution_id: str, ttl_seconds: float = 30.0
    ) -> bool:
        """Atomically renew an existing lock lease held by execution_id.

        NOTE: Lease renewal maintains local process ownership against transient local TTL expiry.
        It does NOT provide distributed fencing or source-side exactly-once semantics.
        """
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat().replace("+00:00", "Z")
        expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat().replace("+00:00", "Z")

        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                # Barrier blocks renewal
                barrier = conn.execute(
                    "SELECT 1 FROM action_resource_barriers WHERE resource_key = ? AND cleared_at IS NULL",
                    (resource_key,),
                ).fetchone()
                if barrier:
                    conn.execute("COMMIT;")
                    return False

                row = conn.execute(
                    "SELECT * FROM action_resource_locks WHERE resource_key = ? AND holder_execution_id = ?",
                    (resource_key, execution_id),
                ).fetchone()
                if not row:
                    conn.execute("COMMIT;")
                    return False

                conn.execute(
                    "UPDATE action_resource_locks SET expires_at = ? WHERE resource_key = ? AND holder_execution_id = ?",
                    (expires_at, resource_key, execution_id),
                )
                conn.execute("COMMIT;")
                return True
            except Exception:
                conn.execute("ROLLBACK;")
                raise

    def release_resource_lock(self, resource_key: str, execution_id: str) -> None:
        """Release a resource lock if held by the given execution ID."""
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                conn.execute(
                    "DELETE FROM action_resource_locks WHERE resource_key = ? AND holder_execution_id = ?",
                    (resource_key, execution_id),
                )
                conn.execute("COMMIT;")
            except Exception:
                conn.execute("ROLLBACK;")
                raise

    def get_resource_lock(self, resource_key: str) -> Optional[Dict[str, Any]]:
        """Retrieve current lock status for a resource key."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM action_resource_locks WHERE resource_key = ?",
                (resource_key,),
            ).fetchone()
            if not row:
                return None
            return {
                "resource_key": row["resource_key"],
                "holder_execution_id": row["holder_execution_id"],
                "acquired_at": row["acquired_at"],
                "expires_at": row["expires_at"],
            }

    # ── Action Audit Ledger ───────────────────────────────────────────────────

    def record_action_audit(self, audit: Optional[Dict[str, Any]] = None, **kwargs) -> None:
        """Record an immutable action execution audit event in the database."""
        event = dict(audit or {})
        event.update(kwargs)
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        cleaned_details = redact_sensitive_data(event.get("details", {}))
        details_str = json.dumps(cleaned_details) if isinstance(cleaned_details, (dict, list)) else str(cleaned_details or "")

        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                conn.execute(
                    """
                    INSERT INTO audit_events (
                        timestamp, actor_id, device_id, action, decision, ip_address, details
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.get("timestamp", now_iso),
                        event.get("actor_id", "unauthenticated"),
                        event.get("device_id"),
                        f"action:{event.get('action_id', 'unknown')}",
                        event.get("decision", "unknown"),
                        event.get("ip_address", ""),
                        details_str[:8192],
                    ),
                )
                conn.execute("COMMIT;")
            except Exception:
                conn.execute("ROLLBACK;")
                raise

    def list_action_audits(self, action_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """List recorded audit events, optionally filtered by action_id."""
        if self.read_only and not self.db_path.is_file():
            return []
        try:
            with self._get_connection() as conn:
                if action_id:
                    act_tag = f"action:{action_id}" if not action_id.startswith("action:") else action_id
                    rows = conn.execute(
                        "SELECT * FROM audit_events WHERE action = ? ORDER BY id DESC LIMIT ?",
                        (act_tag, limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM audit_events ORDER BY id DESC LIMIT ?",
                        (limit,),
                    ).fetchall()

                results = []
                for r in rows:
                    raw_details = r["details"]
                    parsed = raw_details
                    if raw_details:
                        try:
                            parsed = json.loads(raw_details)
                        except Exception:
                            parsed = raw_details
                    results.append({
                        "id": r["id"],
                        "timestamp": r["timestamp"],
                        "actor_id": r["actor_id"],
                        "device_id": r["device_id"],
                        "action": r["action"],
                        "decision": r["decision"],
                        "ip_address": r["ip_address"],
                        "details": parsed,
                    })
                return results
        except (sqlite3.OperationalError, FileNotFoundError):
            return []
