"""Read-only SQLite query interface for command invocation history."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from .invocation_store import resolve_invocation_db_path


class ReadOnlyHistoryReader:
    """Read-only reader for querying invocation history and statistics.

    Uses SQLite URI read-only mode (mode=ro) to guarantee no write locks, journal files,
    or database mutations can occur during queries.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).resolve()
        if not self.path.is_file():
            raise FileNotFoundError(f"Invocation database not found at {self.path}")

    def _connect(self) -> sqlite3.Connection:
        """Create a read-only SQLite connection using URI mode=ro."""
        uri = f"file:{self.path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 15000;")
        return conn


def open_invocation_reader(path: Optional[Path | str] = None) -> ReadOnlyHistoryReader:
    """Open a read-only reader for the invocation database.

    Args:
        path: Path to invocations SQLite file. If None, resolves default platform path.

    Returns:
        ReadOnlyHistoryReader instance.

    Raises:
        FileNotFoundError: If the database file does not exist.
    """
    if path is None:
        target_path = resolve_invocation_db_path(create=False)
    else:
        target_path = Path(path).resolve()

    return ReadOnlyHistoryReader(target_path)
