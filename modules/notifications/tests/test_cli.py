"""Tests for scripts-notify CLI interface."""

import json
import pytest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from notifications.cli import main
from notifications.models import EventEnvelopeV1
from notifications.storage import StorageEngine


def test_cli_help(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "scripts-notify" in captured.out or "usage:" in captured.out


def test_cli_health(tmp_path: Path, capsys):
    db_file = tmp_path / "cli.db"
    ret = main(["health", "-d", str(db_file), "-j"])
    assert ret == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "healthy"
    assert data["schema_version"] >= 1


def test_cli_publish_json(tmp_path: Path, capsys):
    db_file = tmp_path / "cli.db"
    event_payload = {
        "schema_version": 1,
        "event_id": str(uuid.uuid4()),
        "source": "cli_test",
        "kind": "test.cli",
        "incident_key": "cli:test",
        "severity": "critical",
        "occurred_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "summary": "CLI published critical incident",
        "lifecycle": "open",
    }
    ret = main(["publish", "-j", json.dumps(event_payload), "-d", str(db_file)])
    assert ret == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is True
    assert data["result"]["transition"] == "opened"


def test_cli_publish_file(tmp_path: Path, capsys):
    db_file = tmp_path / "cli.db"
    event_payload = {
        "schema_version": 1,
        "event_id": str(uuid.uuid4()),
        "source": "cli_test",
        "kind": "test.file",
        "incident_key": "cli:file",
        "severity": "warning",
        "occurred_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "summary": "File published warning",
        "lifecycle": "open",
    }
    event_file = tmp_path / "event.json"
    event_file.write_text(json.dumps(event_payload))

    ret = main(["publish", "-f", str(event_file), "-d", str(db_file)])
    assert ret == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is True


def test_cli_incidents_list(tmp_path: Path, capsys):
    db_file = tmp_path / "cli.db"
    # Publish an event first
    event_payload = {
        "schema_version": 1,
        "event_id": str(uuid.uuid4()),
        "source": "cli_test",
        "kind": "test.list",
        "incident_key": "cli:list",
        "severity": "info",
        "occurred_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "summary": "List testing event",
        "lifecycle": "open",
    }
    main(["publish", "-j", json.dumps(event_payload), "-d", str(db_file)])
    capsys.readouterr()  # Clear capture buffer

    ret = main(["incidents", "list", "-d", str(db_file), "-j"])
    assert ret == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is True
    assert len(data["incidents"]) == 1
    assert data["incidents"][0]["summary"] == "List testing event"


def test_cli_acknowledge_dry_run_vs_apply(tmp_path: Path, capsys):
    db_file = tmp_path / "cli.db"
    event_payload = {
        "schema_version": 1,
        "event_id": str(uuid.uuid4()),
        "source": "cli_test",
        "kind": "test.ack",
        "incident_key": "cli:ack",
        "severity": "critical",
        "occurred_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "summary": "Ack test event",
        "lifecycle": "open",
    }
    main(["publish", "-j", json.dumps(event_payload), "-d", str(db_file)])
    capsys.readouterr()  # Clear capture buffer

    storage = StorageEngine(db_file)
    incidents = storage.list_incidents()
    inc_id = incidents[0].incident_id

    # Dry-run acknowledge (without -a/--apply)
    ret_dry = main(["incidents", "acknowledge", "-i", inc_id, "-d", str(db_file), "-j"])
    assert ret_dry == 0
    captured_dry = capsys.readouterr()
    data_dry = json.loads(captured_dry.out)
    assert data_dry["dry_run"] is True
    assert storage.get_incident(inc_id).status == "open"  # Status unchanged!

    # Real acknowledge with -a/--apply
    ret_apply = main(["incidents", "acknowledge", "-i", inc_id, "-a", "-d", str(db_file), "-j"])
    assert ret_apply == 0
    captured_apply = capsys.readouterr()
    data_apply = json.loads(captured_apply.out)
    assert data_apply["ok"] is True
    assert storage.get_incident(inc_id).status == "acknowledged"  # Status updated!


def test_cli_coordinator_status_and_test(tmp_path: Path, capsys):
    """Coordinator CLI commands validate loopback target and report unmonitored status."""
    db_file = tmp_path / "cli.db"

    # Status without observations
    ret_stat = main(["coordinator", "status", "-d", str(db_file), "-j"])
    assert ret_stat == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is True
    assert data["monitored"] is False
    assert data["observation"] is None

    # Test loopback validation
    ret_test = main(["coordinator", "test", "-u", "http://127.0.0.1:1235/status", "-j"])
    assert ret_test == 0
    captured_test = capsys.readouterr()
    data_test = json.loads(captured_test.out)
    assert data_test["ok"] is True
    assert data_test["loopback_validated"] is True

    # Test non-loopback rejection
    ret_bad = main(["coordinator", "test", "-u", "http://example.com/status", "-j"])
    assert ret_bad == 1
