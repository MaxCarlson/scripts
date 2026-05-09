from __future__ import annotations

import sqlite3
from pathlib import Path

from jellyfin_doctor.diagnose import diagnose_db, diagnose_logs, diagnose_paths
from jellyfin_doctor.paths import JellyfinPaths


def test_diagnose_db_valid_database_ok(work_tmp: Path) -> None:
    db = work_tmp / "jellyfin.db"
    conn = sqlite3.connect(db)
    for table in ("__EFMigrationsHistory", "Devices", "Users", "DisplayPreferences", "ActivityLogs"):
        conn.execute(f"CREATE TABLE {table} (id TEXT)")
    conn.commit()
    conn.close()
    result = diagnose_db(database=db)
    assert result["status"] == "ok"
    assert result["quick_check"] == "ok"


def test_diagnose_db_missing_migrations_table(work_tmp: Path) -> None:
    db = work_tmp / "jellyfin.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE Users (id TEXT)")
    conn.commit()
    conn.close()
    result = diagnose_db(database=db)
    assert result["status"] == "missing_table"
    assert "__EFMigrationsHistory" in result["missing_tables"]


def test_diagnose_db_unreadable_missing_file(work_tmp: Path) -> None:
    result = diagnose_db(database=work_tmp / "missing.db")
    assert result["status"] == "unreadable"


def test_diagnose_logs_missing_log(work_tmp: Path) -> None:
    result = diagnose_logs(log_dir=work_tmp, lines=100)
    assert result["status"] == "missing_log"


def test_diagnose_paths_reports_state_dirs(work_tmp: Path) -> None:
    paths = JellyfinPaths.from_overrides(server_dir=work_tmp / "server")
    paths.cache_dir.mkdir(parents=True)
    (paths.cache_dir / "x").write_text("x", encoding="utf-8")
    result = diagnose_paths(paths)
    assert result["cache"]["exists"] is True
    assert result["cache"]["files"] == 1


