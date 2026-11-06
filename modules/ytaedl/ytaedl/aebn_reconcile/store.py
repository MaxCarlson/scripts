"""Transactional SQLite state for resumable AEBN reconciliation."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ReconciliationStore:
    """Own a versioned database and append-only event journal."""

    def __init__(self, path: Path | str):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA busy_timeout=15000")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self._migrate()

    def __enter__(self) -> "ReconciliationStore":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield self.connection
        except BaseException:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    def _migrate(self) -> None:
        current = self.connection.execute("PRAGMA user_version").fetchone()[0]
        if current > SCHEMA_VERSION:
            raise RuntimeError(f"Reconciliation database schema {current} is newer than supported {SCHEMA_VERSION}")
        if current == SCHEMA_VERSION:
            return
        with self.transaction() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS movies (
                    movie_key TEXT PRIMARY KEY,
                    site TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    movie_id TEXT NOT NULL,
                    canonical_url TEXT NOT NULL,
                    title TEXT,
                    studio TEXT,
                    duration_seconds REAL,
                    scene_count INTEGER,
                    metadata_at TEXT,
                    metadata_status TEXT NOT NULL DEFAULT 'pending',
                    metadata_error TEXT,
                    timing_error TEXT
                );
                CREATE TABLE IF NOT EXISTS requested_scenes (
                    movie_key TEXT NOT NULL REFERENCES movies(movie_key),
                    scene_id TEXT NOT NULL,
                    ordinal INTEGER,
                    start_seconds REAL,
                    end_seconds REAL,
                    original_url TEXT NOT NULL,
                    metadata_status TEXT NOT NULL DEFAULT 'pending',
                    status TEXT NOT NULL DEFAULT 'unknown',
                    status_detail TEXT,
                    PRIMARY KEY(movie_key, scene_id)
                );
                CREATE TABLE IF NOT EXISTS movie_scene_metadata (
                    movie_key TEXT NOT NULL REFERENCES movies(movie_key),
                    ordinal INTEGER NOT NULL,
                    scene_id TEXT,
                    start_seconds REAL,
                    end_seconds REAL,
                    PRIMARY KEY(movie_key, ordinal)
                );
                CREATE TABLE IF NOT EXISTS scene_sources (
                    movie_key TEXT NOT NULL,
                    scene_id TEXT NOT NULL,
                    source_file TEXT NOT NULL,
                    source_line INTEGER NOT NULL,
                    PRIMARY KEY(movie_key, scene_id, source_file, source_line),
                    FOREIGN KEY(movie_key, scene_id) REFERENCES requested_scenes(movie_key, scene_id)
                );
                CREATE TABLE IF NOT EXISTS media_candidates (
                    candidate_id INTEGER PRIMARY KEY,
                    movie_key TEXT NOT NULL REFERENCES movies(movie_key),
                    path TEXT NOT NULL,
                    root_path TEXT NOT NULL,
                    classification TEXT NOT NULL,
                    scene_ordinal INTEGER,
                    size_bytes INTEGER NOT NULL,
                    mtime_ns INTEGER NOT NULL,
                    device_id TEXT,
                    file_id TEXT,
                    duration_seconds REAL,
                    has_video INTEGER,
                    match_evidence TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    identity_confirmed INTEGER NOT NULL DEFAULT 0,
                    approval TEXT NOT NULL DEFAULT 'undecided',
                    approval_fingerprint TEXT,
                    approved_at TEXT,
                    deletion_state TEXT NOT NULL DEFAULT 'not_started',
                    final_path TEXT,
                    error TEXT,
                    UNIQUE(movie_key, path)
                );
                CREATE TABLE IF NOT EXISTS candidate_scenes (
                    candidate_id INTEGER NOT NULL REFERENCES media_candidates(candidate_id) ON DELETE CASCADE,
                    movie_key TEXT NOT NULL,
                    scene_id TEXT NOT NULL,
                    required INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY(candidate_id, movie_key, scene_id),
                    FOREIGN KEY(movie_key, scene_id) REFERENCES requested_scenes(movie_key, scene_id)
                );
                CREATE TABLE IF NOT EXISTS download_jobs (
                    job_id INTEGER PRIMARY KEY,
                    movie_key TEXT NOT NULL,
                    scene_id TEXT NOT NULL,
                    target_dir TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    process_id INTEGER,
                    started_at TEXT,
                    ended_at TEXT,
                    exit_code INTEGER,
                    output_path TEXT,
                    verification_status TEXT NOT NULL DEFAULT 'pending',
                    verification_json TEXT,
                    error TEXT,
                    UNIQUE(movie_key, scene_id),
                    FOREIGN KEY(movie_key, scene_id) REFERENCES requested_scenes(movie_key, scene_id)
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY,
                    at TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    movie_key TEXT,
                    scene_id TEXT,
                    candidate_id INTEGER,
                    details_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_scenes_status ON requested_scenes(status);
                CREATE INDEX IF NOT EXISTS idx_candidates_approval ON media_candidates(approval, deletion_state);
                CREATE INDEX IF NOT EXISTS idx_jobs_status ON download_jobs(status, verification_status);
                """
            )
            db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        return self.connection.execute(sql, parameters)

    def record_event(self, kind: str, *, movie_key: str | None = None, scene_id: str | None = None,
                     candidate_id: int | None = None, details: dict[str, Any] | None = None) -> None:
        self.connection.execute(
            "INSERT INTO events(at, kind, movie_key, scene_id, candidate_id, details_json) VALUES (?, ?, ?, ?, ?, ?)",
            (_now(), kind, movie_key, scene_id, candidate_id, json.dumps(details or {}, ensure_ascii=False)),
        )

    def upsert_movie(self, values: dict[str, Any]) -> None:
        self.connection.execute(
            """INSERT INTO movies(movie_key,site,content_type,movie_id,canonical_url,title,studio,duration_seconds,
               scene_count,metadata_at,metadata_status,metadata_error,timing_error) VALUES (:movie_key,:site,:content_type,:movie_id,
               :canonical_url,:title,:studio,:duration_seconds,:scene_count,:metadata_at,:metadata_status,:metadata_error,:timing_error)
               ON CONFLICT(movie_key) DO UPDATE SET canonical_url=excluded.canonical_url,title=excluded.title,
               studio=excluded.studio,duration_seconds=excluded.duration_seconds,scene_count=excluded.scene_count,
               metadata_at=excluded.metadata_at,metadata_status=excluded.metadata_status,metadata_error=excluded.metadata_error,
               timing_error=excluded.timing_error""",
            values,
        )

    def upsert_scene(self, values: dict[str, Any]) -> None:
        self.connection.execute(
            """INSERT INTO requested_scenes(movie_key,scene_id,ordinal,start_seconds,end_seconds,original_url,
               metadata_status,status,status_detail) VALUES (:movie_key,:scene_id,:ordinal,:start_seconds,:end_seconds,
               :original_url,:metadata_status,:status,:status_detail)
               ON CONFLICT(movie_key,scene_id) DO UPDATE SET ordinal=excluded.ordinal,start_seconds=excluded.start_seconds,
               end_seconds=excluded.end_seconds,metadata_status=excluded.metadata_status,status=excluded.status,
               status_detail=excluded.status_detail""",
            values,
        )

    def add_source(self, movie_key: str, scene_id: str, source_file: str, source_line: int) -> None:
        self.connection.execute(
            "INSERT OR IGNORE INTO scene_sources(movie_key,scene_id,source_file,source_line) VALUES(?,?,?,?)",
            (movie_key, scene_id, source_file, source_line),
        )

    def metadata_scenes(self, movie_key: str) -> list[dict[str, Any]]:
        return [dict(row) for row in self.connection.execute(
            "SELECT * FROM movie_scene_metadata WHERE movie_key=? ORDER BY ordinal", (movie_key,))]

    def replace_metadata_scenes(self, movie_key: str, scenes: list[dict[str, Any]]) -> None:
        self.connection.execute("DELETE FROM movie_scene_metadata WHERE movie_key=?", (movie_key,))
        self.connection.executemany(
            "INSERT INTO movie_scene_metadata(movie_key,ordinal,scene_id,start_seconds,end_seconds) VALUES(?,?,?,?,?)",
            [(movie_key, item["ordinal"], item.get("scene_id"), item.get("start_seconds"), item.get("end_seconds"))
             for item in scenes],
        )

    def list_scenes(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT s.*,m.title,m.studio,m.movie_id FROM requested_scenes s JOIN movies m USING(movie_key) ORDER BY m.movie_id, s.ordinal, s.scene_id"
        )
        return [dict(row) for row in rows]

    def list_candidates(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """SELECT c.*,m.title,m.movie_id,
               (SELECT COUNT(*) FROM candidate_scenes cs WHERE cs.candidate_id=c.candidate_id) AS required_scene_count,
               (SELECT COUNT(*) FROM candidate_scenes cs JOIN requested_scenes s
                 ON s.movie_key=cs.movie_key AND s.scene_id=cs.scene_id
                 WHERE cs.candidate_id=c.candidate_id AND s.status='scene_verified') AS verified_scene_count,
               CASE WHEN c.classification='full_movie' AND c.identity_confirmed=1
                 AND EXISTS(SELECT 1 FROM candidate_scenes cs WHERE cs.candidate_id=c.candidate_id)
                 AND NOT EXISTS(SELECT 1 FROM candidate_scenes cs JOIN requested_scenes s
                   ON s.movie_key=cs.movie_key AND s.scene_id=cs.scene_id
                   WHERE cs.candidate_id=c.candidate_id AND s.status!='scene_verified')
                 THEN 1 ELSE 0 END AS eligible
               FROM media_candidates c JOIN movies m USING(movie_key) ORDER BY c.movie_key,c.path"""
        )
        return [dict(row) for row in rows]

    def list_jobs(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.connection.execute("SELECT * FROM download_jobs ORDER BY job_id")]

    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.connection.execute("SELECT value_json FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        self.connection.execute(
            "INSERT INTO settings(key,value_json) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
            (key, json.dumps(value, ensure_ascii=False)),
        )
