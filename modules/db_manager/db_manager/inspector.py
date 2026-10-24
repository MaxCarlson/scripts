"""
inspector.py — Structural inspection, metadata extraction, and health checks for SQLite databases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3
from typing import Any

from db_manager.connections import get_readonly_connection


@dataclass(frozen=True)
class DatabaseInfo:
    path: str
    file_size_bytes: int
    sqlite_version: str
    page_size: int
    page_count: int
    calculated_db_size: int
    journal_mode: str
    wal_file_present: bool
    shm_file_present: bool
    schema_version: int
    user_version: int
    application_id: int
    foreign_keys_enabled: bool
    table_count: int
    view_count: int
    index_count: int
    trigger_count: int
    mtime_iso: str
    ctime_iso: str
    read_only_tested: bool = True
    assumptions_note: str = (
        "File metadata reflects current filesystem state. Page size and count are reported by PRAGMA. "
        "Integrity is not evaluated in info; use check for integrity verification."
    )


@dataclass(frozen=True)
class ColumnInfo:
    cid: int
    name: str
    type: str
    notnull: bool
    default_value: Any
    pk: int
    hidden: int = 0


@dataclass(frozen=True)
class IndexInfo:
    seq: int
    name: str
    unique: bool
    origin: str
    partial: bool
    columns: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ForeignKeyInfo:
    id: int
    seq: int
    table: str
    from_col: str
    to_col: str | None
    on_update: str
    on_delete: str
    match: str


@dataclass(frozen=True)
class TableSummary:
    name: str
    type: str  # "table", "view", "virtual table"
    is_without_rowid: bool
    column_count: int
    primary_keys: list[str]
    foreign_key_count: int
    index_count: int
    row_count: int | None
    row_count_exact: bool
    sql: str | None


@dataclass(frozen=True)
class TableSchema:
    name: str
    type: str
    sql: str | None
    is_without_rowid: bool
    columns: list[ColumnInfo]
    indexes: list[IndexInfo]
    foreign_keys: list[ForeignKeyInfo]


@dataclass(frozen=True)
class IntegrityReport:
    quick_check: list[str]
    integrity_check: list[str] | None
    foreign_key_violations: list[dict[str, Any]]
    is_healthy: bool
    notes: str = (
        "Integrity checks verify SQLite B-tree, page allocation, and foreign-key constraints. "
        "Passing integrity checks does not guarantee application-level business rule correctness."
    )


def _is_without_rowid(sql: str | None) -> bool:
    if not sql:
        return False
    # Check for WITHOUT ROWID clause at table definition end
    clean = re.sub(r"\s+", " ", sql).strip()
    return bool(re.search(r"\bWITHOUT\s+ROWID\b", clean, re.IGNORECASE))


def inspect_database(db_path: str | Path, timeout: float = 5.0) -> DatabaseInfo:
    """
    Extracts deep metadata and statistics from the target SQLite database.
    """
    path = Path(db_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Database file not found: {path}")

    stat = path.stat()
    file_size = stat.st_size
    mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
    ctime = datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).isoformat()

    wal_file = path.parent / f"{path.name}-wal"
    shm_file = path.parent / f"{path.name}-shm"

    with get_readonly_connection(path, timeout=timeout) as conn:
        sqlite_version = sqlite3.sqlite_version
        page_size = conn.execute("PRAGMA page_size;").fetchone()[0]
        page_count = conn.execute("PRAGMA page_count;").fetchone()[0]
        journal_mode = str(conn.execute("PRAGMA journal_mode;").fetchone()[0]).upper()
        schema_version = conn.execute("PRAGMA schema_version;").fetchone()[0]
        user_version = conn.execute("PRAGMA user_version;").fetchone()[0]
        application_id = conn.execute("PRAGMA application_id;").fetchone()[0]
        foreign_keys = bool(conn.execute("PRAGMA foreign_keys;").fetchone()[0])

        # Object counts from sqlite_master
        master_rows = conn.execute(
            "SELECT type, count(*) as cnt FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' GROUP BY type;"
        ).fetchall()
        counts = {row["type"]: row["cnt"] for row in master_rows}

    return DatabaseInfo(
        path=str(path),
        file_size_bytes=file_size,
        sqlite_version=sqlite_version,
        page_size=page_size,
        page_count=page_count,
        calculated_db_size=page_size * page_count,
        journal_mode=journal_mode,
        wal_file_present=wal_file.exists(),
        shm_file_present=shm_file.exists(),
        schema_version=schema_version,
        user_version=user_version,
        application_id=application_id,
        foreign_keys_enabled=foreign_keys,
        table_count=counts.get("table", 0),
        view_count=counts.get("view", 0),
        index_count=counts.get("index", 0),
        trigger_count=counts.get("trigger", 0),
        mtime_iso=mtime,
        ctime_iso=ctime,
    )


def list_tables(conn: sqlite3.Connection, exact_count: bool = False) -> list[TableSummary]:
    """
    Lists tables and views with schema metadata, column counts, indexes, and row estimates.
    Does not execute expensive COUNT(*) by default unless exact_count=True.
    """
    objects = conn.execute(
        "SELECT type, name, sql FROM sqlite_master "
        "WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' "
        "ORDER BY type, name;"
    ).fetchall()

    results: list[TableSummary] = []
    for obj in objects:
        name = obj["name"]
        raw_type = obj["type"]
        sql = obj["sql"]

        is_vtab = bool(sql and re.search(r"\bCREATE\s+VIRTUAL\s+TABLE\b", sql, re.IGNORECASE))
        table_type = "virtual table" if is_vtab else raw_type
        without_rowid = _is_without_rowid(sql)

        # Columns
        col_rows = conn.execute(f"PRAGMA table_info({_quote_ident(name)});").fetchall()
        column_count = len(col_rows)
        primary_keys = [c["name"] for c in col_rows if c["pk"] > 0]

        # Foreign keys
        fk_rows = conn.execute(f"PRAGMA foreign_key_list({_quote_ident(name)});").fetchall()
        foreign_key_count = len(set(f["id"] for f in fk_rows))

        # Indexes
        idx_rows = conn.execute(f"PRAGMA index_list({_quote_ident(name)});").fetchall()
        index_count = len(idx_rows)

        # Row count
        row_count = None
        if exact_count and raw_type == "table":
            try:
                row_count = conn.execute(f"SELECT COUNT(*) FROM {_quote_ident(name)};").fetchone()[0]
            except sqlite3.OperationalError:
                row_count = None

        results.append(
            TableSummary(
                name=name,
                type=table_type,
                is_without_rowid=without_rowid,
                column_count=column_count,
                primary_keys=primary_keys,
                foreign_key_count=foreign_key_count,
                index_count=index_count,
                row_count=row_count,
                row_count_exact=exact_count,
                sql=sql,
            )
        )

    return results


def get_schema(conn: sqlite3.Connection, table_name: str | None = None) -> list[TableSchema]:
    """
    Fetches full DDL, columns, foreign keys, and index definitions for tables/views.
    """
    query = "SELECT type, name, sql FROM sqlite_master WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'"
    params: list[Any] = []
    if table_name:
        query += " AND name = ?"
        params.append(table_name)
    query += " ORDER BY type, name;"

    objects = conn.execute(query, params).fetchall()
    results: list[TableSchema] = []

    for obj in objects:
        name = obj["name"]
        raw_type = obj["type"]
        sql = obj["sql"]
        without_rowid = _is_without_rowid(sql)

        # Columns with table_xinfo fallback to table_info
        try:
            col_rows = conn.execute(f"PRAGMA table_xinfo({_quote_ident(name)});").fetchall()
        except sqlite3.OperationalError:
            col_rows = conn.execute(f"PRAGMA table_info({_quote_ident(name)});").fetchall()

        columns: list[ColumnInfo] = []
        for c in col_rows:
            hidden = c["hidden"] if "hidden" in c.keys() else 0
            columns.append(
                ColumnInfo(
                    cid=c["cid"],
                    name=c["name"],
                    type=c["type"] or "",
                    notnull=bool(c["notnull"]),
                    default_value=c["dflt_value"],
                    pk=c["pk"],
                    hidden=hidden,
                )
            )

        # Indexes
        idx_rows = conn.execute(f"PRAGMA index_list({_quote_ident(name)});").fetchall()
        indexes: list[IndexInfo] = []
        for idx in idx_rows:
            idx_name = idx["name"]
            # Fetch index columns
            idx_cols_rows = conn.execute(f"PRAGMA index_info({_quote_ident(idx_name)});").fetchall()
            idx_cols = [r["name"] for r in idx_cols_rows]
            indexes.append(
                IndexInfo(
                    seq=idx["seq"],
                    name=idx_name,
                    unique=bool(idx["unique"]),
                    origin=idx["origin"] if "origin" in idx.keys() else "",
                    partial=bool(idx["partial"]) if "partial" in idx.keys() else False,
                    columns=idx_cols,
                )
            )

        # Foreign keys
        fk_rows = conn.execute(f"PRAGMA foreign_key_list({_quote_ident(name)});").fetchall()
        foreign_keys: list[ForeignKeyInfo] = [
            ForeignKeyInfo(
                id=fk["id"],
                seq=fk["seq"],
                table=fk["table"],
                from_col=fk["from"],
                to_col=fk["to"],
                on_update=fk["on_update"],
                on_delete=fk["on_delete"],
                match=fk["match"],
            )
            for fk in fk_rows
        ]

        results.append(
            TableSchema(
                name=name,
                type=raw_type,
                sql=sql,
                is_without_rowid=without_rowid,
                columns=columns,
                indexes=indexes,
                foreign_keys=foreign_keys,
            )
        )

    return results


def check_database(
    conn: sqlite3.Connection, check_integrity: bool = False, check_foreign_keys: bool = True
) -> IntegrityReport:
    """
    Executes read-only PRAGMA quick_check, optional integrity_check, and foreign_key_check.
    """
    quick_rows = conn.execute("PRAGMA quick_check;").fetchall()
    quick_results = [r[0] for r in quick_rows]

    integrity_results: list[str] | None = None
    if check_integrity:
        int_rows = conn.execute("PRAGMA integrity_check;").fetchall()
        integrity_results = [r[0] for r in int_rows]

    fk_violations: list[dict[str, Any]] = []
    if check_foreign_keys:
        fk_rows = conn.execute("PRAGMA foreign_key_check;").fetchall()
        for r in fk_rows:
            # PRAGMA foreign_key_check returns: (table, rowid, parent_table, fk_index)
            fk_violations.append(
                {
                    "table": r[0],
                    "rowid": r[1],
                    "parent_table": r[2],
                    "fk_index": r[3],
                }
            )

    quick_ok = quick_results == ["ok"]
    integrity_ok = (integrity_results is None) or (integrity_results == ["ok"])
    fks_ok = len(fk_violations) == 0

    is_healthy = quick_ok and integrity_ok and fks_ok

    return IntegrityReport(
        quick_check=quick_results,
        integrity_check=integrity_results,
        foreign_key_violations=fk_violations,
        is_healthy=is_healthy,
    )


def _quote_ident(ident: str) -> str:
    """Escapes and double-quotes a SQLite identifier."""
    return f'"{ident.replace(chr(34), chr(34) + chr(34))}"'
