# File: knowledge_manager/db.py
import sqlite3
import uuid
from pathlib import Path
from typing import Optional, List
from datetime import datetime, timezone, date

# Assuming your models.py is in the same package
from .models import Project, ProjectStatus, Task, TaskStatus

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
            due_date TEXT, -- Stored as ISO 8601 string (YYYY-MM-DD)
            details_md_path TEXT,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL,
            FOREIGN KEY (parent_task_id) REFERENCES tasks(id) ON DELETE CASCADE
        )
        """)
        conn.commit()
        # print(f"Database initialized successfully at {db_path}") # Consider logging instead of printing
    except sqlite3.Error as e:
        # print(f"An error occurred during database initialization: {e}") # Consider logging
        raise # Re-raise the exception so the caller can handle it
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

# --- Project CRUD Operations ---

def add_project(conn: sqlite3.Connection, project: Project) -> Project:
    project.modified_at = datetime.now(timezone.utc)
    sql = """
    INSERT INTO projects (id, name, status, created_at, modified_at, description_md_path)
    VALUES (?, ?, ?, ?, ?, ?)
    """
    cursor = conn.cursor()
    try:
        cursor.execute(sql, (
            str(project.id),
            project.name,
            project.status.value,
            project.created_at.isoformat(),
            project.modified_at.isoformat(),
            str(project.description_md_path) if project.description_md_path else None
        ))
        conn.commit()
    except sqlite3.IntegrityError as e:
        raise
    return project

def get_project_by_id(conn: sqlite3.Connection, project_id: uuid.UUID) -> Optional[Project]:
    sql = "SELECT id, name, status, created_at, modified_at, description_md_path FROM projects WHERE id = ?"
    cursor = conn.cursor()
    cursor.execute(sql, (str(project_id),))
    row = cursor.fetchone()
    if row:
        return Project(
            id=uuid.UUID(row[0]), name=row[1], status=ProjectStatus(row[2]),
            created_at=datetime.fromisoformat(row[3]), modified_at=datetime.fromisoformat(row[4]),
            description_md_path=Path(row[5]) if row[5] else None
        )
    return None

def get_project_by_name(conn: sqlite3.Connection, name: str) -> Optional[Project]:
    sql = "SELECT id, name, status, created_at, modified_at, description_md_path FROM projects WHERE name = ?"
    cursor = conn.cursor()
    cursor.execute(sql, (name,))
    row = cursor.fetchone()
    if row:
        return Project(
            id=uuid.UUID(row[0]), name=row[1], status=ProjectStatus(row[2]),
            created_at=datetime.fromisoformat(row[3]), modified_at=datetime.fromisoformat(row[4]),
            description_md_path=Path(row[5]) if row[5] else None
        )
    return None

def list_projects(conn: sqlite3.Connection, status: Optional[ProjectStatus] = None) -> List[Project]:
    base_sql = "SELECT id, name, status, created_at, modified_at, description_md_path FROM projects"
    params = []
    conditions = []
    if status:
        conditions.append("status = ?")
        params.append(status.value)
    if conditions:
        base_sql += " WHERE " + " AND ".join(conditions)
    base_sql += " ORDER BY name ASC"
    cursor = conn.cursor()
    cursor.execute(base_sql, params)
    rows = cursor.fetchall()
    return [
        Project(
            id=uuid.UUID(row[0]), name=row[1], status=ProjectStatus(row[2]),
            created_at=datetime.fromisoformat(row[3]), modified_at=datetime.fromisoformat(row[4]),
            description_md_path=Path(row[5]) if row[5] else None
        ) for row in rows
    ]

def update_project(conn: sqlite3.Connection, project: Project) -> Optional[Project]:
    project.modified_at = datetime.now(timezone.utc)
    sql = """
    UPDATE projects SET name = ?, status = ?, modified_at = ?, description_md_path = ?
    WHERE id = ?
    """
    cursor = conn.cursor()
    try:
        cursor.execute(sql, (
            project.name, project.status.value, project.modified_at.isoformat(),
            str(project.description_md_path) if project.description_md_path else None,
            str(project.id)
        ))
        conn.commit()
    except sqlite3.Error as e:
        raise
    return project if cursor.rowcount > 0 else None

def delete_project(conn: sqlite3.Connection, project_id: uuid.UUID) -> bool:
    sql = "DELETE FROM projects WHERE id = ?"
    cursor = conn.cursor()
    try:
        cursor.execute(sql, (str(project_id),))
        conn.commit()
    except sqlite3.Error as e:
        raise
    return cursor.rowcount > 0

# --- Task CRUD Operations ---

def add_task(conn: sqlite3.Connection, task: Task) -> Task:
    """
    Adds a new task to the database.
    Updates the task's modified_at timestamp.

    Args:
        conn: Active SQLite database connection.
        task: Task object to add.

    Returns:
        The added Task object.
    """
    task.modified_at = datetime.now(timezone.utc)
    sql = """
    INSERT INTO tasks (id, title, status, project_id, parent_task_id, 
                       created_at, modified_at, completed_at, 
                       priority, due_date, details_md_path)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    cursor = conn.cursor()
    try:
        cursor.execute(sql, (
            str(task.id),
            task.title,
            task.status.value,
            str(task.project_id) if task.project_id else None,
            str(task.parent_task_id) if task.parent_task_id else None,
            task.created_at.isoformat(),
            task.modified_at.isoformat(),
            task.completed_at.isoformat() if task.completed_at else None,
            task.priority,
            task.due_date.isoformat() if task.due_date else None,
            str(task.details_md_path) if task.details_md_path else None
        ))
        conn.commit()
    except sqlite3.IntegrityError as e:
        # Could be due to non-existent project_id or parent_task_id if FKs are checked
        # print(f"Database integrity error adding task: {e}") # Consider logging
        raise
    return task

def get_task_by_id(conn: sqlite3.Connection, task_id: uuid.UUID) -> Optional[Task]:
    """
    Retrieves a task by its ID.

    Args:
        conn: Active SQLite database connection.
        task_id: UUID of the task to retrieve.

    Returns:
        A Task object if found, else None.
    """
    sql = """
    SELECT id, title, status, project_id, parent_task_id, 
           created_at, modified_at, completed_at, 
           priority, due_date, details_md_path 
    FROM tasks WHERE id = ?
    """
    cursor = conn.cursor()
    cursor.execute(sql, (str(task_id),))
    row = cursor.fetchone()
    if row:
        return Task(
            id=uuid.UUID(row[0]),
            title=row[1],
            status=TaskStatus(row[2]),
            project_id=uuid.UUID(row[3]) if row[3] else None,
            parent_task_id=uuid.UUID(row[4]) if row[4] else None,
            created_at=datetime.fromisoformat(row[5]),
            modified_at=datetime.fromisoformat(row[6]),
            completed_at=datetime.fromisoformat(row[7]) if row[7] else None,
            priority=row[8],
            due_date=date.fromisoformat(row[9]) if row[9] else None,
            details_md_path=Path(row[10]) if row[10] else None
        )
    return None

def list_tasks(conn: sqlite3.Connection, 
               project_id: Optional[uuid.UUID] = None, 
               status: Optional[TaskStatus] = None,
               parent_task_id: Optional[uuid.UUID] = None,
               include_subtasks_of_any_parent: bool = False) -> List[Task]:
    """
    Lists tasks, optionally filtered by project_id, status, or parent_task_id.
    Orders tasks by priority (ascending) then created_at (ascending) by default.

    Args:
        conn: Active SQLite database connection.
        project_id: Optional UUID of the project to filter tasks by.
        status: Optional TaskStatus to filter by.
        parent_task_id: Optional UUID of the parent task. If None and 
                        `include_subtasks_of_any_parent` is False, lists top-level tasks.
                        If a UUID, lists direct subtasks of that parent.
        include_subtasks_of_any_parent: If True, `parent_task_id` being None has no effect on
                                        filtering by parentage (all tasks considered).
                                        If False (default) and `parent_task_id` is None,
                                        only tasks with NULL parent_task_id are returned.
                                        This argument is ignored if `parent_task_id` is a UUID.


    Returns:
        A list of Task objects.
    """
    base_sql = """
    SELECT id, title, status, project_id, parent_task_id, 
           created_at, modified_at, completed_at, 
           priority, due_date, details_md_path 
    FROM tasks
    """
    params = []
    conditions = []

    if project_id:
        conditions.append("project_id = ?")
        params.append(str(project_id))
    
    if status:
        conditions.append("status = ?")
        params.append(status.value)

    if parent_task_id is not None: # Explicitly listing subtasks of a specific parent
        conditions.append("parent_task_id = ?")
        params.append(str(parent_task_id))
    elif not include_subtasks_of_any_parent: # Listing top-level tasks (parent_task_id IS NULL)
        conditions.append("parent_task_id IS NULL")


    if conditions:
        base_sql += " WHERE " + " AND ".join(conditions)
    
    base_sql += " ORDER BY priority ASC, created_at ASC" # Default ordering

    cursor = conn.cursor()
    cursor.execute(base_sql, params)
    rows = cursor.fetchall()
    return [
        Task(
            id=uuid.UUID(row[0]), title=row[1], status=TaskStatus(row[2]),
            project_id=uuid.UUID(row[3]) if row[3] else None,
            parent_task_id=uuid.UUID(row[4]) if row[4] else None,
            created_at=datetime.fromisoformat(row[5]),
            modified_at=datetime.fromisoformat(row[6]),
            completed_at=datetime.fromisoformat(row[7]) if row[7] else None,
            priority=row[8],
            due_date=date.fromisoformat(row[9]) if row[9] else None,
            details_md_path=Path(row[10]) if row[10] else None
        ) for row in rows
    ]

def update_task(conn: sqlite3.Connection, task: Task) -> Optional[Task]:
    """
    Updates an existing task in the database.
    The task ID must exist. Updates modified_at timestamp.

    Args:
        conn: Active SQLite database connection.
        task: Task object with updated data. Its ID is used to find the record.

    Returns:
        The updated Task object if successful, None if task_id not found or update failed.
    """
    task.modified_at = datetime.now(timezone.utc)
    # If status is DONE and completed_at is not set, set it now.
    if task.status == TaskStatus.DONE and task.completed_at is None:
        task.completed_at = datetime.now(timezone.utc)
    # If status is not DONE, ensure completed_at is None (or handle as per requirements)
    elif task.status != TaskStatus.DONE:
        task.completed_at = None

    sql = """
    UPDATE tasks
    SET title = ?, status = ?, project_id = ?, parent_task_id = ?,
        modified_at = ?, completed_at = ?, priority = ?, 
        due_date = ?, details_md_path = ?
    WHERE id = ?
    """
    cursor = conn.cursor()
    try:
        cursor.execute(sql, (
            task.title,
            task.status.value,
            str(task.project_id) if task.project_id else None,
            str(task.parent_task_id) if task.parent_task_id else None,
            task.modified_at.isoformat(),
            task.completed_at.isoformat() if task.completed_at else None,
            task.priority,
            task.due_date.isoformat() if task.due_date else None,
            str(task.details_md_path) if task.details_md_path else None,
            str(task.id)
        ))
        conn.commit()
    except sqlite3.Error as e:
        # print(f"Database error updating task: {e}") # Consider logging
        raise

    if cursor.rowcount == 0:
        return None # Task ID not found
    return task

def delete_task(conn: sqlite3.Connection, task_id: uuid.UUID) -> bool:
    """
    Deletes a task by its ID.
    Note: Foreign key constraints (ON DELETE CASCADE for parent_task_id)
    will handle deleting subtasks if this task is a parent.

    Args:
        conn: Active SQLite database connection.
        task_id: UUID of the task to delete.

    Returns:
        True if a task was deleted, False otherwise.
    """
    sql = "DELETE FROM tasks WHERE id = ?"
    cursor = conn.cursor()
    try:
        cursor.execute(sql, (str(task_id),))
        conn.commit()
    except sqlite3.Error as e:
        # print(f"Database error deleting task: {e}") # Consider logging
        raise
    return cursor.rowcount > 0

# End of File: knowledge_manager/db.py
