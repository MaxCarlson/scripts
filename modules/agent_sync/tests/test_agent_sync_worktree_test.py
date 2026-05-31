import subprocess
from pathlib import Path

import pytest

from agent_sync.worktree import (
    create_worktree,
    list_worktrees,
    remove_worktree,
    worktree_branch_name,
    worktree_dir_name,
)


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main", str(path)], check=True,
                   capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"],
                   check=True, capture_output=True)
    (path / "README.md").write_text("init", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True,
                   capture_output=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", "init"],
                   check=True, capture_output=True)


def test_branch_name_format() -> None:
    name = worktree_branch_name("TASK-20260101-abc123", "claude", "auth-fix")
    assert name == "ags/TASK-20260101-abc123/claude/auth-fix"


def test_dir_name_format() -> None:
    name = worktree_dir_name("TASK-20260101-abc123", "claude", "auth-fix")
    assert name == "TASK-20260101-abc123--claude--auth-fix"


def test_create_and_remove_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    wt_path, branch = create_worktree(
        repo_root=repo,
        task_id="TASK-20260101-abc123",
        agent="claude",
        slug="auth-fix",
        base_branch="main",
    )
    assert wt_path.exists()
    assert branch == "ags/TASK-20260101-abc123/claude/auth-fix"

    remove_worktree(repo_root=repo, worktree_path=wt_path)
    assert not wt_path.exists()


def test_list_worktrees(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    wt_path, _ = create_worktree(repo, "TASK-001", "claude", "fix", "main")
    trees = list_worktrees(repo)
    paths = [t["worktree"] for t in trees]
    assert str(wt_path) in paths
    remove_worktree(repo, wt_path)
