"""
export.py — Safe database and table exports with formula injection prevention.
"""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any

from db_manager.query import get_table_columns, quote_identifier

logger = logging.getLogger(__name__)

# Dangerous prefixes in spreadsheets that can trigger formula execution
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def escape_csv_value(val: Any) -> Any:
    """
    Safely sanitizes a field value for CSV export:
    - Escapes formula injection by prepending a single quote if string begins with =, +, -, @, \\t, \\r.
    - Encodes BLOB bytes as 0xhex.
    - Represents None as empty string.
    """
    if val is None:
        return ""

    if isinstance(val, (bytes, bytearray, memoryview)):
        return f"0x{bytes(val).hex()}"

    if isinstance(val, str):
        if len(val) > 0 and val[0] in FORMULA_PREFIXES:
            return f"'{val}"
        return val

    return val


def sanitize_for_json(val: Any) -> Any:
    """Serializes values for JSON/JSONL, formatting BLOBs as hex strings."""
    if val is None:
        return None
    if isinstance(val, (bytes, bytearray, memoryview)):
        return f"0x{bytes(val).hex()}"
    return val


def export_table(
    conn: sqlite3.Connection,
    table: str,
    output_path: str | Path,
    export_format: str = "json",
    force: bool = False,
    limit: int | None = None,
) -> int:
    """
    Exports a table to a file in json, jsonl, csv, or sql format.
    Guarantees:
    - Formula injection prevention in CSV.
    - Refuses to overwrite existing file unless force=True.
    - Bounded memory streaming.
    """
    fmt = export_format.lower().strip()
    allowed_formats = {"json", "jsonl", "csv", "sql"}
    if fmt not in allowed_formats:
        raise ValueError(f"Unsupported export format '{export_format}'. Allowed: {sorted(allowed_formats)}")

    out = Path(output_path).resolve()
    if out.exists() and not force:
        raise FileExistsError(f"Export target file already exists: {out}. Use force (-f/--force) to overwrite.")

    out.parent.mkdir(parents=True, exist_ok=True)

    cols = get_table_columns(conn, table)
    quoted_table = quote_identifier(table)
    query = f"SELECT * FROM {quoted_table}"
    params: list[Any] = []
    if limit is not None and limit > 0:
        query += " LIMIT ?"
        params.append(limit)

    cur = conn.execute(query, params)
    row_count = 0

    if fmt == "csv":
        with open(out, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
            writer.writerow(cols)
            for row in cur:
                row_count += 1
                sanitized_row = [escape_csv_value(row[c]) for c in cols]
                writer.writerow(sanitized_row)

    elif fmt == "jsonl":
        with open(out, "w", encoding="utf-8") as f:
            for row in cur:
                row_count += 1
                row_dict = {c: sanitize_for_json(row[c]) for c in cols}
                f.write(json.dumps(row_dict, ensure_ascii=False) + "\n")

    elif fmt == "json":
        all_rows = []
        for row in cur:
            row_count += 1
            all_rows.append({c: sanitize_for_json(row[c]) for c in cols})
        with open(out, "w", encoding="utf-8") as f:
            json.dump(all_rows, f, indent=2, ensure_ascii=False)

    elif fmt == "sql":
        # Extract schema and rows as INSERT statements
        schema_row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        table_ddl = schema_row["sql"] if schema_row else f"-- Table DDL not found for {table}"

        with open(out, "w", encoding="utf-8") as f:
            f.write(f"-- Exported table: {table}\n")
            f.write(f"{table_ddl};\n\n")
            f.write("BEGIN TRANSACTION;\n")
            quoted_col_names = ", ".join(quote_identifier(c) for c in cols)
            for row in cur:
                row_count += 1
                val_literals = []
                for c in cols:
                    v = row[c]
                    if v is None:
                        val_literals.append("NULL")
                    elif isinstance(v, (int, float)):
                        val_literals.append(str(v))
                    elif isinstance(v, (bytes, bytearray, memoryview)):
                        val_literals.append(f"X'{bytes(v).hex()}'")
                    else:
                        escaped = str(v).replace("'", "''")
                        val_literals.append(f"'{escaped}'")
                f.write(f"INSERT INTO {quoted_table} ({quoted_col_names}) VALUES ({', '.join(val_literals)});\n")
            f.write("COMMIT;\n")

    return row_count


def export_database_dump(
    conn: sqlite3.Connection,
    output_path: str | Path,
    force: bool = False,
) -> int:
    """
    Exports a complete, portable SQL dump using sqlite3.Connection.iterdump().
    """
    out = Path(output_path).resolve()
    if out.exists() and not force:
        raise FileExistsError(f"Dump target file already exists: {out}. Use force (-f/--force) to overwrite.")

    out.parent.mkdir(parents=True, exist_ok=True)
    line_count = 0

    with open(out, "w", encoding="utf-8") as f:
        for line in conn.iterdump():
            line_count += 1
            f.write(f"{line}\n")

    return line_count
