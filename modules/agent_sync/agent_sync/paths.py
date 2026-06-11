"""Path helpers for agent_sync."""

from pathlib import Path
import subprocess


def find_repo_root(start: Path | None = None) -> Path:
    """Return the nearest git repository root, or the start directory if none is found."""
    here = (start or Path.cwd()).expanduser().resolve()
    for candidate in [here, *here.parents]:
        if (candidate / ".git").exists():
            return candidate
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=here,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = result.stdout.strip()
        if output:
            return Path(output).expanduser().resolve()
    except (subprocess.SubprocessError, FileNotFoundError):
        return here
    return here


def agent_sync_dir(repo_root: Path) -> Path:
    """Return the repo-local agent_sync state directory."""
    return repo_root / ".agent_sync"


def config_path(repo_root: Path) -> Path:
    """Return the repo-local worker config path."""
    return agent_sync_dir(repo_root) / "workers.json"


def audit_dir(repo_root: Path) -> Path:
    """Return the repo-local audit directory."""
    return agent_sync_dir(repo_root) / "audit"


def docs_dir(repo_root: Path) -> Path:
    """Return the repo-local generated docs directory."""
    return repo_root / "agent_sync" / "docs"


def db_path(repo_root: Path) -> Path:
    """Return the repo-local SQLite database path used by future coordination phases."""
    return repo_root / "agent_sync" / "db" / "state.sqlite3"
