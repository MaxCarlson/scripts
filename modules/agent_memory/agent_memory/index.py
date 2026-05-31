from __future__ import annotations

import hashlib
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

# Schema-level migration version tracked in the `schema_meta` table.
_INDEX_SCHEMA_VERSION = 2

_DDL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS notes (
    id                     TEXT PRIMARY KEY,
    path                   TEXT NOT NULL UNIQUE,
    project                TEXT NOT NULL,
    kind                   TEXT NOT NULL,
    title                  TEXT NOT NULL,
    body_excerpt           TEXT NOT NULL,
    created_at             TEXT NOT NULL,
    created_by             TEXT NOT NULL,
    content_hash           TEXT NOT NULL,
    schema_version         INTEGER NOT NULL DEFAULT 1,
    updated_at             TEXT NOT NULL DEFAULT '',
    updated_by             TEXT NOT NULL DEFAULT '',
    status                 TEXT NOT NULL DEFAULT 'active',
    layer                  TEXT NOT NULL DEFAULT '',
    source_agent           TEXT,
    session_id             TEXT,
    confidence             REAL,
    review_required        INTEGER NOT NULL DEFAULT 0,
    classification_reason  TEXT,
    classification_method  TEXT,
    body_hash              TEXT NOT NULL DEFAULT ''
) STRICT;

CREATE TABLE IF NOT EXISTS note_tags (
    note_id TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    tag     TEXT NOT NULL,
    PRIMARY KEY (note_id, tag)
) STRICT;

CREATE TABLE IF NOT EXISTS note_links (
    source_note_id TEXT NOT NULL,
    relation       TEXT NOT NULL,
    target_note_id TEXT NOT NULL,
    PRIMARY KEY (source_note_id, relation, target_note_id)
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

# Columns added in V2 that may be absent in older SQLite index files.
_V2_COLUMNS: list[tuple[str, str]] = [
    ("schema_version", "INTEGER NOT NULL DEFAULT 1"),
    ("updated_at", "TEXT NOT NULL DEFAULT ''"),
    ("updated_by", "TEXT NOT NULL DEFAULT ''"),
    ("status", "TEXT NOT NULL DEFAULT 'active'"),
    ("layer", "TEXT NOT NULL DEFAULT ''"),
    ("source_agent", "TEXT"),
    ("session_id", "TEXT"),
    ("confidence", "REAL"),
    ("review_required", "INTEGER NOT NULL DEFAULT 0"),
    ("classification_reason", "TEXT"),
    ("classification_method", "TEXT"),
    ("body_hash", "TEXT NOT NULL DEFAULT ''"),
]


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
        self._migrate_v2_columns()
        try:
            self._conn.executescript(_FTS_DDL)
            self._fts_available = True
        except sqlite3.OperationalError:
            logger.warning("FTS5 unavailable — falling back to LIKE search")
        self._conn.execute(
            "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('schema_version', ?)",
            (str(_INDEX_SCHEMA_VERSION),),
        )
        self._conn.commit()

    def _migrate_v2_columns(self) -> None:
        """Add V2 columns to the notes table if they are missing (live migration)."""
        cur = self._conn.execute("PRAGMA table_info(notes)")
        existing = {row[1] for row in cur.fetchall()}
        for col_name, col_def in _V2_COLUMNS:
            if col_name not in existing:
                try:
                    self._conn.execute(
                        f"ALTER TABLE notes ADD COLUMN {col_name} {col_def}"
                    )
                    logger.info("Migrated index: added column '%s'", col_name)
                except sqlite3.OperationalError as exc:
                    logger.warning("Could not add column '%s': %s", col_name, exc)

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
        # V2 fields — all optional for backward compatibility
        schema_version: int = 1,
        updated_at: str = "",
        updated_by: str = "",
        status: str = "active",
        layer: str = "",
        source_agent: str | None = None,
        session_id: str | None = None,
        confidence: float | None = None,
        review_required: bool = False,
        classification_reason: str | None = None,
        classification_method: str | None = None,
        related: list[str] | None = None,
        supersedes: list[str] | None = None,
        superseded_by: list[str] | None = None,
        evidence_for: list[str] | None = None,
    ) -> None:
        """Insert or update a note record and its tags."""
        excerpt = body[:2000]
        content_hash = _sha256(full_content)
        body_hash = _sha256(body)
        self._conn.execute(
            """
            INSERT INTO notes
                (id, path, project, kind, title, body_excerpt,
                 created_at, created_by, content_hash,
                 schema_version, updated_at, updated_by, status, layer,
                 source_agent, session_id, confidence, review_required,
                 classification_reason, classification_method, body_hash)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                path=excluded.path, project=excluded.project,
                kind=excluded.kind, title=excluded.title,
                body_excerpt=excluded.body_excerpt,
                created_at=excluded.created_at,
                created_by=excluded.created_by,
                content_hash=excluded.content_hash,
                schema_version=excluded.schema_version,
                updated_at=excluded.updated_at,
                updated_by=excluded.updated_by,
                status=excluded.status,
                layer=excluded.layer,
                source_agent=excluded.source_agent,
                session_id=excluded.session_id,
                confidence=excluded.confidence,
                review_required=excluded.review_required,
                classification_reason=excluded.classification_reason,
                classification_method=excluded.classification_method,
                body_hash=excluded.body_hash
            """,
            (
                note_id, path, project, kind, title, excerpt,
                created_at, created_by, content_hash,
                schema_version, updated_at, updated_by, status, layer,
                source_agent, session_id, confidence,
                int(review_required),
                classification_reason, classification_method, body_hash,
            ),
        )
        self._conn.execute("DELETE FROM note_tags WHERE note_id=?", (note_id,))
        for tag in tags:
            self._conn.execute(
                "INSERT OR IGNORE INTO note_tags (note_id, tag) VALUES (?,?)",
                (note_id, tag),
            )
        # Update note_links for relationship fields.
        self._conn.execute("DELETE FROM note_links WHERE source_note_id=?", (note_id,))
        _relation_map = {
            "related": related or [],
            "supersedes": supersedes or [],
            "superseded_by": superseded_by or [],
            "evidence_for": evidence_for or [],
        }
        for relation, targets in _relation_map.items():
            for target_id in targets:
                if target_id:
                    self._conn.execute(
                        "INSERT OR IGNORE INTO note_links "
                        "(source_note_id, relation, target_note_id) VALUES (?,?,?)",
                        (note_id, relation, target_id),
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
        status: str | None = None,
        layer: str | None = None,
    ) -> list[dict]:
        """Return note records matching filters, newest first."""
        sql = "SELECT DISTINCT n.* FROM notes n"
        params: list[object] = []
        where: list[str] = []

        if tags:
            placeholders = ",".join("?" * len(tags))
            sql += " JOIN note_tags t ON t.note_id = n.id"
            where.append(f"t.tag IN ({placeholders})")
            params.extend(tags)
        if project is not None:
            where.append("n.project=?")
            params.append(project)
        if kind is not None:
            where.append("n.kind=?")
            params.append(kind)
        if status is not None:
            where.append("n.status=?")
            params.append(status)
        if layer is not None:
            where.append("n.layer=?")
            params.append(layer)
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

    def get_links(self, note_id: str) -> list[dict]:
        """Return all note_links rows where source_note_id matches."""
        rows = self._conn.execute(
            "SELECT * FROM note_links WHERE source_note_id=?", (note_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
