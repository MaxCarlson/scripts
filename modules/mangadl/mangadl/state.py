from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from .models import InputUrl, JobState

SCHEMA_VERSION = 1


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=30, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA busy_timeout=30000")
        self._initialize()

    def _initialize(self) -> None:
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runs(
                id TEXT PRIMARY KEY, started REAL NOT NULL, finished REAL, status TEXT NOT NULL,
                config_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS jobs(
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES runs(id),
                url TEXT NOT NULL, canonical_url TEXT NOT NULL, source TEXT NOT NULL, source_line INTEGER NOT NULL,
                backend TEXT NOT NULL, state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                worker INTEGER, attempt_id TEXT, lease_deadline REAL, next_attempt REAL NOT NULL DEFAULT 0,
                images_done INTEGER NOT NULL DEFAULT 0, images_total INTEGER,
                bytes_done INTEGER NOT NULL DEFAULT 0, bytes_total INTEGER,
                title TEXT NOT NULL DEFAULT '', site TEXT NOT NULL DEFAULT '', destination TEXT NOT NULL DEFAULT '',
                error_category TEXT, error_message TEXT, created REAL NOT NULL, updated REAL NOT NULL,
                UNIQUE(run_id, canonical_url)
            );
            CREATE TABLE IF NOT EXISTS attempts(
                attempt_id TEXT PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id), worker INTEGER NOT NULL,
                started REAL NOT NULL, finished REAL, status TEXT NOT NULL, error_category TEXT, error_message TEXT
            );
            CREATE TABLE IF NOT EXISTS events(
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, job_id INTEGER NOT NULL,
                attempt_id TEXT NOT NULL, worker INTEGER NOT NULL, event TEXT NOT NULL, wall_time REAL NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS jobs_ready ON jobs(run_id, state, next_attempt);
            """)
        row = self.connection.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
        if row and int(row[0]) != SCHEMA_VERSION:
            raise RuntimeError(
                f"state schema {row[0]} is incompatible with {SCHEMA_VERSION}; no migrations are performed"
            )
        self.connection.execute(
            "INSERT OR IGNORE INTO metadata(key, value) VALUES('schema_version', ?)", (str(SCHEMA_VERSION),)
        )

    def close(self) -> None:
        self.connection.close()

    def create_run(self, config: dict[str, Any], run_id: str | None = None) -> str:
        run_id = run_id or time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
        self.connection.execute(
            "INSERT INTO runs(id, started, status, config_json) VALUES(?, ?, 'running', ?)",
            (run_id, time.time(), json.dumps(config, sort_keys=True, default=str)),
        )
        return run_id

    def add_jobs(self, run_id: str, inputs: list[InputUrl], backends: dict[str, str]) -> None:
        now = time.time()
        with self.connection:
            self.connection.executemany(
                """INSERT OR IGNORE INTO jobs(
                    run_id,url,canonical_url,source,source_line,backend,state,created,updated
                ) VALUES(?,?,?,?,?,?,'queued',?,?)""",
                [
                    (
                        run_id,
                        item.url,
                        item.canonical_url,
                        item.source,
                        item.line,
                        backends[item.canonical_url],
                        now,
                        now,
                    )
                    for item in inputs
                ],
            )

    def recover_expired(self, run_id: str, now: float | None = None) -> int:
        now = now or time.time()
        cursor = self.connection.execute(
            """UPDATE jobs SET state='queued', worker=NULL, attempt_id=NULL, lease_deadline=NULL, updated=?
               WHERE run_id=? AND state IN ('leased','running') AND lease_deadline < ?""",
            (now, run_id, now),
        )
        return cursor.rowcount

    def lease(self, run_id: str, worker: int, lease_seconds: float = 30.0) -> sqlite3.Row | None:
        now = time.time()
        attempt_id = uuid.uuid4().hex
        with self.connection:
            row = self.connection.execute(
                """SELECT * FROM jobs WHERE run_id=? AND state IN ('queued','retry_wait')
                   AND next_attempt <= ? ORDER BY id LIMIT 1""",
                (run_id, now),
            ).fetchone()
            if row is None:
                return None
            updated = self.connection.execute(
                """UPDATE jobs SET state='leased', worker=?, attempt_id=?, lease_deadline=?,
                   attempts=attempts+1, updated=? WHERE id=? AND state IN ('queued','retry_wait')""",
                (worker, attempt_id, now + lease_seconds, now, row["id"]),
            )
            if updated.rowcount != 1:
                return None
            self.connection.execute(
                "INSERT INTO attempts(attempt_id,job_id,worker,started,status) VALUES(?,?,?,?,'running')",
                (attempt_id, row["id"], worker, now),
            )
            return self.connection.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()

    def heartbeat(self, job_id: int, attempt_id: str, lease_seconds: float = 30.0) -> bool:
        cursor = self.connection.execute(
            "UPDATE jobs SET lease_deadline=?, updated=? WHERE id=? AND attempt_id=? AND state IN ('leased','running')",
            (time.time() + lease_seconds, time.time(), job_id, attempt_id),
        )
        return cursor.rowcount == 1

    def apply_event(self, event: dict[str, Any]) -> bool:
        row = self.connection.execute("SELECT attempt_id,state FROM jobs WHERE id=?", (event["job_id"],)).fetchone()
        if row is None or row["attempt_id"] != event["attempt_id"]:
            return False
        data = event.get("data", {})
        state = data.get("state")
        values = {
            "images_done": data.get("images_done"),
            "images_total": data.get("images_total"),
            "bytes_done": data.get("bytes_done"),
            "bytes_total": data.get("bytes_total"),
            "title": data.get("title"),
            "site": data.get("site"),
            "destination": data.get("destination"),
        }
        assignments = ["updated=?"]
        params: list[Any] = [time.time()]
        if state:
            assignments.append("state=?")
            params.append(state)
        for key, value in values.items():
            if value is not None:
                assignments.append(f"{key}=?")
                params.append(value)
        self.connection.execute(
            f"UPDATE jobs SET {','.join(assignments)} WHERE id=? AND attempt_id=?",
            (*params, event["job_id"], event["attempt_id"]),
        )
        self.connection.execute(
            "INSERT INTO events(run_id,job_id,attempt_id,worker,event,wall_time,payload_json) VALUES(?,?,?,?,?,?,?)",
            (
                event["run_id"],
                event["job_id"],
                event["attempt_id"],
                event["worker"],
                event["event"],
                event["wall_time"],
                json.dumps(data, sort_keys=True),
            ),
        )
        return True

    def complete(self, job_id: int, attempt_id: str, state: JobState, category: str = "", message: str = "") -> bool:
        now = time.time()
        with self.connection:
            cursor = self.connection.execute(
                """UPDATE jobs SET state=?,error_category=?,error_message=?,worker=NULL,lease_deadline=NULL,updated=?
                   WHERE id=? AND attempt_id=?""",
                (state.value, category or None, message or None, now, job_id, attempt_id),
            )
            if cursor.rowcount != 1:
                return False
            self.connection.execute(
                "UPDATE attempts SET finished=?,status=?,error_category=?,error_message=? WHERE attempt_id=?",
                (now, state.value, category or None, message or None, attempt_id),
            )
            return True

    def retry(self, job_id: int, attempt_id: str, delay: float, category: str, message: str) -> bool:
        now = time.time()
        with self.connection:
            cursor = self.connection.execute(
                """UPDATE jobs SET state='retry_wait',next_attempt=?,error_category=?,error_message=?,
                   worker=NULL,lease_deadline=NULL,updated=? WHERE id=? AND attempt_id=?""",
                (now + delay, category, message, now, job_id, attempt_id),
            )
            self.connection.execute(
                "UPDATE attempts SET finished=?,status='retry_wait',error_category=?,error_message=? WHERE attempt_id=?",
                (now, category, message, attempt_id),
            )
            return cursor.rowcount == 1

    def jobs(self, run_id: str) -> list[dict[str, Any]]:
        return [
            dict(row) for row in self.connection.execute("SELECT * FROM jobs WHERE run_id=? ORDER BY id", (run_id,))
        ]

    def counts(self, run_id: str) -> dict[str, int]:
        return {
            row[0]: row[1]
            for row in self.connection.execute(
                "SELECT state,COUNT(*) FROM jobs WHERE run_id=? GROUP BY state", (run_id,)
            )
        }

    def finish_run(self, run_id: str, status: str) -> None:
        self.connection.execute("UPDATE runs SET finished=?,status=? WHERE id=?", (time.time(), status, run_id))

    def latest_run(self) -> str | None:
        row = self.connection.execute("SELECT id FROM runs ORDER BY started DESC LIMIT 1").fetchone()
        return row[0] if row else None
