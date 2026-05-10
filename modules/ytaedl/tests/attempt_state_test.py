"""Attempt identity handling for manager worker progress state."""

from __future__ import annotations

import ytaedl.manager as manager


def test_new_attempt_clears_previous_progress():
    ws = manager.WorkerState(slot=1)
    manager._begin_worker_attempt(ws, "downloading", "attempt-old", clear_progress=True)
    assert manager._apply_worker_progress_event(
        ws,
        {
            "event": "progress",
            "attempt_id": "attempt-old",
            "downloaded": 99,
            "total": 100,
            "speed_bps": 10,
            "percent": 99.0,
        },
        generation=1,
    )
    assert ws.percent == 99.0

    manager._begin_worker_attempt(ws, "fallback", "attempt-new", clear_progress=True)

    assert ws.active_attempt_id == "attempt-new"
    assert ws.percent is None
    assert ws.downloaded_bytes is None
    assert ws.progress_attempt_id is None


def test_old_fallback_progress_cannot_update_after_new_attempt_is_active():
    ws = manager.WorkerState(slot=1)
    manager._begin_worker_attempt(ws, "fallback", "candidate-2", clear_progress=True)

    accepted = manager._apply_worker_progress_event(
        ws,
        {
            "event": "progress",
            "attempt_id": "candidate-1",
            "downloaded": 999,
            "total": 1000,
            "speed_bps": 100,
            "percent": 99.9,
        },
        generation=3,
    )

    assert not accepted
    assert ws.active_attempt_id == "candidate-2"
    assert ws.percent is None
    assert ws.downloaded_bytes is None


def test_matching_attempt_progress_updates_worker_state():
    ws = manager.WorkerState(slot=1)
    manager._begin_worker_attempt(ws, "fallback", "candidate-2", clear_progress=True)

    accepted = manager._apply_worker_progress_event(
        ws,
        {
            "event": "progress",
            "attempt_id": "candidate-2",
            "downloaded": 25,
            "total": 100,
            "speed_bps": 5,
        },
        generation=3,
    )

    assert accepted
    assert ws.percent == 25.0
    assert ws.downloaded_bytes == 25
    assert ws.progress_attempt_id == "candidate-2"
