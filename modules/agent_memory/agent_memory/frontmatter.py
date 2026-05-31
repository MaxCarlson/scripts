from __future__ import annotations

import re
from typing import Any

import yaml

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)", re.DOTALL)

CURRENT_SCHEMA_VERSION: int = 2

# Fields required for V1 notes (and minimum set for V2).
REQUIRED_FIELDS_V1: frozenset[str] = frozenset({
    "id", "schema_version", "kind", "project",
    "created_at", "created_by", "tags",
})

# Additional fields required when schema_version == 2.
REQUIRED_FIELDS_V2_EXTRA: frozenset[str] = frozenset({
    "title", "updated_at", "updated_by", "status",
})

REQUIRED_FIELDS_V2: frozenset[str] = REQUIRED_FIELDS_V1 | REQUIRED_FIELDS_V2_EXTRA

# All optional V2 fields (informational; not validated as required).
OPTIONAL_FIELDS_V2: frozenset[str] = frozenset({
    "layer", "source_agent", "session_id", "confidence",
    "review_required", "classification_reason", "classification_method",
    "files", "related", "supersedes", "superseded_by", "evidence_for",
})

# Kept for backward-compatibility with callers that import REQUIRED_FIELDS.
REQUIRED_FIELDS: frozenset[str] = REQUIRED_FIELDS_V1


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from Markdown text.

    Returns:
        Tuple of (metadata dict, body string). If no frontmatter is found,
        metadata is {} and body is the full text.
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    meta: dict[str, Any] = yaml.safe_load(m.group(1)) or {}
    body = m.group(2).lstrip("\n")
    return meta, body


def write_frontmatter(meta: dict[str, Any], body: str) -> str:
    """Serialize YAML frontmatter + body to a Markdown string."""
    fm = yaml.dump(
        meta,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )
    return f"---\n{fm}---\n\n{body}"


def validate_frontmatter(meta: dict[str, Any]) -> list[str]:
    """Return validation error messages for a note's frontmatter.

    Chooses the required-field set based on ``schema_version`` in *meta*:
    - V1 notes (schema_version == 1 or absent): only V1 required fields.
    - V2 notes (schema_version == 2): V1 + V2 extra required fields.
    """
    version = int(meta.get("schema_version", 1))
    required = REQUIRED_FIELDS_V2 if version >= 2 else REQUIRED_FIELDS_V1
    return [
        f"Missing required field: '{f}'"
        for f in sorted(required)
        if f not in meta
    ]
