# tests/store_test.py
from __future__ import annotations
from pathlib import Path
import pytest
from agent_memory.store import NoteStore


def test_create_note_writes_file(tmp_path: Path) -> None:
    store = NoteStore(root=tmp_path)
    note = store.create_note(
        kind="decision",
        project="my-project",
        title="Use SQLite",
        body="## Summary\n\nUse SQLite.",
        created_by="claude-code",
        tags=["sqlite"],
    )
    assert note.path.exists()
    assert note.id != ""
    assert note.kind == "decision"
    assert note.project == "my-project"


def test_create_note_path_matches_kind_and_project(tmp_path: Path) -> None:
    store = NoteStore(root=tmp_path)
    note = store.create_note(
        kind="decision",
        project="my-project",
        title="Test",
        body="Body.",
        created_by="test",
    )
    assert "my-project" in str(note.path)
    assert "decision" in str(note.path)


def test_create_note_global_project(tmp_path: Path) -> None:
    store = NoteStore(root=tmp_path)
    note = store.create_note(
        kind="preference",
        project=None,
        title="Always use pathlib",
        body="Use pathlib.Path everywhere.",
        created_by="test",
    )
    assert note.project == "global"
    assert "global" in str(note.path)


def test_create_note_project_required_kind_raises(tmp_path: Path) -> None:
    store = NoteStore(root=tmp_path)
    with pytest.raises(ValueError, match="requires an explicit"):
        store.create_note(
            kind="handoff",
            project=None,
            title="Handoff note",
            body="Body.",
            created_by="test",
        )


def test_create_note_invalid_kind_raises(tmp_path: Path) -> None:
    store = NoteStore(root=tmp_path)
    with pytest.raises(ValueError, match="Invalid kind"):
        store.create_note(
            kind="bogus",
            project="proj",
            title="Test",
            body="Body.",
            created_by="test",
        )


def test_create_note_dry_run_does_not_write(tmp_path: Path) -> None:
    store = NoteStore(root=tmp_path)
    note = store.create_note(
        kind="decision",
        project="proj",
        title="Dry run test",
        body="Body.",
        created_by="test",
        dry_run=True,
    )
    assert note.id != ""
    # No file written
    assert not (tmp_path / "projects").exists()


def test_create_note_file_has_valid_frontmatter(tmp_path: Path) -> None:
    store = NoteStore(root=tmp_path)
    note = store.create_note(
        kind="bug",
        project="proj",
        title="Repro steps",
        body="Steps here.",
        created_by="test",
        tags=["repro"],
    )
    from agent_memory.frontmatter import parse_frontmatter, validate_frontmatter
    text = note.path.read_text(encoding="utf-8")
    meta, _ = parse_frontmatter(text)
    errors = validate_frontmatter(meta)
    assert errors == []
    assert meta["kind"] == "bug"
    assert meta["tags"] == ["repro"]
