"""Read-only adapter for inspecting notifications broker incidents, events, and outbox."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ReadOnlyNotificationsAdapter:
    """Provides non-mutating query access to the notifications SQLite database."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path.resolve()

    def _get_ro_connection(self) -> sqlite3.Connection:
        """Open SQLite database in strict read-only mode via URI filename."""
        if not self.db_path.is_file():
            raise FileNotFoundError(f"Notifications database not found at {self.db_path}")

        # SQLite URI read-only connection
        uri = f"file:{self.db_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=3.0)
        conn.row_factory = sqlite3.Row
        return conn

    def get_summary(self) -> Dict[str, Any]:
        """Aggregate high-level status of incidents, outbox, and broker health."""
        if not self.db_path.is_file():
            return {
                "ok": True,
                "available": False,
                "status": "unavailable",
                "message": "Notifications database not initialized or broker offline.",
                "active_incidents": 0,
                "acknowledged_incidents": 0,
                "resolved_incidents": 0,
                "total_incidents": 0,
                "pending_outbox": 0,
                "schema_version": None,
                "last_event_time": None,
            }

        try:
            with self._get_ro_connection() as conn:
                # Schema version
                ver_row = conn.execute(
                    "SELECT MAX(version) as version FROM schema_migrations"
                ).fetchone()
                schema_ver = ver_row["version"] if ver_row and ver_row["version"] is not None else 1

                # Incident counts by status
                rows = conn.execute(
                    "SELECT status, COUNT(*) as count FROM incidents GROUP BY status"
                ).fetchall()
                counts = {r["status"]: r["count"] for r in rows}

                # Pending outbox items
                outbox_row = conn.execute(
                    "SELECT COUNT(*) as count FROM outbox WHERE status = 'pending'"
                ).fetchone()
                pending_outbox = outbox_row["count"] if outbox_row else 0

                # Last event timestamp
                last_event_row = conn.execute(
                    "SELECT occurred_at FROM events ORDER BY occurred_at DESC LIMIT 1"
                ).fetchone()
                last_event_time = last_event_row["occurred_at"] if last_event_row else None

                active = counts.get("open", 0) + counts.get("reopened", 0)
                ack = counts.get("acknowledged", 0)
                resolved = counts.get("resolved", 0)
                total = sum(counts.values())

                return {
                    "ok": True,
                    "available": True,
                    "status": "healthy",
                    "active_incidents": active,
                    "acknowledged_incidents": ack,
                    "resolved_incidents": resolved,
                    "total_incidents": total,
                    "pending_outbox": pending_outbox,
                    "schema_version": schema_ver,
                    "last_event_time": last_event_time,
                }
        except Exception as exc:
            logger.warning("Failed querying notifications database: %s", exc)
            return {
                "ok": True,
                "available": False,
                "status": "degraded",
                "message": f"Database query error: {exc}",
                "active_incidents": 0,
                "acknowledged_incidents": 0,
                "resolved_incidents": 0,
                "total_incidents": 0,
                "pending_outbox": 0,
                "schema_version": None,
                "last_event_time": None,
            }

    def list_incidents(
        self,
        status: Optional[str] = None,
        severity: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Query paginated incidents with optional filtering."""
        if not self.db_path.is_file():
            return {"items": [], "total": 0, "limit": limit, "offset": offset, "available": False}

        try:
            with self._get_ro_connection() as conn:
                clauses = []
                params: List[Any] = []

                if status:
                    if status == "active":
                        clauses.append("status IN ('open', 'reopened')")
                    else:
                        clauses.append("status = ?")
                        params.append(status)

                if severity:
                    clauses.append("severity = ?")
                    params.append(severity)

                if source:
                    clauses.append("source = ?")
                    params.append(source)

                where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

                # Total matching count
                count_query = f"SELECT COUNT(*) as count FROM incidents {where_sql}"
                total_row = conn.execute(count_query, params).fetchone()
                total = total_row["count"] if total_row else 0

                # Paginated items
                items_query = f"""
                    SELECT incident_id, incident_key, source, severity, status,
                           summary, first_seen, last_seen, resolved_at, acknowledged_at,
                           occurrence_count, active_occurrence_id
                    FROM incidents
                    {where_sql}
                    ORDER BY last_seen DESC
                    LIMIT ? OFFSET ?
                """
                query_params = params + [min(max(1, limit), 100), max(0, offset)]
                rows = conn.execute(items_query, query_params).fetchall()

                items = [dict(r) for r in rows]
                return {
                    "items": items,
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                    "available": True,
                }
        except Exception as exc:
            logger.warning("Failed listing incidents: %s", exc)
            return {"items": [], "total": 0, "limit": limit, "offset": offset, "available": False}

    def get_incident(self, incident_id: str) -> Optional[Dict[str, Any]]:
        """Fetch complete incident record with recent transitions and delivery history."""
        if not self.db_path.is_file():
            return None

        try:
            with self._get_ro_connection() as conn:
                row = conn.execute(
                    "SELECT * FROM incidents WHERE incident_id = ?", (incident_id,)
                ).fetchone()
                if not row:
                    return None

                data = dict(row)

                # Fetch occurrence records
                occ_rows = conn.execute(
                    """
                    SELECT occurrence_id, incident_id, status, severity, opened_at, closed_at, resolution_evidence
                    FROM occurrences
                    WHERE incident_id = ?
                    ORDER BY opened_at DESC
                    LIMIT 20
                    """,
                    (incident_id,),
                ).fetchall()
                data["occurrences"] = [dict(o) for o in occ_rows]

                # Fetch transitions with event summary
                trans_rows = conn.execute(
                    """
                    SELECT t.transition_id, t.from_status, t.to_status, t.transition_name,
                           t.timestamp, t.details_json, e.summary, e.occurred_at
                    FROM transitions t
                    LEFT JOIN events e ON t.event_id = e.event_id
                    WHERE t.incident_id = ?
                    ORDER BY t.timestamp DESC
                    LIMIT 20
                    """,
                    (incident_id,),
                ).fetchall()
                data["transitions"] = [dict(t) for t in trans_rows]

                # Fetch associated delivery attempts via outbox join
                attempts_rows = conn.execute(
                    """
                    SELECT d.attempt_id, d.outbox_id, d.attempted_at, d.status,
                           d.provider_message_id, d.duration_ms, d.error_category, d.error_message,
                           o.provider_id
                    FROM delivery_attempts d
                    JOIN outbox o ON d.outbox_id = o.outbox_id
                    WHERE o.incident_id = ?
                    ORDER BY d.attempted_at DESC
                    LIMIT 20
                    """,
                    (incident_id,),
                ).fetchall()
                data["delivery_attempts"] = [dict(a) for a in attempts_rows]

                return data
        except Exception as exc:
            logger.warning("Failed fetching incident %s: %s", incident_id, exc)
            return None

    def list_recent_notifications(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Query recent rendered notifications across outbox and events."""
        if not self.db_path.is_file():
            return []

        try:
            with self._get_ro_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT o.outbox_id, o.event_id, o.incident_id, o.provider_id, o.status,
                           o.retry_count, o.max_retries, o.next_retry_at, o.created_at,
                           o.updated_at, o.error_message, e.summary, e.severity, e.source
                    FROM outbox o
                    LEFT JOIN events e ON o.event_id = e.event_id
                    ORDER BY o.created_at DESC
                    LIMIT ?
                    """,
                    (min(max(1, limit), 100),),
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception as exc:
            logger.warning("Failed listing notifications: %s", exc)
            return []
