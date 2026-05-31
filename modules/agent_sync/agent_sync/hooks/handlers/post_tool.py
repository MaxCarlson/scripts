"""PostToolUse hook handler — record changed files (stub, extended in Phase 2)."""
from pathlib import Path

from agent_sync.hooks.normalize import HookEvent


def handle(event: HookEvent, db_path: Path) -> dict:
    """Record file write events for artifact tracking (stub — extended in Phase 2)."""
    return {}
