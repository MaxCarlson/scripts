from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

VALID_KINDS: frozenset[str] = frozenset({
    "constraint", "preference", "decision", "code_note",
    "handoff", "task", "bug", "session",
})

GLOBAL_DEFAULT_KINDS: frozenset[str] = frozenset({"constraint", "preference"})
PROJECT_REQUIRED_KINDS: frozenset[str] = frozenset({"handoff", "task", "bug"})
LLM_CLASSIFY_KINDS: frozenset[str] = frozenset({"decision", "code_note", "session"})


@dataclass
class Note:
    """A single memory note loaded from a Markdown file."""

    id: str
    path: Path
    kind: str
    project: str
    title: str
    body: str
    created_at: str
    created_by: str
    tags: list[str] = field(default_factory=list)
    schema_version: int = 1
