from __future__ import annotations

import re
from typing import Any

import yaml

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)", re.DOTALL)

REQUIRED_FIELDS: frozenset[str] = frozenset({
    "id", "schema_version", "kind", "project",
    "created_at", "created_by", "tags",
})


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
    """Return validation error messages. Empty list means valid."""
    return [
        f"Missing required field: '{field}'"
        for field in sorted(REQUIRED_FIELDS)
        if field not in meta
    ]
