# File: knowledge_manager/db.py
import sqlite3
import uuid
from pathlib import Path
from typing import Optional, List
from datetime import datetime, timezone, date

from .models import Project, ProjectStatus, Task, TaskStatus

DEFAULT_DB_FILE_NAME = "knowledge_manager.db"

def get_db_connection(db_path: Path) -> sqlite3.Connection:
    """
    Establishes a database connection to the SQLite database specified by db_path.
    Enables foreign key constraint enforcement for the connection.
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db(db_path: Path) -> None:
    """
    Initializes the database by creating the 'projects' and 'tasks' tables
    if they do not already exist.
    """
    conn = None
    try:
        conn = get_db_connection(db_path)
        cursor = conn.cursor()

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
        conn.commit()
    except sqlite3.Error as e:
        raise 
    finally:
        if conn:
            conn.close()

def get_default_db_path(base_dir: Optional[Path] = None) -> Path:
    """
    Determines the default path for the database file.
    Uses ~/.local/share/knowledge_manager_data/ if base_dir is not provided
    (aligning with utils.py's DEFAULT_BASE_DATA_DIR_NAME).
    """
    # This should align with utils.DEFAULT_BASE_DATA_DIR_NAME for consistency
    # Assuming utils.py defines DEFAULT_BASE_DATA_DIR_NAME = "knowledge_manager_data"
    # and utils.DB_FILE_NAME = "knowledge_manager.db"
    if base_dir:
        # If base_dir is provided, it's assumed to be the root data dir
        # e.g., ~/.local/share/knowledge_manager_data/
        km_data_dir = base_dir
    else:
        km_data_dir = Path.home() / ".local" / "share" / "knowledge_manager_data"
    
    km_data_dir.mkdir(parents=True, exist_ok=True)
    return km_data_dir / DEFAULT_DB_FILE_NAME

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
            str(project.id), project.name, project.status.value,
            project.created_at.isoformat(), project.modified_at.isoformat(),
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
            str(task.id), task.title, task.status.value,
            str(task.project_id) if task.project_id else None,
            str(task.parent_task_id) if task.parent_task_id else None,
            task.created_at.isoformat(), task.modified_at.isoformat(),
            task.completed_at.isoformat() if task.completed_at else None,
            task.priority,
            task.due_date.isoformat() if task.due_date else None,
            str(task.details_md_path) if task.details_md_path else None
        ))
        conn.commit()
    except sqlite3.IntegrityError as e:
        raise
    return task

def get_task_by_id(conn: sqlite3.Connection, task_id: uuid.UUID) -> Optional[Task]:
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
            id=uuid.UUID(row[0]), title=row[1], status=TaskStatus(row[2]),
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

def get_tasks_by_title_prefix(
    conn: sqlite3.Connection, 
    title_prefix: str, 
    project_id: Optional[uuid.UUID] = None,
    limit: Optional[int] = None
) -> List[Task]:
    """
    Retrieves tasks where the title starts with the given prefix.
    Optionally filters by project_id. Case-insensitive.
    """
    sql_parts = [
        "SELECT id, title, status, project_id, parent_task_id, "
        "created_at, modified_at, completed_at, "
        "priority, due_date, details_md_path",
        "FROM tasks",
        "WHERE lower(title) LIKE lower(?)"
    ]
    params = [title_prefix + '%']

    if project_id:
        sql_parts.append("AND project_id = ?")
        params.append(str(project_id))
    
    sql_parts.append("ORDER BY created_at DESC") 

    if limit is not None and limit > 0:
        sql_parts.append("LIMIT ?")
        params.append(limit)

    sql = " ".join(sql_parts)
    cursor = conn.cursor()
    cursor.execute(sql, params)
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

def list_tasks(conn: sqlite3.Connection, 
               project_id: Optional[uuid.UUID] = None, 
               status: Optional[TaskStatus] = None,
               parent_task_id: Optional[uuid.UUID] = None,
               include_subtasks_of_any_parent: bool = False) -> List[Task]:
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
    if parent_task_id is not None:
        conditions.append("parent_task_id = ?")
        params.append(str(parent_task_id))
    elif not include_subtasks_of_any_parent:
        conditions.append("parent_task_id IS NULL")

    if conditions:
        base_sql += " WHERE " + " AND ".join(conditions)
    base_sql += " ORDER BY priority ASC, created_at ASC"
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
    task.modified_at = datetime.now(timezone.utc)
    if task.status == TaskStatus.DONE and task.completed_at is None:
        task.completed_at = datetime.now(timezone.utc)
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
            task.title, task.status.value,
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
        raise
    return task if cursor.rowcount > 0 else None

def delete_task(conn: sqlite3.Connection, task_id: uuid.UUID) -> bool:
    sql = "DELETE FROM tasks WHERE id = ?"
    cursor = conn.cursor()
    try:
        cursor.execute(sql, (str(task_id),))
        conn.commit()
    except sqlite3.Error as e:
        raise
    return cursor.rowcount > 0

# End of File: knowledge_manager/db.py
