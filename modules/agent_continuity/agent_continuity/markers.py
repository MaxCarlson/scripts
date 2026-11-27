"""Deterministic Workflow-ID marker parser for agent prompts and handoffs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .identifiers import is_workflow_id

_CANONICAL_RE = re.compile(r"^\s*Workflow-ID:\s*([A-Za-z0-9_-]{2,64})\s*$", re.IGNORECASE)
_LEGACY_RE = re.compile(r"^\s*\[wf:([A-Za-z0-9_-]{2,64})\]\s*$", re.IGNORECASE)
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
_VALID_SLUG_TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

MAX_PROMPT_SCAN_CHARS = 131_072


@dataclass(slots=True)
class MarkerParseResult:
    """Result of scanning prompt text for Workflow-ID markers."""

    marker: str | None
    markers_found: list[str] = field(default_factory=list)
    conflict: bool = False
    ignored_malformed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "marker": self.marker,
            "markers_found": list(self.markers_found),
            "conflict": self.conflict,
            "ignored_malformed": list(self.ignored_malformed),
        }


def _normalize_marker_token(raw: str) -> str | None:
    token = raw.strip().lower()
    if is_workflow_id(token):
        return token
    if token.startswith("wf_"):
        # Looks like a malformed wf_<hex> ID (e.g. too short or non-hex)
        return None
    if _VALID_SLUG_TOKEN_RE.match(token):
        return token
    return None


def parse_workflow_markers(text: str | None, *, max_chars: int = MAX_PROMPT_SCAN_CHARS) -> MarkerParseResult:
    """
    Extract authoritative Workflow-ID markers from prompt/handoff text.

    Rules:
    - Ignores lines inside fenced code blocks (``` or ~~~) and Markdown blockquotes (> ...).
    - Requires standalone marker lines (`Workflow-ID: <id_or_slug>` or `[wf:<id_or_slug>]`)
      so inline prose or backtick examples are never treated as active directives.
    - Detects multiple distinct markers as a conflict rather than silently picking one.
    - Never stores or returns raw prompt content.
    """
    if not text:
        return MarkerParseResult(marker=None)

    bounded = text[:max_chars]
    found: list[str] = []
    seen: set[str] = set()
    malformed: list[str] = []

    fence_char: str | None = None
    fence_len = 0

    for line in bounded.splitlines():
        fence_match = _FENCE_RE.match(line)
        if fence_match:
            seq = fence_match.group(1)
            if fence_char is None:
                fence_char = seq[0]
                fence_len = len(seq)
            elif seq[0] == fence_char and len(seq) >= fence_len:
                fence_char = None
                fence_len = 0
            continue

        if fence_char is not None:
            continue

        stripped_left = line.lstrip()
        if stripped_left.startswith(">"):
            continue

        match = _CANONICAL_RE.match(line) or _LEGACY_RE.match(line)
        if not match:
            continue

        raw_token = match.group(1)
        norm = _normalize_marker_token(raw_token)
        if norm is None:
            malformed.append(raw_token)
            continue
        if norm not in seen:
            seen.add(norm)
            found.append(norm)

    if len(found) > 1:
        return MarkerParseResult(
            marker=None,
            markers_found=found,
            conflict=True,
            ignored_malformed=malformed,
        )
    return MarkerParseResult(
        marker=found[0] if found else None,
        markers_found=found,
        conflict=False,
        ignored_malformed=malformed,
    )
