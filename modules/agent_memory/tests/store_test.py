# tests/store_test.py
from __future__ import annotations
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_memory.classify import PlacementError
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
    with pytest.raises(ValueError, match="requires a project"):
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


def test_get_note_returns_note(tmp_path: Path) -> None:
    store = NoteStore(root=tmp_path)
    note = store.create_note(
        kind="preference",
        project=None,
        title="Use pathlib",
        body="Always use pathlib.Path.",
        created_by="test",
    )
    fetched = store.get_note(note.id)
    assert fetched is not None
    assert fetched.id == note.id


def test_get_note_returns_none_for_missing(tmp_path: Path) -> None:
    store = NoteStore(root=tmp_path)
    result = store.get_note("nonexistent_id")
    assert result is None


def test_list_notes_returns_all(tmp_path: Path) -> None:
    store = NoteStore(root=tmp_path)
    store.create_note(
        kind="constraint",
        project=None,
        title="Constraint note",
        body="Body.",
        created_by="test",
    )
    store.create_note(
        kind="preference",
        project=None,
        title="Preference note",
        body="Body.",
        created_by="test",
    )
    notes = store.list_notes()
    assert len(notes) == 2


def test_list_notes_filters_by_kind(tmp_path: Path) -> None:
    store = NoteStore(root=tmp_path)
    store.create_note(
        kind="constraint",
        project=None,
        title="Constraint one",
        body="Body.",
        created_by="test",
    )
    store.create_note(
        kind="constraint",
        project=None,
        title="Constraint two",
        body="Body.",
        created_by="test",
    )
    store.create_note(
        kind="preference",
        project=None,
        title="Preference note",
        body="Body.",
        created_by="test",
    )
    notes = store.list_notes(kind="constraint")
    assert len(notes) == 2


def test_search_finds_by_title_keyword(tmp_path: Path) -> None:
    store = NoteStore(root=tmp_path)
    note = store.create_note(
        kind="preference",
        project=None,
        title="unique_search_term_xyz",
        body="Body.",
        created_by="test",
    )
    results = store.search("unique_search_term_xyz")
    assert any(n.id == note.id for n in results)


def test_rebuild_index_reindexes_all_files(tmp_path: Path) -> None:
    store = NoteStore(root=tmp_path)
    store.create_note(
        kind="constraint",
        project=None,
        title="Note one",
        body="Body.",
        created_by="test",
    )
    store.create_note(
        kind="preference",
        project=None,
        title="Note two",
        body="Body.",
        created_by="test",
    )
    # Delete the SQLite index so a fresh store starts empty
    db_path = tmp_path / ".index" / "notes.sqlite3"
    db_path.unlink(missing_ok=True)
    fresh_store = NoteStore(root=tmp_path)
    count = fresh_store.rebuild_index()
    assert count == 2


def test_verify_returns_empty_for_valid_notes(tmp_path: Path) -> None:
    store = NoteStore(root=tmp_path)
    store.create_note(
        kind="constraint",
        project=None,
        title="Valid note one",
        body="Body.",
        created_by="test",
    )
    store.create_note(
        kind="preference",
        project=None,
        title="Valid note two",
        body="Body.",
        created_by="test",
    )
    errors = store.verify()
    assert errors == []


def test_verify_flags_kind_mismatch(tmp_path: Path) -> None:
    store = NoteStore(root=tmp_path)
    note = store.create_note(
        kind="preference",
        project=None,
        title="Mismatch test",
        body="Body.",
        created_by="test",
    )
    # Corrupt the frontmatter kind field in the file
    text = note.path.read_text(encoding="utf-8")
    corrupted = text.replace("kind: preference", "kind: invalid_kind", 1)
    assert "kind: invalid_kind" in corrupted  # guard: replace must have matched
    note.path.write_text(corrupted, encoding="utf-8")
    errors = store.verify()
    assert len(errors) == 1
    assert "invalid_kind" in errors[0]


def test_create_note_auto_classify_calls_determine_project(tmp_path: Path) -> None:
    store = NoteStore(root=tmp_path)
    with patch("agent_memory.store.determine_project", return_value="global") as mock_classify:
        note = store.create_note(
            kind="decision",
            project=None,
            title="Auto classify me",
            body="## Summary\n\nDetails.",
            created_by="test",
            auto_classify=True,
        )
    mock_classify.assert_called_once()
    assert note.project == "global"


def test_create_note_no_auto_classify_passes_false_to_determine_project(tmp_path: Path) -> None:
    store = NoteStore(root=tmp_path)
    with patch("agent_memory.store.determine_project", return_value="global") as mock_classify:
        note = store.create_note(
            kind="decision",
            project=None,
            title="No classify",
            body="## Summary\n\nContent.",
            created_by="test",
            auto_classify=False,
        )
    call_kwargs = mock_classify.call_args.kwargs
    assert call_kwargs["auto_classify"] is False
    assert note.project == "global"


def test_create_note_project_required_kind_raises_placement_error(tmp_path: Path) -> None:
    store = NoteStore(root=tmp_path)
    with pytest.raises(PlacementError):
        store.create_note(
            kind="handoff",
            project=None,
            title="Missing project",
            body="",
            created_by="test",
        )
