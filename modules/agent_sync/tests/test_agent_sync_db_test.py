import sqlite3
from pathlib import Path

import pytest

from agent_sync.db.connection import get_connection
from agent_sync.db.schema import initialize_schema


def test_get_connection_returns_connection(tmp_path: Path) -> None:
    db_path = tmp_path / "test.sqlite3"
    conn = get_connection(db_path)
    assert isinstance(conn, sqlite3.Connection)
    conn.close()


def test_get_connection_enables_wal(tmp_path: Path) -> None:
    db_path = tmp_path / "test.sqlite3"
    conn = get_connection(db_path)
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"
    conn.close()


def test_get_connection_enforces_foreign_keys(tmp_path: Path) -> None:
    db_path = tmp_path / "test.sqlite3"
    conn = get_connection(db_path)
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk == 1
    conn.close()


def test_get_connection_creates_parent_dirs(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "dir" / "state.sqlite3"
    conn = get_connection(db_path)
    assert db_path.exists()
    conn.close()


def test_initialize_schema_creates_tables(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / "state.sqlite3")
    initialize_schema(conn)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    expected = {
        "schema_meta", "agents", "tasks", "task_dependencies",
        "runs", "claims", "handoffs", "events", "artifacts", "memory_links",
    }
    assert expected.issubset(tables)
    conn.close()


def test_initialize_schema_is_idempotent(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / "state.sqlite3")
    initialize_schema(conn)
    initialize_schema(conn)  # should not raise
    conn.close()


def test_schema_meta_has_version(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / "state.sqlite3")
    initialize_schema(conn)
    version = conn.execute("SELECT schema_version FROM schema_meta").fetchone()
    assert version is not None
    assert version[0] == 1
    conn.close()
