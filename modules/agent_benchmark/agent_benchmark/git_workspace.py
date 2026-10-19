"""Initialize only a benchmark-owned, fresh trial repository; never host Git config."""

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import uuid

ISOLATION_POLICY = "isolated-git-project-v1"


@dataclass(frozen=True)
class GitIdentity:
    trial_id: str
    root_commit: str
    worktree: str
    policy_version: str = ISOLATION_POLICY


def initialize_git(workspace: Path) -> GitIdentity:
    """Create a unique root commit without inherited repositories, hooks or remotes."""
    workspace = workspace.resolve()
    if (workspace / ".git").exists():
        raise ValueError("Trial Git metadata must not already exist")
    # GIT_DIR/WORK_TREE/CONFIG_COUNT and identity variables must not redirect these
    # writes or load user filters/hooks. No HOME or shared service settings change.
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_ATTR_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
    command = ["git", "-c", "user.name=Benchmark Worker", "-c", "user.email=benchmark@trial.local",
               "-c", "commit.gpgSign=false", "-c", "core.autocrlf=false",
               "-c", f"core.hooksPath={workspace / '.git/disabled-hooks'}"]

    def run(*args: str) -> str:
        result = subprocess.run([*command, *args], cwd=workspace, env=env, check=True,
                                capture_output=True, text=True, encoding="utf-8", timeout=10)
        return result.stdout.strip()

    run("init", "--quiet", "--template=", "--initial-branch=benchmark", "--object-format=sha1")
    if Path(run("rev-parse", "--show-toplevel")).resolve() != workspace:
        raise RuntimeError("Git initialization escaped the trial workspace")
    run("add", "--force", "--all", "--", ".")
    trial_id = uuid.uuid4().hex
    run("commit", "--quiet", "-m", f"agent-benchmark initial seed [{trial_id}]")
    root = run("rev-list", "--max-parents=0", "HEAD")
    if len(root) != 40 or root != run("rev-parse", "HEAD") or run("remote"):
        raise RuntimeError("Trial repository must have one independent root and no remote")
    return GitIdentity(trial_id, root, str(workspace))
