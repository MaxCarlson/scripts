# File: knowledge_manager/db.py
import sqlite3
import uuid
from pathlib import Path
from typing import Optional, List, Tuple
from datetime import datetime, timezone, date

from .models import Project, ProjectStatus, Task, TaskStatus

DEFAULT_DB_FILE_NAME = "knowledge_manager.db"

def get_db_connection(db_path: Path) -> sqlite3.Connection:
    """
    Establishes a database connection to the SQLite database specified by db_path.
    Enables foreign key constraint enforcement for the connection.
    Runs migrations if needed.
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    _run_migrations(conn)
    return conn


def _run_migrations(conn: sqlite3.Connection) -> None:
    """
    Run database migrations to upgrade schema.
    Safe to call multiple times - migrations are idempotent.
    """
    cursor = conn.cursor()

    # Migration 1: Add task_links table (for cross-project linking)
    # Check if table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='task_links'")
    if not cursor.fetchone():
        # Table doesn't exist - create it
        cursor.execute("""
        CREATE TABLE task_links (
            task_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            is_origin BOOLEAN NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            modified_at TEXT NOT NULL,
            PRIMARY KEY (task_id, project_id),
            FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
        """)

        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_links_task_id ON task_links(task_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_links_project_id ON task_links(project_id)")

        conn.commit()

def init_db(db_path: Path) -> None:
    """
    Initializes the database by creating the 'projects', 'tasks', and 'task_links' tables
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

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS task_links (
            task_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            is_origin BOOLEAN NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            modified_at TEXT NOT NULL,
            PRIMARY KEY (task_id, project_id),
            FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
        """)

        # Create indexes for performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_links_task_id ON task_links(task_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_links_project_id ON task_links(project_id)")

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
    if base_dir:
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
    base_sql += " ORDER BY modified_at DESC"
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
               status_filter: Optional[List[TaskStatus]] = None,
               parent_task_id: Optional[uuid.UUID] = None,
               include_subtasks_of_any_parent: bool = False) -> List[Task]:
    """
    List tasks for a project, including:
    1. Tasks with project_id set (legacy/backward compatibility)
    2. Tasks linked via task_links table (new cross-project linking)
    """

    if project_id:
        # Get task IDs from both sources
        task_ids_set = set()

        # 1. Get tasks with project_id set (legacy)
        legacy_sql = "SELECT id FROM tasks WHERE project_id = ?"
        cursor = conn.cursor()
        cursor.execute(legacy_sql, (str(project_id),))
        for row in cursor.fetchall():
            task_ids_set.add(row[0])

        # 2. Get tasks linked via task_links
        linked_task_ids = get_linked_tasks(conn, project_id)
        for task_id in linked_task_ids:
            task_ids_set.add(str(task_id))

        # Build query for these specific tasks
        if not task_ids_set:
            return []

        placeholders = ','.join('?' for _ in task_ids_set)
        base_sql = f"""
        SELECT id, title, status, project_id, parent_task_id,
               created_at, modified_at, completed_at,
               priority, due_date, details_md_path
        FROM tasks
        WHERE id IN ({placeholders})
        """
        params = list(task_ids_set)
    else:
        # No project filter - return all tasks
        base_sql = """
        SELECT id, title, status, project_id, parent_task_id,
               created_at, modified_at, completed_at,
               priority, due_date, details_md_path
        FROM tasks
        """
        params = []

    conditions = []

    if status_filter:
        placeholders = ','.join('?' for _ in status_filter)
        conditions.append(f"status IN ({placeholders})")
        params.extend(s.value for s in status_filter)

    if parent_task_id is not None:
        conditions.append("parent_task_id = ?")
        params.append(str(parent_task_id))
    elif not include_subtasks_of_any_parent:
        conditions.append("parent_task_id IS NULL")

    if conditions:
        if " WHERE " in base_sql:
            base_sql += " AND " + " AND ".join(conditions)
        else:
            base_sql += " WHERE " + " AND ".join(conditions)

    base_sql += """
    ORDER BY
        CASE status
            WHEN 'done' THEN 1
            ELSE 0
        END,
        modified_at DESC
    """

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

# --- Task Link Operations ---

def add_task_link(
    conn: sqlite3.Connection,
    task_id: uuid.UUID,
    project_id: uuid.UUID,
    is_origin: bool = False
) -> bool:
    """
    Create a link between a task and a project.
    Returns True if link was created, False if it already existed.
    """
    now = datetime.now(timezone.utc).isoformat()
    sql = """
    INSERT OR REPLACE INTO task_links (task_id, project_id, is_origin, created_at, modified_at)
    VALUES (?, ?, ?, ?, ?)
    """
    cursor = conn.cursor()
    try:
        cursor.execute(sql, (str(task_id), str(project_id), 1 if is_origin else 0, now, now))
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        raise

def get_task_links(conn: sqlite3.Connection, task_id: uuid.UUID) -> List[Tuple[uuid.UUID, bool]]:
    """
    Get all project links for a task.
    Returns list of (project_id, is_origin) tuples.
    """
    sql = "SELECT project_id, is_origin FROM task_links WHERE task_id = ?"
    cursor = conn.cursor()
    cursor.execute(sql, (str(task_id),))
    rows = cursor.fetchall()
    return [(uuid.UUID(row[0]), bool(row[1])) for row in rows]

def get_linked_tasks(conn: sqlite3.Connection, project_id: uuid.UUID) -> List[uuid.UUID]:
    """
    Get all tasks linked to a project (via task_links table).
    Returns list of task IDs.
    """
    sql = "SELECT task_id FROM task_links WHERE project_id = ?"
    cursor = conn.cursor()
    cursor.execute(sql, (str(project_id),))
    rows = cursor.fetchall()
    return [uuid.UUID(row[0]) for row in rows]

def delete_task_link(
    conn: sqlite3.Connection,
    task_id: uuid.UUID,
    project_id: uuid.UUID
) -> bool:
    """
    Remove a link between a task and a project.
    Returns True if link was deleted, False if it didn't exist.
    """
    sql = "DELETE FROM task_links WHERE task_id = ? AND project_id = ?"
    cursor = conn.cursor()
    try:
        cursor.execute(sql, (str(task_id), str(project_id)))
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        raise

def get_task_origin_project(conn: sqlite3.Connection, task_id: uuid.UUID) -> Optional[uuid.UUID]:
    """
    Get the origin project for a task (where is_origin = TRUE).
    Returns project_id or None if no origin found.
    """
    sql = "SELECT project_id FROM task_links WHERE task_id = ? AND is_origin = 1"
    cursor = conn.cursor()
    cursor.execute(sql, (str(task_id),))
    row = cursor.fetchone()
    return uuid.UUID(row[0]) if row else None

def is_task_origin(conn: sqlite3.Connection, task_id: uuid.UUID, project_id: uuid.UUID) -> bool:
    """
    Check if a task originated in a specific project.
    """
    sql = "SELECT is_origin FROM task_links WHERE task_id = ? AND project_id = ?"
    cursor = conn.cursor()
    cursor.execute(sql, (str(task_id), str(project_id)))
    row = cursor.fetchone()
    return bool(row[0]) if row else False
