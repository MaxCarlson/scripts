from __future__ import annotations
from agent_memory.frontmatter import (
    CURRENT_SCHEMA_VERSION,
    REQUIRED_FIELDS,
    REQUIRED_FIELDS_V1,
    REQUIRED_FIELDS_V2,
    REQUIRED_FIELDS_V2_EXTRA,
    parse_frontmatter,
    validate_frontmatter,
    write_frontmatter,
)


_SAMPLE_V1 = """\
---
id: 20260531T000000Z_aabbccdd
schema_version: 1
kind: decision
project: my-project
created_at: 2026-05-31T00:00:00Z
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
created_at: 2026-05-31T00:00:00Z
created_by: claude-code
updated_at: 2026-05-31T01:00:00Z
updated_by: claude-code
status: active
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


# --- validate_frontmatter ---

def test_validate_v1_valid() -> None:
    meta, _ = parse_frontmatter(_SAMPLE_V1)
    errors = validate_frontmatter(meta)
    assert errors == []


def test_validate_v1_missing_field() -> None:
    meta, _ = parse_frontmatter(_SAMPLE_V1)
    del meta["kind"]
    errors = validate_frontmatter(meta)
    assert any("kind" in e for e in errors)


def test_validate_v1_missing_all_fields() -> None:
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
        "tags": [],
        "review_required": True,
    }
    output = write_frontmatter(meta, "Body.")
    meta2, _ = parse_frontmatter(output)
    assert meta2["review_required"] is True
    assert isinstance(meta2["review_required"], bool)
