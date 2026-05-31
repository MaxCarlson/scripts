"""SessionStart hook handler — inject SESSION_BRIEF.md context."""
from pathlib import Path

from agent_sync.hooks.normalize import HookEvent


def handle(event: HookEvent, db_path: Path) -> dict:
    """Return a hook output dict that injects the session brief.

    The returned dict is printed as JSON to stdout so the provider
    injects it as additional context at session start.
    """
    brief_path = Path(event.repo_root) / "agent_sync" / "docs" / "SESSION_BRIEF.md"
    if brief_path.exists():
        brief = brief_path.read_text(encoding="utf-8")
        return {
            "type": "inject",
            "content": f"[agent_sync session brief]\n{brief}",
        }
    return {}
