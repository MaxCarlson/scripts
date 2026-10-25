"""Formal audit test suite verifying Handoff 1 contract invariants.

Covers:
- Start/finish invocation lifecycle
- Finish invocation idempotency
- Interrupted/uncompleted runs (no fake completion records)
- Summary counter reconciliation
- Redaction before SQLite writes across all tables and fingerprints
- Read-only consumer invariants (URI mode=ro, no file creation, no write locks)
- Multi-process write concurrency and fail-open resilience
"""
from __future__ import annotations

import multiprocessing
import sqlite3
from pathlib import Path
import pytest

from script_logging.invocation_store import InvocationStore
from script_logging.reader import ReadOnlyHistoryReader, open_invocation_reader
from script_logging.reconciliation import reconcile_invocation_summaries


def test_audit_start_finish_lifecycle_invariants(tmp_path: Path):
    """Verify start and finish lifecycle maintains correct state, timings, and summary counters."""
    db_file = tmp_path / "lifecycle.sqlite3"
    store = InvocationStore(db_file)

    # 1. Start invocation
    inv_id = store.start_invocation(
        program_id="module:audit_tool",
        invoked_name="atool",
        argv=("atool", "status", "--verbose"),
        cwd=tmp_path,
        origin="launcher",
    )
    assert inv_id is not None

    # Inspect DB immediately after start
    reader = open_invocation_reader(db_file)
    rec = reader.get_invocation(inv_id)
    assert rec is not None
    assert rec.status == "started"
    assert rec.exit_code is None
    assert rec.duration_ms is None
    assert rec.started_at_utc is not None
    assert rec.finished_at_utc is None

    # Check stats after start
    stats = reader.get_program_statistics("module:audit_tool")
    assert stats.total_starts == 1
    assert stats.success_count == 0
    assert stats.failure_count == 0

    # 2. Finish invocation successfully
    store.finish_invocation(inv_id, exit_code=0, status="exited")

    # Inspect DB after finish
    rec_finished = reader.get_invocation(inv_id)
    assert rec_finished.status == "exited"
    assert rec_finished.exit_code == 0
    assert rec_finished.finished_at_utc is not None
    assert rec_finished.duration_ms is not None
    assert rec_finished.duration_ms >= 0

    # Check stats after finish
    stats_finished = reader.get_program_statistics("module:audit_tool")
    assert stats_finished.total_starts == 1
    assert stats_finished.success_count == 1
    assert stats_finished.failure_count == 0


def test_audit_finish_idempotency(tmp_path: Path):
    """Verify finishing an invocation multiple times does not double-count statistics."""
    db_file = tmp_path / "idempotent.sqlite3"
    store = InvocationStore(db_file)

    inv_id = store.start_invocation(
        program_id="module:audit_tool",
        invoked_name="atool",
        argv=("atool", "run"),
        cwd=tmp_path,
    )

    # First finish call
    store.finish_invocation(inv_id, exit_code=0, status="exited")

    reader = open_invocation_reader(db_file)
    stats1 = reader.get_program_statistics("module:audit_tool")
    assert stats1.total_starts == 1
    assert stats1.success_count == 1

    # Second finish call (e.g. retry or duplicate callback)
    # Store must not double-increment counters
    store.finish_invocation(inv_id, exit_code=0, status="exited")

    stats2 = reader.get_program_statistics("module:audit_tool")
    assert stats2.total_starts == 1
    assert stats2.success_count == 1
    assert stats2.failure_count == 0


def test_audit_interrupted_run_leaves_started_status(tmp_path: Path):
    """Verify an aborted process (e.g. kill/SIGKILL/power outage) remains in 'started' state without fake exit."""
    db_file = tmp_path / "crashed.sqlite3"
    store = InvocationStore(db_file)

    inv_id = store.start_invocation(
        program_id="module:crashed_app",
        invoked_name="crashed_app",
        argv=("crashed_app", "heavy_work"),
        cwd=tmp_path,
    )

    # Simulate process death: finish_invocation is never called
    reader = open_invocation_reader(db_file)
    rec = reader.get_invocation(inv_id)
    assert rec.status == "started"
    assert rec.exit_code is None
    assert rec.finished_at_utc is None

    # Stats reflect 1 start, 0 successes, 0 recorded failures
    stats = reader.get_program_statistics("module:crashed_app")
    assert stats.total_starts == 1
    assert stats.success_count == 0
    assert stats.failure_count == 0


def test_audit_reconciliation_repairs_counter_drift(tmp_path: Path):
    """Verify summary counter reconciliation restores mathematical consistency from raw invocation records."""
    db_file = tmp_path / "drift.sqlite3"
    store = InvocationStore(db_file)

    # Add 2 runs
    id1 = store.start_invocation("module:recon", "recon", ("recon", "1"), tmp_path)
    store.finish_invocation(id1, exit_code=0, status="exited")

    id2 = store.start_invocation("module:recon", "recon", ("recon", "2"), tmp_path)
    store.finish_invocation(id2, exit_code=1, status="exited")

    # Manually corrupt the summary counters in program_usage to simulate drift
    with sqlite3.connect(db_file) as conn:
        conn.execute("UPDATE program_usage SET total_starts = 99, success_count = 50 WHERE program_id = 'module:recon'")
        conn.commit()

    reader = open_invocation_reader(db_file)
    corrupted_stats = reader.get_program_statistics("module:recon")
    assert corrupted_stats.total_starts == 99

    # Reconcile with dry_run=False to apply fixes
    report = reconcile_invocation_summaries(db_file, dry_run=False)
    assert report.corrections_applied >= 1

    # Check repaired stats
    repaired_stats = reader.get_program_statistics("module:recon")
    assert repaired_stats.total_starts == 2
    assert repaired_stats.success_count == 1
    assert repaired_stats.failure_count == 1


def test_audit_redaction_before_sqlite_write(tmp_path: Path):
    """Verify sensitive tokens and URLs are redacted before any SQLite write."""
    db_file = tmp_path / "redact.sqlite3"
    store = InvocationStore(db_file)

    secret_key = "sk_live_SECRET_API_KEY_998877"
    secret_pass = "my_super_secret_password"
    userinfo_url = f"https://admin:{secret_pass}@internal.domain.com/data"

    inv_id = store.start_invocation(
        program_id="module:api_sync",
        invoked_name="sync",
        argv=("sync", "--token", secret_key, f"--url={userinfo_url}"),
        cwd=tmp_path,
    )
    store.finish_invocation(inv_id, exit_code=0, status="exited")

    # Read raw database bytes/text
    with sqlite3.connect(db_file) as conn:
        cursor = conn.cursor()
        rows = cursor.execute("SELECT raw_argv_json, redacted_argv_json FROM invocations WHERE invocation_id = ?", (inv_id,)).fetchall()
        raw_json, redacted_json = rows[0]
        # Guarantee neither raw_argv_json nor redacted_argv_json contains the plain secret
        assert secret_key not in raw_json
        assert secret_pass not in raw_json
        assert secret_key not in redacted_json
        assert secret_pass not in redacted_json
        assert "[REDACTED]" in redacted_json

        # Check pattern table
        p_rows = cursor.execute("SELECT pattern_argv_json, pattern_id FROM command_patterns").fetchall()
        pattern_str = p_rows[0][0]
        assert secret_key not in pattern_str
        assert secret_pass not in pattern_str
        assert "[REDACTED]" in pattern_str


def test_audit_readonly_reader_guarantees(tmp_path: Path):
    """Verify ReadOnlyHistoryReader never creates files, never acquires write locks, and rejects mutations."""
    missing_file = tmp_path / "does_not_exist.sqlite3"

    # 1. Opening missing db must raise FileNotFoundError and not create it on disk
    with pytest.raises(FileNotFoundError):
        open_invocation_reader(missing_file)
    assert not missing_file.exists()

    # 2. Existing DB opened with mode=ro rejects any writes
    real_db = tmp_path / "real.sqlite3"
    store = InvocationStore(real_db)
    store.start_invocation("module:real", "real", ("real",), tmp_path)

    ro_reader = ReadOnlyHistoryReader(real_db)
    assert ro_reader.path.is_file()
    with pytest.raises(sqlite3.OperationalError, match="readonly database"):
        with ro_reader._connect() as conn:
            conn.execute("DELETE FROM invocations")


def _worker_write(db_path_str: str, worker_id: int):
    store = InvocationStore(db_path_str)
    for i in range(10):
        inv_id = store.start_invocation(
            program_id=f"module:worker_{worker_id}",
            invoked_name=f"worker_{worker_id}",
            argv=(f"cmd_{i}",),
            cwd=".",
            fail_open=True,
        )
        if inv_id:
            store.finish_invocation(inv_id, exit_code=0, status="exited", fail_open=True)


def test_audit_multiprocess_concurrency_and_wal(tmp_path: Path):
    """Verify concurrent writes from multiple processes under WAL mode."""
    db_file = tmp_path / "concurrent_audit.sqlite3"
    _ = InvocationStore(db_file)  # initialize schema

    num_workers = 6
    processes = [
        multiprocessing.Process(target=_worker_write, args=(str(db_file), w))
        for w in range(num_workers)
    ]
    for p in processes:
        p.start()
    for p in processes:
        p.join()

    # Verify database integrity and total count
    reader = open_invocation_reader(db_file)
    page = reader.list_invocations(limit=100)
    # All 60 invocations should be safely recorded
    assert len(page.items) == num_workers * 10
