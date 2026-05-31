# tests/note_test.py
from __future__ import annotations
from pathlib import Path
from agent_memory.note import (
    ACTIVE_KINDS,
    ALL_READABLE_KINDS,
    DEFAULT_LAYER_BY_KIND,
    DEFAULT_STATUS,
    DEPRECATED_KINDS,
    GLOBAL_DEFAULT_KINDS,
    LLM_CLASSIFY_KINDS,
    PROJECT_REQUIRED_KINDS,
    VALID_KINDS,
    VALID_LAYERS,
    VALID_STATUSES,
    Note,
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
    # V2 defaults
    assert note.status == DEFAULT_STATUS
    assert note.review_required is False
    assert note.related == []
    assert note.supersedes == []
    assert note.superseded_by == []
    assert note.evidence_for == []
    assert note.files == []


def test_note_v2_fields_roundtrip() -> None:
    note = Note(
        id="20260531T000000Z_aabbccdd",
        path=Path("/tmp/test.md"),
        kind="reflection",
        project="global",
        title="V2 note",
        body="# V2 note\n\nBody.",
        created_at="2026-05-31T00:00:00Z",
        created_by="claude-code",
        tags=[],
        schema_version=2,
        updated_at="2026-05-31T01:00:00Z",
        updated_by="claude-code",
        status="active",
        layer="reflective",
        source_agent="gemini",
        session_id="sess-abc",
        confidence=0.9,
        review_required=True,
        related=["note-id-1"],
        supersedes=["old-note-id"],
        superseded_by=[],
        evidence_for=["decision-id-1"],
        files=["src/foo.py"],
    )
    assert note.schema_version == 2
    assert note.status == "active"
    assert note.layer == "reflective"
    assert note.source_agent == "gemini"
    assert note.confidence == 0.9
    assert note.review_required is True
    assert note.related == ["note-id-1"]
    assert note.supersedes == ["old-note-id"]
    assert note.evidence_for == ["decision-id-1"]
    assert note.files == ["src/foo.py"]


# --- Kind taxonomy ---

def test_active_kinds_contains_all_expected() -> None:
    for k in (
        "constraint", "preference", "decision", "code_note",
        "handoff", "bug", "environment", "procedure", "evidence",
        "task_state", "task_lesson", "reflection",
    ):
        assert k in ACTIVE_KINDS, f"Expected '{k}' in ACTIVE_KINDS"


def test_deprecated_kinds_contains_expected() -> None:
    assert "task" in DEPRECATED_KINDS
    assert "session" in DEPRECATED_KINDS


def test_all_readable_kinds_is_union() -> None:
    assert ALL_READABLE_KINDS == ACTIVE_KINDS | DEPRECATED_KINDS


def test_valid_kinds_equals_all_readable() -> None:
    assert VALID_KINDS == ALL_READABLE_KINDS


def test_deprecated_kinds_not_in_active() -> None:
    assert ACTIVE_KINDS.isdisjoint(DEPRECATED_KINDS)


# --- Placement policy sets (active kinds only) ---

def test_kind_sets_are_disjoint() -> None:
    assert GLOBAL_DEFAULT_KINDS.isdisjoint(PROJECT_REQUIRED_KINDS)
    assert GLOBAL_DEFAULT_KINDS.isdisjoint(LLM_CLASSIFY_KINDS)
    assert PROJECT_REQUIRED_KINDS.isdisjoint(LLM_CLASSIFY_KINDS)


def test_active_kinds_covered_by_placement_policy() -> None:
    """Every active kind has exactly one placement policy."""
    covered = GLOBAL_DEFAULT_KINDS | PROJECT_REQUIRED_KINDS | LLM_CLASSIFY_KINDS
    assert covered == ACTIVE_KINDS


def test_deprecated_kinds_not_in_placement_sets() -> None:
    for k in DEPRECATED_KINDS:
        assert k not in GLOBAL_DEFAULT_KINDS
        assert k not in PROJECT_REQUIRED_KINDS
        assert k not in LLM_CLASSIFY_KINDS


# --- Status ---

def test_valid_statuses_contains_expected() -> None:
    for s in ("active", "superseded", "archived", "draft"):
        assert s in VALID_STATUSES


def test_default_status_is_active() -> None:
    assert DEFAULT_STATUS == "active"


# --- Layer ---

def test_valid_layers_contains_expected() -> None:
    for layer in ("core", "working", "archival", "reflective"):
        assert layer in VALID_LAYERS


def test_all_active_kinds_have_default_layer() -> None:
    for kind in ACTIVE_KINDS:
        assert kind in DEFAULT_LAYER_BY_KIND, f"Kind '{kind}' missing from DEFAULT_LAYER_BY_KIND"
        assert DEFAULT_LAYER_BY_KIND[kind] in VALID_LAYERS


def test_deprecated_kinds_have_default_layer() -> None:
    for kind in DEPRECATED_KINDS:
        assert kind in DEFAULT_LAYER_BY_KIND, f"Deprecated kind '{kind}' missing from DEFAULT_LAYER_BY_KIND"
