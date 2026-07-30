from __future__ import annotations

from datetime import datetime, timezone

from rrbackup.run_monitor import RunMonitorModel, _worker
from rrbackup.run_progress import BackupProgress
from rrbackup.viewer import build_demo_records


UTC = timezone.utc
NOW = datetime(2026, 7, 29, 20, 0, tzinfo=UTC)


def test_monitor_worker_tracks_progress_and_terminal_results() -> None:
    records = build_demo_records(now=NOW)[:2]
    model = RunMonitorModel(records)
    progress = BackupProgress(
        seconds_elapsed=10,
        percent_done=0.5,
        total_files=20,
        files_done=10,
        total_bytes=200,
        bytes_done=100,
        current_files=("/C/example.bin",),
        updated_utc=NOW,
    )

    def callback(record, progress_callback, control):
        del control
        progress_callback(progress)
        return (
            {
                "backup": record.definition.name,
                "record": {
                    "state": "success",
                    "run_id": record.definition.name,
                },
            },
            0,
        )

    _worker(records, callback, model)
    jobs, active_name, message, started, stop_all = model.snapshot()
    outcome = model.outcome()

    assert [job.state for job in jobs] == ["SUCCESS", "SUCCESS"]
    assert all(job.progress == progress for job in jobs)
    assert active_name is None
    assert "finished as SUCCESS" in message
    assert started is False
    assert stop_all is False
    assert len(outcome.payloads) == 2
    assert outcome.exit_codes == (0, 0)


def test_monitor_stop_marks_pending_jobs_cancelled() -> None:
    records = build_demo_records(now=NOW)[:2]
    model = RunMonitorModel(records)
    model.stop_all = True

    _worker(records, lambda *args: ({}, 0), model)
    jobs, _, _, _, _ = model.snapshot()

    assert [job.state for job in jobs] == ["CANCELLED", "CANCELLED"]
    assert model.done.is_set()
