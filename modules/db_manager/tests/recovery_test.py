"""
Unit tests for db_manager.recovery.
"""

from pathlib import Path
import sqlite3

from db_manager.recovery import (
    check_sqlite_header,
    find_nearby_backups,
    diagnose_database_recovery,
)


def test_check_sqlite_header(tmp_path: Path):
    db_file = tmp_path / "valid.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute("CREATE TABLE t(x);")

    assert check_sqlite_header(db_file) is True

    corrupt_file = tmp_path / "corrupt.db"
    corrupt_file.write_bytes(b"NOT A SQLITE FILE HEADER")
    assert check_sqlite_header(corrupt_file) is False


def test_diagnose_and_find_nearby_backups(tmp_path: Path):
    db_file = tmp_path / "app.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute("CREATE TABLE users (id INT PRIMARY KEY);")

    # Create synthetic backup files
    bak1 = tmp_path / "app.db.pre-edit-20261024_090000.bak"
    with sqlite3.connect(bak1) as conn:
        conn.execute("CREATE TABLE users (id INT PRIMARY KEY);")

    bak1_manifest = tmp_path / "app.db.pre-edit-20261024_090000.bak.manifest.json"
    bak1_manifest.write_text('{"manifest_version": "1.0"}')

    candidates = find_nearby_backups(db_file)
    assert len(candidates) >= 1
    assert candidates[0].path == str(bak1)
    assert candidates[0].manifest_path == str(bak1_manifest)
    assert candidates[0].is_valid_sqlite is True

    # Run full diagnostics
    diag = diagnose_database_recovery(db_file)
    assert diag.header_valid is True
    assert diag.file_size_bytes > 0
    assert len(diag.nearby_backups) >= 1
    assert "Deleted rows cannot generally be reconstructed" in diag.notes
