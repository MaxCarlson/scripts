"""
connections.py — SQLite connection management with read-only and write safety policies.
"""

from __future__ import annotations

import logging
from pathlib import Path
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)

# Safe read-only PRAGMAs permitted in read-only mode
SAFE_READONLY_PRAGMAS = {
    "table_info",
    "table_xinfo",
    "index_list",
    "index_info",
    "index_xinfo",
    "foreign_key_list",
    "database_list",
    "quick_check",
    "integrity_check",
    "foreign_key_check",
    "foreign_keys",
    "user_version",
    "schema_version",
    "page_size",
    "page_count",
    "journal_mode",
    "application_id",
    "freelist_count",
    "data_version",
    "encoding",
    "compile_options",
    "query_only",
    "busy_timeout",
    "table_list",
}

# Pragmas that are read-only inspection even when given an argument (like table_name)
SAFE_PARAMETRIZED_PRAGMAS = {
    "table_info",
    "table_xinfo",
    "index_list",
    "index_info",
    "index_xinfo",
    "foreign_key_list",
    "quick_check",
    "integrity_check",
    "foreign_key_check",
    "table_list",
}


def read_only_authorizer(
    action: int, arg1: str | None, arg2: str | None, dbname: str | None, trigger: str | None
) -> int:
    """
    SQLite authorizer callback for strict read-only connections.
    Denies all DDL, DML, ATTACH, DETACH, VACUUM, and mutating PRAGMAs.
    """
    # Allow reading columns and selecting rows
    if action in (
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_FUNCTION,
        sqlite3.SQLITE_TRANSACTION,
        sqlite3.SQLITE_RECURSIVE,
    ):
        return sqlite3.SQLITE_OK

    # Strictly controlled PRAGMA handling
    if action == sqlite3.SQLITE_PRAGMA:
        pragma_name = (arg1 or "").lower()
        if pragma_name in SAFE_READONLY_PRAGMAS:
            # If an argument is provided, verify it is a safe parameterized inspection or benign setting
            if arg2 is not None and pragma_name not in SAFE_PARAMETRIZED_PRAGMAS:
                # Disallow modifying pragmas via query (e.g. PRAGMA user_version = 5)
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    # Deny everything else (INSERT, UPDATE, DELETE, CREATE, DROP, ALTER, ATTACH, DETACH, etc.)
    return sqlite3.SQLITE_DENY


def write_authorizer(action: int, arg1: str | None, arg2: str | None, dbname: str | None, trigger: str | None) -> int:
    """
    SQLite authorizer callback for write connections.
    Permits local DML and DDL, but strictly denies ATTACH and DETACH to prevent external file access.
    """
    if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH):
        return sqlite3.SQLITE_DENY

    if action == sqlite3.SQLITE_PRAGMA:
        pragma_name = (arg1 or "").lower()
        # Block dangerous system pragmas even in write mode
        if pragma_name in ("writable_schema", "load_extension"):
            return sqlite3.SQLITE_DENY

    return sqlite3.SQLITE_OK


class ManagedReadonlyConnection:
    """Wrapper around sqlite3.Connection ensuring connection is closed when context exits."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def __enter__(self) -> sqlite3.Connection:
        return self._conn

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self._conn.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

    def close(self) -> None:
        self._conn.close()


class ManagedWriteConnection:
    """Wrapper around sqlite3.Connection committing/rolling back and closing on exit."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def __enter__(self) -> sqlite3.Connection:
        return self._conn

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        try:
            if exc_type is not None:
                self._conn.rollback()
            else:
                self._conn.commit()
        finally:
            self._conn.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

    def close(self) -> None:
        self._conn.close()


def get_readonly_connection(db_path: str | Path, timeout: float = 5.0) -> ManagedReadonlyConnection:
    """
    Opens an existing SQLite database in strict read-only mode.

    Guarantees:
    - Never creates a non-existent database file or parent directories.
    - Connects using SQLite URI mode=ro.
    - Sets PRAGMA query_only = ON;.
    - Sets busy_timeout.
    - Uses sqlite3.Row row factory for column-aware dictionary-like access.
    - Disables extension loading.
    - Installs strict read_only_authorizer blocking ATTACH, DML, DDL, and mutating PRAGMAs.
    """
    path = Path(db_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Database file not found: {path}")
    if not path.is_file():
        raise ValueError(f"Target path is not a file: {path}")

    # Use URI mode=ro to enforce read-only at the SQLite VFS layer
    uri = path.as_uri() + "?mode=ro"
    timeout_seconds = max(0.1, float(timeout))

    try:
        conn = sqlite3.connect(
            uri,
            uri=True,
            timeout=timeout_seconds,
            check_same_thread=False,
        )
    except sqlite3.OperationalError as exc:
        raise sqlite3.OperationalError(f"Cannot open SQLite database in read-only mode '{path}': {exc}") from exc

    conn.row_factory = sqlite3.Row

    # Disable dynamic extension loading if supported
    if hasattr(conn, "enable_load_extension"):
        try:
            conn.enable_load_extension(False)
        except (AttributeError, sqlite3.OperationalError):
            pass

    # Configure timeout and query_only mode
    busy_ms = int(timeout_seconds * 1000)
    conn.execute(f"PRAGMA busy_timeout = {busy_ms};")
    conn.execute("PRAGMA query_only = ON;")

    # Install read-only authorizer
    conn.set_authorizer(read_only_authorizer)

    return ManagedReadonlyConnection(conn)


def get_write_connection(
    db_path: str | Path,
    timeout: float = 10.0,
    enforce_foreign_keys: bool = True,
    create_if_missing: bool = False,
) -> ManagedWriteConnection:
    """
    Opens a SQLite database for controlled transactional writing.

    Guarantees:
    - Fails if the file does not exist unless create_if_missing=True.
    - Connects with mode=rw (or mode=rwc if create_if_missing).
    - Sets foreign_keys enforcement if enabled.
    - Sets busy timeout.
    - Uses sqlite3.Row row factory.
    - Installs write_authorizer blocking ATTACH/DETACH and dangerous pragmas.
    """
    path = Path(db_path).resolve()
    if not create_if_missing:
        if not path.exists():
            raise FileNotFoundError(f"Database file not found: {path}")
        if not path.is_file():
            raise ValueError(f"Target path is not a file: {path}")

    timeout_seconds = max(0.1, float(timeout))

    if create_if_missing:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(path),
            timeout=timeout_seconds,
            check_same_thread=False,
        )
    else:
        uri = path.as_uri() + "?mode=rw"
        conn = sqlite3.connect(
            uri,
            uri=True,
            timeout=timeout_seconds,
            check_same_thread=False,
        )

    conn.row_factory = sqlite3.Row

    if hasattr(conn, "enable_load_extension"):
        try:
            conn.enable_load_extension(False)
        except (AttributeError, sqlite3.OperationalError):
            pass

    busy_ms = int(timeout_seconds * 1000)
    conn.execute(f"PRAGMA busy_timeout = {busy_ms};")

    if enforce_foreign_keys:
        conn.execute("PRAGMA foreign_keys = ON;")

    conn.set_authorizer(write_authorizer)

    return ManagedWriteConnection(conn)
