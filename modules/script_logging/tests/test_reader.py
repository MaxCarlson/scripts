from pathlib import Path
import sqlite3
import pytest

from script_logging.invocation_store import InvocationStore
from script_logging.reader import ReadOnlyHistoryReader, open_invocation_reader


def test_reader_does_not_create_missing_db(tmp_path: Path):
    missing_path = tmp_path / "nonexistent" / "invocations.sqlite3"
    with pytest.raises(FileNotFoundError, match="not found"):
        open_invocation_reader(missing_path)
    assert not missing_path.exists()
    assert not missing_path.parent.exists()


def test_reader_cannot_write(tmp_path: Path):
    db_path = tmp_path / "invocations.sqlite3"
    InvocationStore(db_path)  # create and initialize

    reader = open_invocation_reader(db_path)
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        with reader._connect() as conn:
            conn.execute("INSERT INTO schema_meta VALUES ('test', 'fail')")


def test_reader_default_path_resolution(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "env_test.sqlite3"
    monkeypatch.setenv("SCRIPT_LOGGING_INVOCATION_DB", str(db_path))

    # Should raise when database does not exist
    with pytest.raises(FileNotFoundError):
        open_invocation_reader()

    # Create it
    InvocationStore(db_path)
    reader = open_invocation_reader()
    assert isinstance(reader, ReadOnlyHistoryReader)
    assert reader.path == db_path
    with reader._connect() as conn:
        row = conn.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
        assert row["value"] == "1"
