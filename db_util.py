import os
import sqlite3

DB_PATH = os.path.expanduser("~/tmp/mrsync.db")

def initialize_database(verbose_print):
    """Initialize the SQLite database."""
    verbose_print(1, "Initializing database...")
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                destination TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('queued', 'active', 'completed'))
            )
        """)
        conn.commit()

def add_task(source, destination, verbose_print):
    """Add a new task to the queue."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO tasks (source, destination, status) VALUES (?, ?, ?)", (source, destination, 'queued'))
        conn.commit()
    verbose_print(2, f"Task added: source={source}, destination={destination}")

def detect_conflicts(path):
    """Detect conflicts with active tasks."""
    conflicts = []
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT source, destination FROM tasks WHERE status = 'active'")
        for source, dest in cursor.fetchall():
            if os.path.commonpath([path, source]) == path or os.path.commonpath([path, dest]) == path:
                conflicts.append((source, dest))
    return conflicts

def active_tasks_on_same_drive(destination):
    """Check if multiple tasks are running on the same drive."""
    drive = os.path.splitdrive(destination)[0]
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT destination FROM tasks WHERE status = 'active'")
        active_tasks = [os.path.splitdrive(dest)[0] for dest, in cursor.fetchall()]
        return active_tasks.count(drive) > 1  # More than one task on the same drive

