# File: knowledge_manager/db.py
import sqlite3
from pathlib import Path
from typing import Optional

# It's good practice to define the database file path.
# This might be made configurable later.
DEFAULT_DB_FILE_NAME = "knowledge_manager.db"

def get_db_connection(db_path: Path) -> sqlite3.Connection:
    """
    Establishes a database connection to the SQLite database specified by db_path.
    Enables foreign key constraint enforcement for the connection.

    Args:
        db_path (Path): The path to the SQLite database file.

    Returns:
        sqlite3.Connection: A connection object to the database.
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db(db_path: Path) -> None:
    """
    Initializes the database by creating the 'projects' and 'tasks' tables
    if they do not already exist.

    Args:
        db_path (Path): The path to the SQLite database file.
    """
    conn = None
    try:
        conn = get_db_connection(db_path)
        cursor = conn.cursor()

        # Create projects table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            modified_at TEXT NOT NULL,
            description_md_path TEXT
        )
        """)

        # Create tasks table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            project_id TEXT,
            parent_task_id TEXT,
            created_at TEXT NOT NULL,
            modified_at TEXT NOT NULL,
            completed_at TEXT,
            priority INTEGER,
            due_date TEXT,
            details_md_path TEXT,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL,
            FOREIGN KEY (parent_task_id) REFERENCES tasks(id) ON DELETE CASCADE
        )
        """)
        # ON DELETE SET NULL for project_id: If a project is deleted, tasks are not deleted but unlinked.
        # ON DELETE CASCADE for parent_task_id: If a parent task is deleted, its subtasks are also deleted.
        # These are common choices but can be adjusted based on desired behavior.

        conn.commit()
        print(f"Database initialized successfully at {db_path}")
    except sqlite3.Error as e:
        print(f"An error occurred during database initialization: {e}")
        # Potentially re-raise or handle more gracefully
    finally:
        if conn:
            conn.close()

def get_default_db_path(base_dir: Optional[Path] = None) -> Path:
    """
    Determines the default path for the database file.
    Uses ~/.local/share/knowledge_manager/ if base_dir is not provided.
    """
    if base_dir:
        km_dir = base_dir / "knowledge_manager"
    else:
        # A common cross-platform location for user-specific application data
        km_dir = Path.home() / ".local" / "share" / "knowledge_manager"
    
    km_dir.mkdir(parents=True, exist_ok=True) # Ensure the directory exists
    return km_dir / DEFAULT_DB_FILE_NAME

# Example of how you might call init_db in your main application setup:
# if __name__ == '__main__':
#     db_file_path = get_default_db_path()
#     init_db(db_file_path)

# End of File: knowledge_manager/db.py
