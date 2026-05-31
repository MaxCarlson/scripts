# agent_memory Core — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`
> (recommended) or `superpowers:executing-plans` to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `NoteStore` — the Python API for creating, reading, listing,
searching, and indexing Markdown memory notes backed by SQLite.

**Architecture:** `note.py` defines the `Note` dataclass and kind constants.
`frontmatter.py` parses/writes YAML frontmatter. `naming.py` generates
collision-safe filenames. `index.py` manages the SQLite cache. `store.py`
orchestrates everything — it is the only public API surface.

**Tech Stack:** Python 3.11+, `pyyaml>=6.0`, `sqlite3` (stdlib), `uv run pytest`.
`llm_local` is NOT imported in this plan — classification is wired in Plan 4.

**Prerequisites:** `llm_local` installed (Plan 1 complete). `pyyaml` available
in the scripts `.venv`.

**Working directory:** `/home/mcarls/scripts/modules/agent_memory/`

---

## File Map

| File | Responsibility |
|---|---|
| `agent_memory/note.py` | `Note` dataclass, `VALID_KINDS`, kind-scope constants |
| `agent_memory/frontmatter.py` | `parse_frontmatter()`, `write_frontmatter()`, `validate_frontmatter()` |
| `agent_memory/naming.py` | `make_note_id()`, `slugify()`, `make_filename()` |
| `agent_memory/index.py` | `NoteIndex` SQLite wrapper — upsert, delete, list, search, rebuild |
| `agent_memory/store.py` | `NoteStore` — `create_note()`, `get_note()`, `list_notes()`, `search()`, `rebuild_index()`, `verify()` |
| `agent_memory/__init__.py` | Re-export `NoteStore`, `Note` |
| `tests/note_test.py` | Note dataclass + constants tests |
| `tests/frontmatter_test.py` | Frontmatter parse/write/validate tests |
| `tests/naming_test.py` | ID generation and filename tests |
| `tests/index_test.py` | SQLite index tests |
| `tests/store_test.py` | NoteStore integration tests |

---

## Task 1: `Note` dataclass + kind constants

**Files:**
- Create: `agent_memory/note.py`
- Create: `tests/note_test.py`

- [ ] **Step 1: Write failing tests**

```python
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
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /home/mcarls/scripts/modules/agent_memory
uv run pytest tests/note_test.py -v --tb=short
```

Expected: `ModuleNotFoundError: No module named 'agent_memory.note'`

- [ ] **Step 3: Write `agent_memory/note.py`**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

VALID_KINDS: frozenset[str] = frozenset({
    "constraint", "preference", "decision", "code_note",
    "handoff", "task", "bug", "session",
})

# Kinds that default to "global" when project is None
GLOBAL_DEFAULT_KINDS: frozenset[str] = frozenset({"constraint", "preference"})

# Kinds that require an explicit project (error if project is None)
PROJECT_REQUIRED_KINDS: frozenset[str] = frozenset({"handoff", "task", "bug"})

# Kinds where LLM classification is used when project is None
LLM_CLASSIFY_KINDS: frozenset[str] = frozenset({"decision", "code_note", "session"})


@dataclass
class Note:
    """A single memory note loaded from a Markdown file."""

    id: str
    path: Path
    kind: str
    project: str          # "global" or a project slug
    title: str
    body: str             # full body text (after frontmatter)
    created_at: str       # ISO 8601 UTC string
    created_by: str
    tags: list[str] = field(default_factory=list)
    schema_version: int = 1
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/note_test.py -v --tb=short
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add agent_memory/note.py tests/note_test.py
git commit -m "feat(agent_memory): add Note dataclass and kind constants"
```

---

## Task 2: Frontmatter parsing and writing

**Files:**
- Create: `agent_memory/frontmatter.py`
- Create: `tests/frontmatter_test.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/frontmatter_test.py
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
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/frontmatter_test.py -v --tb=short
```

Expected: `ModuleNotFoundError: No module named 'agent_memory.frontmatter'`

- [ ] **Step 3: Write `agent_memory/frontmatter.py`**

```python
from __future__ import annotations

import re
from typing import Any

import yaml

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)", re.DOTALL)

REQUIRED_FIELDS: frozenset[str] = frozenset({
    "id", "schema_version", "kind", "project",
    "created_at", "created_by", "tags",
})


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from Markdown text.

    Returns:
        Tuple of (metadata dict, body string). If no frontmatter is found,
        metadata is {} and body is the full text.
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    meta: dict[str, Any] = yaml.safe_load(m.group(1)) or {}
    body = m.group(2).lstrip("\n")
    return meta, body


def write_frontmatter(meta: dict[str, Any], body: str) -> str:
    """Serialize YAML frontmatter + body to a Markdown string."""
    fm = yaml.dump(
        meta,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )
    return f"---\n{fm}---\n\n{body}"


def validate_frontmatter(meta: dict[str, Any]) -> list[str]:
    """Return validation error messages. Empty list means valid."""
    return [
        f"Missing required field: '{field}'"
        for field in sorted(REQUIRED_FIELDS)
        if field not in meta
    ]
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/frontmatter_test.py -v --tb=short
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add agent_memory/frontmatter.py tests/frontmatter_test.py
git commit -m "feat(agent_memory): add frontmatter parse/write/validate"
```

---

## Task 3: Note ID generation and file naming

**Files:**
- Create: `agent_memory/naming.py`
- Create: `tests/naming_test.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/naming_test.py
from __future__ import annotations
import re
from agent_memory.naming import make_note_id, slugify, make_filename

_ID_RE = re.compile(r"^\d{8}T\d{6}Z_[0-9a-f]{8}$")


def test_make_note_id_format() -> None:
    note_id = make_note_id()
    assert _ID_RE.match(note_id), f"Bad ID format: {note_id}"


def test_make_note_id_unique() -> None:
    ids = {make_note_id() for _ in range(100)}
    assert len(ids) == 100


def test_slugify_basic() -> None:
    assert slugify("Use SQLite for index") == "use-sqlite-for-index"


def test_slugify_special_chars() -> None:
    assert slugify("hello! world? (yes)") == "hello-world-yes"


def test_slugify_truncates_at_60() -> None:
    long_title = "a" * 100
    result = slugify(long_title)
    assert len(result) <= 60


def test_slugify_strips_trailing_dashes() -> None:
    result = slugify("hello---")
    assert not result.endswith("-")


def test_make_filename_format() -> None:
    note_id = "20260531T055512Z_a3f9e1b2"
    filename = make_filename(note_id, "Use SQLite for index")
    assert filename == "20260531T055512Z_a3f9e1b2_use-sqlite-for-index.md"


def test_make_filename_ends_with_md() -> None:
    filename = make_filename("20260531T000000Z_aabbccdd", "Some Title")
    assert filename.endswith(".md")
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/naming_test.py -v --tb=short
```

Expected: `ModuleNotFoundError: No module named 'agent_memory.naming'`

- [ ] **Step 3: Write `agent_memory/naming.py`**

```python
from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone


def make_note_id() -> str:
    """Generate a collision-safe note ID: UTC timestamp + 8 random hex chars.

    Example: 20260531T055512Z_a3f9e1b2
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{ts}_{secrets.token_hex(4)}"


def slugify(text: str, max_len: int = 60) -> str:
    """Convert text to a URL-safe, lowercase slug."""
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:max_len].rstrip("-")


def make_filename(note_id: str, title: str) -> str:
    """Return the .md filename for a note: <id>_<slug>.md"""
    slug = slugify(title)
    return f"{note_id}_{slug}.md"
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/naming_test.py -v --tb=short
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add agent_memory/naming.py tests/naming_test.py
git commit -m "feat(agent_memory): add note ID generation and filename helpers"
```

---

## Task 4: SQLite index (`NoteIndex`)

**Files:**
- Create: `agent_memory/index.py`
- Create: `tests/index_test.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/index_test.py
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
    path: str = "/notes/test.md",
    project: str = "proj",
    kind: str = "decision",
    title: str = "Test note",
    tags: list[str] | None = None,
) -> None:
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
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/index_test.py -v --tb=short
```

Expected: `ModuleNotFoundError: No module named 'agent_memory.index'`

- [ ] **Step 3: Write `agent_memory/index.py`**

```python
from __future__ import annotations

import hashlib
import logging
import sqlite3
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DDL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS notes (
    id           TEXT PRIMARY KEY,
    path         TEXT NOT NULL UNIQUE,
    project      TEXT NOT NULL,
    kind         TEXT NOT NULL,
    title        TEXT NOT NULL,
    body_excerpt TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    created_by   TEXT NOT NULL,
    content_hash TEXT NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS note_tags (
    note_id TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    tag     TEXT NOT NULL,
    PRIMARY KEY (note_id, tag)
) STRICT;
"""

_FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts
    USING fts5(title, body_excerpt, content=notes, content_rowid=rowid);
"""


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class NoteIndex:
    """SQLite-backed index over Markdown note files. Rebuildable from disk."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._fts_available = False
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(_DDL)
        try:
            self._conn.executescript(_FTS_DDL)
            self._fts_available = True
        except sqlite3.OperationalError:
            logger.warning("FTS5 unavailable — falling back to LIKE search")
        self._conn.commit()

    def upsert(
        self,
        *,
        note_id: str,
        path: str,
        project: str,
        kind: str,
        title: str,
        body: str,
        created_at: str,
        created_by: str,
        tags: list[str],
        full_content: str,
    ) -> None:
        """Insert or update a note record and its tags."""
        excerpt = body[:2000]
        content_hash = _sha256(full_content)
        self._conn.execute(
            """
            INSERT INTO notes
                (id, path, project, kind, title, body_excerpt,
                 created_at, created_by, content_hash)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                path=excluded.path, project=excluded.project,
                kind=excluded.kind, title=excluded.title,
                body_excerpt=excluded.body_excerpt,
                created_at=excluded.created_at,
                created_by=excluded.created_by,
                content_hash=excluded.content_hash
            """,
            (note_id, path, project, kind, title, excerpt,
             created_at, created_by, content_hash),
        )
        self._conn.execute("DELETE FROM note_tags WHERE note_id=?", (note_id,))
        for tag in tags:
            self._conn.execute(
                "INSERT OR IGNORE INTO note_tags (note_id, tag) VALUES (?,?)",
                (note_id, tag),
            )
        self._conn.commit()

    def delete(self, note_id: str) -> None:
        """Remove a note and its tags from the index."""
        self._conn.execute("DELETE FROM notes WHERE id=?", (note_id,))
        self._conn.commit()

    def get(self, note_id: str) -> Optional[dict]:
        """Return a note record dict with 'tags' key, or None if not found."""
        row = self._conn.execute(
            "SELECT * FROM notes WHERE id=?", (note_id,)
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        tag_rows = self._conn.execute(
            "SELECT tag FROM note_tags WHERE note_id=?", (note_id,)
        ).fetchall()
        result["tags"] = [r["tag"] for r in tag_rows]
        return result

    def list_notes(
        self,
        project: Optional[str] = None,
        kind: Optional[str] = None,
        tags: Optional[list[str]] = None,
        limit: int = 100,
    ) -> list[dict]:
        """Return note records matching filters, newest first."""
        sql = "SELECT DISTINCT n.* FROM notes n"
        params: list = []
        where: list[str] = []

        if tags:
            placeholders = ",".join("?" * len(tags))
            sql += f" JOIN note_tags t ON t.note_id = n.id"
            where.append(f"t.tag IN ({placeholders})")
            params.extend(tags)
        if project is not None:
            where.append("n.project=?")
            params.append(project)
        if kind is not None:
            where.append("n.kind=?")
            params.append(kind)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY n.created_at DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def search(
        self,
        query: str,
        project: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> list[dict]:
        """Full-text search using FTS5 or LIKE fallback."""
        if self._fts_available:
            return self._search_fts(query, project, kind)
        return self._search_like(query, project, kind)

    def _search_fts(self, query: str, project: Optional[str], kind: Optional[str]) -> list[dict]:
        sql = """
            SELECT n.* FROM notes_fts f
            JOIN notes n ON n.rowid = f.rowid
            WHERE notes_fts MATCH ?
        """
        params: list = [query]
        if project is not None:
            sql += " AND n.project=?"
            params.append(project)
        if kind is not None:
            sql += " AND n.kind=?"
            params.append(kind)
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def _search_like(self, query: str, project: Optional[str], kind: Optional[str]) -> list[dict]:
        like = f"%{query}%"
        sql = "SELECT * FROM notes WHERE (title LIKE ? OR body_excerpt LIKE ?)"
        params: list = [like, like]
        if project is not None:
            sql += " AND project=?"
            params.append(project)
        if kind is not None:
            sql += " AND kind=?"
            params.append(kind)
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def all_records(self) -> list[dict]:
        """Return all (id, path, content_hash) records — used for rebuild diff."""
        rows = self._conn.execute(
            "SELECT id, path, content_hash FROM notes"
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/index_test.py -v --tb=short
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add agent_memory/index.py tests/index_test.py
git commit -m "feat(agent_memory): add NoteIndex SQLite wrapper with FTS5"
```

---

## Task 5: `NoteStore.create_note()`

**Files:**
- Create: `agent_memory/store.py`
- Create: `tests/store_test.py`

- [ ] **Step 1: Write failing tests for create_note**

```python
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
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/store_test.py -v --tb=short
```

Expected: `ModuleNotFoundError: No module named 'agent_memory.store'`

- [ ] **Step 3: Write `agent_memory/store.py`**

```python
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from agent_memory.frontmatter import parse_frontmatter, validate_frontmatter, write_frontmatter
from agent_memory.index import NoteIndex
from agent_memory.naming import make_filename, make_note_id
from agent_memory.note import (
    GLOBAL_DEFAULT_KINDS,
    LLM_CLASSIFY_KINDS,
    PROJECT_REQUIRED_KINDS,
    VALID_KINDS,
    Note,
)

logger = logging.getLogger(__name__)

_DEFAULT_ROOT = Path.home() / "scripts" / "modules" / "agent_memory" / "notes"


def _get_default_root() -> Path:
    env = os.environ.get("AGENT_MEMORY_ROOT")
    return Path(env) if env else _DEFAULT_ROOT


class NoteStore:
    """Read/write interface for Markdown memory notes with SQLite indexing."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self._root = root if root is not None else _get_default_root()
        self._index = NoteIndex(self._root / ".index" / "notes.sqlite3")

    def _note_dir(self, project: str, kind: str) -> Path:
        if project == "global":
            return self._root / "global" / kind
        return self._root / "projects" / project / kind

    def _read_note_file(self, path: Path) -> Note:
        text = path.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(text)
        title = ""
        for line in body.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
        return Note(
            id=str(meta["id"]),
            path=path,
            kind=str(meta["kind"]),
            project=str(meta["project"]),
            title=title or str(meta.get("id", "")),
            body=body,
            created_at=str(meta["created_at"]),
            created_by=str(meta["created_by"]),
            tags=list(meta.get("tags") or []),
            schema_version=int(meta.get("schema_version", 1)),
        )

    def _resolve_project(
        self, kind: str, project: Optional[str], auto_classify: bool
    ) -> str:
        if project is not None:
            return project
        if kind in GLOBAL_DEFAULT_KINDS:
            return "global"
        if kind in PROJECT_REQUIRED_KINDS:
            raise ValueError(
                f"Kind '{kind}' requires an explicit project. "
                "These kinds are always project-specific (handoff, task, bug)."
            )
        # LLM_CLASSIFY_KINDS: decision, code_note, session
        if auto_classify:
            from agent_memory.classify import classify_placement
            result = classify_placement(
                kind=kind,
                title="",
                body="",
                known_projects=self._known_projects(),
            )
            if result:
                logger.info("Classified as: %s (via local LLM)", result)
                return result
        return "global"

    def _known_projects(self) -> list[str]:
        projects_dir = self._root / "projects"
        if not projects_dir.exists():
            return []
        return [p.name for p in sorted(projects_dir.iterdir()) if p.is_dir()]

    def create_note(
        self,
        *,
        kind: str,
        project: Optional[str],
        title: str,
        body: str,
        created_by: str,
        tags: Optional[list[str]] = None,
        auto_classify: bool = False,
        dry_run: bool = False,
    ) -> Note:
        """Create a new memory note.

        Args:
            kind: Note kind (must be in VALID_KINDS).
            project: Project slug, "global", or None (triggers auto-placement).
            title: Human-readable note title.
            body: Markdown body text (without the # Title line).
            created_by: Agent or human identifier (e.g. "claude-code").
            tags: Optional list of tag strings.
            auto_classify: If True and project is None, call llm_local to classify.
            dry_run: If True, return the Note without writing any files.
        """
        if kind not in VALID_KINDS:
            raise ValueError(
                f"Invalid kind '{kind}'. Valid kinds: {sorted(VALID_KINDS)}"
            )
        resolved_project = self._resolve_project(kind, project, auto_classify)
        note_id = make_note_id()
        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        resolved_tags = tags or []

        meta: dict = {
            "id": note_id,
            "schema_version": 1,
            "kind": kind,
            "project": resolved_project,
            "created_at": created_at,
            "created_by": created_by,
            "tags": resolved_tags,
        }
        full_body = f"# {title}\n\n{body}"
        content = write_frontmatter(meta, full_body)

        note = Note(
            id=note_id,
            path=Path(),
            kind=kind,
            project=resolved_project,
            title=title,
            body=full_body,
            created_at=created_at,
            created_by=created_by,
            tags=resolved_tags,
        )

        if dry_run:
            return note

        note_dir = self._note_dir(resolved_project, kind)
        note_dir.mkdir(parents=True, exist_ok=True)
        filename = make_filename(note_id, title)
        note_path = note_dir / filename

        tmp_path = note_path.with_suffix(".tmp")
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.rename(note_path)

        note.path = note_path
        self._index.upsert(
            note_id=note_id,
            path=str(note_path),
            project=resolved_project,
            kind=kind,
            title=title,
            body=full_body,
            created_at=created_at,
            created_by=created_by,
            tags=resolved_tags,
            full_content=content,
        )
        return note

    def get_note(self, note_id: str) -> Optional[Note]:
        """Return a Note by ID, reading from disk. None if not found."""
        record = self._index.get(note_id)
        if record is None:
            return None
        path = Path(record["path"])
        if not path.exists():
            return None
        return self._read_note_file(path)

    def list_notes(
        self,
        project: Optional[str] = None,
        kind: Optional[str] = None,
        tags: Optional[list[str]] = None,
        limit: int = 20,
    ) -> list[Note]:
        """Return notes matching filters, newest first."""
        records = self._index.list_notes(
            project=project, kind=kind, tags=tags, limit=limit
        )
        notes: list[Note] = []
        for rec in records:
            path = Path(rec["path"])
            if path.exists():
                try:
                    notes.append(self._read_note_file(path))
                except Exception as exc:
                    logger.warning("Skipping unreadable note %s: %s", path, exc)
        return notes

    def search(
        self,
        query: str,
        project: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> list[Note]:
        """Full-text search across titles and bodies."""
        records = self._index.search(query, project=project, kind=kind)
        notes: list[Note] = []
        for rec in records:
            path = Path(rec["path"])
            if path.exists():
                try:
                    notes.append(self._read_note_file(path))
                except Exception as exc:
                    logger.warning("Skipping unreadable note %s: %s", path, exc)
        return notes

    def rebuild_index(self) -> int:
        """Scan all .md files under notes root and rebuild SQLite index.

        Returns:
            Number of notes indexed.
        """
        count = 0
        for md_file in sorted(self._root.rglob("*.md")):
            if ".index" in md_file.parts:
                continue
            try:
                text = md_file.read_text(encoding="utf-8")
                meta, body = parse_frontmatter(text)
                if not meta.get("id"):
                    continue
                title = ""
                for line in body.splitlines():
                    if line.startswith("# "):
                        title = line[2:].strip()
                        break
                self._index.upsert(
                    note_id=str(meta["id"]),
                    path=str(md_file),
                    project=str(meta.get("project", "global")),
                    kind=str(meta.get("kind", "")),
                    title=title,
                    body=body,
                    created_at=str(meta.get("created_at", "")),
                    created_by=str(meta.get("created_by", "")),
                    tags=list(meta.get("tags") or []),
                    full_content=text,
                )
                count += 1
            except Exception as exc:
                logger.warning("Skipping %s: %s", md_file, exc)
        return count

    def verify(self) -> list[str]:
        """Check all notes for validation errors.

        Returns:
            List of error strings. Empty means all notes are valid.
        """
        errors: list[str] = []
        for md_file in sorted(self._root.rglob("*.md")):
            if ".index" in md_file.parts:
                continue
            try:
                text = md_file.read_text(encoding="utf-8")
                meta, _ = parse_frontmatter(text)
                for err in validate_frontmatter(meta):
                    errors.append(f"{md_file}: {err}")
                if not errors:
                    path_kind = md_file.parent.name
                    if meta.get("kind") and meta["kind"] != path_kind:
                        errors.append(
                            f"{md_file}: frontmatter kind='{meta['kind']}' "
                            f"but directory says '{path_kind}'"
                        )
            except Exception as exc:
                errors.append(f"{md_file}: parse error: {exc}")
        return errors
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/store_test.py -v --tb=short
```

Expected: 8 passed. If you see `ModuleNotFoundError: agent_memory.classify`, add
a stub `agent_memory/classify.py`:

```python
# agent_memory/classify.py  (temporary stub — full impl in Plan 4)
from __future__ import annotations
from typing import Optional

def classify_placement(
    *, kind: str, title: str, body: str, known_projects: list[str]
) -> Optional[str]:
    return None
```

Re-run after adding the stub.

- [ ] **Step 5: Run all tests so far**

```bash
uv run pytest tests/ -v --tb=short
```

Expected: All tests pass (note, frontmatter, naming, index, store).

- [ ] **Step 6: Update `agent_memory/__init__.py`**

```python
"""agent_memory — persistent markdown-file memory for AI agents."""

__version__ = "0.1.0"

from agent_memory.note import Note
from agent_memory.store import NoteStore

__all__ = ["Note", "NoteStore"]
```

- [ ] **Step 7: Commit**

```bash
git add agent_memory/ tests/store_test.py
git commit -m "feat(agent_memory): add NoteStore with create_note, get_note, list_notes, search, rebuild_index, verify"
```

---

## Task 6: Extend store tests for get/list/search/rebuild/verify

**Files:**
- Modify: `tests/store_test.py` (append)

- [ ] **Step 1: Append remaining tests**

```python
# Append to tests/store_test.py


def test_get_note_returns_note(tmp_path: Path) -> None:
    store = NoteStore(root=tmp_path)
    created = store.create_note(
        kind="decision", project="proj", title="Get test",
        body="Body.", created_by="test",
    )
    fetched = store.get_note(created.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.title == "Get test"


def test_get_note_returns_none_for_missing(tmp_path: Path) -> None:
    store = NoteStore(root=tmp_path)
    assert store.get_note("nonexistent-id") is None


def test_list_notes_returns_all(tmp_path: Path) -> None:
    store = NoteStore(root=tmp_path)
    store.create_note(kind="decision", project="proj", title="A",
                      body=".", created_by="test")
    store.create_note(kind="bug", project="proj", title="B",
                      body=".", created_by="test")
    notes = store.list_notes()
    assert len(notes) == 2


def test_list_notes_filters_by_kind(tmp_path: Path) -> None:
    store = NoteStore(root=tmp_path)
    store.create_note(kind="decision", project="proj", title="D1",
                      body=".", created_by="test")
    store.create_note(kind="bug", project="proj", title="B1",
                      body=".", created_by="test")
    notes = store.list_notes(kind="decision")
    assert len(notes) == 1
    assert notes[0].kind == "decision"


def test_search_finds_by_title_keyword(tmp_path: Path) -> None:
    store = NoteStore(root=tmp_path)
    store.create_note(kind="decision", project="proj",
                      title="Use SQLite for storage",
                      body="Details.", created_by="test")
    store.create_note(kind="decision", project="proj",
                      title="Python packaging guide",
                      body="Details.", created_by="test")
    results = store.search("SQLite")
    assert len(results) == 1
    assert "SQLite" in results[0].title


def test_rebuild_index_reindexes_all_files(tmp_path: Path) -> None:
    store = NoteStore(root=tmp_path)
    store.create_note(kind="decision", project="proj",
                      title="Note A", body=".", created_by="test")
    store.create_note(kind="bug", project="proj",
                      title="Note B", body=".", created_by="test")
    # Force-rebuild from scratch
    store._index.close()
    from agent_memory.index import NoteIndex
    store._index = NoteIndex(tmp_path / ".index" / "notes.sqlite3")
    store._index.close()
    import sqlite3
    (tmp_path / ".index" / "notes.sqlite3").unlink()
    store._index = NoteIndex(tmp_path / ".index" / "notes.sqlite3")
    count = store.rebuild_index()
    assert count == 2


def test_verify_returns_empty_for_valid_notes(tmp_path: Path) -> None:
    store = NoteStore(root=tmp_path)
    store.create_note(kind="decision", project="proj",
                      title="Valid note", body=".", created_by="test")
    errors = store.verify()
    assert errors == []


def test_verify_flags_kind_mismatch(tmp_path: Path) -> None:
    store = NoteStore(root=tmp_path)
    note = store.create_note(kind="decision", project="proj",
                             title="Mismatch test", body=".", created_by="test")
    # Manually write wrong kind into frontmatter
    text = note.path.read_text(encoding="utf-8")
    text = text.replace("kind: decision", "kind: bug")
    note.path.write_text(text, encoding="utf-8")
    errors = store.verify()
    assert any("kind" in e for e in errors)
```

- [ ] **Step 2: Run all tests**

```bash
uv run pytest tests/ -v --tb=short
```

Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/store_test.py
git commit -m "test(agent_memory): add get/list/search/rebuild/verify coverage"
```

---

## Phase 2 Definition of Done

- [ ] `from agent_memory import NoteStore, Note` works after `pip install -e .`
- [ ] `store.create_note(kind, project, title, body, created_by)` writes a valid `.md` file
- [ ] File naming: `<id>_<slug>.md` in `projects/<project>/<kind>/` or `global/<kind>/`
- [ ] Frontmatter has all 7 required fields; path/kind consistency enforced
- [ ] `store.get_note(id)` reads from disk
- [ ] `store.list_notes(project, kind, tags)` returns filtered results
- [ ] `store.search(query)` returns full-text matches
- [ ] `store.rebuild_index()` rebuilds SQLite from disk files
- [ ] `store.verify()` detects frontmatter errors and path/kind mismatches
- [ ] All tests pass: `uv run pytest tests/ -v`
