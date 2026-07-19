import time
from pathlib import Path

from mangadl.models import InputUrl, JobState
from mangadl.state import StateStore


def _store(tmp_path: Path) -> tuple[StateStore, str]:
    store = StateStore(tmp_path / "state.sqlite3")
    run_id = store.create_run({}, "test-run")
    item = InputUrl("1", "https://nhentai.net/g/1/", "test", 1)
    store.add_jobs(run_id, [item], {item.canonical_url: "gallery-dl"})
    return store, run_id


def test_lease_is_unique_and_completion_is_attempt_guarded(tmp_path: Path) -> None:
    store, run_id = _store(tmp_path)
    try:
        job = store.lease(run_id, 1)
        assert job is not None
        assert store.lease(run_id, 2) is None
        assert not store.complete(job["id"], "stale", JobState.SUCCEEDED)
        assert store.complete(job["id"], job["attempt_id"], JobState.SUCCEEDED)
        assert store.counts(run_id) == {"succeeded": 1}
    finally:
        store.close()


def test_expired_lease_recovers(tmp_path: Path) -> None:
    store, run_id = _store(tmp_path)
    try:
        job = store.lease(run_id, 1, lease_seconds=-1)
        assert job is not None
        assert store.recover_expired(run_id, time.time()) == 1
        recovered = store.lease(run_id, 2)
        assert recovered is not None and recovered["attempt_id"] != job["attempt_id"]
    finally:
        store.close()


def test_stale_event_is_ignored(tmp_path: Path) -> None:
    store, run_id = _store(tmp_path)
    try:
        job = store.lease(run_id, 1)
        event = {
            "run_id": run_id,
            "job_id": job["id"],
            "attempt_id": "old",
            "worker": 1,
            "event": "heartbeat",
            "wall_time": time.time(),
            "data": {"bytes_done": 10},
        }
        assert not store.apply_event(event)
        assert store.jobs(run_id)[0]["bytes_done"] == 0
    finally:
        store.close()
