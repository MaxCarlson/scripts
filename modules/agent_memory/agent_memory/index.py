from __future__ import annotations

import hashlib
import logging
import sqlite3
from pathlib import Path

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

CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
  INSERT INTO notes_fts(rowid, title, body_excerpt) VALUES (new.rowid, new.title, new.body_excerpt);
END;

CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
  INSERT INTO notes_fts(notes_fts, rowid, title, body_excerpt) VALUES('delete', old.rowid, old.title, old.body_excerpt);
END;

CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
  INSERT INTO notes_fts(notes_fts, rowid, title, body_excerpt) VALUES('delete', old.rowid, old.title, old.body_excerpt);
  INSERT INTO notes_fts(rowid, title, body_excerpt) VALUES (new.rowid, new.title, new.body_excerpt);
END;
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

    def get(self, note_id: str) -> dict | None:
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
        project: str | None = None,
        kind: str | None = None,
        tags: list[str] | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Return note records matching filters, newest first."""
        sql = "SELECT DISTINCT n.* FROM notes n"
        params: list[object] = []
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
        project: str | None = None,
        kind: str | None = None,
    ) -> list[dict]:
        """Full-text search using FTS5 or LIKE fallback."""
        if self._fts_available:
            return self._search_fts(query, project, kind)
        return self._search_like(query, project, kind)

    def _search_fts(self, query: str, project: str | None, kind: str | None) -> list[dict]:
        sql = """
            SELECT n.* FROM notes_fts f
            JOIN notes n ON n.rowid = f.rowid
            WHERE notes_fts MATCH ?
        """
        params: list[object] = [query]
        if project is not None:
            sql += " AND n.project=?"
            params.append(project)
        if kind is not None:
            sql += " AND n.kind=?"
            params.append(kind)
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def _search_like(self, query: str, project: str | None, kind: str | None) -> list[dict]:
        like = f"%{query}%"
        sql = "SELECT * FROM notes WHERE (title LIKE ? OR body_excerpt LIKE ?)"
        params: list[object] = [like, like]
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
        """Close the database connection."""
        self._conn.close()
