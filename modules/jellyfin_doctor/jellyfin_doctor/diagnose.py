"""Diagnostic commands for Jellyfin logs, DBs, processes, and paths."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .logs import analyze_lines, read_recent_lines
from .paths import JellyfinPaths, resolve_log_file
from .process import find_processes
from .utils import tree_size

KEY_TABLES = ("__EFMigrationsHistory", "Devices", "Users", "DisplayPreferences", "ActivityLogs")


def diagnose_logs(*, log_file: Path | None = None, log_dir: Path | None = None, lines: int = 500) -> dict[str, object]:
    """Analyze recent Jellyfin log lines."""
    resolved = resolve_log_file(log_file, log_dir)
    if resolved is None or not resolved.exists():
        return {"status": "missing_log", "log_file": resolved, "summary": None}
    summary = analyze_lines(read_recent_lines(resolved, lines=lines))
    return {"status": "ok", "log_file": resolved, "summary": summary.to_dict()}


def diagnose_db(*, database: Path, full: bool = False, force: bool = False) -> dict[str, object]:
    """Run offline SQLite checks for a Jellyfin database."""
    del force
    if not database.exists():
        return {"status": "unreadable", "database": database, "error": "database file does not exist"}
    try:
        conn = sqlite3.connect(str(database), timeout=0.2)
        try:
            quick_check = conn.execute("PRAGMA quick_check;").fetchone()[0]
            integrity_check = conn.execute("PRAGMA integrity_check;").fetchone()[0] if full else None
            journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
            page_count = conn.execute("PRAGMA page_count;").fetchone()[0]
            freelist_count = conn.execute("PRAGMA freelist_count;").fetchone()[0]
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            missing = [table for table in KEY_TABLES if table not in tables]
        finally:
            conn.close()
    except sqlite3.OperationalError as exc:
        text = str(exc).lower()
        if "locked" in text:
            return {"status": "locked", "database": database, "error": str(exc)}
        return {"status": "corrupt", "database": database, "error": str(exc)}
    except Exception as exc:
        return {"status": "unreadable", "database": database, "error": str(exc)}
    status = "ok"
    if quick_check != "ok" or (integrity_check not in (None, "ok")):
        status = "corrupt"
    elif missing:
        status = "missing_table"
    return {
        "status": status,
        "database": database,
        "quick_check": quick_check,
        "integrity_check": integrity_check,
        "journal_mode": journal_mode,
        "page_count": page_count,
        "freelist_count": freelist_count,
        "missing_tables": missing,
    }


def diagnose_processes(processes: list[str] | None = None) -> dict[str, object]:
    """Return matching Jellyfin process information."""
    return {"processes": find_processes(processes or ["jellyfin", "Jellyfin.Windows.Tray", "ffmpeg", "ffprobe"])}


def diagnose_paths(paths: JellyfinPaths) -> dict[str, object]:
    """Return path status for Jellyfin state directories."""
    result: dict[str, object] = {}
    for name, path in paths.report_dirs().items():
        bytes_total, files = tree_size(path)
        disabled = []
        if path.parent.exists():
            disabled = sorted(path.parent.glob(f"{path.name}.disabled.*"))
        result[name] = {
            "path": path,
            "exists": path.exists(),
            "bytes": bytes_total,
            "files": files,
            "last_write_time": path.stat().st_mtime if path.exists() else None,
            "disabled": disabled,
        }
    return result

