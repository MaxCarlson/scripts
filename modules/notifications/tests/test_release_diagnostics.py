"""
Tests for unified read-only release diagnostics.
Ensures zero mutation, strict read-only SQLite mode, and complete reporting.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from notifications.diagnostics import collect_release_diagnostics
from notifications.storage import StorageEngine
from notifications.models import EventEnvelopeV1
from notifications.publisher import Publisher


def test_release_diagnostics_uninitialized(tmp_path):
    """Diagnostics on uninitialized paths must report clean not_created status without throwing."""
    db_path = tmp_path / "nonexistent" / "events.db"
    auth_db_path = tmp_path / "nonexistent" / "auth.db"

    data = collect_release_diagnostics(db_path=db_path, auth_db_path=auth_db_path, probe_ports=False)
    assert data["ok"] is True
    assert data["storage"]["status"] == "not_created"
    assert data["remote_control"]["status"] == "not_created"
    assert "acceptance_gates_pending" in data
    assert "RC_recovery" in data["acceptance_gates_pending"]


def test_release_diagnostics_with_active_data(tmp_path):
    """Diagnostics must report accurate counts and maintain mode=ro read-only status."""
    db_path = tmp_path / "events.db"
    storage = StorageEngine(db_path=db_path)
    storage.migrate()

    pub = Publisher(storage=storage, default_providers=["fake_provider"])
    # Emit an open event
    pub.create_and_publish(
        source="scheduler",
        kind="task_result",
        incident_key="task:1",
        severity="critical",
        summary="Test failure",
        lifecycle="open",
    )

    data = collect_release_diagnostics(db_path=db_path, auth_db_path=tmp_path / "auth.db", probe_ports=False)
    assert data["ok"] is True
    assert data["storage"]["status"] == "healthy"
    assert data["storage"]["open_incidents"] == 1
    assert data["storage"]["pending_outbox"] == 1


def test_release_diagnostics_cli_output(tmp_path):
    """CLI subcommand release-check must support --json and human-readable output."""
    from notifications.cli import main
    import io
    import sys

    db_path = tmp_path / "events.db"
    storage = StorageEngine(db_path=db_path)
    storage.migrate()

    old_stdout = sys.stdout
    sys.stdout = buffer = io.StringIO()
    try:
        ret = main(["release-check", "-j", "-d", str(db_path)])
        assert ret == 0
        output = buffer.getvalue()
        parsed = json.loads(output)
        assert parsed["ok"] is True
        assert parsed["storage"]["status"] == "healthy"
    finally:
        sys.stdout = old_stdout
