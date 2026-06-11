from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)", re.DOTALL)
_FRONTMATTER_OPEN_RE = re.compile(r"^---\n")

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

# ---------------------------------------------------------------------------
# ValidationIssue — structured diagnostic for frontmatter / path problems
# ---------------------------------------------------------------------------

# Stable issue code constants.
CODE_MISSING_REQUIRED = "MISSING_REQUIRED"
CODE_WRONG_TYPE = "WRONG_TYPE"
CODE_UNKNOWN_KIND = "UNKNOWN_KIND"
CODE_UNKNOWN_STATUS = "UNKNOWN_STATUS"
CODE_INVALID_LAYER = "INVALID_LAYER"
CODE_MISSING_LAYER = "MISSING_LAYER"
CODE_CONFIDENCE_RANGE = "CONFIDENCE_RANGE"
CODE_NON_LIST_FIELD = "NON_LIST_FIELD"
CODE_MIXED_TYPE_LIST = "MIXED_TYPE_LIST"
CODE_NO_FRONTMATTER = "NO_FRONTMATTER"
CODE_YAML_PARSE_ERROR = "YAML_PARSE_ERROR"
CODE_MISSING_CLOSING_DELIMITER = "MISSING_CLOSING_DELIMITER"
CODE_KIND_PATH_MISMATCH = "KIND_PATH_MISMATCH"
CODE_PROJECT_PATH_MISMATCH = "PROJECT_PATH_MISMATCH"
CODE_UNKNOWN_LAYOUT = "UNKNOWN_LAYOUT"
CODE_DUPLICATE_ID = "DUPLICATE_ID"


@dataclass(frozen=True)
class ValidationIssue:
    """A structured diagnostic produced by frontmatter validation or path checks."""

    path: Path | None
    field: str | None
    code: str
    message: str
    severity: Literal["error", "warning"]

    def __str__(self) -> str:  # pragma: no cover
        loc = str(self.path) if self.path else "<unknown>"
        field_part = f" [{self.field}]" if self.field else ""
        return f"{self.severity.upper()}: {loc}{field_part} ({self.code}) {self.message}"


# ---------------------------------------------------------------------------
# FrontmatterParseResult — safe-parse result that preserves raw content
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FrontmatterParseResult:
    """Result of a safe frontmatter parse. Always populated even on failure."""

    metadata: dict[str, Any]
    body: str
    issues: list[ValidationIssue]
    raw_frontmatter: str | None
    has_frontmatter: bool


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from Markdown text.

    Returns:
        Tuple of (metadata dict, body string). If no frontmatter is found,
        metadata is {} and body is the full text.
    """
    # Strip UTF-8 BOM if present before matching.
    if text.startswith("\ufeff"):
        text = text[1:]
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    meta: dict[str, Any] = yaml.safe_load(m.group(1)) or {}
    body = m.group(2).lstrip("\n")
    return meta, body


def parse_frontmatter_safe(text: str, path: Path | None = None) -> FrontmatterParseResult:
    """Parse frontmatter with full error recovery and structured diagnostics.

    Unlike ``parse_frontmatter()``, this function:
    - Strips a UTF-8 BOM before matching.
    - Returns structured ``ValidationIssue`` objects instead of raising.
    - Preserves raw_frontmatter text for diagnostic use.
    - Preserves body text even when YAML parsing fails.
    - Runs ``validate_frontmatter_structured()`` on successfully parsed metadata.

    Returns:
        A ``FrontmatterParseResult`` that is always populated.
    """
    issues: list[ValidationIssue] = []

    # Strip UTF-8 BOM.
    if text.startswith("\ufeff"):
        text = text[1:]

    # No opening delimiter → no frontmatter at all.
    if not _FRONTMATTER_OPEN_RE.match(text):
        issues.append(
            ValidationIssue(
                path=path,
                field=None,
                code=CODE_NO_FRONTMATTER,
                message="File has no YAML frontmatter block.",
                severity="error",
            )
        )
        return FrontmatterParseResult(
            metadata={},
            body=text,
            issues=issues,
            raw_frontmatter=None,
            has_frontmatter=False,
        )

    # Opening delimiter present — try to find a closing one.
    m = _FRONTMATTER_RE.match(text)
    if not m:
        # Opening `---` found but no closing `---`.
        issues.append(
            ValidationIssue(
                path=path,
                field=None,
                code=CODE_MISSING_CLOSING_DELIMITER,
                message="Frontmatter block has no closing '---' delimiter.",
                severity="error",
            )
        )
        # Body is everything after the first line.
        body = text.partition("\n")[2]
        return FrontmatterParseResult(
            metadata={},
            body=body,
            issues=issues,
            raw_frontmatter=None,
            has_frontmatter=True,
        )

    raw_fm = m.group(1)
    body = m.group(2).lstrip("\n")

    # Try to parse YAML.
    try:
        meta: dict[str, Any] = yaml.safe_load(raw_fm) or {}
    except yaml.YAMLError as exc:
        issues.append(
            ValidationIssue(
                path=path,
                field=None,
                code=CODE_YAML_PARSE_ERROR,
                message=f"YAML parse error: {exc}",
                severity="error",
            )
        )
        return FrontmatterParseResult(
            metadata={},
            body=body,
            issues=issues,
            raw_frontmatter=raw_fm,
            has_frontmatter=True,
        )

    # Run structured validation on successfully parsed metadata.
    issues.extend(validate_frontmatter_structured(meta, path=path))

    return FrontmatterParseResult(
        metadata=meta,
        body=body,
        issues=issues,
        raw_frontmatter=raw_fm,
        has_frontmatter=True,
    )


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def write_frontmatter(meta: dict[str, Any], body: str) -> str:
    """Serialize YAML frontmatter + body to a Markdown string."""
    fm = yaml.dump(
        meta,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )
    return f"---\n{fm}---\n\n{body}"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_frontmatter_structured(
    meta: dict[str, Any],
    path: Path | None = None,
) -> list[ValidationIssue]:
    """Return structured ``ValidationIssue`` objects for a note's frontmatter.

    Validates:
    - Required fields by schema version.
    - Field types per the reject-vs-normalize policy.
    - Enum fields: kind, status.
    - Layer: warning if absent, error if invalid value.
    - List fields: must be list[str] only.
    - Confidence range: 0.0–1.0 when present.
    """
    # Import here to avoid top-level circular-import risk; note.py is stable.
    from agent_memory.note import ALL_READABLE_KINDS, VALID_LAYERS, VALID_STATUSES

    issues: list[ValidationIssue] = []
    version = meta.get("schema_version")
    schema_ver = int(version) if isinstance(version, (int, float)) else 1
    required = REQUIRED_FIELDS_V2 if schema_ver >= 2 else REQUIRED_FIELDS_V1

    # --- Required field presence ---
    for field in sorted(required):
        if field not in meta:
            issues.append(
                ValidationIssue(
                    path=path,
                    field=field,
                    code=CODE_MISSING_REQUIRED,
                    message=f"Missing required field '{field}'.",
                    severity="error",
                )
            )

    # --- Type checks for present fields ---
    _check_str(issues, meta, "id", path)
    _check_int(issues, meta, "schema_version", path)
    _check_str(issues, meta, "kind", path)
    _check_str(issues, meta, "project", path)
    _check_str(issues, meta, "created_at", path)
    _check_str(issues, meta, "created_by", path)
    if schema_ver >= 2:
        _check_str(issues, meta, "title", path)
        _check_str(issues, meta, "updated_at", path)
        _check_str(issues, meta, "updated_by", path)

    # tags must be list[str]
    if "tags" in meta:
        _check_list_of_str(issues, meta, "tags", path)

    # status: string + known value
    if "status" in meta:
        if not isinstance(meta["status"], str):
            issues.append(
                ValidationIssue(
                    path=path,
                    field="status",
                    code=CODE_WRONG_TYPE,
                    message=f"Field 'status' must be a string, got {type(meta['status']).__name__}.",
                    severity="error",
                )
            )
        elif meta["status"] not in VALID_STATUSES:
            issues.append(
                ValidationIssue(
                    path=path,
                    field="status",
                    code=CODE_UNKNOWN_STATUS,
                    message=f"Unknown status '{meta['status']}'. Valid: {sorted(VALID_STATUSES)}.",
                    severity="error",
                )
            )

    # layer: warning if absent, error if invalid value
    if "layer" not in meta:
        issues.append(
            ValidationIssue(
                path=path,
                field="layer",
                code=CODE_MISSING_LAYER,
                message="Optional field 'layer' is absent; defaulting to 'archival'.",
                severity="warning",
            )
        )
    elif not isinstance(meta["layer"], str):
        issues.append(
            ValidationIssue(
                path=path,
                field="layer",
                code=CODE_WRONG_TYPE,
                message=f"Field 'layer' must be a string, got {type(meta['layer']).__name__}.",
                severity="error",
            )
        )
    elif meta["layer"] not in VALID_LAYERS:
        issues.append(
            ValidationIssue(
                path=path,
                field="layer",
                code=CODE_INVALID_LAYER,
                message=f"Unknown layer '{meta['layer']}'. Valid: {sorted(VALID_LAYERS)}.",
                severity="error",
            )
        )

    # kind: string + known value (check after type check)
    if "kind" in meta and isinstance(meta["kind"], str) and meta["kind"] not in ALL_READABLE_KINDS:
        issues.append(
            ValidationIssue(
                path=path,
                field="kind",
                code=CODE_UNKNOWN_KIND,
                message=f"Unknown kind '{meta['kind']}'. Valid: {sorted(ALL_READABLE_KINDS)}.",
                severity="error",
            )
        )

    # review_required: must be bool (not int 0/1)
    if "review_required" in meta and not isinstance(meta["review_required"], bool):
        issues.append(
            ValidationIssue(
                path=path,
                field="review_required",
                code=CODE_WRONG_TYPE,
                message=(
                    f"Field 'review_required' must be a boolean, got {type(meta['review_required']).__name__}."
                ),
                severity="error",
            )
        )

    # confidence: float or int, 0.0–1.0
    if "confidence" in meta:
        conf = meta["confidence"]
        if not isinstance(conf, (int, float)) or isinstance(conf, bool):
            issues.append(
                ValidationIssue(
                    path=path,
                    field="confidence",
                    code=CODE_WRONG_TYPE,
                    message=f"Field 'confidence' must be a number, got {type(conf).__name__}.",
                    severity="error",
                )
            )
        elif not (0.0 <= float(conf) <= 1.0):
            issues.append(
                ValidationIssue(
                    path=path,
                    field="confidence",
                    code=CODE_CONFIDENCE_RANGE,
                    message=f"Field 'confidence' must be between 0.0 and 1.0, got {conf!r}.",
                    severity="error",
                )
            )

    # Relationship fields must be list[str].
    for rel_field in ("related", "supersedes", "superseded_by", "evidence_for", "files"):
        if rel_field in meta:
            _check_list_of_str(issues, meta, rel_field, path)

    return issues


def validate_frontmatter(meta: dict[str, Any]) -> list[str]:
    """Return validation error messages for a note's frontmatter.

    Backward-compatible wrapper over ``validate_frontmatter_structured()``.
    Returns only error-severity issues as plain strings.

    Chooses the required-field set based on ``schema_version`` in *meta*:
    - V1 notes (schema_version == 1 or absent): only V1 required fields.
    - V2 notes (schema_version == 2): V1 + V2 extra required fields.
    """
    return [i.message for i in validate_frontmatter_structured(meta) if i.severity == "error"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _check_str(
    issues: list[ValidationIssue],
    meta: dict[str, Any],
    field: str,
    path: Path | None,
) -> None:
    if field in meta and not isinstance(meta[field], str):
        issues.append(
            ValidationIssue(
                path=path,
                field=field,
                code=CODE_WRONG_TYPE,
                message=f"Field '{field}' must be a string, got {type(meta[field]).__name__}.",
                severity="error",
            )
        )


def _check_int(
    issues: list[ValidationIssue],
    meta: dict[str, Any],
    field: str,
    path: Path | None,
) -> None:
    if field in meta and not isinstance(meta[field], int):
        issues.append(
            ValidationIssue(
                path=path,
                field=field,
                code=CODE_WRONG_TYPE,
                message=f"Field '{field}' must be an integer, got {type(meta[field]).__name__}.",
                severity="error",
            )
        )


def _check_list_of_str(
    issues: list[ValidationIssue],
    meta: dict[str, Any],
    field: str,
    path: Path | None,
) -> None:
    value = meta[field]
    if not isinstance(value, list):
        issues.append(
            ValidationIssue(
                path=path,
                field=field,
                code=CODE_NON_LIST_FIELD,
                message=f"Field '{field}' must be a list, got {type(value).__name__}.",
                severity="error",
            )
        )
        return
    bad = [item for item in value if not isinstance(item, str)]
    if bad:
        issues.append(
            ValidationIssue(
                path=path,
                field=field,
                code=CODE_MIXED_TYPE_LIST,
                message=(
                    f"Field '{field}' must be a list of strings; "
                    f"found non-string item(s): {bad[:3]!r}."
                ),
                severity="error",
            )
        )
