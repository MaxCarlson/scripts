"""
Unit tests for db_manager.inspector.
"""

from pathlib import Path
import sqlite3

from db_manager.connections import get_readonly_connection
from db_manager.inspector import (
    inspect_database,
    list_tables,
    get_schema,
    check_database,
)


def _create_test_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute(
            """
            CREATE TABLE departments (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                dept_id INTEGER,
                salary REAL,
                FOREIGN KEY (dept_id) REFERENCES departments(id)
            );
            """
        )
        conn.execute("CREATE INDEX idx_emp_dept ON employees(dept_id);")
        conn.execute(
            "CREATE VIEW v_emp_summary AS SELECT e.id, e.name, d.name as dept FROM employees e JOIN departments d ON e.dept_id = d.id;"
        )
        conn.execute(
            "CREATE TRIGGER trig_emp AFTER INSERT ON employees BEGIN UPDATE departments SET name = name WHERE id = NEW.dept_id; END;"
        )
        conn.execute(
            """
            CREATE TABLE word_counts (
                word TEXT PRIMARY KEY,
                count INTEGER
            ) WITHOUT ROWID;
            """
        )

        conn.execute("INSERT INTO departments VALUES (1, 'Engineering');")
        conn.execute("INSERT INTO employees (name, dept_id, salary) VALUES ('Alice', 1, 95000);")
        conn.execute("INSERT INTO employees (name, dept_id, salary) VALUES ('Bob', 1, 90000);")
        conn.execute("INSERT INTO word_counts VALUES ('sqlite', 10);")


def test_inspect_database(tmp_path: Path):
    db_file = tmp_path / "test_inspect.db"
    _create_test_db(db_file)

    info = inspect_database(db_file)
    assert info.file_size_bytes > 0
    assert info.page_size > 0
    assert info.page_count > 0
    assert info.calculated_db_size > 0
    assert info.table_count == 3  # departments, employees, word_counts
    assert info.view_count == 1  # v_emp_summary
    assert info.index_count >= 1  # idx_emp_dept
    assert info.trigger_count == 1
    assert not info.wal_file_present

    # Synthetic WAL presence check
    wal_dummy = tmp_path / "test_inspect.db-wal"
    wal_dummy.write_bytes(b"dummy")
    info_wal = inspect_database(db_file)
    assert info_wal.wal_file_present


def test_list_tables(tmp_path: Path):
    db_file = tmp_path / "test_tables.db"
    _create_test_db(db_file)

    with get_readonly_connection(db_file) as conn:
        # Default: exact_count is False (row_count is None)
        tables = list_tables(conn, exact_count=False)
        names = {t.name: t for t in tables}

        assert "departments" in names
        assert "employees" in names
        assert "word_counts" in names
        assert "v_emp_summary" in names

        assert names["employees"].type == "table"
        assert names["employees"].column_count == 4
        assert names["employees"].primary_keys == ["id"]
        assert names["employees"].foreign_key_count == 1
        assert names["employees"].row_count is None
        assert not names["employees"].is_without_rowid

        assert names["word_counts"].is_without_rowid
        assert names["v_emp_summary"].type == "view"

        # When exact_count=True
        tables_exact = list_tables(conn, exact_count=True)
        names_exact = {t.name: t for t in tables_exact}
        assert names_exact["departments"].row_count == 1
        assert names_exact["employees"].row_count == 2
        assert names_exact["word_counts"].row_count == 1


def test_get_schema(tmp_path: Path):
    db_file = tmp_path / "test_schema.db"
    _create_test_db(db_file)

    with get_readonly_connection(db_file) as conn:
        schema = get_schema(conn, table_name="employees")
        assert len(schema) == 1
        emp = schema[0]
        assert emp.name == "employees"
        col_names = [c.name for c in emp.columns]
        assert col_names == ["id", "name", "dept_id", "salary"]

        assert len(emp.foreign_keys) == 1
        fk = emp.foreign_keys[0]
        assert fk.table == "departments"
        assert fk.from_col == "dept_id"
        assert fk.to_col == "id"

        idx_names = [i.name for i in emp.indexes]
        assert "idx_emp_dept" in idx_names


def test_check_database_healthy_and_violation(tmp_path: Path):
    db_file = tmp_path / "test_check.db"
    _create_test_db(db_file)

    with get_readonly_connection(db_file) as conn:
        report = check_database(conn, check_integrity=True, check_foreign_keys=True)
        assert report.is_healthy
        assert report.quick_check == ["ok"]
        assert report.integrity_check == ["ok"]
        assert len(report.foreign_key_violations) == 0

    # Create a database with FK violation (disabled FK during insert)
    broken_db = tmp_path / "broken.db"
    with sqlite3.connect(broken_db) as conn:
        conn.execute("PRAGMA foreign_keys = OFF;")
        conn.execute("CREATE TABLE parent (id INT PRIMARY KEY);")
        conn.execute("CREATE TABLE child (id INT PRIMARY KEY, parent_id INT REFERENCES parent(id));")
        conn.execute("INSERT INTO child VALUES (1, 999);")  # 999 does not exist in parent!

    with get_readonly_connection(broken_db) as conn:
        report_broken = check_database(conn, check_integrity=True, check_foreign_keys=True)
        assert not report_broken.is_healthy
        assert len(report_broken.foreign_key_violations) == 1
        assert report_broken.foreign_key_violations[0]["table"] == "child"
