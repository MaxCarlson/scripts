"""
query.py — Parameterized querying, bounded table browsing, and safe searching.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import sqlite3
import time
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BrowseResult:
    table: str
    columns: list[str]
    rows: list[dict[str, Any]]
    total_rows: int | None
    limit: int
    offset: int
    has_more: bool


@dataclass(frozen=True)
class SearchResult:
    table: str
    pattern: str
    searched_columns: list[str]
    matches: list[dict[str, Any]]
    is_full_scan: bool
    warning: str | None
    limit: int


@dataclass(frozen=True)
class QueryResult:
    sql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    execution_time_ms: float


def quote_identifier(ident: str) -> str:
    """Escapes and double-quotes a SQLite identifier."""
    if not ident:
        raise ValueError("Identifier cannot be empty")
    return f'"{ident.replace(chr(34), chr(34) + chr(34))}"'


def get_table_columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    """Retrieves validated column names for a table or view."""
    # Validate table exists
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (table_name,),
    ).fetchone()
    if not exists:
        raise ValueError(f"Table or view '{table_name}' does not exist in database")

    cols = conn.execute(f"PRAGMA table_info({quote_identifier(table_name)});").fetchall()
    return [c["name"] for c in cols]


def get_indexed_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    """Returns set of column names that participate in indexes or are primary keys."""
    indexed: set[str] = set()

    # PK columns
    cols = conn.execute(f"PRAGMA table_info({quote_identifier(table_name)});").fetchall()
    for c in cols:
        if c["pk"] > 0:
            indexed.add(c["name"])

    # Index columns
    idx_list = conn.execute(f"PRAGMA index_list({quote_identifier(table_name)});").fetchall()
    for idx in idx_list:
        idx_info = conn.execute(f"PRAGMA index_info({quote_identifier(idx['name'])});").fetchall()
        for r in idx_info:
            indexed.add(r["name"])

    return indexed


def format_value_for_display(val: Any, max_text_len: int = 120, max_blob_hex_len: int = 16) -> str:
    """
    Renders values safely for CLI display:
    - None -> <NULL>
    - bytes/blob -> <BLOB size bytes: 0xhex...>
    - long text -> truncated
    """
    if val is None:
        return "<NULL>"

    if isinstance(val, (bytes, bytearray, memoryview)):
        raw = bytes(val)
        size = len(raw)
        hex_slice = raw[:max_blob_hex_len].hex()
        ellipsis = "..." if size > max_blob_hex_len else ""
        return f"<BLOB {size} bytes: 0x{hex_slice}{ellipsis}>"

    text = str(val)
    if len(text) > max_text_len:
        return text[:max_text_len] + "..."
    return text


def browse_table(
    conn: sqlite3.Connection,
    table: str,
    columns: list[str] | None = None,
    filter_col: str | None = None,
    filter_val: Any = None,
    filter_op: str = "=",
    sort_col: str | None = None,
    sort_desc: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> BrowseResult:
    """
    Browses a table with bounded pagination, projection, filtering, and sorting.
    All table/column identifiers are strictly validated and quoted.
    Values are passed as parameters.
    """
    valid_cols = get_table_columns(conn, table)

    # Validate projection
    if columns:
        for c in columns:
            if c not in valid_cols:
                raise ValueError(f"Unknown column '{c}' in table '{table}'")
        selected_cols = columns
    else:
        selected_cols = valid_cols

    quoted_table = quote_identifier(table)
    quoted_proj = ", ".join(quote_identifier(c) for c in selected_cols)

    sql_parts = [f"SELECT {quoted_proj} FROM {quoted_table}"]
    params: list[Any] = []

    # Optional filter
    if filter_col:
        if filter_col not in valid_cols:
            raise ValueError(f"Filter column '{filter_col}' does not exist in table '{table}'")
        op = filter_op.strip().upper()
        allowed_ops = {"=", "!=", "<>", ">", "<", ">=", "<=", "LIKE", "IS", "IS NOT"}
        if op not in allowed_ops:
            raise ValueError(f"Unsupported filter operator: '{filter_op}'")

        if filter_val is None:
            if op in ("=", "IS"):
                sql_parts.append(f"WHERE {quote_identifier(filter_col)} IS NULL")
            else:
                sql_parts.append(f"WHERE {quote_identifier(filter_col)} IS NOT NULL")
        else:
            sql_parts.append(f"WHERE {quote_identifier(filter_col)} {op} ?")
            params.append(filter_val)

    # Sorting
    if sort_col:
        if sort_col not in valid_cols:
            raise ValueError(f"Sort column '{sort_col}' does not exist in table '{table}'")
        order_dir = "DESC" if sort_desc else "ASC"
        sql_parts.append(f"ORDER BY {quote_identifier(sort_col)} {order_dir}")

    # Pagination: fetch limit + 1 to detect has_more
    fetch_limit = max(1, min(limit, 5000))
    fetch_offset = max(0, offset)
    sql_parts.append("LIMIT ? OFFSET ?")
    params.extend([fetch_limit + 1, fetch_offset])

    query = " ".join(sql_parts)
    cur = conn.execute(query, params)
    raw_rows = cur.fetchall()

    has_more = len(raw_rows) > fetch_limit
    effective_rows = raw_rows[:fetch_limit]

    rows_dict = [dict(r) for r in effective_rows]

    return BrowseResult(
        table=table,
        columns=selected_cols,
        rows=rows_dict,
        total_rows=None,
        limit=fetch_limit,
        offset=fetch_offset,
        has_more=has_more,
    )


def search_table(
    conn: sqlite3.Connection,
    table: str,
    pattern: str,
    columns: list[str] | None = None,
    limit: int = 100,
) -> SearchResult:
    """
    Searches a table across specified or all text columns using parameterized LIKE predicates.
    Identifies whether the search triggers an unindexed full table scan.
    """
    valid_cols = get_table_columns(conn, table)
    indexed_cols = get_indexed_columns(conn, table)

    if columns:
        for c in columns:
            if c not in valid_cols:
                raise ValueError(f"Column '{c}' does not exist in table '{table}'")
        target_cols = columns
    else:
        target_cols = valid_cols

    if not target_cols:
        raise ValueError(f"No searchable columns found in table '{table}'")

    # Detect if any searched column is unindexed
    unindexed = [c for c in target_cols if c not in indexed_cols]
    is_full_scan = len(unindexed) > 0 or pattern.startswith("%")

    warning = None
    if is_full_scan:
        warning = f"Notice: Search on '{table}' performs an unindexed full scan (columns without index: {', '.join(unindexed)})"

    quoted_table = quote_identifier(table)
    quoted_cols = [quote_identifier(c) for c in valid_cols]

    # Build predicates: col LIKE ?
    predicates = [f"CAST({quote_identifier(c)} AS TEXT) LIKE ?" for c in target_cols]
    where_clause = " OR ".join(predicates)

    like_pattern = f"%{pattern}%" if not ("%" in pattern or "_" in pattern) else pattern
    params = [like_pattern] * len(target_cols)

    fetch_limit = max(1, min(limit, 5000))
    query = f"SELECT {', '.join(quoted_cols)} FROM {quoted_table} WHERE {where_clause} LIMIT ?"
    params.append(fetch_limit)

    cur = conn.execute(query, params)
    raw_rows = cur.fetchall()

    return SearchResult(
        table=table,
        pattern=pattern,
        searched_columns=target_cols,
        matches=[dict(r) for r in raw_rows],
        is_full_scan=is_full_scan,
        warning=warning,
        limit=fetch_limit,
    )


def execute_readonly_query(
    conn: sqlite3.Connection,
    sql: str,
    params: tuple[Any, ...] | dict[str, Any] = (),
    limit: int = 100,
) -> QueryResult:
    """
    Executes a bounded read-only query (SELECT, EXPLAIN).
    Guaranteed by read-only authorizer and PRAGMA query_only = ON;.
    """
    cleaned = sql.strip()
    if not cleaned:
        raise ValueError("SQL query cannot be empty")

    start_time = time.perf_counter()
    cur = conn.execute(cleaned, params)
    fetch_limit = max(1, min(limit, 10000))

    # Fetch rows up to limit + 1 to detect truncation
    rows_raw = cur.fetchmany(fetch_limit + 1)
    elapsed_ms = (time.perf_counter() - start_time) * 1000.0

    truncated = len(rows_raw) > fetch_limit
    effective_rows = rows_raw[:fetch_limit]

    col_names = [desc[0] for desc in cur.description] if cur.description else []
    rows_dict = [dict(r) for r in effective_rows]

    return QueryResult(
        sql=sql,
        columns=col_names,
        rows=rows_dict,
        row_count=len(rows_dict),
        truncated=truncated,
        execution_time_ms=elapsed_ms,
    )
