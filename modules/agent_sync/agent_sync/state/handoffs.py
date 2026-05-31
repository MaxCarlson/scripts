import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class Handoff:
    handoff_id: str
    task_id: str
    from_run_id: str
    to_agent_name: str
    handoff_md_path: str
    status: str
    created_at: str
    accepted_at: Optional[str] = None


def create_handoff(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    from_run_id: str,
    to_agent_name: str,
    handoff_md_path: str,
) -> Handoff:
    """Create a handoff record with status='proposed'."""
    h = Handoff(
        handoff_id=f"HO-{uuid.uuid4().hex[:10]}",
        task_id=task_id,
        from_run_id=from_run_id,
        to_agent_name=to_agent_name,
        handoff_md_path=handoff_md_path,
        status="proposed",
        created_at=_now(),
    )
    conn.execute(
        """
        INSERT INTO handoffs
          (handoff_id, task_id, from_run_id, to_agent_name,
           handoff_md_path, status, created_at)
        VALUES (?,?,?,?,?,?,?)
        """,
        (h.handoff_id, h.task_id, h.from_run_id, h.to_agent_name,
         h.handoff_md_path, h.status, h.created_at),
    )
    conn.commit()
    return h


def accept_handoff(conn: sqlite3.Connection, handoff_id: str) -> None:
    """Mark a handoff as accepted."""
    conn.execute(
        "UPDATE handoffs SET status='accepted', accepted_at=? WHERE handoff_id=?",
        (_now(), handoff_id),
    )
    conn.commit()
