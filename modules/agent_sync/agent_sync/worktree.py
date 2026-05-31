"""Git worktree lifecycle management for agent_sync.

All worktrees follow the naming convention:
  directory:  .agent_sync/worktrees/<task-id>--<agent>--<slug>
  branch:     ags/<task-id>/<agent>/<slug>

Module-managed worktrees are used for all agents (including Claude Code) for
cross-vendor consistency.
"""
import subprocess
from pathlib import Path


def worktree_branch_name(task_id: str, agent: str, slug: str) -> str:
    """Return the branch name for a task worktree."""
    return f"ags/{task_id}/{agent}/{slug}"


def worktree_dir_name(task_id: str, agent: str, slug: str) -> str:
    """Return the directory basename for a task worktree."""
    return f"{task_id}--{agent}--{slug}"


def _wt_root(repo_root: Path) -> Path:
    return repo_root / ".agent_sync" / "worktrees"


def create_worktree(
    repo_root: Path,
    task_id: str,
    agent: str,
    slug: str,
    base_branch: str,
) -> tuple[Path, str]:
    """Create a new Git worktree and branch for a task.

    Args:
        repo_root: Absolute path to the repository root.
        task_id: Task identifier (e.g. TASK-20260101-abc123).
        agent: Agent name (e.g. claude, codex, gemini).
        slug: Short slug describing the work (e.g. auth-fix).
        base_branch: Branch to base the new worktree branch on.

    Returns:
        Tuple of (worktree_path, branch_name).
    """
    branch = worktree_branch_name(task_id, agent, slug)
    wt_dir = _wt_root(repo_root) / worktree_dir_name(task_id, agent, slug)
    wt_dir.parent.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(wt_dir), base_branch],
        cwd=str(repo_root),
        check=True,
        capture_output=True,
    )
    return wt_dir, branch


def remove_worktree(repo_root: Path, worktree_path: Path) -> None:
    """Remove a worktree and prune stale references."""
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree_path)],
        cwd=str(repo_root),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "worktree", "prune"],
        cwd=str(repo_root),
        check=True,
        capture_output=True,
    )


def list_worktrees(repo_root: Path) -> list[dict]:
    """Return a list of dicts describing each worktree.

    Each dict has keys: worktree, HEAD, branch.
    """
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=str(repo_root),
        check=True,
        capture_output=True,
        text=True,
    )
    trees: list[dict] = []
    current: dict = {}
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            if current:
                trees.append(current)
            current = {"worktree": line[len("worktree "):]}
        elif line.startswith("HEAD "):
            current["HEAD"] = line[len("HEAD "):]
        elif line.startswith("branch "):
            current["branch"] = line[len("branch "):]
        elif line == "bare":
            current["bare"] = True
    if current:
        trees.append(current)
    return trees
