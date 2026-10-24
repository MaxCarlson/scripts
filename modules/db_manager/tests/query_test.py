"""
Unit tests for db_manager.query.
"""

from pathlib import Path
import sqlite3
import pytest

from db_manager.connections import get_readonly_connection
from db_manager.query import (
    quote_identifier,
    format_value_for_display,
    browse_table,
    search_table,
    execute_readonly_query,
)


def _setup_query_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE products (id INT PRIMARY KEY, name TEXT, category TEXT, price REAL, data BLOB);")
        conn.execute("CREATE INDEX idx_prod_cat ON products(category);")

        conn.execute("INSERT INTO products VALUES (1, 'Laptop', 'Electronics', 1200.0, X'DEADBEEF');")
        conn.execute("INSERT INTO products VALUES (2, 'Keyboard', 'Electronics', 75.0, X'CAFEBABE');")
        conn.execute("INSERT INTO products VALUES (3, 'Mouse', 'Electronics', 25.0, NULL);")
        conn.execute("INSERT INTO products VALUES (4, 'Desk', 'Furniture', 350.0, NULL);")
        conn.execute("INSERT INTO products VALUES (5, 'Chair', 'Furniture', 150.0, NULL);")


def test_quote_identifier():
    assert quote_identifier("foo") == '"foo"'
    assert quote_identifier('user"name') == '"user""name"'
    with pytest.raises(ValueError):
        quote_identifier("")


def test_format_value_for_display():
    assert format_value_for_display(None) == "<NULL>"
    assert format_value_for_display(123) == "123"

    blob_val = b"\xde\xad\xbe\xef\x00\x01\x02\x03"
    assert format_value_for_display(blob_val) == "<BLOB 8 bytes: 0xdeadbeef00010203>"

    long_blob = b"A" * 64
    preview = format_value_for_display(long_blob, max_blob_hex_len=4)
    assert preview == "<BLOB 64 bytes: 0x41414141...>"

    long_str = "x" * 200
    assert len(format_value_for_display(long_str, max_text_len=50)) == 53  # 50 + "..."


def test_browse_table_pagination_and_sorting(tmp_path: Path):
    db_file = tmp_path / "test_browse.db"
    _setup_query_db(db_file)

    with get_readonly_connection(db_file) as conn:
        # Bounded page 1
        res = browse_table(conn, table="products", limit=2, offset=0, sort_col="id")
        assert len(res.rows) == 2
        assert res.rows[0]["name"] == "Laptop"
        assert res.rows[1]["name"] == "Keyboard"
        assert res.has_more is True

        # Page 2
        res2 = browse_table(conn, table="products", limit=2, offset=2, sort_col="id")
        assert len(res2.rows) == 2
        assert res2.rows[0]["name"] == "Mouse"
        assert res2.rows[1]["name"] == "Desk"
        assert res2.has_more is True

        # Descending sort
        res_desc = browse_table(conn, table="products", limit=2, sort_col="price", sort_desc=True)
        assert res_desc.rows[0]["name"] == "Laptop"
        assert res_desc.rows[1]["name"] == "Desk"


def test_browse_table_filter_and_projection(tmp_path: Path):
    db_file = tmp_path / "test_browse.db"
    _setup_query_db(db_file)

    with get_readonly_connection(db_file) as conn:
        res = browse_table(
            conn,
            table="products",
            columns=["id", "name"],
            filter_col="category",
            filter_val="Furniture",
        )
        assert len(res.rows) == 2
        assert set(res.rows[0].keys()) == {"id", "name"}
        assert {r["name"] for r in res.rows} == {"Desk", "Chair"}

        # Unknown column raises ValueError
        with pytest.raises(ValueError, match="Unknown column"):
            browse_table(conn, table="products", columns=["nonexistent"])


def test_search_table_parameterized(tmp_path: Path):
    db_file = tmp_path / "test_search.db"
    _setup_query_db(db_file)

    with get_readonly_connection(db_file) as conn:
        # Search indexed column
        res_cat = search_table(conn, table="products", pattern="Furniture", columns=["category"])
        assert len(res_cat.matches) == 2

        # Search unindexed column triggers warning
        res_name = search_table(conn, table="products", pattern="Desk", columns=["name"])
        assert len(res_name.matches) == 1
        assert res_name.matches[0]["name"] == "Desk"
        assert res_name.is_full_scan is True
        assert res_name.warning is not None
        assert "unindexed full scan" in res_name.warning

        # Injection attempt in pattern is safely parameterized and finds nothing
        res_inj = search_table(conn, table="products", pattern="' OR 1=1 --")
        assert len(res_inj.matches) == 0


def test_execute_readonly_query(tmp_path: Path):
    db_file = tmp_path / "test_query.db"
    _setup_query_db(db_file)

    with get_readonly_connection(db_file) as conn:
        res = execute_readonly_query(
            conn,
            sql="SELECT name, price FROM products WHERE price > ? ORDER BY price DESC",
            params=(100.0,),
        )
        assert res.row_count == 3
        assert res.columns == ["name", "price"]
        assert res.rows[0]["name"] == "Laptop"
        assert not res.truncated

        # Unsafe query fails via authorizer
        with pytest.raises(sqlite3.DatabaseError):
            execute_readonly_query(conn, sql="DELETE FROM products WHERE id = 1")


def test_execute_readonly_query_timeout_progress_handler(tmp_path: Path):
    db_file = tmp_path / "test_timeout.db"
    _setup_query_db(db_file)

    runaway_sql = "WITH RECURSIVE cnt(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM cnt) SELECT count(*) FROM cnt;"

    with get_readonly_connection(db_file) as conn:
        with pytest.raises(TimeoutError, match="Query execution exceeded resource limits"):
            execute_readonly_query(conn, sql=runaway_sql, timeout_sec=0.2, max_vm_steps=50_000)
