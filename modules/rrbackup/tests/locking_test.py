from __future__ import annotations

import json

import pytest

from rrbackup.locking import (
    AlreadyRunningError,
    InvalidLockError,
    LockOwnershipError,
    ProcessIdentity,
    ProcessLock,
)


def identity(pid: int = 100, create_time: float = 10.0) -> ProcessIdentity:
    return ProcessIdentity(pid=pid, create_time=create_time, executable="python")


def test_acquire_and_release_round_trip(tmp_path):
    path = tmp_path / "backup.lock"
    lock = ProcessLock(
        path,
        identity_factory=lambda: identity(),
        matcher=lambda value: value == identity(),
    )

    lock.acquire()
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert lock.acquired
    assert payload["process"]["pid"] == 100
    assert payload["token"] == lock.token
    assert lock.inspect().active

    lock.release()
    assert not path.exists()
    assert not lock.acquired


def test_context_manager_releases_after_error(tmp_path):
    path = tmp_path / "backup.lock"

    with pytest.raises(RuntimeError, match="boom"):
        with ProcessLock(
            path,
            identity_factory=lambda: identity(),
            matcher=lambda value: value == identity(),
        ):
            raise RuntimeError("boom")

    assert not path.exists()


def test_live_matching_process_blocks_acquisition(tmp_path):
    path = tmp_path / "backup.lock"
    path.write_text(
        json.dumps(
            {
                "token": "other",
                "process": identity(pid=222).to_dict(),
            }
        ),
        encoding="utf-8",
    )
    lock = ProcessLock(
        path,
        identity_factory=lambda: identity(),
        matcher=lambda value: value.pid == 222,
    )

    with pytest.raises(AlreadyRunningError, match="222"):
        lock.acquire()

    assert path.exists()


def test_stale_process_lock_is_replaced(tmp_path):
    path = tmp_path / "backup.lock"
    path.write_text(
        json.dumps(
            {
                "token": "stale",
                "process": identity(pid=222).to_dict(),
            }
        ),
        encoding="utf-8",
    )
    lock = ProcessLock(
        path,
        identity_factory=lambda: identity(pid=333),
        matcher=lambda value: False,
    )

    lock.acquire()
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["process"]["pid"] == 333
    assert payload["token"] == lock.token


def test_stale_lock_is_not_removed_after_token_changes(tmp_path, monkeypatch):
    path = tmp_path / "backup.lock"
    path.write_text(
        json.dumps(
            {
                "token": "stale",
                "process": identity(pid=222).to_dict(),
            }
        ),
        encoding="utf-8",
    )
    lock = ProcessLock(
        path,
        identity_factory=lambda: identity(pid=333),
        matcher=lambda value: value.pid == 444,
    )
    original_inspect = lock.inspect
    calls = {"count": 0}

    def racing_inspect():
        inspection = original_inspect()
        if calls["count"] == 0:
            path.write_text(
                json.dumps(
                    {
                        "token": "replacement",
                        "process": identity(pid=444).to_dict(),
                    }
                ),
                encoding="utf-8",
            )
        calls["count"] += 1
        return inspection

    monkeypatch.setattr(lock, "inspect", racing_inspect)

    with pytest.raises(AlreadyRunningError, match="444"):
        lock.acquire()

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["token"] == "replacement"
    assert payload["process"]["pid"] == 444


def test_invalid_lock_is_not_removed_automatically(tmp_path):
    path = tmp_path / "backup.lock"
    path.write_text("not-json", encoding="utf-8")
    lock = ProcessLock(
        path,
        identity_factory=lambda: identity(),
        matcher=lambda value: False,
    )

    with pytest.raises(InvalidLockError):
        lock.acquire()

    assert path.read_text(encoding="utf-8") == "not-json"


def test_release_refuses_foreign_token(tmp_path):
    path = tmp_path / "backup.lock"
    lock = ProcessLock(
        path,
        identity_factory=lambda: identity(),
        matcher=lambda value: True,
    )
    lock.acquire()

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["token"] = "foreign"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(LockOwnershipError):
        lock.release()

    assert path.exists()


def test_inspect_reports_invalid_and_missing_locks(tmp_path):
    path = tmp_path / "backup.lock"
    lock = ProcessLock(
        path,
        identity_factory=lambda: identity(),
        matcher=lambda value: False,
    )

    missing = lock.inspect()
    assert not missing.exists
    assert missing.valid

    path.write_text("[]", encoding="utf-8")
    invalid = lock.inspect()
    assert invalid.exists
    assert not invalid.valid
