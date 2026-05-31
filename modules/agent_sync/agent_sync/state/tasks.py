import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
import uuid


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _task_id() -> str:
    return f"TASK-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"


@dataclass
class Task:
    task_id: str
    title: str
    kind: str
    priority: int
    status: str
    target_branch: str
    manifest_path: str
    summary_md: str
    routing_json: str
    scoring_json: str
    created_at: str
    updated_at: str
    parent_task_id: Optional[str] = None
    acceptance_md: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


def create_task(
    conn: sqlite3.Connection,
    *,
    title: str,
    kind: str,
    priority: int,
    target_branch: str,
    summary_md: str,
    parent_task_id: Optional[str] = None,
    acceptance_md: Optional[str] = None,
    routing: Optional[dict] = None,
    scoring: Optional[dict] = None,
    manifest_path: str = "",
) -> Task:
    """Insert a new task with status='ready' and return it."""
    now = _now()
    task = Task(
        task_id=_task_id(),
        title=title,
        kind=kind,
        priority=priority,
        status="ready",
        target_branch=target_branch,
        manifest_path=manifest_path,
        summary_md=summary_md,
        routing_json=json.dumps(routing or {}),
        scoring_json=json.dumps(scoring or {}),
        created_at=now,
        updated_at=now,
        parent_task_id=parent_task_id,
        acceptance_md=acceptance_md,
    )
    conn.execute(
        """
        INSERT INTO tasks
          (task_id, parent_task_id, title, kind, priority, status,
           target_branch, manifest_path, summary_md, acceptance_md,
           routing_json, scoring_json, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (task.task_id, task.parent_task_id, task.title, task.kind,
         task.priority, task.status, task.target_branch, task.manifest_path,
         task.summary_md, task.acceptance_md, task.routing_json,
         task.scoring_json, task.created_at, task.updated_at),
    )
    conn.commit()
    return task


def get_task(conn: sqlite3.Connection, task_id: str) -> Optional[Task]:
    """Return a Task by ID, or None if not found."""
    row = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
    if row is None:
        return None
    return Task(**dict(row))


def update_task_status(conn: sqlite3.Connection, task_id: str, status: str) -> None:
    """Update task status and updated_at timestamp."""
    conn.execute(
        "UPDATE tasks SET status=?, updated_at=? WHERE task_id=?",
        (status, _now(), task_id),
    )
    conn.commit()


def list_tasks(
    conn: sqlite3.Connection,
    *,
    status: Optional[str] = None,
    kind: Optional[str] = None,
) -> list[Task]:
    """Return tasks, optionally filtered by status and/or kind."""
    clauses: list[str] = []
    params: list[str] = []
    if status:
        clauses.append("status=?")
        params.append(status)
    if kind:
        clauses.append("kind=?")
        params.append(kind)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM tasks {where} ORDER BY priority DESC, created_at",
        params,
    ).fetchall()
    return [Task(**dict(r)) for r in rows]
