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
    assert report_force.target_preexisted is True
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


def test_restore_without_backup_leaves_existing_target_intact_on_failure(tmp_path: Path, monkeypatch):
    import db_manager.backup

    src = tmp_path / "src_nobak.db"
    dst = tmp_path / "bak_nobak.db"
    _init_source_db(src)
    backup_database(src, dst)

    target = tmp_path / "target_never_delete.db"
    with sqlite3.connect(target) as conn:
        conn.execute("CREATE TABLE irreplaceable (val TEXT);")
        conn.execute("INSERT INTO irreplaceable VALUES ('safe and sound');")

    real_get_ro = db_manager.backup.get_readonly_connection
    bak_opens = 0

    class FailingBackupConn:
        def __init__(self, inner):
            self._inner = inner

        def backup(self, *args, **kwargs):
            raise RuntimeError("Simulated network/disk crash during restore")

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

    # When create_backup_of_target=False, a failure MUST NEVER delete the target
    with pytest.raises(RuntimeError, match="Target database pre-existed and create_backup_of_target was False"):
        restore_database(dst, target, force=True, create_backup_of_target=False)

    # Verify target was NOT deleted and its original data remains intact
    assert target.exists()
    with get_readonly_connection(target) as conn:
        val = conn.execute("SELECT val FROM irreplaceable;").fetchone()["val"]
        assert val == "safe and sound"


def test_online_backup_manifest_distinguishes_raw_source_from_wal_snapshot(tmp_path: Path):
    src = tmp_path / "wal_source.db"
    dst = tmp_path / "wal_snapshot.db"

    # Setup database with active uncheckpointed WAL frames
    conn_reader = sqlite3.connect(src)
    try:
        conn_reader.execute("PRAGMA journal_mode = WAL;")
        conn_reader.execute("CREATE TABLE test_data (id INT, text TEXT);")

        conn_writer = sqlite3.connect(src)
        try:
            for i in range(100):
                conn_writer.execute("INSERT INTO test_data VALUES (?, ?);", (i, f"data-{i} * 1000"))
            conn_writer.commit()
        finally:
            conn_writer.close()

        # WAL file should exist
        wal_file = tmp_path / "wal_source.db-wal"
        assert wal_file.exists()
        assert wal_file.stat().st_size > 0

        manifest = backup_database(src, dst, write_manifest=True)

        assert manifest.is_wal_mode is True
        assert manifest.wal_file_present is True
        assert manifest.source_file_sha256 != ""
        assert manifest.backup_snapshot_sha256 != ""
        assert manifest.source_wal_file_sha256 is not None
        assert "backup_snapshot_sha256 represents the logical, WAL-consistent database snapshot" in manifest.audit_notes

        # Because WAL frames were pending and online backup consolidates them into the destination snapshot,
        # the raw source main file sha256 differs from the WAL-consistent backup snapshot sha256
        assert manifest.source_file_sha256 != manifest.backup_snapshot_sha256

        # Verify the backup snapshot has all 100 rows
        with get_readonly_connection(dst) as conn:
            assert conn.execute("SELECT count(*) FROM test_data;").fetchone()[0] == 100
    finally:
        conn_reader.close()
