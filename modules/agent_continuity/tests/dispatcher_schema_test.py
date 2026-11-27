from __future__ import annotations

import sqlite3

from agent_continuity.schema import SCHEMA_VERSION, ensure_schema


def test_schema_v1_migrates_dispatcher_tables_without_losing_workflows(tmp_path):
    path = tmp_path / "registry.sqlite"
    connection = sqlite3.connect(path)
    ensure_schema(connection)
    connection.execute(
        "INSERT INTO workflows(workflow_id, slug, title, status, created_at, updated_at) "
        "VALUES ('wf_abcdef', 'legacy', 'Legacy workflow', 'active', '2026-11-19T00:00:00Z', '2026-11-19T00:00:00Z')"
    )
    connection.execute("DROP TABLE dispatcher_pending_launches")
    connection.execute("DROP TABLE agent_slot_activations")
    connection.execute("DROP TABLE agent_slots")
    connection.execute("DROP TABLE dispatcher_gui_conversations")
    connection.execute("UPDATE schema_metadata SET value = '1' WHERE key = 'schema_version'")

    version = ensure_schema(connection)

    assert version == SCHEMA_VERSION == 4
    assert connection.execute("SELECT title FROM workflows WHERE workflow_id = 'wf_abcdef'").fetchone()[0] == "Legacy workflow"
    assert connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_slot_activations'"
    ).fetchone()
    assert connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='dispatcher_terminal_launches'"
    ).fetchone()
    assert {row[1] for row in connection.execute("PRAGMA table_info(agent_slots)")} >= {
        "workflow_type", "profile_id", "agent_number",
    }
    assert connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='dispatcher_launch_profiles'"
    ).fetchone()
    assert connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='dispatcher_agent_number_reservations'"
    ).fetchone()
    connection.close()


def test_schema_v2_migrates_terminal_launch_projection(tmp_path):
    path = tmp_path / "registry.sqlite"
    connection = sqlite3.connect(path)
    ensure_schema(connection)
    connection.execute("DROP TABLE dispatcher_terminal_launches")
    connection.execute("UPDATE schema_metadata SET value = '2' WHERE key = 'schema_version'")

    assert ensure_schema(connection) == SCHEMA_VERSION
    assert connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='dispatcher_terminal_launches'"
    ).fetchone()
    connection.close()


def test_schema_v3_migrates_profiles_workflows_and_number_reservations(tmp_path):
    path = tmp_path / "registry.sqlite"
    connection = sqlite3.connect(path)
    ensure_schema(connection)
    for column in ("agent_number", "profile_id", "workflow_type"):
        connection.execute(f"ALTER TABLE agent_slots DROP COLUMN {column}")
    connection.execute("DROP TABLE dispatcher_agent_number_reservations")
    connection.execute("DROP TABLE dispatcher_launch_profiles")
    connection.execute("UPDATE schema_metadata SET value = '3' WHERE key = 'schema_version'")

    assert ensure_schema(connection) == SCHEMA_VERSION == 4
    assert {row[1] for row in connection.execute("PRAGMA table_info(agent_slots)")} >= {
        "workflow_type", "profile_id", "agent_number",
    }
    assert connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='dispatcher_launch_profiles'"
    ).fetchone()
    assert connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='dispatcher_agent_number_reservations'"
    ).fetchone()
    connection.close()
