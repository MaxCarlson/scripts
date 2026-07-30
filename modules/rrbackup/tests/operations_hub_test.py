from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from rrbackup.models import RunRecord, RunState
from rrbackup.operations_hub import (
    OperationsHubModel,
    _history_rows,
    build_confirmation_lines,
    build_operation_lines,
)
from rrbackup.run_progress import BackupProgress
from rrbackup.viewer import build_demo_records

UTC = timezone.utc
NOW = datetime(2026, 7, 29, 22, 0, tzinfo=UTC)


def _progress() -> BackupProgress:
    return BackupProgress(
        seconds_elapsed=60,
        percent_done=0.0016,
        total_files=1_533_206,
        files_done=846,
        total_bytes=7_575_000_000_000,
        bytes_done=12_207_000_000,
        current_files=(
            "/C/Games/Black Myth Wukong/b1/Content/Paks/pakchunk0-Windows.pak",
        ),
        updated_utc=NOW,
    )


def _run(record, state: RunState) -> RunRecord:
    run = RunRecord.create(
        profile=record.definition.profile.name,
        backup_set=record.definition.name,
        now=NOW,
    ).transition(RunState.RUNNING, now=NOW)
    run.metadata["progress"] = _progress().to_dict()
    if state == RunState.RUNNING:
        return run
    return run.transition(
        state,
        now=NOW,
        exit_code=1,
        reason="Backup execution was interrupted.",
    )


def test_terminal_attempt_is_idle_and_never_rendered_as_live_activity() -> None:
    record = build_demo_records(now=NOW)[0]
    record = replace(record, latest_run=_run(record, RunState.INTERRUPTED))
    model = OperationsHubModel((record,))

    snapshot = model.snapshots()[0]

    assert snapshot.state == "IDLE"
    assert snapshot.last_result == "INTERRUPTED"
    assert snapshot.progress is None
    assert snapshot.last_attempt_progress is not None
    assert snapshot.current_drives == tuple()
    assert snapshot.seen_drives == tuple()
    assert model.status_line().startswith("RUNNING NOW: 0")
    assert "No backups are currently running" in model.activity_line()

    model.toggle_expanded(True)
    text = "\n".join(line.text for line in build_operation_lines(model.snapshots()))

    assert "IDLE" in text
    assert "INTERRUPTED" in text
    assert "CONFIGURED" in text
    assert "Last attempt partial files" in text
    assert "Last observed files" in text
    assert " ACTIVE " not in text
    assert "Live ETA" not in text


def test_genuinely_running_attempt_shows_live_state_and_drive_activity() -> None:
    record = build_demo_records(now=NOW)[0]
    record = replace(record, latest_run=_run(record, RunState.RUNNING))
    model = OperationsHubModel((record,))

    snapshot = model.snapshots()[0]
    text = "\n".join(line.text for line in build_operation_lines((snapshot,)))

    assert snapshot.state == "RUNNING"
    assert snapshot.last_result == "RUNNING"
    assert snapshot.progress is not None
    assert "RUNNING" in text
    assert "ACTIVE" in text
    assert "aggregate totals only" in text
    assert model.status_counts()["running"] == 1


def test_confirmation_distinguishes_now_from_last_result() -> None:
    record = build_demo_records(now=NOW)[0]
    record = replace(record, latest_run=_run(record, RunState.INTERRUPTED))
    model = OperationsHubModel((record,))
    model.toggle_selected()

    assert model.request_start()
    text = "\n".join(build_confirmation_lines(model.confirmation_snapshots(), dry_run=False))

    assert "NOW IDLE" in text
    assert "LAST RESULT INTERRUPTED" in text
    assert "REAL BACKUP" in text
    assert "Sources" in text


def test_history_tab_contains_attempt_and_completed_snapshot() -> None:
    record = build_demo_records(now=NOW)[0]
    record = replace(record, latest_run=_run(record, RunState.INTERRUPTED))

    rows = _history_rows((record,), "")
    text = "\n".join(row.line for row in rows)

    assert "ATTEMPT" in text
    assert "INTERRUPTED" in text
    assert "SNAPSHOT" in text
    assert "COMPLETED" in text


def test_completed_worker_returns_to_idle_but_keeps_latest_result() -> None:
    record = build_demo_records(now=NOW)[0]
    model = OperationsHubModel((record,))
    payload_run = _run(record, RunState.INTERRUPTED)

    model.complete(
        record.definition.name,
        {
            "backup": record.definition.name,
            "record": payload_run.to_dict(),
            "summary": None,
            "executed": True,
        },
        3,
    )
    snapshot = model.snapshots()[0]

    assert snapshot.state == "IDLE"
    assert snapshot.last_result == "INTERRUPTED"
    assert snapshot.progress is None
    assert snapshot.last_attempt_progress is not None
