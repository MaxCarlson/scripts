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
