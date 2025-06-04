# File: tests/test_db.py
import sqlite3
import pytest
from pathlib import Path

# Adjust the import path based on your project structure.
# If 'knowledge_manager' is a package in your PYTHONPATH:
from knowledge_manager.db import init_db, get_db_connection 

@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    """
    Pytest fixture to create a temporary database file path for testing.
    The database file itself is not created by this fixture, only its path.
    """
    return tmp_path / "test_km.db"

def test_init_db_creates_database_file(temp_db_path: Path):
    """
    Test that init_db creates a database file at the specified path.
    """
    assert not temp_db_path.exists()
    init_db(temp_db_path)
    assert temp_db_path.exists()
    # Clean up by removing the test database file if needed, though tmp_path handles it.

def test_init_db_creates_tables(temp_db_path: Path):
    """
    Test that init_db creates the 'projects' and 'tasks' tables.
    """
    init_db(temp_db_path)

    conn = None
    try:
        conn = get_db_connection(temp_db_path) # Use the same connection getter
        cursor = conn.cursor()

        # Check for projects table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='projects';")
        assert cursor.fetchone() is not None, "Table 'projects' was not created."

        # Check for tasks table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks';")
        assert cursor.fetchone() is not None, "Table 'tasks' was not created."

    finally:
        if conn:
            conn.close()

def test_init_db_projects_table_schema(temp_db_path: Path):
    """
    Test that the 'projects' table has the correct columns and types (simplified check).
    """
    init_db(temp_db_path)
    conn = None
    try:
        conn = get_db_connection(temp_db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(projects);")
        columns = {row[1]: row[2] for row in cursor.fetchall()} # name: type

        expected_columns = {
            "id": "TEXT",
            "name": "TEXT",
            "status": "TEXT",
            "created_at": "TEXT",
            "modified_at": "TEXT",
            "description_md_path": "TEXT"
        }
        for col_name, col_type in expected_columns.items():
            assert col_name in columns, f"Column '{col_name}' missing in 'projects' table."
            # SQLite type affinity can be tricky; TEXT is a safe bet for these.
            # More specific type checks can be added if strict type enforcement is critical
            # beyond what SQLite provides. For example, checking NOT NULL constraints.
            assert columns[col_name].upper() == col_type.upper(), \
                   f"Column '{col_name}' in 'projects' has type '{columns[col_name]}' not '{col_type}'."
    finally:
        if conn:
            conn.close()


def test_init_db_tasks_table_schema(temp_db_path: Path):
    """
    Test that the 'tasks' table has the correct columns and types (simplified check).
    """
    init_db(temp_db_path)
    conn = None
    try:
        conn = get_db_connection(temp_db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(tasks);")
        columns = {row[1]: row[2] for row in cursor.fetchall()}

        expected_columns = {
            "id": "TEXT",
            "title": "TEXT",
            "status": "TEXT",
            "project_id": "TEXT", # Foreign keys are stored as the referenced type
            "parent_task_id": "TEXT",
            "created_at": "TEXT",
            "modified_at": "TEXT",
            "completed_at": "TEXT",
            "priority": "INTEGER",
            "due_date": "TEXT",
            "details_md_path": "TEXT"
        }
        for col_name, col_type in expected_columns.items():
            assert col_name in columns, f"Column '{col_name}' missing in 'tasks' table."
            assert columns[col_name].upper() == col_type.upper(), \
                   f"Column '{col_name}' in 'tasks' has type '{columns[col_name]}' not '{col_type}'."

        # Check foreign key constraints (basic check for existence)
        cursor.execute("PRAGMA foreign_key_list(tasks);")
        fk_info = cursor.fetchall()
        # Example: (id, seq, table, from, to, on_update, on_delete, match)
        project_fk_found = any(row[2] == 'projects' and row[3] == 'project_id' and row[4] == 'id' for row in fk_info)
        task_fk_found = any(row[2] == 'tasks' and row[3] == 'parent_task_id' and row[4] == 'id' for row in fk_info)
        assert project_fk_found, "Foreign key for 'project_id' to 'projects.id' not found or misconfigured."
        assert task_fk_found, "Foreign key for 'parent_task_id' to 'tasks.id' not found or misconfigured."

    finally:
        if conn:
            conn.close()

# End of File: tests/test_db.py
