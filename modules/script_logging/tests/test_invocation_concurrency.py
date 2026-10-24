from __future__ import annotations

import concurrent.futures
from pathlib import Path
import sqlite3
import pytest
from script_logging.invocation_store import InvocationStore


def _run_worker(db_path: Path, worker_id: int, runs: int) -> None:
    store = InvocationStore(db_path)
    for i in range(runs):
        inv_id = store.start_invocation(
            program_id=f"module:worker_{worker_id % 3}",
            invoked_name=f"worker_{worker_id % 3}",
            argv=(f"worker_{worker_id % 3}", "--run", str(i)),
            cwd=Path("/tmp"),
            origin="test",
        )
        store.finish_invocation(inv_id, exit_code=0, status="exited")


def test_multiprocess_multithread_concurrency(tmp_path):
    db_path = tmp_path / "concurrent.sqlite3"
    # Seed db
    InvocationStore(db_path)

    workers = 8
    runs_per_worker = 20
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_run_worker, db_path, wid, runs_per_worker) for wid in range(workers)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    store = InvocationStore(db_path)
    with store._connect() as conn:
        total_invocations = conn.execute("SELECT COUNT(*) FROM invocations").fetchone()[0]
        assert total_invocations == workers * runs_per_worker


def test_fail_open_on_readonly_storage(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "broken.sqlite3"
    store = InvocationStore(db_path)

    # Monkeypatch _connect to simulate OperationalError
    def _failing_connect():
        raise sqlite3.OperationalError("disk I/O error or locked")

    monkeypatch.setattr(store, "_connect", _failing_connect)
    monkeypatch.setenv("SCRIPT_LOGGING_DEBUG", "1")

    # Must fail open (return fallback id or None, not raise exception)
    inv_id = store.start_invocation(
        program_id="module:test",
        invoked_name="test",
        argv=("test",),
        cwd=Path("/tmp"),
        origin="launcher",
        fail_open=True,
    )
    assert inv_id.startswith("fallback-")

    # Finish must also not raise
    store.finish_invocation(inv_id, exit_code=0, status="exited", fail_open=True)

    captured = capsys.readouterr()
    assert "Database error" in captured.err


def test_fail_closed_when_fail_open_is_false(tmp_path, monkeypatch):
    db_path = tmp_path / "broken.sqlite3"
    store = InvocationStore(db_path)

    def _failing_connect():
        raise sqlite3.OperationalError("disk I/O error or locked")

    monkeypatch.setattr(store, "_connect", _failing_connect)

    with pytest.raises(sqlite3.OperationalError):
        store.start_invocation(
            program_id="module:test",
            invoked_name="test",
            argv=("test",),
            cwd=Path("/tmp"),
            origin="launcher",
            fail_open=False,
        )
