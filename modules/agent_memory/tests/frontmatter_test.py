from __future__ import annotations


from agent_memory.frontmatter import (
    CODE_CONFIDENCE_RANGE,
    CODE_INVALID_LAYER,
    CODE_MISSING_CLOSING_DELIMITER,
    CODE_MISSING_LAYER,
    CODE_MISSING_REQUIRED,
    CODE_MIXED_TYPE_LIST,
    CODE_NO_FRONTMATTER,
    CODE_NON_LIST_FIELD,
    CODE_UNKNOWN_KIND,
    CODE_UNKNOWN_STATUS,
    CODE_WRONG_TYPE,
    CODE_YAML_PARSE_ERROR,
    CURRENT_SCHEMA_VERSION,
    FrontmatterParseResult,
    REQUIRED_FIELDS,
    REQUIRED_FIELDS_V1,
    REQUIRED_FIELDS_V2,
    REQUIRED_FIELDS_V2_EXTRA,
    ValidationIssue,
    parse_frontmatter,
    parse_frontmatter_safe,
    validate_frontmatter,
    validate_frontmatter_structured,
    write_frontmatter,
)


# Fixtures use yaml.dump-style quoted dates so PyYAML round-trips them as strings.
_SAMPLE_V1 = """\
---
id: 20260531T000000Z_aabbccdd
schema_version: 1
kind: decision
project: my-project
created_at: '2026-05-31T00:00:00Z'
created_by: claude-code
tags:
  - sqlite
  - memory
---

# Use SQLite

## Summary

Some body text.
"""

_SAMPLE_V2 = """\
---
id: 20260531T000000Z_v2note
schema_version: 2
kind: environment
project: global
title: Use Python 3.11
created_at: '2026-05-31T00:00:00Z'
created_by: claude-code
updated_at: '2026-05-31T01:00:00Z'
updated_by: claude-code
status: active
layer: core
tags:
  - python
---

# Use Python 3.11

Python 3.11 is the minimum required version.
"""


def test_current_schema_version_is_2() -> None:
    assert CURRENT_SCHEMA_VERSION == 2


def test_required_fields_backward_compat() -> None:
    # REQUIRED_FIELDS alias still points to V1 set.
    assert REQUIRED_FIELDS == REQUIRED_FIELDS_V1


def test_v2_required_fields_is_superset_of_v1() -> None:
    assert REQUIRED_FIELDS_V1.issubset(REQUIRED_FIELDS_V2)
    assert REQUIRED_FIELDS_V2_EXTRA <= REQUIRED_FIELDS_V2


# --- parse / write ---

def test_parse_frontmatter_extracts_metadata() -> None:
    meta, body = parse_frontmatter(_SAMPLE_V1)
    assert meta["id"] == "20260531T000000Z_aabbccdd"
    assert meta["kind"] == "decision"
    assert meta["tags"] == ["sqlite", "memory"]


def test_parse_frontmatter_extracts_body() -> None:
    meta, body = parse_frontmatter(_SAMPLE_V1)
    assert "# Use SQLite" in body
    assert "Some body text." in body


def test_parse_frontmatter_no_frontmatter() -> None:
    meta, body = parse_frontmatter("# Just a title\n\nNo frontmatter.")
    assert meta == {}
    assert "Just a title" in body


def test_parse_frontmatter_strips_bom() -> None:
    bom_text = "\ufeff" + _SAMPLE_V1
    meta, body = parse_frontmatter(bom_text)
    assert meta["id"] == "20260531T000000Z_aabbccdd"


def test_write_frontmatter_roundtrip_v1() -> None:
    meta, body = parse_frontmatter(_SAMPLE_V1)
    output = write_frontmatter(meta, body)
    meta2, body2 = parse_frontmatter(output)
    assert meta2["id"] == meta["id"]
    assert meta2["tags"] == meta["tags"]
    assert "# Use SQLite" in body2


def test_write_frontmatter_roundtrip_v2() -> None:
    meta, body = parse_frontmatter(_SAMPLE_V2)
    output = write_frontmatter(meta, body)
    meta2, body2 = parse_frontmatter(output)
    assert meta2["schema_version"] == 2
    assert meta2["title"] == "Use Python 3.11"
    assert meta2["status"] == "active"
    assert "# Use Python 3.11" in body2


# --- validate_frontmatter (backward-compat strings) ---

def test_validate_v1_valid() -> None:
    meta, _ = parse_frontmatter(_SAMPLE_V1)
    # V1 note with all required fields and correct types → no errors.
    errors = validate_frontmatter(meta)
    assert errors == []


def test_validate_v1_missing_field() -> None:
    meta, _ = parse_frontmatter(_SAMPLE_V1)
    del meta["kind"]
    errors = validate_frontmatter(meta)
    assert any("kind" in e for e in errors)


def test_validate_v1_missing_all_fields() -> None:
    # No type errors possible when no fields present; warnings excluded.
    errors = validate_frontmatter({})
    assert len(errors) == len(REQUIRED_FIELDS_V1)


def test_validate_v2_valid() -> None:
    meta, _ = parse_frontmatter(_SAMPLE_V2)
    errors = validate_frontmatter(meta)
    assert errors == []


def test_validate_v2_missing_extra_field() -> None:
    meta, _ = parse_frontmatter(_SAMPLE_V2)
    del meta["updated_at"]
    errors = validate_frontmatter(meta)
    assert any("updated_at" in e for e in errors)


def test_validate_v2_missing_all_fields() -> None:
    errors = validate_frontmatter({"schema_version": 2})
    assert len(errors) == len(REQUIRED_FIELDS_V2) - 1  # schema_version present


def test_validate_v1_note_does_not_require_v2_fields() -> None:
    """A V1 note must not fail for missing title/updated_at/etc."""
    meta, _ = parse_frontmatter(_SAMPLE_V1)
    assert "title" not in meta
    errors = validate_frontmatter(meta)
    assert errors == []


# --- validate_frontmatter_structured (typed issues) ---

def test_structured_validation_issue_type() -> None:
    issues = validate_frontmatter_structured({})
    assert all(isinstance(i, ValidationIssue) for i in issues)


def test_structured_validation_missing_required_has_code() -> None:
    issues = validate_frontmatter_structured({})
    codes = {i.code for i in issues}
    assert CODE_MISSING_REQUIRED in codes


def test_structured_validation_missing_layer_is_warning() -> None:
    meta, _ = parse_frontmatter(_SAMPLE_V1)
    issues = validate_frontmatter_structured(meta)
    layer_issues = [i for i in issues if i.code == CODE_MISSING_LAYER]
    assert layer_issues
    assert all(i.severity == "warning" for i in layer_issues)


def test_structured_validation_v2_valid_no_errors() -> None:
    meta, _ = parse_frontmatter(_SAMPLE_V2)
    errors = [i for i in validate_frontmatter_structured(meta) if i.severity == "error"]
    assert errors == []


def test_scalar_id_produces_wrong_type_error() -> None:
    """YAML numeric ID (e.g. 12345) must produce WRONG_TYPE error, not silent coercion."""
    meta = {
        "id": 12345,  # YAML parses bare integer as int
        "schema_version": 1,
        "kind": "decision",
        "project": "global",
        "created_at": "2026-01-01T00:00:00Z",
        "created_by": "test",
        "tags": [],
    }
    issues = validate_frontmatter_structured(meta)
    codes = {i.code for i in issues}
    assert CODE_WRONG_TYPE in codes
    assert any(i.field == "id" for i in issues if i.code == CODE_WRONG_TYPE)


def test_bool_kind_produces_wrong_type_error() -> None:
    """YAML 'yes'/'no' parsed as bool for kind field must produce WRONG_TYPE."""
    meta = {
        "id": "abc123",
        "schema_version": 1,
        "kind": True,  # YAML 'yes' → bool True
        "project": "global",
        "created_at": "2026-01-01T00:00:00Z",
        "created_by": "test",
        "tags": [],
    }
    issues = validate_frontmatter_structured(meta)
    codes = {i.code for i in issues}
    assert CODE_WRONG_TYPE in codes
    assert any(i.field == "kind" for i in issues if i.code == CODE_WRONG_TYPE)


def test_scalar_tags_produces_non_list_error() -> None:
    """tags: plain-string instead of list must produce NON_LIST_FIELD error."""
    meta = {
        "id": "abc123",
        "schema_version": 1,
        "kind": "decision",
        "project": "global",
        "created_at": "2026-01-01T00:00:00Z",
        "created_by": "test",
        "tags": "scalar-tag",  # scalar instead of list
    }
    issues = validate_frontmatter_structured(meta)
    codes = {i.code for i in issues}
    assert CODE_NON_LIST_FIELD in codes
    assert any(i.field == "tags" for i in issues if i.code == CODE_NON_LIST_FIELD)


def test_mixed_type_tags_list_produces_error() -> None:
    meta = {
        "id": "abc123",
        "schema_version": 1,
        "kind": "decision",
        "project": "global",
        "created_at": "2026-01-01T00:00:00Z",
        "created_by": "test",
        "tags": ["ok-tag", 42, None],
    }
    issues = validate_frontmatter_structured(meta)
    assert any(i.code == CODE_MIXED_TYPE_LIST and i.field == "tags" for i in issues)


def test_unknown_kind_produces_error() -> None:
    meta = {
        "id": "abc",
        "schema_version": 1,
        "kind": "totally-unknown",
        "project": "global",
        "created_at": "2026-01-01T00:00:00Z",
        "created_by": "test",
        "tags": [],
    }
    issues = validate_frontmatter_structured(meta)
    assert any(i.code == CODE_UNKNOWN_KIND for i in issues)


def test_unknown_status_produces_error() -> None:
    meta, _ = parse_frontmatter(_SAMPLE_V2)
    meta["status"] = "deleted"
    issues = validate_frontmatter_structured(meta)
    assert any(i.code == CODE_UNKNOWN_STATUS for i in issues)


def test_invalid_layer_produces_error() -> None:
    meta, _ = parse_frontmatter(_SAMPLE_V2)
    meta["layer"] = "not-a-layer"
    issues = validate_frontmatter_structured(meta)
    assert any(i.code == CODE_INVALID_LAYER for i in issues)


def test_confidence_out_of_range_produces_error() -> None:
    meta, _ = parse_frontmatter(_SAMPLE_V2)
    meta["confidence"] = 1.5
    issues = validate_frontmatter_structured(meta)
    assert any(i.code == CODE_CONFIDENCE_RANGE for i in issues)


def test_confidence_wrong_type_produces_error() -> None:
    meta, _ = parse_frontmatter(_SAMPLE_V2)
    meta["confidence"] = "high"
    issues = validate_frontmatter_structured(meta)
    assert any(i.code == CODE_WRONG_TYPE and i.field == "confidence" for i in issues)


def test_scalar_relationship_field_produces_error() -> None:
    meta, _ = parse_frontmatter(_SAMPLE_V2)
    meta["related"] = "some-id"  # scalar, not list
    issues = validate_frontmatter_structured(meta)
    assert any(i.code == CODE_NON_LIST_FIELD and i.field == "related" for i in issues)


# --- parse_frontmatter_safe ---

def test_safe_parse_valid_v1_returns_result() -> None:
    result = parse_frontmatter_safe(_SAMPLE_V1)
    assert isinstance(result, FrontmatterParseResult)
    assert result.has_frontmatter is True
    assert result.metadata["id"] == "20260531T000000Z_aabbccdd"
    assert "# Use SQLite" in result.body


def test_safe_parse_valid_v2_no_errors() -> None:
    result = parse_frontmatter_safe(_SAMPLE_V2)
    errors = [i for i in result.issues if i.severity == "error"]
    assert errors == []


def test_safe_parse_no_frontmatter_returns_structured_issue() -> None:
    result = parse_frontmatter_safe("# Just a title\n\nNo frontmatter.")
    assert result.has_frontmatter is False
    assert result.metadata == {}
    assert "Just a title" in result.body
    assert any(i.code == CODE_NO_FRONTMATTER for i in result.issues)


def test_safe_parse_missing_closing_delimiter() -> None:
    text = "---\nid: abc\nkind: decision\n# No closing delimiter\n\nBody here."
    result = parse_frontmatter_safe(text)
    assert result.has_frontmatter is True
    assert any(i.code == CODE_MISSING_CLOSING_DELIMITER for i in result.issues)
    assert "Body here." in result.body


def test_safe_parse_malformed_yaml_preserves_body() -> None:
    text = "---\n: invalid: yaml: {unclosed\n---\n\nBody text preserved."
    result = parse_frontmatter_safe(text)
    assert result.has_frontmatter is True
    assert any(i.code == CODE_YAML_PARSE_ERROR for i in result.issues)
    assert "Body text preserved." in result.body
    assert result.metadata == {}


def test_safe_parse_bom_prefixed_file_parses_correctly() -> None:
    bom_text = "\ufeff" + _SAMPLE_V1
    result = parse_frontmatter_safe(bom_text)
    assert result.has_frontmatter is True
    assert result.metadata["id"] == "20260531T000000Z_aabbccdd"
    # BOM should not produce errors.
    assert not any(i.code == CODE_YAML_PARSE_ERROR for i in result.issues)


def test_safe_parse_preserves_raw_frontmatter() -> None:
    result = parse_frontmatter_safe(_SAMPLE_V1)
    assert result.raw_frontmatter is not None
    assert "id:" in result.raw_frontmatter


def test_safe_parse_yaml_document_marker_in_body() -> None:
    """YAML document markers inside body text should not disrupt the parse."""
    text = _SAMPLE_V1 + "\n---\nThis is a line in the body starting with ---.\n"
    result = parse_frontmatter_safe(text)
    assert result.has_frontmatter is True
    assert result.metadata["id"] == "20260531T000000Z_aabbccdd"


def test_safe_parse_with_path_sets_path_on_issues() -> None:
    from pathlib import Path

    result = parse_frontmatter_safe("# No frontmatter", path=Path("/tmp/test.md"))
    assert result.issues
    assert all(str(i.path) == "/tmp/test.md" for i in result.issues)


# --- relationship fields as lists ---

def test_relationship_fields_serialize_as_lists() -> None:
    meta = {
        "id": "abc",
        "schema_version": 2,
        "kind": "reflection",
        "project": "global",
        "title": "Test",
        "created_at": "2026-05-31T00:00:00Z",
        "created_by": "test",
        "updated_at": "2026-05-31T00:00:00Z",
        "updated_by": "test",
        "status": "active",
        "layer": "reflective",
        "tags": [],
        "related": ["id-1", "id-2"],
        "supersedes": ["old-id"],
        "superseded_by": [],
        "evidence_for": ["dec-id"],
        "files": ["src/foo.py"],
    }
    output = write_frontmatter(meta, "Body.")
    meta2, _ = parse_frontmatter(output)
    assert isinstance(meta2["related"], list)
    assert meta2["related"] == ["id-1", "id-2"]
    assert meta2["supersedes"] == ["old-id"]
    assert meta2["superseded_by"] == []
    assert meta2["evidence_for"] == ["dec-id"]
    assert meta2["files"] == ["src/foo.py"]


def test_review_required_serializes_as_bool() -> None:
    meta = {
        "id": "abc",
        "schema_version": 2,
        "kind": "decision",
        "project": "global",
        "title": "Test",
        "created_at": "2026-05-31T00:00:00Z",
        "created_by": "test",
        "updated_at": "2026-05-31T00:00:00Z",
        "updated_by": "test",
        "status": "active",
        "layer": "working",
        "tags": [],
        "review_required": True,
    }
    output = write_frontmatter(meta, "Body.")
    meta2, _ = parse_frontmatter(output)
    assert meta2["review_required"] is True
    assert isinstance(meta2["review_required"], bool)
