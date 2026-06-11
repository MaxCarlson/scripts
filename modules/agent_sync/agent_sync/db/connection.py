"""SQLite connection helpers."""

from pathlib import Path
import sqlite3


def get_connection(path: Path) -> sqlite3.Connection:
    """Open a SQLite connection using agent_sync defaults."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn
