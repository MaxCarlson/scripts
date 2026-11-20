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

    assert version == SCHEMA_VERSION == 2
    assert connection.execute("SELECT title FROM workflows WHERE workflow_id = 'wf_abcdef'").fetchone()[0] == "Legacy workflow"
    assert connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_slot_activations'"
    ).fetchone()
    connection.close()
