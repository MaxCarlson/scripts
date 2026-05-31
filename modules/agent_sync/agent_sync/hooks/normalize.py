"""Normalize provider-specific hook JSON payloads into a common HookEvent."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass
class HookEvent:
    provider: str           # claude | codex | gemini | local
    event: str              # SessionStart | PreToolUse | PostToolUse | Stop
    repo_root: str
    cwd: str
    vendor_session_id: Optional[str] = None
    permission_mode: Optional[str] = None
    tool: Optional[dict] = None
    stop_reason: Optional[str] = None
    raw: dict = field(default_factory=dict)
    ts: str = field(
        default_factory=lambda: datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def normalize_payload(provider: str, event: str, payload: dict) -> HookEvent:
    """Convert a raw provider hook payload into a HookEvent.

    All three providers (Claude, Codex, Gemini) use the same JSON structure
    for these four events. Only documented fields are consumed; unknown fields
    are stored in raw but not relied upon.

    Args:
        provider: One of 'claude', 'codex', 'gemini'.
        event: Hook event name.
        payload: Raw JSON dict from stdin.

    Returns:
        Normalised HookEvent.
    """
    cwd = payload.get("cwd", "")
    repo_root = payload.get("repo_root", cwd)

    tool = None
    if event in ("PreToolUse", "PostToolUse"):
        tool_name = payload.get("tool_name") or payload.get("tool", {}).get("name")
        tool_input = payload.get("tool_input") or payload.get("tool", {}).get("input", {})
        tool_response = payload.get("tool_response") or payload.get("tool", {}).get("response")
        tool = {"name": tool_name, "input": tool_input, "response": tool_response}

    return HookEvent(
        provider=provider,
        event=event,
        repo_root=repo_root,
        cwd=cwd,
        vendor_session_id=payload.get("session_id"),
        permission_mode=payload.get("permission_mode"),
        tool=tool,
        stop_reason=payload.get("stop_reason"),
        raw=payload,
    )
