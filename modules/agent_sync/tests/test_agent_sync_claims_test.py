from pathlib import Path

import pytest

from agent_sync.db.connection import get_connection
from agent_sync.db.schema import initialize_schema
from agent_sync.state.claims import ClaimConflictError, acquire_claims, check_conflicts, release_claims
from agent_sync.state.runs import start_run
from agent_sync.state.tasks import create_task


@pytest.fixture()
def setup(tmp_path: Path):
    conn = get_connection(tmp_path / "state.sqlite3")
    initialize_schema(conn)
    conn.execute(
        "INSERT INTO agents VALUES (?,?,?,?,?,?,?,?,?)",
        ("claude", "claude", "ClaudeAdapter", "claude", None, 1,
         '[]', "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    )
    conn.commit()
    task = create_task(conn, title="T", kind="bugfix", priority=3,
                       target_branch="main", summary_md="s")
    run = start_run(conn, task_id=task.task_id, agent_name="claude",
                    mode="primary", repo_root=Path("/repo"), cwd=Path("/repo"),
                    branch_name="b", worktree_path=Path("/w"))
    return conn, task, run


def test_acquire_and_release_claims(setup) -> None:
    conn, task, run = setup
    paths = [Path("src/auth/token.py"), Path("tests/auth/")]
    claim_ids = acquire_claims(conn, run_id=run.run_id, task_id=task.task_id,
                                repo_root=Path("/repo"), paths=paths,
                                access_mode="write")
    assert len(claim_ids) == 2

    release_claims(conn, run.run_id)
    conflicts = check_conflicts(conn, repo_root=Path("/repo"),
                                paths=[Path("src/auth/token.py")])
    assert conflicts == []


def test_write_claim_conflict_raises(setup) -> None:
    conn, task, run = setup
    acquire_claims(conn, run_id=run.run_id, task_id=task.task_id,
                   repo_root=Path("/repo"), paths=[Path("src/auth/")],
                   access_mode="write")
    # Same file under claimed dir should conflict
    conflicts = check_conflicts(conn, repo_root=Path("/repo"),
                                paths=[Path("src/auth/token.py")])
    assert len(conflicts) == 1


def test_parent_dir_claim_conflicts_with_child_file(setup) -> None:
    conn, task, run = setup
    acquire_claims(conn, run_id=run.run_id, task_id=task.task_id,
                   repo_root=Path("/repo"), paths=[Path("src/auth/token.py")],
                   access_mode="write")
    conflicts = check_conflicts(conn, repo_root=Path("/repo"),
                                paths=[Path("src/auth/")])
    assert len(conflicts) == 1


def test_read_claim_does_not_conflict_with_read(setup) -> None:
    conn, task, run = setup
    acquire_claims(conn, run_id=run.run_id, task_id=task.task_id,
                   repo_root=Path("/repo"), paths=[Path("src/auth/")],
                   access_mode="read")
    # Another read-only claim on same path should not conflict
    conflicts = check_conflicts(conn, repo_root=Path("/repo"),
                                paths=[Path("src/auth/")],
                                access_mode="read")
    assert conflicts == []
