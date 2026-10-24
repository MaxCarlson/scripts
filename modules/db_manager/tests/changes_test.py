"""
Unit tests for db_manager.changes.
"""

from pathlib import Path
import sqlite3
import pytest

from db_manager.connections import get_readonly_connection
from db_manager.changes import (
    parse_key_value_spec,
    init_database,
    plan_and_apply_edit,
    plan_and_apply_insert,
    plan_and_apply_delete,
    execute_mutation_sql,
    compare_databases,
)


def _setup_test_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE users (id INT PRIMARY KEY, name TEXT, role TEXT, score REAL);")
        conn.execute("INSERT INTO users VALUES (1, 'Alice', 'admin', 95.0);")
        conn.execute("INSERT INTO users VALUES (2, 'Bob', 'member', 80.0);")


def test_parse_key_value_spec():
    parsed_json = parse_key_value_spec('{"id": 10, "name": "Test"}')
    assert parsed_json == {"id": 10, "name": "Test"}

    parsed_kv = parse_key_value_spec("id=42,name='Alice',active=true,empty=null,score=99.5")
    assert parsed_kv["id"] == 42
    assert parsed_kv["name"] == "Alice"
    assert parsed_kv["active"] is True
    assert parsed_kv["empty"] is None
    assert parsed_kv["score"] == 99.5


def test_init_database(tmp_path: Path):
    target = tmp_path / "new_db.sqlite3"
    schema = "CREATE TABLE notes (id INT PRIMARY KEY, body TEXT); CREATE TABLE tags (id INT, tag TEXT);"

    # Dry-run
    plan_dry = init_database(target, schema_sql=schema, dry_run=True)
    assert plan_dry.is_dry_run
    assert len(plan_dry.statements) == 2
    assert not target.exists()

    # Write
    plan_write = init_database(target, schema_sql=schema, dry_run=False)
    assert not plan_write.is_dry_run
    assert target.exists()

    with get_readonly_connection(target) as conn:
        master = conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
        names = [r["name"] for r in master]
        assert "notes" in names
        assert "tags" in names


def test_plan_and_apply_edit(tmp_path: Path):
    db_file = tmp_path / "edit_test.db"
    _setup_test_db(db_file)

    # 1. Dry run
    plan_dry = plan_and_apply_edit(
        db_file,
        table="users",
        pk_values={"id": 1},
        new_values={"role": "superadmin"},
        dry_run=True,
    )
    assert plan_dry.is_dry_run
    assert plan_dry.old_values["role"] == "admin"
    assert plan_dry.new_values["role"] == "superadmin"

    # Verify database was NOT changed
    with get_readonly_connection(db_file) as conn:
        role = conn.execute("SELECT role FROM users WHERE id = 1;").fetchone()["role"]
        assert role == "admin"

    # 2. Write mode
    plan_write = plan_and_apply_edit(
        db_file,
        table="users",
        pk_values={"id": 1},
        new_values={"role": "superadmin"},
        dry_run=False,
    )
    assert not plan_write.is_dry_run
    assert plan_write.backup_path is not None
    assert Path(plan_write.backup_path).exists()

    # Verify update succeeded
    with get_readonly_connection(db_file) as conn:
        role = conn.execute("SELECT role FROM users WHERE id = 1;").fetchone()["role"]
        assert role == "superadmin"


def test_edit_optimistic_concurrency_conflict(tmp_path: Path):
    db_file = tmp_path / "concurrency_test.db"
    _setup_test_db(db_file)

    # 1. Non-existent PK raises error
    with pytest.raises(ValueError, match="No row matches primary key"):
        plan_and_apply_edit(
            db_file,
            table="users",
            pk_values={"id": 999},
            new_values={"role": "owner"},
            dry_run=False,
        )

    # 2. Concurrency conflict with expected_old_values
    stale_old = {"id": 1, "name": "Alice", "role": "admin", "score": 95.0}
    # Secretly update row behind the scenes
    with sqlite3.connect(db_file) as conn:
        conn.execute("UPDATE users SET score = 99.0 WHERE id = 1;")

    # Edit with stale expectation must raise Optimistic concurrency violation
    with pytest.raises(RuntimeError, match="Optimistic concurrency violation"):
        plan_and_apply_edit(
            db_file,
            table="users",
            pk_values={"id": 1},
            new_values={"role": "superadmin"},
            dry_run=False,
            expected_old_values=stale_old,
        )

    # Delete with stale expectation must also raise Optimistic concurrency violation
    with pytest.raises(RuntimeError, match="Optimistic concurrency violation"):
        plan_and_apply_delete(
            db_file,
            table="users",
            pk_values={"id": 1},
            dry_run=False,
            expected_old_values=stale_old,
        )


def test_null_safe_optimistic_concurrency(tmp_path: Path):
    db_file = tmp_path / "null_safe_test.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute("CREATE TABLE products (id INT PRIMARY KEY, name TEXT, note TEXT, tag TEXT);")
        conn.execute("INSERT INTO products VALUES (1, 'Widget', NULL, 'hardware');")

    # Edit row where note IS NULL
    plan_edit = plan_and_apply_edit(
        db_file,
        table="products",
        pk_values={"id": 1},
        new_values={"tag": "electronics"},
        dry_run=False,
    )
    assert not plan_edit.is_dry_run
    assert 'note" IS NULL' in plan_edit.sql or "note IS NULL" in plan_edit.sql

    with get_readonly_connection(db_file) as conn:
        row = conn.execute("SELECT tag, note FROM products WHERE id = 1;").fetchone()
        assert row["tag"] == "electronics"
        assert row["note"] is None

    # Delete row where note IS NULL
    plan_del = plan_and_apply_delete(
        db_file,
        table="products",
        pk_values={"id": 1},
        dry_run=False,
    )
    assert not plan_del.is_dry_run
    assert 'note" IS NULL' in plan_del.sql or "note IS NULL" in plan_del.sql

    with get_readonly_connection(db_file) as conn:
        assert conn.execute("SELECT count(*) FROM products;").fetchone()[0] == 0


def test_plan_and_apply_insert_and_delete(tmp_path: Path):
    db_file = tmp_path / "insert_delete_test.db"
    _setup_test_db(db_file)

    # Insert dry-run
    ins_dry = plan_and_apply_insert(
        db_file, table="users", values={"id": 3, "name": "Charlie", "role": "guest", "score": 70.0}, dry_run=True
    )
    assert ins_dry.is_dry_run

    # Insert write
    ins_write = plan_and_apply_insert(
        db_file, table="users", values={"id": 3, "name": "Charlie", "role": "guest", "score": 70.0}, dry_run=False
    )
    assert not ins_write.is_dry_run

    with get_readonly_connection(db_file) as conn:
        row = conn.execute("SELECT name FROM users WHERE id = 3;").fetchone()
        assert row["name"] == "Charlie"

    # Delete dry-run
    del_dry = plan_and_apply_delete(db_file, table="users", pk_values={"id": 3}, dry_run=True)
    assert del_dry.is_dry_run
    assert del_dry.deleted_row["name"] == "Charlie"

    # Delete write
    del_write = plan_and_apply_delete(db_file, table="users", pk_values={"id": 3}, dry_run=False)
    assert not del_write.is_dry_run

    with get_readonly_connection(db_file) as conn:
        row = conn.execute("SELECT name FROM users WHERE id = 3;").fetchone()
        assert row is None


def test_execute_mutation_sql_and_blocks_attach(tmp_path: Path):
    db_file = tmp_path / "sql_test.db"
    _setup_test_db(db_file)

    # Dry-run
    res_dry = execute_mutation_sql(db_file, sql="UPDATE users SET score = 50.0", dry_run=True)
    assert res_dry.is_dry_run

    # Write
    res_write = execute_mutation_sql(db_file, sql="UPDATE users SET score = 50.0", dry_run=False)
    assert not res_write.is_dry_run
    assert res_write.affected_rows == 2

    # Blocks ATTACH even in mutation SQL
    with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
        execute_mutation_sql(db_file, sql="ATTACH DATABASE 'foo.db' AS foo;", dry_run=False)


def test_compare_databases(tmp_path: Path):
    db1 = tmp_path / "db1.sqlite3"
    db2 = tmp_path / "db2.sqlite3"
    _setup_test_db(db1)
    _setup_test_db(db2)

    # Identical
    cmp_same = compare_databases(db1, db2)
    assert cmp_same.identical
    assert len(cmp_same.schema_differences) == 0

    # Modify db2 rowcount
    with sqlite3.connect(db2) as conn:
        conn.execute("INSERT INTO users VALUES (3, 'Charlie', 'member', 75.0);")

    cmp_diff = compare_databases(db1, db2)
    assert not cmp_diff.identical
    assert any("row count mismatch" in d for d in cmp_diff.schema_differences)
