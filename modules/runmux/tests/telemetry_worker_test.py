"""Unit tests for TelemetryHistoryWorker lifecycle, collection, and server restart survivability."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import pytest
from runmux.runner import create_managed_run
from runmux.stats import TelemetrySampler
from runmux.store import RunStore
from runmux.telemetry_store import TelemetryStore
from runmux.telemetry_worker import TelemetryHistoryWorker


@pytest.mark.asyncio
async def test_worker_startup_collection_and_clean_shutdown(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    # Create an active dummy run
    record = store.create_run(
        run_id="20261024-080000-f3a1b2",
        name="worker_test",
        status="running",
        program=sys.executable,
        argv_json="[]",
        cwd=str(tmp_path),
        env_overrides_json="{}",
        auth_token="dummy_token",
        log_path=str(tmp_path / "log.ansi"),
        command_line="python",
    )
    import datetime
    import psutil
    proc = psutil.Process(os.getpid())
    started_iso = datetime.datetime.fromtimestamp(proc.create_time(), datetime.timezone.utc).isoformat()
    store.update_run(record.id, pid=os.getpid(), started_at=started_iso)

    worker = TelemetryHistoryWorker(
        tmp_path,
        cadence_seconds=0.1,
        maintenance_cadence_seconds=0.5,
    )

    t0 = time.monotonic()
    await worker.start()
    assert worker._running is True

    # Allow worker to run 3 ticks (~300ms)
    await asyncio.sleep(0.35)

    stop_t0 = time.monotonic()
    await worker.stop(timeout=1.0)
    stop_elapsed = time.monotonic() - stop_t0
    # Stop must complete cleanly within 500ms
    assert stop_elapsed < 0.5
    assert worker._running is False

    # Verify telemetry was written to telemetry.sqlite3
    telemetry_store = TelemetryStore(tmp_path)
    with telemetry_store.connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM telemetry_raw WHERE run_id = ?", (record.id,)).fetchone()[0]
        assert count >= 1

        host_count = conn.execute("SELECT COUNT(*) FROM host_telemetry_raw").fetchone()[0]
        assert host_count >= 1


@pytest.mark.asyncio
async def test_server_restart_persistence_survivability(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    record = store.create_run(
        run_id="20261024-090000-112233",
        name="survivability_test",
        status="running",
        program=sys.executable,
        argv_json="[]",
        cwd=str(tmp_path),
        env_overrides_json="{}",
        auth_token="dummy_token",
        log_path=str(tmp_path / "log.ansi"),
        command_line="python",
    )
    import datetime
    import psutil
    proc = psutil.Process(os.getpid())
    started_iso = datetime.datetime.fromtimestamp(proc.create_time(), datetime.timezone.utc).isoformat()
    store.update_run(record.id, pid=os.getpid(), started_at=started_iso)

    # Instance 1: collect initial data and stop (simulating web server stopping)
    worker1 = TelemetryHistoryWorker(tmp_path, cadence_seconds=0.1)
    await worker1.start()
    await asyncio.sleep(0.25)
    await worker1.stop()

    # Instance 2: start fresh worker against same state directory (simulating web server restarting)
    worker2 = TelemetryHistoryWorker(tmp_path, cadence_seconds=0.1)
    await worker2.start()
    await asyncio.sleep(0.25)
    await worker2.stop()

    # Query complete raw history from telemetry_store
    telemetry_store = TelemetryStore(tmp_path)
    with telemetry_store.session() as conn:
        raw_count = conn.execute("SELECT COUNT(*) FROM telemetry_raw WHERE run_id = ?", (record.id,)).fetchone()[0]
        assert raw_count >= 2

    points = telemetry_store.query_process_history(
        record.id,
        since=time.time() - 300,
        until=time.time() + 10,
    )
    assert len(points) >= 1
    assert all(p.cpu_percent is not None or p.rss_bytes is not None for p in points)


@pytest.mark.asyncio
async def test_worker_lifecycle_detects_and_recovers_corrupt_database(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    record = store.create_run(
        run_id="20261024-093000-deadbeef",
        name="corruption_recovery_test",
        status="running",
        program=sys.executable,
        argv_json="[]",
        cwd=str(tmp_path),
        env_overrides_json="{}",
        auth_token="dummy_token",
        log_path=str(tmp_path / "log.ansi"),
        command_line="python",
    )
    import datetime
    import psutil
    proc = psutil.Process(os.getpid())
    started_iso = datetime.datetime.fromtimestamp(proc.create_time(), datetime.timezone.utc).isoformat()
    store.update_run(record.id, pid=os.getpid(), started_at=started_iso)

    # Initialize a corrupted telemetry.sqlite3 and WAL file
    db_file = tmp_path / "telemetry.sqlite3"
    db_file.write_bytes(b"CORRUPTED INVALID SQLITE FILE HEADER")
    wal_file = tmp_path / "telemetry.sqlite3-wal"
    wal_file.write_bytes(b"RECOVERABLE WAL DATA")

    worker = TelemetryHistoryWorker(tmp_path, cadence_seconds=0.1)
    await worker.start()

    # Let worker execute loop ticks
    await asyncio.sleep(0.3)
    await worker.stop()

    # Verify that:
    # 1. Recoverable WAL was preserved in quarantine
    wal_quarantined = list(tmp_path.glob("telemetry.sqlite3-wal.corrupt.*"))
    assert len(wal_quarantined) == 1
    assert wal_quarantined[0].read_bytes() == b"RECOVERABLE WAL DATA"

    # 2. Fresh telemetry.sqlite3 was initialized and is healthy
    fresh_store = TelemetryStore(tmp_path)
    assert fresh_store.check_integrity() is True

    # 3. Worker continued running and successfully inserted samples
    with fresh_store.connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM telemetry_raw WHERE run_id = ?", (record.id,)).fetchone()[0]
        assert count >= 1


@pytest.mark.asyncio
async def test_worker_graceful_degradation_when_database_locked(tmp_path: Path) -> None:
    """Verify that the worker's integrity check handles an active lock gracefully without crashing,
    and recovers on the subsequent check once the lock is released."""
    store = RunStore(tmp_path)
    record = store.create_run(
        run_id="20261024-080000-f3a1b2",
        name="worker_lock_test",
        status="running",
        program=sys.executable,
        argv_json="[]",
        cwd=str(tmp_path),
        env_overrides_json="{}",
        auth_token="dummy_token",
        log_path=str(tmp_path / "log.ansi"),
        command_line="python",
    )
    import datetime
    import psutil
    proc = psutil.Process(os.getpid())
    started_iso = datetime.datetime.fromtimestamp(proc.create_time(), datetime.timezone.utc).isoformat()
    store.update_run(record.id, pid=os.getpid(), started_at=started_iso)

    # Initialize a corrupted telemetry.sqlite3
    db_file = tmp_path / "telemetry.sqlite3"
    db_file.write_bytes(b"CORRUPTED INVALID SQLITE FILE HEADER")

    # Hold an open reader handle on the corrupt database
    reader_handle = open(db_file, "rb")
    worker = TelemetryHistoryWorker(tmp_path, cadence_seconds=0.1)

    try:
        # Worker integrity check should log a warning and defer quarantine without raising
        worker._verify_store_integrity_sync()
        assert db_file.exists()
        assert db_file.read_bytes() == b"CORRUPTED INVALID SQLITE FILE HEADER"
    finally:
        reader_handle.close()

    # Lock is now released; subsequent check should successfully quarantine and re-initialize
    worker._verify_store_integrity_sync()
    corrupt_files = list(tmp_path.glob("telemetry.sqlite3.corrupt.*"))
    assert len(corrupt_files) == 1
    assert corrupt_files[0].read_bytes() == b"CORRUPTED INVALID SQLITE FILE HEADER"

    fresh_store = TelemetryStore(tmp_path)
    assert fresh_store.check_integrity() is True
