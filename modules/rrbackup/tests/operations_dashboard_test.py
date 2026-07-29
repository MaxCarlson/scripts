from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from rrbackup.models import RunRecord, RunState
from rrbackup.operations_dashboard import (
    OperationsDashboardModel,
    build_confirmation_lines,
    build_operation_lines,
)
from rrbackup.run_progress import BackupProgress
from rrbackup.viewer import build_demo_records

UTC = timezone.utc
NOW = datetime(2026, 7, 29, 20, 0, tzinfo=UTC)


def _terminal_payload(record, state: RunState, *, reason: str):
    run = RunRecord.create(
        profile=record.definition.profile.name,
        backup_set=record.definition.name,
        now=NOW,
    ).transition(RunState.RUNNING, now=NOW)
    run = run.transition(
        state,
        now=NOW,
        exit_code=0 if state == RunState.SUCCESS else 1,
        reason=reason,
        snapshot_id="snapshot123" if state == RunState.SUCCESS else None,
    )
    return {
        "backup": record.definition.name,
        "record": run.to_dict(),
        "summary": None,
        "executed": True,
    }


def _progress(path: str) -> BackupProgress:
    return BackupProgress(
        seconds_elapsed=10,
        percent_done=0.25,
        total_files=20,
        files_done=5,
        total_bytes=100 * 1024 * 1024,
        bytes_done=25 * 1024 * 1024,
        current_files=(path,),
        updated_utc=NOW,
    )


def test_confirmation_contains_full_information_for_every_selected_backup() -> None:
    model = OperationsDashboardModel(build_demo_records(now=NOW)[:2])
    model.toggle_selected()
    model.move_current(1)
    model.toggle_selected()

    assert model.request_start()
    lines = build_confirmation_lines(model.confirmation_snapshots(), dry_run=False)
    text = "\n".join(lines)

    assert "REAL BACKUP" in text
    assert "daily-documents" in text
    assert "weekly-media" in text
    assert "Repository:" in text
    assert "Schedule:" in text
    assert "Retention:" in text
    assert "Sources" in text
    assert "Nothing starts until Y is pressed" in text


def test_active_operation_lines_include_drive_activity_without_fake_percentages() -> None:
    records = build_demo_records(now=NOW)
    model = OperationsDashboardModel((records[0],))
    observed = []

    def callback(record, progress_callback, control):
        del control
        observed.append(record.definition.name)
        progress_callback(_progress("/C/Users/demo/Documents/report.pdf"))
        return _terminal_payload(record, RunState.SUCCESS, reason="Completed."), 0

    assert model.request_start()
    assert observed == []
    model.confirm(callback)
    model.join()

    snapshot = model.snapshots()[0]
    snapshot = snapshot.__class__(
        **{
            **snapshot.__dict__,
            "state": "RUNNING",
            "progress": _progress("/C/Users/demo/Documents/report.pdf"),
            "current_drives": ("C:",),
            "seen_drives": ("C:",),
        }
    )
    lines = build_operation_lines((snapshot,))
    text = "\n".join(line.text for line in lines)

    assert "RUNNING" in text
    assert "25.00%" in text
    assert "C:" in text
    assert "ACTIVE" in text
    assert "aggregate totals only" in text


def test_confirmation_can_start_two_backups_without_leaving_dashboard() -> None:
    records = build_demo_records(now=NOW)[:2]
    model = OperationsDashboardModel(records)
    called = []

    def callback(record, progress_callback, control):
        del control
        called.append(record.definition.name)
        progress_callback(_progress(record.definition.sources[0]))
        return _terminal_payload(record, RunState.SUCCESS, reason="Completed."), 0

    model.toggle_selected()
    model.move_current(1)
    model.toggle_selected()
    assert model.request_start()
    assert called == []

    model.confirm(callback)
    model.join()
    outcome = model.outcome()

    assert set(called) == {record.definition.name for record in records}
    assert outcome.started_count == 2
    assert outcome.exit_codes == (0, 0)
    assert all(snapshot.state == "SUCCESS" for snapshot in model.snapshots())


def test_stop_confirmation_targets_locally_managed_active_job() -> None:
    record = build_demo_records(now=NOW)[0]
    model = OperationsDashboardModel((record,))
    started = threading.Event()

    def callback(selected, progress_callback, control):
        progress_callback(_progress(selected.definition.sources[0]))
        started.set()
        deadline = time.monotonic() + 2
        while not control.stop_requested and time.monotonic() < deadline:
            time.sleep(0.005)
        assert control.stop_requested
        return _terminal_payload(
            selected,
            RunState.INTERRUPTED,
            reason="Stopped by dashboard.",
        ), 3

    assert model.request_start()
    model.confirm(callback)
    assert started.wait(timeout=1)
    assert model.request_stop()
    model.confirm(callback)
    model.join()

    snapshot = model.snapshots()[0]
    assert snapshot.state == "INTERRUPTED"
    assert model.outcome().exit_codes == (3,)
