"""
Unit tests for db_manager.export.
"""

import json
from pathlib import Path
import sqlite3

from db_manager.connections import get_readonly_connection
from db_manager.export import (
    escape_csv_value,
    export_table,
    export_database_dump,
)


def _init_export_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE accounts (id INT PRIMARY KEY, name TEXT, balance REAL, formula_payload TEXT, raw_data BLOB);"
        )
        conn.execute("INSERT INTO accounts VALUES (1, 'Alice', 1000.50, '=cmd|'' /C calc''!A0', X'01020304');")
        conn.execute("INSERT INTO accounts VALUES (2, 'Bob', 500.0, '+12345', NULL);")
        conn.execute("INSERT INTO accounts VALUES (3, 'Charlie', 20.0, '@SUM(A1:A10)', NULL);")
        conn.execute("INSERT INTO accounts VALUES (4, 'David', 0.0, '-55', NULL);")
        conn.execute("INSERT INTO accounts VALUES (5, 'Eve', 10.0, 'Normal Text', NULL);")


def test_escape_csv_value():
    assert escape_csv_value("=1+1") == "'=1+1"
    assert escape_csv_value("+44") == "'+44"
    assert escape_csv_value("-99") == "'-99"
    assert escape_csv_value("@sum") == "'@sum"
    assert escape_csv_value("\tindent") == "'\tindent"
    assert escape_csv_value("\rreturn") == "'\rreturn"
    assert escape_csv_value("normal") == "normal"
    assert escape_csv_value(None) == ""
    assert escape_csv_value(b"\xde\xad") == "0xdead"
    assert escape_csv_value(42) == 42


def test_export_table_csv(tmp_path: Path):
    db_file = tmp_path / "export_src.db"
    _init_export_db(db_file)
    out_csv = tmp_path / "out.csv"

    with get_readonly_connection(db_file) as conn:
        count = export_table(conn, table="accounts", output_path=out_csv, export_format="csv")
        assert count == 5

    content = out_csv.read_text(encoding="utf-8")
    lines = [line.strip() for line in content.strip().splitlines()]
    assert lines[0] == "id,name,balance,formula_payload,raw_data"

    # Verify formula prefixes were escaped with single quote
    assert "'=cmd|' /C calc'!A0" in content
    assert "'+12345" in content
    assert "'@SUM(A1:A10)" in content
    assert "'-55" in content
    assert "0x01020304" in content


def test_export_table_json_and_jsonl(tmp_path: Path):
    db_file = tmp_path / "export_src.db"
    _init_export_db(db_file)

    out_json = tmp_path / "out.json"
    out_jsonl = tmp_path / "out.jsonl"

    with get_readonly_connection(db_file) as conn:
        export_table(conn, table="accounts", output_path=out_json, export_format="json")
        export_table(conn, table="accounts", output_path=out_jsonl, export_format="jsonl")

    # Verify JSON
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert len(data) == 5
    assert data[0]["raw_data"] == "0x01020304"

    # Verify JSONL
    lines = [json.loads(line) for line in out_jsonl.read_text(encoding="utf-8").strip().splitlines()]
    assert len(lines) == 5
    assert lines[0]["name"] == "Alice"


def test_export_table_sql_and_dump(tmp_path: Path):
    db_file = tmp_path / "export_src.db"
    _init_export_db(db_file)

    out_sql = tmp_path / "table.sql"
    out_dump = tmp_path / "full_dump.sql"

    with get_readonly_connection(db_file) as conn:
        export_table(conn, table="accounts", output_path=out_sql, export_format="sql")
        export_database_dump(conn, output_path=out_dump)

    sql_content = out_sql.read_text(encoding="utf-8")
    assert "CREATE TABLE accounts" in sql_content
    assert 'INSERT INTO "accounts"' in sql_content
    assert "X'01020304'" in sql_content

    dump_content = out_dump.read_text(encoding="utf-8")
    assert "CREATE TABLE accounts" in dump_content
    assert "COMMIT;" in dump_content
