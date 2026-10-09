"""Tests for the daemon's file-backed one-shot run queue."""
from datetime import datetime, timedelta

from scheduler.run_requests import RunRequestQueue


def test_queue_claims_only_requests_that_are_due(tmp_path):
    queue = RunRequestQueue(tmp_path)
    now = datetime(2026, 10, 8, 12, 0, 0)
    request = queue.enqueue("Winget Update", delay_seconds=10, now=now)

    assert request.run_at == now + timedelta(seconds=10)
    assert queue.claim_due(now=now + timedelta(seconds=9)) == []

    due = queue.claim_due(now=now + timedelta(seconds=10))
    assert len(due) == 1
    assert due[0].request_id == request.request_id
    assert due[0].task_name == "Winget Update"
    assert due[0].request_path.suffix == ".running"
    assert queue.claim_due(now=now + timedelta(seconds=11)) == []

    queue.complete(due[0])
    assert list(queue.directory.iterdir()) == []


def test_queue_rejects_negative_delay(tmp_path):
    queue = RunRequestQueue(tmp_path)

    try:
        queue.enqueue("Winget Update", delay_seconds=-1)
    except ValueError as exc:
        assert "cannot be scheduled in the past" in str(exc)
    else:
        raise AssertionError("Expected nonpositive delay to be rejected")


def test_queue_moves_malformed_request_out_of_pending_files(tmp_path):
    queue = RunRequestQueue(tmp_path)
    queue.directory.mkdir()
    invalid = queue.directory / "invalid.json"
    invalid.write_text("not json", encoding="utf-8")

    assert queue.claim_due(now=datetime(2026, 10, 8, 12, 0)) == []
    assert not invalid.exists()
    assert (queue.directory / "invalid.invalid").exists()


def test_queue_expires_stale_requests_instead_of_running_them_later(tmp_path):
    queue = RunRequestQueue(tmp_path)
    now = datetime(2026, 10, 8, 12, 0, 0)
    request = queue.enqueue("Winget Update", delay_seconds=10, now=now)

    assert queue.claim_due(now=request.expires_at) == []
    assert not request.request_path.exists()
    assert request.request_path.with_suffix(".expired").exists()
