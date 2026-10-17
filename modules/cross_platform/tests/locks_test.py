from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from cross_platform.locks import (
    current_process_identity,
    directory_lock,
    external_target_lock_dir,
    folder_read_lock,
    inspect_folder_locks,
    inspect_process,
    probe_byte_range_lock,
    unlock_folder_locks,
)


def test_directory_lock_records_holder_metadata_and_cleans_on_release(tmp_path: Path) -> None:
    target = tmp_path / "gallery"
    target.mkdir()

    with directory_lock(target, filename=".compress.lock", operation="compress -w"):
        # No sidecar files should be created in the gallery folder.
        assert {p.name for p in target.iterdir()} == {".compress.lock"}
        record = probe_byte_range_lock(
            target / ".compress.lock",
            kind="write",
            mode="write",
        )
        assert record.engaged is True
        assert record.stale is False
        assert record.operation == "compress -w"
        assert record.process is not None
        assert record.process.pid == os.getpid()
        assert record.process.alive is True

    after = probe_byte_range_lock(
        target / ".compress.lock",
        kind="write",
        mode="write",
    )
    assert after.engaged is False
    assert after.stale is False
    assert (target / ".compress.lock").stat().st_size == 1


def test_directory_lock_contention_includes_holder_details(tmp_path: Path) -> None:
    target = tmp_path / "lib"
    meta = target / ".mangadl"
    meta.mkdir(parents=True)
    script = (
        "import os, time\n"
        "from pathlib import Path\n"
        "from cross_platform.locks import directory_lock\n"
        f"meta = Path({str(meta)!r})\n"
        f"target = Path({str(target)!r})\n"
        "with directory_lock(meta, filename='operation.lock', operation='run', target=target):\n"
        "    print(f'LOCKED:{os.getpid()}', flush=True)\n"
        "    time.sleep(30)\n"
    )
    env = dict(os.environ)
    repo_modules = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = repo_modules + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        assert proc.stdout is not None
        line = proc.stdout.readline().strip()
        assert line.startswith("LOCKED:")
        child_pid = int(line.split(":", 1)[1])

        with pytest.raises(RuntimeError) as exc_info:
            with directory_lock(meta, filename="operation.lock", operation="repair", target=target):
                pass
        assert str(child_pid) in str(exc_info.value)

        report = inspect_folder_locks(target, discover_processes=False)
        assert report.engaged is True
        assert report.write_locked is True
        assert any(lock.engaged and lock.process and lock.process.pid == child_pid for lock in report.locks)
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_sibling_folders_lock_independently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CROSS_PLATFORM_LOCK_DIR", str(tmp_path / "ext_locks"))
    parent = tmp_path / "Hent"
    folder_a = parent / "tmphent3"
    folder_b = parent / "hent1image"
    (folder_a / ".mangadl").mkdir(parents=True)
    (folder_b / ".mangadl").mkdir(parents=True)

    with directory_lock(folder_a / ".mangadl", filename="operation.lock", operation="run", target=folder_a):
        with directory_lock(folder_b / ".mangadl", filename="operation.lock", operation="compress -w", target=folder_b):
            rep_a = inspect_folder_locks(folder_a, discover_processes=False)
            rep_b = inspect_folder_locks(folder_b, discover_processes=False)
            assert rep_a.engaged is True
            assert rep_b.engaged is True
            assert rep_a.locks[0].operation == "run"
            assert rep_b.locks[0].operation == "compress -w"


def test_folder_read_locks_are_shared_and_leave_target_untouched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CROSS_PLATFORM_LOCK_DIR", str(tmp_path / "ext_locks"))
    target = tmp_path / "tmphent3"
    target.mkdir()

    with folder_read_lock(target, operation="compress -l -D headers") as lock_a:
        with folder_read_lock(target, operation="compress -b") as lock_b:
            assert lock_a != lock_b
            # Target directory remains completely untouched!
            assert list(target.iterdir()) == []
            report = inspect_folder_locks(target, discover_processes=False)
            assert report.engaged is True
            assert report.read_locked is True
            assert report.write_locked is False
            read_ops = {lk.operation for lk in report.locks if lk.mode == "read" and lk.engaged}
            assert read_ops == {"compress -l -D headers", "compress -b"}

    report_after = inspect_folder_locks(target, discover_processes=False)
    assert report_after.engaged is False
    assert list(external_target_lock_dir(target).glob("read-*.lock")) == []


def test_pid_reuse_detected_via_create_time() -> None:
    ident = current_process_identity()
    valid = inspect_process(ident["pid"], expected_create_time=ident["create_time"])
    assert valid.alive is True

    reused = inspect_process(ident["pid"], expected_create_time=float(ident["create_time"]) - 3600.0)
    assert reused.alive is False
    assert reused.state == "pid_reused"


def test_stale_metadata_auto_cleaned_on_status_while_stale_repair_requires_unlock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CROSS_PLATFORM_LOCK_DIR", str(tmp_path / "ext_locks"))
    target = tmp_path / "tmphent3"
    meta_dir = target / ".mangadl"
    meta_dir.mkdir(parents=True)

    # Simulate crashed process leaving offset-1 metadata in operation.lock while OS byte-0 lock is free.
    op_lock = meta_dir / "operation.lock"
    stale_payload = json.dumps({"pid": 999999, "create_time": 100.0, "operation": "crashed-op"}).encode("utf-8")
    op_lock.write_bytes(b"\x00" + stale_payload)

    # Simulate stale repair.lock and stale running row in state.sqlite3.
    repair_lock = meta_dir / "repair.lock"
    repair_lock.write_text("dead-token", encoding="utf-8")

    db_path = meta_dir / "state.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE runs (id TEXT PRIMARY KEY, started TEXT, finished TEXT, status TEXT)"
        )
        conn.execute(
            "INSERT INTO runs (id, started, finished, status) VALUES ('run-1', '2026-10-16T00:00:00Z', NULL, 'running')"
        )
        conn.commit()

    status_report = inspect_folder_locks(
        target,
        auto_clean=True,
        discover_processes=False,
    )
    assert status_report.engaged is False
    assert status_report.stale_count == 2  # repair.lock + state.sqlite3 run-1
    assert status_report.auto_cleaned_count == 1  # operation.lock offset-1 metadata
    assert op_lock.stat().st_size == 1
    assert repair_lock.exists() is True

    unlock_result = unlock_folder_locks(
        target,
        discover_processes=False,
    )
    assert len(unlock_result["unlocked"]) == 2
    assert unlock_result["refused_active"] == []
    assert repair_lock.exists() is False
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT status, finished FROM runs WHERE id = 'run-1'").fetchone()
    assert row is not None
    assert row[0] == "aborted"
    assert row[1] is not None
