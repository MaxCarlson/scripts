"""
Unit tests for db_manager.backup.
"""

import json
from pathlib import Path
import sqlite3
import pytest

from db_manager.connections import get_readonly_connection
from db_manager.backup import (
    backup_database,
    restore_database,
)


def _init_source_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("CREATE TABLE records (id INT PRIMARY KEY, text TEXT);")
        for i in range(10):
            conn.execute("INSERT INTO records VALUES (?, ?);", (i, f"item-{i}"))


def test_backup_creates_manifest_and_valid_db(tmp_path: Path):
    src = tmp_path / "source.db"
    dst = tmp_path / "backup_dest.db"
    _init_source_db(src)

    manifest = backup_database(src, dst)
    assert dst.exists()
    assert manifest.integrity_check_passed
    assert manifest.source_size_bytes > 0
    assert manifest.destination_size_bytes > 0
    assert len(manifest.destination_sha256) == 64

    # Manifest file check
    manifest_file = tmp_path / "backup_dest.db.manifest.json"
    assert manifest_file.exists()
    data = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert data["destination_sha256"] == manifest.destination_sha256

    # Verify backup contents
    with get_readonly_connection(dst) as conn:
        rows = conn.execute("SELECT count(*) FROM records;").fetchone()[0]
        assert rows == 10

    # Overwrite protection without force
    with pytest.raises(FileExistsError):
        backup_database(src, dst, force=False)

    # Overwrite succeeds with force
    manifest_forced = backup_database(src, dst, force=True)
    assert manifest_forced.integrity_check_passed


def test_restore_database(tmp_path: Path):
    src = tmp_path / "source.db"
    dst = tmp_path / "backup.db"
    _init_source_db(src)
    backup_database(src, dst)

    # 1. Restore to brand new location
    restored = tmp_path / "restored.db"
    report = restore_database(dst, restored)
    assert restored.exists()
    assert report.integrity_check_passed

    with get_readonly_connection(restored) as conn:
        rows = conn.execute("SELECT count(*) FROM records;").fetchone()[0]
        assert rows == 10

    # 2. Refuses to overwrite existing target without force
    with pytest.raises(FileExistsError):
        restore_database(dst, restored, force=False)

    # 3. Overwrites with force, creating pre-restore backup and cleaning stale WAL/SHM
    dummy_wal = tmp_path / "restored.db-wal"
    dummy_wal.write_text("stale wal data")

    report_force = restore_database(dst, restored, force=True, create_backup_of_target=True)
    assert report_force.integrity_check_passed
    assert report_force.stale_wal_shm_cleaned is True
    assert report_force.pre_restore_backup_path is not None
    assert Path(report_force.pre_restore_backup_path).exists()
    # Stale dummy data was cleaned (file is now either absent or reinitialized by SQLite)
    if dummy_wal.exists():
        assert dummy_wal.read_text(encoding="utf-8", errors="ignore") != "stale wal data"


def test_restore_safely_handles_locked_database(tmp_path: Path):
    src = tmp_path / "src_lock.db"
    dst = tmp_path / "bak_lock.db"
    _init_source_db(src)
    backup_database(src, dst)

    target = tmp_path / "target_live.db"
    _init_source_db(target)

    # Acquire an exclusive lock on target simulating an active writer/open connection
    lock_conn = sqlite3.connect(target)
    try:
        lock_conn.execute("BEGIN EXCLUSIVE;")
        # Attempting to restore over target must abort safely without unlinking or overwriting
        with pytest.raises(RuntimeError, match="Cannot establish exclusive ownership"):
            restore_database(dst, target, force=True)
    finally:
        lock_conn.close()


def test_restore_rollback_on_failure(tmp_path: Path, monkeypatch):
    import db_manager.backup

    src = tmp_path / "src_fail.db"
    dst = tmp_path / "bak_fail.db"
    _init_source_db(src)
    backup_database(src, dst)

    target = tmp_path / "target_to_protect.db"
    with sqlite3.connect(target) as conn:
        conn.execute("CREATE TABLE preserved (val TEXT);")
        conn.execute("INSERT INTO preserved VALUES ('critical data');")

    real_get_ro = db_manager.backup.get_readonly_connection
    bak_opens = 0

    class FailingBackupConn:
        def __init__(self, inner):
            self._inner = inner

        def backup(self, *args, **kwargs):
            raise RuntimeError("Simulated mid-restore storage failure")

        def __getattr__(self, name):
            return getattr(self._inner, name)

    class ManagedFailingConn:
        def __init__(self, inner):
            self._inner = inner

        def __enter__(self):
            return FailingBackupConn(self._inner.__enter__())

        def __exit__(self, exc_type, exc_val, exc_tb):
            return self._inner.__exit__(exc_type, exc_val, exc_tb)

    def mock_get_readonly(path, **kwargs):
        nonlocal bak_opens
        conn = real_get_ro(path, **kwargs)
        if Path(path).resolve() == dst.resolve():
            bak_opens += 1
            if bak_opens == 2:
                return ManagedFailingConn(conn)
        return conn

    monkeypatch.setattr(db_manager.backup, "get_readonly_connection", mock_get_readonly)

    with pytest.raises(RuntimeError, match="Target was safely rolled back"):
        restore_database(dst, target, force=True, create_backup_of_target=True)

    # Verify target was rolled back to its original state
    with get_readonly_connection(target) as conn:
        val = conn.execute("SELECT val FROM preserved;").fetchone()["val"]
        assert val == "critical data"
