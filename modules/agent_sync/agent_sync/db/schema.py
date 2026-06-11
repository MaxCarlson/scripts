"""SQLite schema initialization."""

import sqlite3


def initialize_schema(conn: sqlite3.Connection) -> None:
    """Initialize the minimal coordination schema."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agents (
            agent_name TEXT PRIMARY KEY,
            binary_name TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'planned',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            task_id TEXT,
            agent_name TEXT NOT NULL,
            worktree_path TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(task_id) REFERENCES tasks(task_id)
        )
        """
    )
    for agent, binary in [("claude", "claude"), ("codex", "codex"), ("gemini", "gemini"), ("local-lmstudio", "local")]:
        conn.execute(
            "INSERT OR IGNORE INTO agents(agent_name, binary_name, enabled) VALUES (?, ?, 1)",
            (agent, binary),
        )
    conn.commit()
