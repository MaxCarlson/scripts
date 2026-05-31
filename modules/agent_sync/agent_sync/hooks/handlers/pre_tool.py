"""PreToolUse hook handler — block forbidden commands."""
import re
from pathlib import Path

from agent_sync.hooks.normalize import HookEvent

# Commands that must not run outside agent-sync integrate
_BLOCKED = [
    re.compile(r"git\s+push"),
    re.compile(r"gh\s+pr\s+(create|merge)"),
    re.compile(r"git\s+commit.*--amend"),
    re.compile(r"\brm\s+-rf\s+/"),
    re.compile(r"\bsudo\b"),
    re.compile(r"\bnpm\s+publish\b"),
    re.compile(r"\bpip\s+publish\b"),
]


def handle(event: HookEvent, db_path: Path) -> dict:
    """Block forbidden commands; allow everything else."""
    if event.tool is None:
        return {}
    tool_name = event.tool.get("name", "")
    if tool_name not in ("Bash", "shell"):
        return {}
    command = event.tool.get("input", {}).get("command", "")
    for pattern in _BLOCKED:
        if pattern.search(command):
            return {
                "type": "block",
                "reason": (
                    f"agent_sync policy: command blocked by PreToolUse guard.\n"
                    f"Matched pattern: {pattern.pattern}\n"
                    f"Use `agent-sync integrate` for merge/push operations."
                ),
            }
    return {}
