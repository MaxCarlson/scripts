"""Worker listing command."""

import json
from pathlib import Path

from agent_sync.config import load_config
from agent_sync.paths import config_path


def cmd_workers(repo_root: Path, *, show_all: bool = False, output_json: bool = False) -> int:
    """List configured workers."""
    config = load_config(config_path(repo_root))
    workers = list(config.workers if show_all else config.enabled_workers())
    if output_json:
        print(json.dumps([worker.to_dict() for worker in workers], indent=2))
        return 0
    print(f"{'NAME':18s} {'KIND':8s} {'ENABLED':7s} {'SCORE':>5s} {'RATE':5s} STRENGTHS")
    print(f"{'-' * 18} {'-' * 8} {'-' * 7} {'-' * 5} {'-' * 5} {'-' * 40}")
    for worker in workers:
        print(
            f"{worker.name:18s} {worker.kind:8s} {str(worker.enabled):7s} "
            f"{worker.capability_score:5.2f} {str(worker.rate_limited):5s} {', '.join(worker.strengths)}"
        )
    return 0
