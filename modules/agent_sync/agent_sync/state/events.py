import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def log_event(
    conn: sqlite3.Connection,
    *,
    provider: str,
    event_type: str,
    payload: dict,
    run_id: Optional[str] = None,
    task_id: Optional[str] = None,
    level: str = "info",
) -> int:
    """Append an event to the events table. Returns the new event_id."""
    cursor = conn.execute(
        """
        INSERT INTO events
          (run_id, task_id, level, event_type, provider, payload_json, created_at)
        VALUES (?,?,?,?,?,?,?)
        """,
        (run_id, task_id, level, event_type, provider,
         json.dumps(payload), _now()),
    )
    conn.commit()
    return cursor.lastrowid  # type: ignore[return-value]


def record_artifact(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    artifact_type: str,
    relative_path: str,
    data: bytes,
    task_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> str:
    """Record an artifact reference in the DB. Returns artifact_id."""
    sha256 = hashlib.sha256(data).hexdigest()
    aid = f"ART-{uuid.uuid4().hex[:10]}"
    conn.execute(
        """
        INSERT INTO artifacts
          (artifact_id, run_id, task_id, artifact_type, relative_path,
           sha256, byte_count, metadata_json, created_at)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (aid, run_id, task_id, artifact_type, relative_path,
         sha256, len(data), json.dumps(metadata or {}), _now()),
    )
    conn.commit()
    return aid
