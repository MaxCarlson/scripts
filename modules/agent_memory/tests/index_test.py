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


# ---------------------------------------------------------------------------
# V2 schema / metadata tests
# ---------------------------------------------------------------------------

def test_index_has_v2_columns(tmp_path: Path) -> None:
    idx = NoteIndex(tmp_path / ".index" / "notes.sqlite3")
    record = idx._conn.execute("PRAGMA table_info(notes)").fetchall()
    col_names = {row[1] for row in record}
    for col in (
        "schema_version", "updated_at", "updated_by", "status", "layer",
        "source_agent", "session_id", "confidence", "review_required",
        "classification_reason", "classification_method", "body_hash",
    ):
        assert col in col_names, f"Expected column '{col}' in notes table"


def test_index_has_note_links_table(tmp_path: Path) -> None:
    idx = NoteIndex(tmp_path / ".index" / "notes.sqlite3")
    tables = {
        row[0]
        for row in idx._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "note_links" in tables


def test_index_has_schema_meta_table(tmp_path: Path) -> None:
    idx = NoteIndex(tmp_path / ".index" / "notes.sqlite3")
    val = idx._conn.execute(
        "SELECT value FROM schema_meta WHERE key='schema_version'"
    ).fetchone()
    assert val is not None
    assert int(val[0]) >= 2


def test_upsert_v2_metadata_stored_and_retrieved(tmp_path: Path) -> None:
    idx = NoteIndex(tmp_path / ".index" / "notes.sqlite3")
    idx.upsert(
        note_id="v2-note",
        path="/notes/v2-note.md",
        project="global",
        kind="environment",
        title="Python env",
        body="# Python env\n\nPython 3.11.",
        created_at="2026-05-31T00:00:00Z",
        created_by="test",
        tags=[],
        full_content="---\nid: v2-note\n---\n\n# Python env\n\nPython 3.11.",
        schema_version=2,
        updated_at="2026-05-31T01:00:00Z",
        updated_by="test",
        status="active",
        layer="core",
        source_agent="gemini",
        session_id="sess-1",
        confidence=0.9,
        review_required=True,
        classification_reason="environment_fact",
        classification_method="deterministic",
    )
    record = idx.get("v2-note")
    assert record["schema_version"] == 2
    assert record["updated_at"] == "2026-05-31T01:00:00Z"
    assert record["status"] == "active"
    assert record["layer"] == "core"
    assert record["source_agent"] == "gemini"
    assert record["session_id"] == "sess-1"
    assert abs(record["confidence"] - 0.9) < 1e-9
    assert record["review_required"] == 1  # stored as int
    assert record["classification_reason"] == "environment_fact"
    assert record["classification_method"] == "deterministic"


def test_body_hash_differs_from_content_hash(tmp_path: Path) -> None:
    idx = NoteIndex(tmp_path / ".index" / "notes.sqlite3")
    body = "# Title\n\nBody."
    full_content = "---\nid: htest\n---\n\n" + body
    idx.upsert(
        note_id="htest",
        path="/notes/htest.md",
        project="global",
        kind="constraint",
        title="Title",
        body=body,
        created_at="2026-05-31T00:00:00Z",
        created_by="test",
        tags=[],
        full_content=full_content,
    )
    record = idx.get("htest")
    # body_hash and content_hash are of different texts; they must differ.
    assert record["body_hash"] != record["content_hash"]


def test_note_links_upserted_with_relation_fields(tmp_path: Path) -> None:
    idx = NoteIndex(tmp_path / ".index" / "notes.sqlite3")
    _upsert_helper(idx, note_id="source")
    idx.upsert(
        note_id="source",
        path="/notes/source.md",
        project="proj",
        kind="reflection",
        title="Reflection",
        body="# Reflection\n\nText.",
        created_at="2026-05-31T00:00:00Z",
        created_by="test",
        tags=[],
        full_content="---\nid: source\n---\n\nText.",
        related=["other-id"],
        supersedes=["old-id"],
        evidence_for=["dec-id"],
    )
    links = idx.get_links("source")
    relations = {(lnk["relation"], lnk["target_note_id"]) for lnk in links}
    assert ("related", "other-id") in relations
    assert ("supersedes", "old-id") in relations
    assert ("evidence_for", "dec-id") in relations


def test_list_notes_filter_by_status(tmp_path: Path) -> None:
    idx = NoteIndex(tmp_path / ".index" / "notes.sqlite3")
    _upsert_helper(idx, note_id="active-1", status="active")
    _upsert_helper(idx, note_id="sup-1", status="superseded")
    active = idx.list_notes(status="active")
    superseded = idx.list_notes(status="superseded")
    assert any(r["id"] == "active-1" for r in active)
    assert not any(r["id"] == "active-1" for r in superseded)
    assert any(r["id"] == "sup-1" for r in superseded)


def test_list_notes_filter_by_layer(tmp_path: Path) -> None:
    idx = NoteIndex(tmp_path / ".index" / "notes.sqlite3")
    _upsert_helper(idx, note_id="core-1", layer="core")
    _upsert_helper(idx, note_id="arch-1", layer="archival")
    core = idx.list_notes(layer="core")
    archival = idx.list_notes(layer="archival")
    assert any(r["id"] == "core-1" for r in core)
    assert any(r["id"] == "arch-1" for r in archival)
    assert not any(r["id"] == "arch-1" for r in core)


def test_live_migration_adds_v2_columns(tmp_path: Path) -> None:
    """Open a fresh index, check it gets V2 columns even on first init."""
    idx = NoteIndex(tmp_path / ".index" / "notes2.sqlite3")
    col_names = {row[1] for row in idx._conn.execute("PRAGMA table_info(notes)").fetchall()}
    assert "status" in col_names
    assert "layer" in col_names
    assert "body_hash" in col_names


def _upsert_helper(
    idx: NoteIndex,
    *,
    note_id: str = "20260531T000000Z_aabbccdd",
    path: str | None = None,
    project: str = "proj",
    kind: str = "decision",
    title: str = "Test note",
    tags: list[str] | None = None,
    status: str = "active",
    layer: str = "",
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
        status=status,
        layer=layer,
    )
