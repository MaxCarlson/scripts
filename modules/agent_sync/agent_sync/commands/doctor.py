"""agent-sync doctor command."""

from pathlib import Path
import shutil

from agent_sync.config import load_config
from agent_sync.paths import config_path, db_path


def cmd_doctor(repo_root: Path, *, verbose: bool = False) -> int:
    """Verify local agent_sync configuration."""
    ok = True
    cfg_path = config_path(repo_root)
    print(f"repo_root: {repo_root}")
    print(f"config:    {cfg_path} {'OK' if cfg_path.exists() else 'MISSING (defaults available)'}")
    print(f"db:        {db_path(repo_root)} {'OK' if db_path(repo_root).exists() else 'MISSING (run init)'}")
    config = load_config(cfg_path)
    print("workers:")
    for worker in config.workers:
        status = "disabled"
        found = "n/a"
        if worker.enabled:
            status = "enabled"
            if worker.kind == "command":
                binary = worker.command[0] if worker.command else ""
                found_path = shutil.which(binary) if binary else None
                found = found_path or "missing"
                if not found_path:
                    ok = False
            elif worker.kind == "local":
                try:
                    import llm_local.client  # noqa: F401
                    found = "llm_local import OK"
                except ImportError:
                    found = "llm_local missing"
                    ok = False
        print(f"  - {worker.name:16s} {worker.kind:8s} {status:8s} {found}")
        if verbose:
            print(f"    score={worker.capability_score} rate_limited={worker.rate_limited} strengths={', '.join(worker.strengths)}")
    return 0 if ok else 1
