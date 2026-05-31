from pathlib import Path

import pytest

from agent_sync.db.connection import get_connection
from agent_sync.db.schema import initialize_schema
from agent_sync.state.tasks import Task, create_task, get_task, list_tasks, update_task_status
from agent_sync.state.runs import Run, end_run, get_active_run, heartbeat, start_run


@pytest.fixture()
def conn(tmp_path: Path):
    c = get_connection(tmp_path / "state.sqlite3")
    initialize_schema(c)
    c.execute(
        "INSERT INTO agents VALUES (?,?,?,?,?,?,?,?,?)",
        ("claude", "claude", "ClaudeAdapter", "claude", None, 1,
         '["code","review"]', "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    )
    c.commit()
    yield c
    c.close()


# --- Task tests ---

def test_create_and_get_task(conn) -> None:
    task = create_task(
        conn,
        title="Fix auth bug",
        kind="bugfix",
        priority=4,
        target_branch="main",
        summary_md="Fix refresh token race.",
    )
    assert task.task_id.startswith("TASK-")
    fetched = get_task(conn, task.task_id)
    assert fetched is not None
    assert fetched.title == "Fix auth bug"
    assert fetched.status == "ready"


def test_update_task_status(conn) -> None:
    task = create_task(conn, title="T", kind="feature", priority=3,
                       target_branch="main", summary_md="s")
    update_task_status(conn, task.task_id, "running")
    updated = get_task(conn, task.task_id)
    assert updated is not None
    assert updated.status == "running"


def test_list_tasks_filters_by_status(conn) -> None:
    create_task(conn, title="A", kind="feature", priority=3,
                target_branch="main", summary_md="s")
    create_task(conn, title="B", kind="bugfix", priority=4,
                target_branch="main", summary_md="s")
    ready = list_tasks(conn, status="ready")
    assert len(ready) == 2
    update_task_status(conn, ready[0].task_id, "running")
    assert len(list_tasks(conn, status="ready")) == 1


def test_get_task_returns_none_for_missing(conn) -> None:
    assert get_task(conn, "TASK-NONEXISTENT") is None


# --- Run tests ---

def test_start_and_end_run(conn) -> None:
    task = create_task(conn, title="T", kind="feature", priority=3,
                       target_branch="main", summary_md="s")
    run = start_run(
        conn,
        task_id=task.task_id,
        agent_name="claude",
        mode="primary",
        repo_root=Path("/repo"),
        cwd=Path("/repo"),
        branch_name="ags/T/claude/fix",
        worktree_path=Path("/repo/.agent_sync/worktrees/T--claude"),
    )
    assert run.run_id.startswith("RUN-")
    assert run.status == "active"

    end_run(conn, run.run_id, status="completed", stop_reason="task done")
    updated = get_active_run(conn, task.task_id)
    assert updated is None


def test_heartbeat_updates_timestamp(conn) -> None:
    task = create_task(conn, title="T", kind="feature", priority=3,
                       target_branch="main", summary_md="s")
    run = start_run(conn, task_id=task.task_id, agent_name="claude",
                    mode="primary", repo_root=Path("/r"), cwd=Path("/r"),
                    branch_name="b", worktree_path=Path("/w"))
    old_ts = conn.execute(
        "SELECT heartbeat_at FROM runs WHERE run_id=?", (run.run_id,)
    ).fetchone()[0]
    heartbeat(conn, run.run_id)
    new_ts = conn.execute(
        "SELECT heartbeat_at FROM runs WHERE run_id=?", (run.run_id,)
    ).fetchone()[0]
    assert new_ts >= old_ts
