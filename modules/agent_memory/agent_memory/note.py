from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Kind taxonomy — V2
# ---------------------------------------------------------------------------

ACTIVE_KINDS: frozenset[str] = frozenset({
    "constraint",
    "preference",
    "decision",
    "code_note",
    "handoff",
    "bug",
    "environment",
    "procedure",
    "evidence",
    "task_state",
    "task_lesson",
    "reflection",
})

# Readable but creation is rejected by default.
DEPRECATED_KINDS: frozenset[str] = frozenset({"task", "session"})

# Union used for index/search compatibility.
ALL_READABLE_KINDS: frozenset[str] = ACTIVE_KINDS | DEPRECATED_KINDS

# Kept for backward-compatibility with existing callers.
VALID_KINDS: frozenset[str] = ALL_READABLE_KINDS

# ---------------------------------------------------------------------------
# Placement policy sets (active kinds only; deprecated kinds not classifiable)
# ---------------------------------------------------------------------------

GLOBAL_DEFAULT_KINDS: frozenset[str] = frozenset({
    "constraint",
    "preference",
    "procedure",
    "environment",
})

PROJECT_REQUIRED_KINDS: frozenset[str] = frozenset({
    "handoff",
    "task_state",
    "bug",
    "evidence",
})

LLM_CLASSIFY_KINDS: frozenset[str] = frozenset({
    "decision",
    "code_note",
    "task_lesson",
    "reflection",
})

# ---------------------------------------------------------------------------
# Lifecycle status
# ---------------------------------------------------------------------------

VALID_STATUSES: frozenset[str] = frozenset({"active", "superseded", "archived", "draft"})
DEFAULT_STATUS: str = "active"

# ---------------------------------------------------------------------------
# Memory layer taxonomy
# ---------------------------------------------------------------------------

VALID_LAYERS: frozenset[str] = frozenset({"core", "working", "archival", "reflective"})

DEFAULT_LAYER_BY_KIND: dict[str, str] = {
    "constraint": "core",
    "preference": "core",
    "procedure": "core",
    "environment": "core",
    "handoff": "working",
    "task_state": "working",
    "decision": "archival",
    "code_note": "archival",
    "bug": "archival",
    "evidence": "archival",
    "task_lesson": "reflective",
    "reflection": "reflective",
    # Deprecated — kept for readback compatibility
    "task": "working",
    "session": "archival",
}


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
    # V2 lifecycle / provenance fields (optional; absent on V1 readback)
    updated_at: str = ""
    updated_by: str = ""
    status: str = DEFAULT_STATUS
    layer: str = ""
    source_agent: str | None = None
    session_id: str | None = None
    confidence: float | None = None
    review_required: bool = False
    classification_reason: str | None = None
    classification_method: str | None = None
    # V2 relationship / context fields
    related: list[str] = field(default_factory=list)
    supersedes: list[str] = field(default_factory=list)
    superseded_by: list[str] = field(default_factory=list)
    evidence_for: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
