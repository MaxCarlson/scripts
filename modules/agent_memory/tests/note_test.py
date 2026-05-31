# tests/note_test.py
from __future__ import annotations
from pathlib import Path
from agent_memory.note import (
    Note, VALID_KINDS, GLOBAL_DEFAULT_KINDS,
    PROJECT_REQUIRED_KINDS, LLM_CLASSIFY_KINDS,
)


def test_note_dataclass_fields() -> None:
    note = Note(
        id="20260531T000000Z_aabbccdd",
        path=Path("/tmp/test.md"),
        kind="decision",
        project="my-project",
        title="Test note",
        body="# Test note\n\nBody text.",
        created_at="2026-05-31T00:00:00Z",
        created_by="claude-code",
        tags=["a", "b"],
    )
    assert note.schema_version == 1
    assert note.tags == ["a", "b"]


def test_valid_kinds_contains_all_expected() -> None:
    for k in ("constraint", "preference", "decision", "code_note",
              "handoff", "task", "bug", "session"):
        assert k in VALID_KINDS


def test_kind_sets_are_disjoint() -> None:
    assert GLOBAL_DEFAULT_KINDS.isdisjoint(PROJECT_REQUIRED_KINDS)
    assert GLOBAL_DEFAULT_KINDS.isdisjoint(LLM_CLASSIFY_KINDS)
    assert PROJECT_REQUIRED_KINDS.isdisjoint(LLM_CLASSIFY_KINDS)


def test_all_kinds_covered_by_one_set() -> None:
    covered = GLOBAL_DEFAULT_KINDS | PROJECT_REQUIRED_KINDS | LLM_CLASSIFY_KINDS
    assert covered == VALID_KINDS
