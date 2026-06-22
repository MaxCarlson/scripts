"""Tests for process-owned URL-file locking."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from ytaedl.urlfile_lock import UrlFileLock, lock_path_for, probe_urlfile_lock


def test_lock_acquire_release_and_metadata(tmp_path: Path) -> None:
    source = tmp_path / "urls.txt"
    lock_dir = tmp_path / "archive" / "locks"
    source.write_text("https://example.com/video\n", encoding="utf-8")

    first = UrlFileLock(source, worker_slot=3, manager_pid=123, lock_dir=lock_dir)
    assert first.try_acquire().acquired

    blocked = UrlFileLock(source, lock_dir=lock_dir).try_acquire()
    assert blocked.status == "held"
    assert blocked.owner
    assert blocked.owner["pid"] == os.getpid()
    assert blocked.owner["worker_slot"] == 3

    first.release()
    assert probe_urlfile_lock(source, lock_dir).status == "available"


def test_stale_or_malformed_metadata_does_not_hold_lock(tmp_path: Path) -> None:
    source = tmp_path / "urls.txt"
    lock_dir = tmp_path / "archive" / "locks"
    source.write_text("https://example.com/video\n", encoding="utf-8")
    lock_path = lock_path_for(source, lock_dir)
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text("{not-json", encoding="utf-8")

    assert probe_urlfile_lock(source, lock_dir).status == "available"


def test_equivalent_paths_share_lock_identity(tmp_path: Path) -> None:
    source = tmp_path / "urls.txt"
    lock_dir = tmp_path / "archive" / "locks"
    source.write_text("https://example.com/video\n", encoding="utf-8")

    assert lock_path_for(source, lock_dir) == lock_path_for(tmp_path / "." / "urls.txt", lock_dir)


def test_same_named_files_in_different_directories_have_distinct_locks(tmp_path: Path) -> None:
    lock_dir = tmp_path / "archive" / "locks"
    first = tmp_path / "f1" / "urlfile.txt"
    second = tmp_path / "f2" / "urlfile.txt"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("https://example.com/first\n", encoding="utf-8")
    second.write_text("https://example.com/second\n", encoding="utf-8")

    first_lock = lock_path_for(first, lock_dir)
    second_lock = lock_path_for(second, lock_dir)

    assert first_lock.parent == lock_dir.resolve()
    assert second_lock.parent == lock_dir.resolve()
    assert first_lock != second_lock
    assert first_lock.name.startswith("urlfile.txt.")
    assert second_lock.name.startswith("urlfile.txt.")
    assert not first.with_name(first.name + ".ytaedl.lock").exists()
    assert not second.with_name(second.name + ".ytaedl.lock").exists()


def test_process_exit_returns_lock(tmp_path: Path) -> None:
    source = tmp_path / "urls.txt"
    ready = tmp_path / "ready.json"
    lock_dir = tmp_path / "archive" / "locks"
    source.write_text("https://example.com/video\n", encoding="utf-8")
    code = (
        "import json,sys,time\n"
        "from pathlib import Path\n"
        "from ytaedl.urlfile_lock import UrlFileLock\n"
        "lock=UrlFileLock(Path(sys.argv[1]), lock_dir=Path(sys.argv[3]))\n"
        "attempt=lock.try_acquire()\n"
        "Path(sys.argv[2]).write_text(json.dumps({'status': attempt.status}))\n"
        "time.sleep(60)\n"
    )
    proc = subprocess.Popen([sys.executable, "-c", code, str(source), str(ready), str(lock_dir)])
    try:
        deadline = time.time() + 10
        while not ready.exists() and time.time() < deadline:
            time.sleep(0.05)
        assert json.loads(ready.read_text(encoding="utf-8"))["status"] == "acquired"
        assert probe_urlfile_lock(source, lock_dir).status == "held"
        proc.kill()
        proc.wait(timeout=10)
        deadline = time.time() + 10
        while probe_urlfile_lock(source, lock_dir).status != "available" and time.time() < deadline:
            time.sleep(0.05)
        assert probe_urlfile_lock(source, lock_dir).status == "available"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)


def test_waiter_acquires_after_owner_releases(tmp_path: Path) -> None:
    source = tmp_path / "urls.txt"
    lock_dir = tmp_path / "archive" / "locks"
    source.write_text("https://example.com/video\n", encoding="utf-8")
    owner = UrlFileLock(source, lock_dir=lock_dir)
    assert owner.try_acquire().acquired
    waits = []

    release_thread = threading.Thread(
        target=lambda: (time.sleep(0.1), owner.release()),
        daemon=True,
    )
    release_thread.start()
    waiter = UrlFileLock(source, lock_dir=lock_dir)
    attempt = waiter.acquire_waiting(
        lambda: False,
        poll_seconds=0.02,
        on_wait=lambda blocked: waits.append(blocked.status),
    )
    try:
        assert attempt.acquired
        assert waits
    finally:
        waiter.release()
        release_thread.join(timeout=2)


def test_probe_does_not_create_lock_file(tmp_path: Path) -> None:
    source = tmp_path / "urls.txt"
    lock_dir = tmp_path / "archive" / "locks"
    source.write_text("https://example.com/video\n", encoding="utf-8")

    lock_path = lock_path_for(source, lock_dir)
    assert not lock_path.exists()

    attempt = probe_urlfile_lock(source, lock_dir)
    assert attempt.status == "available"
    assert not lock_path.exists()
