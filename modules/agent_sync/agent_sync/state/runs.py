import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import uuid


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _run_id() -> str:
    return f"RUN-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"


@dataclass
class Run:
    run_id: str
    task_id: str
    agent_name: str
    mode: str
    status: str
    repo_root: str
    cwd: str
    branch_name: str
    worktree_path: str
    heartbeat_at: str
    started_at: str
    parent_run_id: Optional[str] = None
    vendor_session_id: Optional[str] = None
    vendor_transcript_path: Optional[str] = None
    permission_mode: Optional[str] = None
    model_name: Optional[str] = None
    ended_at: Optional[str] = None
    stop_reason: Optional[str] = None
    summary_md: Optional[str] = None


def start_run(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    agent_name: str,
    mode: str,
    repo_root: Path,
    cwd: Path,
    branch_name: str,
    worktree_path: Path,
    parent_run_id: Optional[str] = None,
    model_name: Optional[str] = None,
    permission_mode: Optional[str] = None,
) -> Run:
    """Insert a new run with status='active' and return it."""
    now = _now()
    run = Run(
        run_id=_run_id(),
        task_id=task_id,
        agent_name=agent_name,
        mode=mode,
        status="active",
        repo_root=str(repo_root),
        cwd=str(cwd),
        branch_name=branch_name,
        worktree_path=str(worktree_path),
        heartbeat_at=now,
        started_at=now,
        parent_run_id=parent_run_id,
        model_name=model_name,
        permission_mode=permission_mode,
    )
    conn.execute(
        """
        INSERT INTO runs
          (run_id, task_id, parent_run_id, agent_name, mode, status,
           repo_root, cwd, branch_name, worktree_path,
           model_name, permission_mode,
           heartbeat_at, started_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (run.run_id, run.task_id, run.parent_run_id, run.agent_name, run.mode,
         run.status, run.repo_root, run.cwd, run.branch_name, run.worktree_path,
         run.model_name, run.permission_mode, run.heartbeat_at, run.started_at),
    )
    conn.commit()
    return run


def end_run(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    status: str,
    stop_reason: Optional[str] = None,
    summary_md: Optional[str] = None,
) -> None:
    """Mark a run as ended with the given status."""
    conn.execute(
        "UPDATE runs SET status=?, ended_at=?, stop_reason=?, summary_md=? WHERE run_id=?",
        (status, _now(), stop_reason, summary_md, run_id),
    )
    conn.commit()


def heartbeat(conn: sqlite3.Connection, run_id: str) -> None:
    """Refresh the heartbeat timestamp for a run."""
    conn.execute(
        "UPDATE runs SET heartbeat_at=? WHERE run_id=?",
        (_now(), run_id),
    )
    conn.commit()


def get_active_run(conn: sqlite3.Connection, task_id: str) -> Optional[Run]:
    """Return the active run for a task, or None."""
    row = conn.execute(
        "SELECT * FROM runs WHERE task_id=? AND status='active' LIMIT 1",
        (task_id,),
    ).fetchone()
    return Run(**dict(row)) if row else None
