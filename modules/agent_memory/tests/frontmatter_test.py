from __future__ import annotations
from agent_memory.frontmatter import parse_frontmatter, write_frontmatter, validate_frontmatter


_SAMPLE = """\
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


def test_parse_frontmatter_extracts_metadata() -> None:
    meta, body = parse_frontmatter(_SAMPLE)
    assert meta["id"] == "20260531T000000Z_aabbccdd"
    assert meta["kind"] == "decision"
    assert meta["tags"] == ["sqlite", "memory"]


def test_parse_frontmatter_extracts_body() -> None:
    meta, body = parse_frontmatter(_SAMPLE)
    assert "# Use SQLite" in body
    assert "Some body text." in body


def test_parse_frontmatter_no_frontmatter() -> None:
    meta, body = parse_frontmatter("# Just a title\n\nNo frontmatter.")
    assert meta == {}
    assert "Just a title" in body


def test_write_frontmatter_roundtrip() -> None:
    meta, body = parse_frontmatter(_SAMPLE)
    output = write_frontmatter(meta, body)
    meta2, body2 = parse_frontmatter(output)
    assert meta2["id"] == meta["id"]
    assert meta2["tags"] == meta["tags"]
    assert "# Use SQLite" in body2


def test_validate_frontmatter_valid() -> None:
    meta, _ = parse_frontmatter(_SAMPLE)
    errors = validate_frontmatter(meta)
    assert errors == []


def test_validate_frontmatter_missing_field() -> None:
    meta, _ = parse_frontmatter(_SAMPLE)
    del meta["kind"]
    errors = validate_frontmatter(meta)
    assert any("kind" in e for e in errors)


def test_validate_frontmatter_missing_all_fields() -> None:
    errors = validate_frontmatter({})
    assert len(errors) == 7   # all 7 required fields missing
