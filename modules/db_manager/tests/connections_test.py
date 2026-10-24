"""
Unit tests for db_manager.connections.
"""

from pathlib import Path
import sqlite3
import pytest

from db_manager.connections import get_readonly_connection, get_write_connection


def test_readonly_nonexistent_file_raises_and_creates_nothing(tmp_path: Path):
    nonexistent = tmp_path / "subdir" / "does_not_exist.db"
    with pytest.raises(FileNotFoundError):
        get_readonly_connection(nonexistent)

    assert not nonexistent.exists()
    assert not nonexistent.parent.exists()


def test_readonly_allows_reads_and_safe_pragmas(tmp_path: Path):
    db_file = tmp_path / "sample.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);")
        conn.execute("INSERT INTO users (name) VALUES ('Alice');")

    with get_readonly_connection(db_file) as ro_conn:
        cur = ro_conn.execute("SELECT name FROM users WHERE id = 1;")
        row = cur.fetchone()
        assert row is not None
        assert row["name"] == "Alice"

        # Safe pragmas must succeed
        page_size = ro_conn.execute("PRAGMA page_size;").fetchone()
        assert page_size is not None and page_size[0] > 0

        info = ro_conn.execute("PRAGMA table_info('users');").fetchall()
        assert len(info) == 2


def test_readonly_blocks_dml(tmp_path: Path):
    db_file = tmp_path / "sample.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);")
        conn.execute("INSERT INTO users (name) VALUES ('Alice');")

    with get_readonly_connection(db_file) as ro_conn:
        with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
            ro_conn.execute("INSERT INTO users (name) VALUES ('Bob');")

        with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
            ro_conn.execute("UPDATE users SET name = 'Charlie' WHERE id = 1;")

        with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
            ro_conn.execute("DELETE FROM users WHERE id = 1;")


def test_readonly_blocks_ddl_and_attach(tmp_path: Path):
    db_file = tmp_path / "sample.db"
    other_db = tmp_path / "other.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute("CREATE TABLE t (x INT);")
    with sqlite3.connect(other_db) as conn:
        conn.execute("CREATE TABLE o (y INT);")

    with get_readonly_connection(db_file) as ro_conn:
        with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
            ro_conn.execute("CREATE TABLE evil (z INT);")

        with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
            ro_conn.execute("DROP TABLE t;")

        with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
            ro_conn.execute("ALTER TABLE t ADD COLUMN w TEXT;")

        with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
            ro_conn.execute(f"ATTACH DATABASE '{other_db}' AS other;")

        with pytest.raises(sqlite3.DatabaseError, match=r"(not authorized|authorization denied)"):
            ro_conn.execute("VACUUM;")


def test_write_connection_allows_dml_and_blocks_attach(tmp_path: Path):
    db_file = tmp_path / "write_sample.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute("CREATE TABLE t (id INT PRIMARY KEY, val TEXT);")

    other_db = tmp_path / "other.db"
    with sqlite3.connect(other_db) as conn:
        conn.execute("CREATE TABLE o (y INT);")

    with get_write_connection(db_file) as w_conn:
        w_conn.execute("INSERT INTO t VALUES (1, 'hello');")
        w_conn.commit()

        # Check write succeeded
        cur = w_conn.execute("SELECT val FROM t WHERE id = 1;")
        assert cur.fetchone()["val"] == "hello"

        # ATTACH must be denied even in write mode
        with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
            w_conn.execute(f"ATTACH DATABASE '{other_db}' AS other;")
