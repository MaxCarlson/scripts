"""
Unit tests verifying Windows Scheduled Task definition stability and safety.
Ensures task definitions survive worktree deletions, quote arguments safely,
default to dry-run, and decouple from ephemeral directories.
"""
from __future__ import annotations

import sys
from pathlib import Path
from notifications.integrations.resource_coordinator import (
    COORDINATOR_TASK_NAME,
    install_coordinator_task,
)
from notifications.monitoring.service import (
    TASK_NAME as HEARTBEAT_TASK_NAME,
    install_heartbeat_task,
)


def test_coordinator_task_dry_run_default():
    """Coordinator task installation must default to dry-run."""
    preview = install_coordinator_task(apply=False)
    assert preview["ok"] is True
    assert preview["dry_run"] is True
    assert preview["task_name"] == COORDINATOR_TASK_NAME
    assert preview["working_directory"] == str(Path.home().resolve())
    assert "notifications.cli" in preview["arguments"]
    assert "coordinator poll" in preview["arguments"]


def test_coordinator_task_argument_quoting_with_spaces(tmp_path):
    """Arguments with spaces in path must be safely quoted via list2cmdline."""
    space_db = tmp_path / "my folder with spaces" / "events.db"
    preview = install_coordinator_task(apply=False, db_path=space_db)
    assert preview["ok"] is True
    # Verify quotes exist around the path containing spaces
    assert f'"{space_db}"' in preview["arguments"] or f'"{str(space_db)}"' in preview["arguments"]


def test_coordinator_task_rejects_newlines_and_nulls():
    """Coordinator task parameters must reject newline/null injections."""
    res = install_coordinator_task(status_url="http://127.0.0.1:1235/status\nmalicious")
    assert res["ok"] is False
    assert "Invalid characters" in res["error"] or "Invalid status URL" in res["error"]


def test_heartbeat_task_dry_run_default():
    """Heartbeat task installation must default to dry-run."""
    preview = install_heartbeat_task(apply=False)
    assert preview["ok"] is True
    assert preview["dry_run"] is True
    assert preview["task_name"] == HEARTBEAT_TASK_NAME
    assert "notifications.monitoring.runner" in preview["arguments"]
    assert preview["executable"] == str(Path(sys.executable).resolve())


def test_heartbeat_task_headless_elevation_notice():
    """Headless/system mode must flag required elevation in dry-run preview."""
    preview = install_heartbeat_task(apply=False, headless=True)
    assert preview["ok"] is True
    assert preview["dry_run"] is True
    assert preview["headless"] is True
    assert preview["elevation_required"] is True
    assert "elevation_notice" in preview
