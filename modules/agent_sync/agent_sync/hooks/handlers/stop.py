"""Stop hook handler — emit HANDOFF.md and end run (stub, extended in Phase 2)."""
from pathlib import Path

from agent_sync.hooks.normalize import HookEvent


def handle(event: HookEvent, db_path: Path) -> dict:
    """Emit HANDOFF.md candidate on session stop (stub — extended in Phase 2)."""
    handoff_path = Path(event.repo_root) / "agent_sync" / "docs" / "HANDOFF.md"
    if not handoff_path.exists():
        handoff_path.parent.mkdir(parents=True, exist_ok=True)
        handoff_path.write_text(
            f"# Handoff\n\nSession stopped by {event.provider}.\n"
            f"Repo root: {event.repo_root}\n"
            f"Session ID: {event.vendor_session_id}\n"
            f"\nExtended handoff generation wired in Phase 2.\n",
            encoding="utf-8",
        )
    return {}
