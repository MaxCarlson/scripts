from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from rrbackup.models import RunRecord, RunState
from rrbackup.state import RunStateStore, atomic_write_json, read_json

UTC = timezone.utc
NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def make_record(run_id: str = "run-1") -> RunRecord:
    return RunRecord.create(
        profile="local",
        backup_set="local-main",
        now=NOW,
        run_id=run_id,
    )


def test_atomic_write_json_round_trip(tmp_path):
    path = tmp_path / "nested" / "state.json"
    atomic_write_json(path, {"value": 1})

    assert read_json(path) == {"value": 1}
    assert not list(path.parent.glob("*.tmp"))


def test_read_json_returns_empty_when_missing(tmp_path):
    assert read_json(tmp_path / "missing.json") == {}


def test_read_json_rejects_non_object(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="JSON object"):
        read_json(path)


def test_store_saves_latest_and_run_history(tmp_path):
    store = RunStateStore(tmp_path / "state")
    record = make_record()

    store.save(record)

    assert store.load_latest() == record
    assert store.load_run("run-1") == record
    assert store.load_run("missing") is None


def test_only_real_success_updates_last_success(tmp_path):
    store = RunStateStore(tmp_path / "state")
    queued = make_record()
    dry_run = queued.transition(RunState.DRY_RUN, now=NOW, exit_code=0)
    store.save(dry_run)

    assert store.load_last_success() is None

    real = make_record("run-2").transition(RunState.RUNNING, now=NOW)
    success = real.transition(RunState.SUCCESS, now=NOW, exit_code=0)
    store.save(success)

    assert store.load_last_success() == success

    failed = make_record("run-3").transition(RunState.RUNNING, now=NOW)
    failed = failed.transition(RunState.FAILURE, now=NOW, exit_code=1)
    store.save(failed)

    assert store.load_latest() == failed
    assert store.load_last_success() == success


def test_reconcile_stale_running_marks_interrupted(tmp_path):
    store = RunStateStore(tmp_path / "state")
    running = make_record().transition(RunState.RUNNING, now=NOW)
    running.pid = 123
    running.process_start_time = 456.0
    store.save(running)

    reconciled = store.reconcile_stale_running(lambda pid, start: False)

    assert reconciled is not None
    assert reconciled.state == RunState.INTERRUPTED
    assert store.load_latest().state == RunState.INTERRUPTED
    assert store.load_last_success() is None


def test_reconcile_preserves_live_running_record(tmp_path):
    store = RunStateStore(tmp_path / "state")
    running = make_record().transition(RunState.RUNNING, now=NOW)
    running.pid = 123
    running.process_start_time = 456.0
    store.save(running)

    result = store.reconcile_stale_running(
        lambda pid, start: pid == 123 and start == 456.0
    )

    assert result == running
    assert store.load_latest() == running


def test_reconcile_missing_identity_marks_interrupted(tmp_path):
    store = RunStateStore(tmp_path / "state")
    running = make_record().transition(RunState.RUNNING, now=NOW)
    store.save(running)

    result = store.reconcile_stale_running(lambda pid, start: True)

    assert result.state == RunState.INTERRUPTED
    assert "identity" in result.reason.lower()


def test_atomic_write_failure_removes_temporary_file(tmp_path, monkeypatch):
    path = tmp_path / "state.json"

    def fail_replace(source, target):
        raise OSError("replace failed")

    monkeypatch.setattr("rrbackup.state.os.replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        atomic_write_json(path, {"value": 1})

    assert not path.exists()
    assert not list(tmp_path.glob("*.tmp"))
