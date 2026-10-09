"""SQLite event and process-run history with independent output retention."""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def _epoch(value: str) -> float:
    """Normalize ISO timestamps for cross-offset range queries."""
    parsed = datetime.fromisoformat(value)
    return parsed.timestamp()


@dataclass(frozen=True)
class EventRecord:
    source: str
    event_type: str
    occurred_at: str
    message: str
    entity_type: str = ""
    entity_id: str = ""
    level: str = "INFO"
    metadata: Dict[str, Any] = field(default_factory=dict)
    record_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass(frozen=True)
class RunRecord:
    source: str
    entity_type: str
    entity_id: str
    display_name: str
    started_at: str
    finished_at: str
    status: str
    duration_sec: float
    exit_code: int
    origin: str = "manual"
    scheduled_for: Optional[str] = None
    parent_id: Optional[str] = None
    stdout: Optional[str] = ""
    stderr: Optional[str] = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    record_id: str = field(default_factory=lambda: uuid.uuid4().hex)


class HistoryStore:
    """Durable generic history for applications and jobs.

    Each operation opens a short SQLite transaction. Callers may use the same
    database from independent processes without sharing a Python lock.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    record_id TEXT PRIMARY KEY, source TEXT NOT NULL,
                    event_type TEXT NOT NULL, occurred_at TEXT NOT NULL,
                    occurred_epoch REAL NOT NULL, message TEXT NOT NULL,
                    entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
                    level TEXT NOT NULL, metadata_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_source_time ON events(source, occurred_epoch);
                CREATE INDEX IF NOT EXISTS events_entity_time ON events(source, entity_type, entity_id, occurred_epoch);
                CREATE TABLE IF NOT EXISTS runs (
                    record_id TEXT PRIMARY KEY, source TEXT NOT NULL,
                    entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
                    display_name TEXT NOT NULL, started_at TEXT NOT NULL,
                    started_epoch REAL NOT NULL, finished_at TEXT NOT NULL,
                    status TEXT NOT NULL, duration_sec REAL NOT NULL,
                    exit_code INTEGER NOT NULL, origin TEXT NOT NULL,
                    scheduled_for TEXT, parent_id TEXT,
                    stdout TEXT, stderr TEXT, metadata_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS runs_entity_time ON runs(source, entity_type, entity_id, started_epoch);
                CREATE INDEX IF NOT EXISTS runs_parent_time ON runs(source, parent_id, started_epoch);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.path), timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout = 15000")
        return db

    def append_event(self, event: EventRecord) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event.record_id, event.source, event.event_type, event.occurred_at,
                    _epoch(event.occurred_at), event.message, event.entity_type, event.entity_id,
                    event.level, json.dumps(event.metadata, ensure_ascii=False),
                ),
            )

    def append_run(self, run: RunRecord) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run.record_id, run.source, run.entity_type, run.entity_id, run.display_name,
                    run.started_at, _epoch(run.started_at), run.finished_at, run.status,
                    run.duration_sec, run.exit_code, run.origin, run.scheduled_for, run.parent_id,
                    run.stdout, run.stderr, json.dumps(run.metadata, ensure_ascii=False),
                ),
            )

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> RunRecord:
        return RunRecord(
            record_id=row["record_id"], source=row["source"], entity_type=row["entity_type"],
            entity_id=row["entity_id"], display_name=row["display_name"],
            started_at=row["started_at"], finished_at=row["finished_at"],
            status=row["status"], duration_sec=row["duration_sec"], exit_code=row["exit_code"],
            origin=row["origin"], scheduled_for=row["scheduled_for"], parent_id=row["parent_id"],
            stdout=row["stdout"], stderr=row["stderr"], metadata=json.loads(row["metadata_json"]),
        )

    def get_run(self, record_id: str) -> Optional[RunRecord]:
        with self._connect() as db:
            row = db.execute("SELECT * FROM runs WHERE record_id = ?", (record_id,)).fetchone()
        return self._run_from_row(row) if row else None

    def list_runs(
        self, *, source: Optional[str] = None, entity_type: Optional[str] = None,
        entity_id: Optional[str] = None, parent_id: Optional[str] = None,
        since: Optional[str] = None, before: Optional[str] = None,
        limit: Optional[int] = None, include_output: bool = False,
    ) -> List[RunRecord]:
        clauses: List[str] = []
        values: List[Any] = []
        for column, value in (
            ("source", source), ("entity_type", entity_type), ("entity_id", entity_id), ("parent_id", parent_id),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                values.append(value)
        if since is not None:
            clauses.append("started_epoch >= ?")
            values.append(_epoch(since))
        if before is not None:
            clauses.append("started_epoch < ?")
            values.append(_epoch(before))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        selection = "*" if include_output else (
            "record_id, source, entity_type, entity_id, display_name, started_at, started_epoch, "
            "finished_at, status, duration_sec, exit_code, origin, scheduled_for, parent_id, "
            "NULL AS stdout, NULL AS stderr, metadata_json"
        )
        query = "SELECT " + selection + " FROM runs" + where + " ORDER BY started_epoch DESC, record_id DESC"
        if limit is not None:
            query += " LIMIT ?"
            values.append(max(0, limit))
        with self._connect() as db:
            rows = db.execute(query, values).fetchall()
        return [self._run_from_row(row) for row in rows]

    def list_events(
        self, *, source: Optional[str] = None, entity_type: Optional[str] = None,
        entity_id: Optional[str] = None, since: Optional[str] = None,
        event_type: Optional[str] = None,
    ) -> List[EventRecord]:
        clauses: List[str] = []
        values: List[Any] = []
        for column, value in (
            ("source", source), ("entity_type", entity_type),
            ("entity_id", entity_id), ("event_type", event_type),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                values.append(value)
        if since is not None:
            clauses.append("occurred_epoch >= ?")
            values.append(_epoch(since))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as db:
            rows = db.execute("SELECT * FROM events" + where + " ORDER BY occurred_epoch DESC", values).fetchall()
        return [
            EventRecord(
                record_id=row["record_id"], source=row["source"], event_type=row["event_type"],
                occurred_at=row["occurred_at"], message=row["message"],
                entity_type=row["entity_type"], entity_id=row["entity_id"], level=row["level"],
                metadata=json.loads(row["metadata_json"]),
            )
            for row in rows
        ]

    def prune_output(self, before: str, *, source: Optional[str] = None) -> int:
        clauses = "started_epoch < ?"
        values: List[Any] = [_epoch(before)]
        if source is not None:
            clauses += " AND source = ?"
            values.append(source)
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE runs SET stdout = NULL, stderr = NULL WHERE " + clauses + " AND stdout IS NOT NULL", values
            )
            return cursor.rowcount

    def clear(self, *, source: Optional[str] = None) -> None:
        with self._connect() as db:
            if source is None:
                db.execute("DELETE FROM events")
                db.execute("DELETE FROM runs")
            else:
                db.execute("DELETE FROM events WHERE source = ?", (source,))
                db.execute("DELETE FROM runs WHERE source = ?", (source,))

    def clear_events(self, *, source: Optional[str] = None) -> None:
        with self._connect() as db:
            if source is None:
                db.execute("DELETE FROM events")
            else:
                db.execute("DELETE FROM events WHERE source = ?", (source,))

    def clear_runs(self, *, source: Optional[str] = None) -> None:
        with self._connect() as db:
            if source is None:
                db.execute("DELETE FROM runs")
            else:
                db.execute("DELETE FROM runs WHERE source = ?", (source,))
