import sqlite3
from pathlib import Path

import pytest

from agent_sync.db.connection import get_connection
from agent_sync.db.schema import initialize_schema
from agent_sync.routing import AgentCapability, select_agent


def _fresh_db(tmp_path: Path) -> sqlite3.Connection:
    conn = get_connection(tmp_path / "state.sqlite3")
    initialize_schema(conn)
    return conn


def test_select_agent_explicit_returns_that_agent(tmp_path: Path) -> None:
    conn = _fresh_db(tmp_path)
    result = select_agent(conn=conn, preferred="codex", capabilities_required=frozenset())
    assert result == "codex"


def test_select_agent_auto_prefers_least_loaded(tmp_path: Path) -> None:
    conn = _fresh_db(tmp_path)
    conn.execute("INSERT INTO tasks (task_id, title, description, status) VALUES ('T1', 'T', '', 'in_progress')")
    conn.execute("INSERT INTO runs (run_id, task_id, agent_name, worktree_path, status) VALUES ('R1', 'T1', 'claude', '/tmp/x', 'active')")
    conn.commit()
    result = select_agent(conn=conn, preferred="auto", capabilities_required=frozenset({AgentCapability.CODE_REVIEW}))
    assert result != "claude"


def test_select_agent_unknown_explicit_raises(tmp_path: Path) -> None:
    conn = _fresh_db(tmp_path)
    with pytest.raises(ValueError, match="Unknown agent"):
        select_agent(conn=conn, preferred="unknown", capabilities_required=frozenset())
