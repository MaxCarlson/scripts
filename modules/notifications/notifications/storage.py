"""SQLite storage engine with WAL mode, migrations, and transactional durability."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterator, Optional

from notifications.exceptions import (
    DatabaseBusyError,
    DatabaseCorruptError,
    DatabaseFullError,
    PayloadConflictError,
    StorageError,
)
from notifications.models import (
    DeliveryAttempt,
    EventEnvelopeV1,
    Incident,
    Occurrence,
    OutboxItem,
    PublishResult,
    Transition,
)

SCHEMA_VERSION_1_SQL = """
-- Version 1 Schema Migration

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    source TEXT NOT NULL,
    kind TEXT NOT NULL,
    incident_key TEXT NOT NULL,
    severity TEXT NOT NULL,
    lifecycle TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    received_at TEXT NOT NULL,
    summary TEXT NOT NULL,
    correlation_id TEXT,
    resource TEXT,
    details_ref TEXT,
    labels_json TEXT NOT NULL DEFAULT '{}',
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS incidents (
    incident_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    incident_key TEXT NOT NULL,
    active_occurrence_id TEXT,
    status TEXT NOT NULL,
    severity TEXT NOT NULL,
    summary TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    acknowledged_at TEXT,
    resolved_at TEXT,
    last_notified_at TEXT,
    occurrence_count INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS occurrences (
    occurrence_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL REFERENCES incidents(incident_id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    severity TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    resolution_evidence TEXT
);

CREATE TABLE IF NOT EXISTS transitions (
    transition_id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id TEXT NOT NULL REFERENCES incidents(incident_id) ON DELETE CASCADE,
    occurrence_id TEXT NOT NULL REFERENCES occurrences(occurrence_id) ON DELETE CASCADE,
    event_id TEXT NOT NULL REFERENCES events(event_id),
    from_status TEXT,
    to_status TEXT NOT NULL,
    transition_name TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS outbox (
    outbox_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    incident_id TEXT NOT NULL REFERENCES incidents(incident_id) ON DELETE CASCADE,
    provider_id TEXT NOT NULL,
    status TEXT NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 5,
    next_retry_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS delivery_attempts (
    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    outbox_id INTEGER NOT NULL REFERENCES outbox(outbox_id) ON DELETE CASCADE,
    attempted_at TEXT NOT NULL,
    status TEXT NOT NULL,
    provider_message_id TEXT,
    duration_ms INTEGER,
    error_category TEXT,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS acknowledgements (
    ack_id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id TEXT NOT NULL REFERENCES incidents(incident_id) ON DELETE CASCADE,
    occurrence_id TEXT NOT NULL REFERENCES occurrences(occurrence_id) ON DELETE CASCADE,
    acknowledged_at TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_incident_key ON events(source, incident_key);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status);
CREATE INDEX IF NOT EXISTS idx_outbox_queue ON outbox(status, next_retry_at);
CREATE INDEX IF NOT EXISTS idx_transitions_incident ON transitions(incident_id, timestamp);
"""

SCHEMA_VERSION_2_SQL = """
-- Version 2 Schema Migration: Resource Coordinator Monitoring Observations

CREATE TABLE IF NOT EXISTS rc_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observed_at TEXT NOT NULL,
    status TEXT NOT NULL,
    contract_version TEXT NOT NULL,
    has_recovery_contract INTEGER NOT NULL DEFAULT 0,
    recovery_required INTEGER,
    inhibition_active INTEGER,
    inhibition_reason TEXT,
    journal_status TEXT,
    miner_state TEXT,
    error_message TEXT,
    details_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_rc_observations_time ON rc_observations(observed_at);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _map_sqlite_error(exc: Exception) -> Exception:
    msg = str(exc).lower()
    if "database is locked" in msg or "busy" in msg:
        return DatabaseBusyError(str(exc))
    if "malformed" in msg or "corrupt" in msg or "file is not a database" in msg or "disk i/o error" in msg:
        return DatabaseCorruptError(str(exc))
    if "full" in msg:
        return DatabaseFullError(str(exc))
    return StorageError(str(exc))


class StorageEngine:
    """ACID-compliant SQLite storage engine for notification events and outbox."""

    def __init__(self, db_path: Path | str, busy_timeout_ms: int = 5000) -> None:
        self.db_path = Path(db_path).resolve()
        self.busy_timeout_ms = busy_timeout_ms
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()

    def get_connection(self) -> sqlite3.Connection:
        """Get or initialize a thread-local SQLite connection."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            try:
                conn = sqlite3.connect(
                    str(self.db_path),
                    timeout=self.busy_timeout_ms / 1000.0,
                    isolation_level=None,  # Autocommit mode; transactions managed via BEGIN/COMMIT
                )
                conn.row_factory = sqlite3.Row
                conn.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms};")
                conn.execute("PRAGMA foreign_keys = ON;")
                conn.execute("PRAGMA journal_mode = WAL;")
                conn.execute("PRAGMA synchronous = NORMAL;")
                self._local.conn = conn
            except sqlite3.Error as exc:
                raise _map_sqlite_error(exc) from exc
        return conn

    def close(self) -> None:
        """Close the thread-local SQLite connection if open."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            self._local.conn = None

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Produce an open SQLite connection configured with WAL and busy timeout."""
        yield self.get_connection()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Produce a connection inside an explicit immediate transaction."""
        conn = self.get_connection()
        conn.execute("BEGIN IMMEDIATE;")
        try:
            yield conn
            conn.execute("COMMIT;")
        except Exception:
            conn.execute("ROLLBACK;")
            raise

    def migrate(self) -> int:
        """Apply all pending migrations in order."""
        try:
            with self.connect() as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);"
                )
                row = conn.execute("SELECT MAX(version) FROM schema_migrations;").fetchone()
                current_version = row[0] or 0

                if current_version < 1:
                    conn.executescript(SCHEMA_VERSION_1_SQL)
                    conn.execute(
                        "INSERT OR REPLACE INTO schema_migrations (version, applied_at) VALUES (?, ?);",
                        (1, _now_iso()),
                    )
                    current_version = 1

                if current_version < 2:
                    conn.executescript(SCHEMA_VERSION_2_SQL)
                    conn.execute(
                        "INSERT OR REPLACE INTO schema_migrations (version, applied_at) VALUES (?, ?);",
                        (2, _now_iso()),
                    )
                    current_version = 2

                return current_version
        except sqlite3.Error as exc:
            raise _map_sqlite_error(exc) from exc

    def get_schema_version(self) -> int:
        """Return the current database schema migration version."""
        try:
            with self.connect() as conn:
                row = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations';"
                ).fetchone()
                if not row:
                    return 0
                ver_row = conn.execute("SELECT MAX(version) FROM schema_migrations;").fetchone()
                return ver_row[0] or 0
        except sqlite3.Error as exc:
            raise _map_sqlite_error(exc) from exc

    def record_event(
        self, event: EventEnvelopeV1, conn: Optional[sqlite3.Connection] = None
    ) -> tuple[bool, EventEnvelopeV1]:
        """
        Record a normalized event.
        Returns (is_new, event). If already exists with same payload, returns (False, event).
        Raises PayloadConflictError if event_id already exists with differing payload.
        """
        now = _now_iso()

        def _exec(c: sqlite3.Connection) -> tuple[bool, EventEnvelopeV1]:
            existing = c.execute(
                "SELECT payload_sha256, payload_json FROM events WHERE event_id = ?;",
                (event.event_id,),
            ).fetchone()
            if existing:
                if existing["payload_sha256"] == event.payload_sha256:
                    return False, event
                raise PayloadConflictError(
                    f"Event ID '{event.event_id}' already exists with different payload content"
                )

            c.execute(
                """
                INSERT INTO events (
                    event_id, schema_version, source, kind, incident_key,
                    severity, lifecycle, occurred_at, received_at, summary,
                    correlation_id, resource, details_ref, labels_json,
                    payload_json, payload_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    event.event_id,
                    event.schema_version,
                    event.source,
                    event.kind,
                    event.incident_key,
                    event.severity,
                    event.lifecycle,
                    event.occurred_at,
                    now,
                    event.summary,
                    event.correlation_id,
                    event.resource,
                    event.details_ref,
                    json.dumps(event.labels, sort_keys=True),
                    event.to_canonical_json(),
                    event.payload_sha256,
                ),
            )
            return True, event

        try:
            if conn is not None:
                return _exec(conn)
            with self.connect() as c:
                c.execute("BEGIN IMMEDIATE;")
                try:
                    res = _exec(c)
                    c.execute("COMMIT;")
                    return res
                except Exception:
                    c.execute("ROLLBACK;")
                    raise
        except sqlite3.Error as exc:
            raise _map_sqlite_error(exc) from exc

    def get_event(self, event_id: str, conn: Optional[sqlite3.Connection] = None) -> Optional[EventEnvelopeV1]:
        """Retrieve an event by ID."""
        def _exec(c: sqlite3.Connection) -> Optional[EventEnvelopeV1]:
            row = c.execute("SELECT payload_json FROM events WHERE event_id = ?;", (event_id,)).fetchone()
            if not row:
                return None
            data = json.loads(row["payload_json"])
            return EventEnvelopeV1.from_dict(data)

        try:
            if conn is not None:
                return _exec(conn)
            with self.connect() as c:
                return _exec(c)
        except sqlite3.Error as exc:
            raise _map_sqlite_error(exc) from exc

    def save_incident(self, incident: Incident, conn: Optional[sqlite3.Connection] = None) -> None:
        """Upsert an incident record."""
        def _exec(c: sqlite3.Connection) -> None:
            c.execute(
                """
                INSERT INTO incidents (
                    incident_id, source, incident_key, active_occurrence_id,
                    status, severity, summary, first_seen, last_seen,
                    acknowledged_at, resolved_at, last_notified_at, occurrence_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(incident_id) DO UPDATE SET
                    active_occurrence_id = excluded.active_occurrence_id,
                    status = excluded.status,
                    severity = excluded.severity,
                    summary = excluded.summary,
                    last_seen = excluded.last_seen,
                    acknowledged_at = excluded.acknowledged_at,
                    resolved_at = excluded.resolved_at,
                    last_notified_at = excluded.last_notified_at,
                    occurrence_count = excluded.occurrence_count;
                """,
                (
                    incident.incident_id,
                    incident.source,
                    incident.incident_key,
                    incident.active_occurrence_id,
                    incident.status,
                    incident.severity,
                    incident.summary,
                    incident.first_seen,
                    incident.last_seen,
                    incident.acknowledged_at,
                    incident.resolved_at,
                    incident.last_notified_at,
                    incident.occurrence_count,
                ),
            )

        try:
            if conn is not None:
                _exec(conn)
                return
            with self.connect() as c:
                c.execute("BEGIN IMMEDIATE;")
                try:
                    _exec(c)
                    c.execute("COMMIT;")
                except Exception:
                    c.execute("ROLLBACK;")
                    raise
        except sqlite3.Error as exc:
            raise _map_sqlite_error(exc) from exc

    def get_incident(self, incident_id: str, conn: Optional[sqlite3.Connection] = None) -> Optional[Incident]:
        """Fetch an incident by ID."""
        def _exec(c: sqlite3.Connection) -> Optional[Incident]:
            row = c.execute("SELECT * FROM incidents WHERE incident_id = ?;", (incident_id,)).fetchone()
            if not row:
                return None
            return Incident(
                incident_id=row["incident_id"],
                source=row["source"],
                incident_key=row["incident_key"],
                active_occurrence_id=row["active_occurrence_id"],
                status=row["status"],
                severity=row["severity"],
                summary=row["summary"],
                first_seen=row["first_seen"],
                last_seen=row["last_seen"],
                acknowledged_at=row["acknowledged_at"],
                resolved_at=row["resolved_at"],
                last_notified_at=row["last_notified_at"],
                occurrence_count=row["occurrence_count"],
            )

        try:
            if conn is not None:
                return _exec(conn)
            with self.connect() as c:
                return _exec(c)
        except sqlite3.Error as exc:
            raise _map_sqlite_error(exc) from exc

    def list_incidents(
        self, status: Optional[str] = None, limit: int = 50, conn: Optional[sqlite3.Connection] = None
    ) -> list[Incident]:
        """List incidents with optional status filter."""
        def _exec(c: sqlite3.Connection) -> list[Incident]:
            if status:
                rows = c.execute(
                    "SELECT * FROM incidents WHERE status = ? ORDER BY last_seen DESC LIMIT ?;",
                    (status, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM incidents ORDER BY last_seen DESC LIMIT ?;",
                    (limit,),
                ).fetchall()

            return [
                Incident(
                    incident_id=r["incident_id"],
                    source=r["source"],
                    incident_key=r["incident_key"],
                    active_occurrence_id=r["active_occurrence_id"],
                    status=r["status"],
                    severity=r["severity"],
                    summary=r["summary"],
                    first_seen=r["first_seen"],
                    last_seen=r["last_seen"],
                    acknowledged_at=r["acknowledged_at"],
                    resolved_at=r["resolved_at"],
                    last_notified_at=r["last_notified_at"],
                    occurrence_count=r["occurrence_count"],
                )
                for r in rows
            ]

        try:
            if conn is not None:
                return _exec(conn)
            with self.connect() as c:
                return _exec(c)
        except sqlite3.Error as exc:
            raise _map_sqlite_error(exc) from exc

    def save_occurrence(self, occurrence: Occurrence, conn: Optional[sqlite3.Connection] = None) -> None:
        """Upsert an occurrence record."""
        def _exec(c: sqlite3.Connection) -> None:
            c.execute(
                """
                INSERT INTO occurrences (
                    occurrence_id, incident_id, status, severity,
                    opened_at, closed_at, resolution_evidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(occurrence_id) DO UPDATE SET
                    status = excluded.status,
                    severity = excluded.severity,
                    closed_at = excluded.closed_at,
                    resolution_evidence = excluded.resolution_evidence;
                """,
                (
                    occurrence.occurrence_id,
                    occurrence.incident_id,
                    occurrence.status,
                    occurrence.severity,
                    occurrence.opened_at,
                    occurrence.closed_at,
                    occurrence.resolution_evidence,
                ),
            )

        try:
            if conn is not None:
                _exec(conn)
                return
            with self.connect() as c:
                c.execute("BEGIN IMMEDIATE;")
                try:
                    _exec(c)
                    c.execute("COMMIT;")
                except Exception:
                    c.execute("ROLLBACK;")
                    raise
        except sqlite3.Error as exc:
            raise _map_sqlite_error(exc) from exc

    def get_occurrence(self, occurrence_id: str, conn: Optional[sqlite3.Connection] = None) -> Optional[Occurrence]:
        """Fetch an occurrence by ID."""
        def _exec(c: sqlite3.Connection) -> Optional[Occurrence]:
            row = c.execute("SELECT * FROM occurrences WHERE occurrence_id = ?;", (occurrence_id,)).fetchone()
            if not row:
                return None
            return Occurrence(
                occurrence_id=row["occurrence_id"],
                incident_id=row["incident_id"],
                status=row["status"],
                severity=row["severity"],
                opened_at=row["opened_at"],
                closed_at=row["closed_at"],
                resolution_evidence=row["resolution_evidence"],
            )

        try:
            if conn is not None:
                return _exec(conn)
            with self.connect() as c:
                return _exec(c)
        except sqlite3.Error as exc:
            raise _map_sqlite_error(exc) from exc

    def record_transition(self, transition: Transition, conn: Optional[sqlite3.Connection] = None) -> int:
        """Record an append-only incident state transition."""
        def _exec(c: sqlite3.Connection) -> int:
            cursor = c.execute(
                """
                INSERT INTO transitions (
                    incident_id, occurrence_id, event_id, from_status,
                    to_status, transition_name, timestamp, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    transition.incident_id,
                    transition.occurrence_id,
                    transition.event_id,
                    transition.from_status,
                    transition.to_status,
                    transition.transition_name,
                    transition.timestamp,
                    json.dumps(transition.details, sort_keys=True),
                ),
            )
            return cursor.lastrowid or 0

        try:
            if conn is not None:
                return _exec(conn)
            with self.connect() as c:
                c.execute("BEGIN IMMEDIATE;")
                try:
                    tid = _exec(c)
                    c.execute("COMMIT;")
                    return tid
                except Exception:
                    c.execute("ROLLBACK;")
                    raise
        except sqlite3.Error as exc:
            raise _map_sqlite_error(exc) from exc

    def list_transitions(self, incident_id: str, conn: Optional[sqlite3.Connection] = None) -> list[Transition]:
        """List state transitions for an incident."""
        def _exec(c: sqlite3.Connection) -> list[Transition]:
            rows = c.execute(
                "SELECT * FROM transitions WHERE incident_id = ? ORDER BY transition_id ASC;",
                (incident_id,),
            ).fetchall()
            return [
                Transition(
                    transition_id=r["transition_id"],
                    incident_id=r["incident_id"],
                    occurrence_id=r["occurrence_id"],
                    event_id=r["event_id"],
                    from_status=r["from_status"],
                    to_status=r["to_status"],
                    transition_name=r["transition_name"],
                    timestamp=r["timestamp"],
                    details=json.loads(r["details_json"]),
                )
                for r in rows
            ]

        try:
            if conn is not None:
                return _exec(conn)
            with self.connect() as c:
                return _exec(c)
        except sqlite3.Error as exc:
            raise _map_sqlite_error(exc) from exc

    def enqueue_outbox(
        self,
        event_id: str,
        incident_id: str,
        provider_id: str,
        max_retries: int = 5,
        conn: Optional[sqlite3.Connection] = None,
    ) -> int:
        """Queue a notification for external provider delivery."""
        now = _now_iso()

        def _exec(c: sqlite3.Connection) -> int:
            cursor = c.execute(
                """
                INSERT INTO outbox (
                    event_id, incident_id, provider_id, status,
                    retry_count, max_retries, next_retry_at, created_at, updated_at
                ) VALUES (?, ?, ?, 'pending', 0, ?, ?, ?, ?);
                """,
                (event_id, incident_id, provider_id, max_retries, now, now, now),
            )
            return cursor.lastrowid or 0

        try:
            if conn is not None:
                return _exec(conn)
            with self.connect() as c:
                c.execute("BEGIN IMMEDIATE;")
                try:
                    outbox_id = _exec(c)
                    c.execute("COMMIT;")
                    return outbox_id
                except Exception:
                    c.execute("ROLLBACK;")
                    raise
        except sqlite3.Error as exc:
            raise _map_sqlite_error(exc) from exc

    def get_outbox_item(self, outbox_id: int, conn: Optional[sqlite3.Connection] = None) -> Optional[OutboxItem]:
        """Retrieve an outbox item by ID."""
        def _exec(c: sqlite3.Connection) -> Optional[OutboxItem]:
            row = c.execute("SELECT * FROM outbox WHERE outbox_id = ?;", (outbox_id,)).fetchone()
            if not row:
                return None
            return OutboxItem(
                outbox_id=row["outbox_id"],
                event_id=row["event_id"],
                incident_id=row["incident_id"],
                provider_id=row["provider_id"],
                status=row["status"],
                retry_count=row["retry_count"],
                max_retries=row["max_retries"],
                next_retry_at=row["next_retry_at"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                error_message=row["error_message"],
            )

        try:
            if conn is not None:
                return _exec(conn)
            with self.connect() as c:
                return _exec(c)
        except sqlite3.Error as exc:
            raise _map_sqlite_error(exc) from exc

    def list_pending_outbox(
        self, limit: int = 50, now_iso: Optional[str] = None, conn: Optional[sqlite3.Connection] = None
    ) -> list[OutboxItem]:
        """Retrieve pending or retryable outbox items ready for dispatch."""
        now = now_iso or _now_iso()

        def _exec(c: sqlite3.Connection) -> list[OutboxItem]:
            rows = c.execute(
                """
                SELECT * FROM outbox
                WHERE status IN ('pending', 'retryable_error')
                  AND next_retry_at <= ?
                  AND retry_count < max_retries
                ORDER BY outbox_id ASC
                LIMIT ?;
                """,
                (now, limit),
            ).fetchall()
            return [
                OutboxItem(
                    outbox_id=r["outbox_id"],
                    event_id=r["event_id"],
                    incident_id=r["incident_id"],
                    provider_id=r["provider_id"],
                    status=r["status"],
                    retry_count=r["retry_count"],
                    max_retries=r["max_retries"],
                    next_retry_at=r["next_retry_at"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                    error_message=r["error_message"],
                )
                for r in rows
            ]

        try:
            if conn is not None:
                return _exec(conn)
            with self.connect() as c:
                return _exec(c)
        except sqlite3.Error as exc:
            raise _map_sqlite_error(exc) from exc

    def claim_outbox_item(self, outbox_id: int, conn: Optional[sqlite3.Connection] = None) -> bool:
        """Atomically transition an outbox item from pending/retryable to attempting."""
        now = _now_iso()

        def _exec(c: sqlite3.Connection) -> bool:
            cursor = c.execute(
                """
                UPDATE outbox
                SET status = 'attempting', updated_at = ?
                WHERE outbox_id = ? AND status IN ('pending', 'retryable_error');
                """,
                (now, outbox_id),
            )
            return cursor.rowcount > 0

        try:
            if conn is not None:
                return _exec(conn)
            with self.connect() as c:
                c.execute("BEGIN IMMEDIATE;")
                try:
                    success = _exec(c)
                    c.execute("COMMIT;")
                    return success
                except Exception:
                    c.execute("ROLLBACK;")
                    raise
        except sqlite3.Error as exc:
            raise _map_sqlite_error(exc) from exc

    def record_delivery_attempt(
        self,
        outbox_id: int,
        status: str,
        provider_message_id: Optional[str] = None,
        duration_ms: Optional[int] = None,
        error_category: Optional[str] = None,
        error_message: Optional[str] = None,
        retry_after_seconds: Optional[float] = None,
        conn: Optional[sqlite3.Connection] = None,
    ) -> None:
        """Record attempt and update outbox status within a single transaction."""
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat().replace("+00:00", "Z")

        def _exec(c: sqlite3.Connection) -> None:
            c.execute(
                """
                INSERT INTO delivery_attempts (
                    outbox_id, attempted_at, status, provider_message_id,
                    duration_ms, error_category, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    outbox_id,
                    now,
                    status,
                    provider_message_id,
                    duration_ms,
                    error_category,
                    error_message,
                ),
            )

            item = c.execute("SELECT retry_count, max_retries FROM outbox WHERE outbox_id = ?;", (outbox_id,)).fetchone()
            if not item:
                return

            new_retry_count = item["retry_count"] + (1 if status != "provider_accepted" else 0)
            new_status = status
            if status == "retryable_error" and new_retry_count >= item["max_retries"]:
                new_status = "terminal_error"

            if retry_after_seconds and retry_after_seconds > 0:
                next_retry = (now_dt + timedelta(seconds=retry_after_seconds)).isoformat().replace("+00:00", "Z")
            else:
                delay = min(300.0, 2.0 * (2.0 ** new_retry_count))
                next_retry = (now_dt + timedelta(seconds=delay)).isoformat().replace("+00:00", "Z")

            c.execute(
                """
                UPDATE outbox
                SET status = ?, retry_count = ?, next_retry_at = ?,
                    updated_at = ?, error_message = ?
                WHERE outbox_id = ?;
                """,
                (new_status, new_retry_count, next_retry, now, error_message, outbox_id),
            )

        try:
            if conn is not None:
                _exec(conn)
                return
            with self.connect() as c:
                c.execute("BEGIN IMMEDIATE;")
                try:
                    _exec(c)
                    c.execute("COMMIT;")
                except Exception:
                    c.execute("ROLLBACK;")
                    raise
        except sqlite3.Error as exc:
            raise _map_sqlite_error(exc) from exc

    def list_delivery_attempts(
        self, outbox_id: int, conn: Optional[sqlite3.Connection] = None
    ) -> list[DeliveryAttempt]:
        """List all delivery attempts for an outbox item."""
        def _exec(c: sqlite3.Connection) -> list[DeliveryAttempt]:
            rows = c.execute(
                "SELECT * FROM delivery_attempts WHERE outbox_id = ? ORDER BY attempt_id ASC;",
                (outbox_id,),
            ).fetchall()
            return [
                DeliveryAttempt(
                    attempt_id=r["attempt_id"],
                    outbox_id=r["outbox_id"],
                    attempted_at=r["attempted_at"],
                    status=r["status"],
                    provider_message_id=r["provider_message_id"],
                    duration_ms=r["duration_ms"],
                    error_category=r["error_category"],
                    error_message=r["error_message"],
                )
                for r in rows
            ]

        try:
            if conn is not None:
                return _exec(conn)
            with self.connect() as c:
                return _exec(c)
        except sqlite3.Error as exc:
            raise _map_sqlite_error(exc) from exc

    def reset_stalled_outbox_items(
        self, stalled_seconds: float = 300.0, conn: Optional[sqlite3.Connection] = None
    ) -> int:
        """Recover outbox items stuck in 'attempting' state after worker crash/restart."""
        cutoff_dt = datetime.now(timezone.utc) - timedelta(seconds=stalled_seconds)
        cutoff = cutoff_dt.isoformat().replace("+00:00", "Z")
        now = _now_iso()

        def _exec(c: sqlite3.Connection) -> int:
            cursor = c.execute(
                """
                UPDATE outbox
                SET status = 'pending', updated_at = ?
                WHERE status = 'attempting' AND updated_at <= ?;
                """,
                (now, cutoff),
            )
            return cursor.rowcount

        try:
            if conn is not None:
                return _exec(conn)
            with self.connect() as c:
                c.execute("BEGIN IMMEDIATE;")
                try:
                    count = _exec(c)
                    c.execute("COMMIT;")
                    return count
                except Exception:
                    c.execute("ROLLBACK;")
                    raise
        except sqlite3.Error as exc:
            raise _map_sqlite_error(exc) from exc

    def record_acknowledgement(
        self,
        incident_id: str,
        occurrence_id: str,
        actor: str,
        reason: Optional[str] = None,
        conn: Optional[sqlite3.Connection] = None,
    ) -> int:
        """Record an explicit human operator acknowledgement."""
        now = _now_iso()

        def _exec(c: sqlite3.Connection) -> int:
            cursor = c.execute(
                """
                INSERT INTO acknowledgements (
                    incident_id, occurrence_id, acknowledged_at, actor, reason
                ) VALUES (?, ?, ?, ?, ?);
                """,
                (incident_id, occurrence_id, now, actor, reason),
            )
            return cursor.lastrowid or 0

        try:
            if conn is not None:
                return _exec(conn)
            with self.connect() as c:
                c.execute("BEGIN IMMEDIATE;")
                try:
                    ack_id = _exec(c)
                    c.execute("COMMIT;")
                    return ack_id
                except Exception:
                    c.execute("ROLLBACK;")
                    raise
        except sqlite3.Error as exc:
            raise _map_sqlite_error(exc) from exc

    def save_rc_observation(
        self, observation: dict[str, Any], conn: Optional[sqlite3.Connection] = None
    ) -> int:
        """Persist a normalized Resource Coordinator monitoring observation."""
        now = _now_iso()

        def _exec(c: sqlite3.Connection) -> int:
            cur = c.execute(
                """
                INSERT INTO rc_observations (
                    observed_at, status, contract_version, has_recovery_contract,
                    recovery_required, inhibition_active, inhibition_reason,
                    journal_status, miner_state, error_message, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    observation.get("observed_at", now),
                    observation.get("status", "unknown"),
                    observation.get("contract_version", "unknown"),
                    1 if observation.get("has_recovery_contract") else 0,
                    1 if observation.get("recovery_required") is True else (0 if observation.get("recovery_required") is False else None),
                    1 if observation.get("inhibition_active") is True else (0 if observation.get("inhibition_active") is False else None),
                    observation.get("inhibition_reason"),
                    observation.get("journal_status"),
                    observation.get("miner_state"),
                    observation.get("error_message"),
                    json.dumps(observation.get("details", {})),
                ),
            )
            return cur.lastrowid or 0

        try:
            if conn is not None:
                return _exec(conn)
            with self.connect() as c:
                c.execute("BEGIN IMMEDIATE;")
                try:
                    row_id = _exec(c)
                    c.execute("COMMIT;")
                    return row_id
                except Exception:
                    c.execute("ROLLBACK;")
                    raise
        except sqlite3.Error as exc:
            raise _map_sqlite_error(exc) from exc

    def get_latest_rc_observation(
        self, conn: Optional[sqlite3.Connection] = None
    ) -> Optional[dict[str, Any]]:
        """Fetch the most recent Resource Coordinator monitoring observation."""
        def _exec(c: sqlite3.Connection) -> Optional[dict[str, Any]]:
            row = c.execute(
                "SELECT * FROM rc_observations ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if not row:
                return None
            data = dict(row)
            if data.get("details_json"):
                try:
                    data["details"] = json.loads(data["details_json"])
                except Exception:
                    data["details"] = {}
            data["has_recovery_contract"] = bool(data.get("has_recovery_contract"))
            if data.get("recovery_required") is not None:
                data["recovery_required"] = bool(data["recovery_required"])
            if data.get("inhibition_active") is not None:
                data["inhibition_active"] = bool(data["inhibition_active"])
            return data

        try:
            if conn is not None:
                return _exec(conn)
            with self.connect() as c:
                return _exec(c)
        except sqlite3.Error as exc:
            raise _map_sqlite_error(exc) from exc
