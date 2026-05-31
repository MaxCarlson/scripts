from __future__ import annotations
from pathlib import Path
from agent_memory.index import NoteIndex


def test_upsert_and_get(tmp_path: Path) -> None:
    idx = NoteIndex(tmp_path / ".index" / "notes.sqlite3")
    idx.upsert(
        note_id="20260531T000000Z_aabbccdd",
        path="/notes/projects/proj/decision/20260531T000000Z_aabbccdd_test.md",
        project="proj",
        kind="decision",
        title="Test note",
        body="# Test note\n\nBody text.",
        created_at="2026-05-31T00:00:00Z",
        created_by="claude-code",
        tags=["sqlite", "memory"],
        full_content="---\nid: 20260531T000000Z_aabbccdd\n---\n\n# Test note\n\nBody text.",
    )
    record = idx.get("20260531T000000Z_aabbccdd")
    assert record is not None
    assert record["title"] == "Test note"
    assert record["kind"] == "decision"
    assert "sqlite" in record["tags"]


def test_upsert_updates_existing(tmp_path: Path) -> None:
    idx = NoteIndex(tmp_path / ".index" / "notes.sqlite3")
    _upsert_helper(idx, note_id="id1", title="Original")
    _upsert_helper(idx, note_id="id1", title="Updated")
    record = idx.get("id1")
    assert record["title"] == "Updated"


def test_delete_removes_record(tmp_path: Path) -> None:
    idx = NoteIndex(tmp_path / ".index" / "notes.sqlite3")
    _upsert_helper(idx, note_id="id1")
    idx.delete("id1")
    assert idx.get("id1") is None


def test_list_notes_by_project(tmp_path: Path) -> None:
    idx = NoteIndex(tmp_path / ".index" / "notes.sqlite3")
    _upsert_helper(idx, note_id="id1", project="proj-a")
    _upsert_helper(idx, note_id="id2", project="proj-b")
    records = idx.list_notes(project="proj-a")
    assert len(records) == 1
    assert records[0]["project"] == "proj-a"


def test_list_notes_by_kind(tmp_path: Path) -> None:
    idx = NoteIndex(tmp_path / ".index" / "notes.sqlite3")
    _upsert_helper(idx, note_id="id1", kind="decision")
    _upsert_helper(idx, note_id="id2", kind="bug")
    records = idx.list_notes(kind="decision")
    assert len(records) == 1
    assert records[0]["kind"] == "decision"


def test_list_notes_by_tags(tmp_path: Path) -> None:
    idx = NoteIndex(tmp_path / ".index" / "notes.sqlite3")
    _upsert_helper(idx, note_id="id1", tags=["sqlite", "memory"])
    _upsert_helper(idx, note_id="id2", tags=["python"])
    records = idx.list_notes(tags=["sqlite"])
    assert len(records) == 1


def test_search_finds_by_title(tmp_path: Path) -> None:
    idx = NoteIndex(tmp_path / ".index" / "notes.sqlite3")
    _upsert_helper(idx, note_id="id1", title="Use SQLite for storage")
    _upsert_helper(idx, note_id="id2", title="Python packaging guide")
    results = idx.search("SQLite")
    assert len(results) == 1
    assert results[0]["title"] == "Use SQLite for storage"


def test_all_records_returns_id_path_hash(tmp_path: Path) -> None:
    idx = NoteIndex(tmp_path / ".index" / "notes.sqlite3")
    _upsert_helper(idx, note_id="id1")
    records = idx.all_records()
    assert len(records) == 1
    assert "id" in records[0] and "path" in records[0] and "content_hash" in records[0]


def _upsert_helper(
    idx: NoteIndex,
    *,
    note_id: str = "20260531T000000Z_aabbccdd",
    path: str | None = None,
    project: str = "proj",
    kind: str = "decision",
    title: str = "Test note",
    tags: list[str] | None = None,
) -> None:
    if path is None:
        path = f"/notes/{note_id}.md"
    idx.upsert(
        note_id=note_id,
        path=path,
        project=project,
        kind=kind,
        title=title,
        body="# Test\n\nBody.",
        created_at="2026-05-31T00:00:00Z",
        created_by="test",
        tags=tags or ["tag1"],
        full_content=f"---\nid: {note_id}\n---\n\n# Test\n\nBody.",
    )
