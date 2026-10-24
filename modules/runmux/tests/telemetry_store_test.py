"""Unit tests for TelemetryStore persistence, rollups, pruning, and budget enforcement."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest
from runmux.models import RunRecord
from runmux.stats import HostTelemetry, ProcessStats
from runmux.telemetry_store import TelemetryStore


def make_dummy_record(run_id: str = "20261024-080000-f3a1b2", pid: int = 12345) -> RunRecord:
    return RunRecord(
        id=run_id,
        numeric_id=1,
        name="test_worker",
        status="running",
        created_at="2026-10-24T08:00:00Z",
        updated_at="2026-10-24T08:00:00Z",
        started_at="2026-10-24T08:00:01Z",
        ended_at=None,
        exit_code=None,
        pid=pid,
        supervisor_pid=12344,
        program="python",
        argv_json='["python", "app.py"]',
        cwd="C:/test",
        env_overrides_json="{}",
        port=8080,
        auth_token="dummy_token",
        log_path="C:/test/log.txt",
        command_line="python app.py",
        restart_of=None,
        duplicate_of=None,
        rows=24,
        columns=80,
    )


def test_telemetry_store_initialization(tmp_path: Path) -> None:
    store = TelemetryStore(tmp_path)
    assert store.db_path.is_file()

    with store.connect() as conn:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert journal_mode.lower() == "wal"

        auto_vacuum = conn.execute("PRAGMA auto_vacuum").fetchone()[0]
        assert auto_vacuum == 2 # 2 = INCREMENTAL


def test_telemetry_store_insert_and_rollup(tmp_path: Path) -> None:
    store = TelemetryStore(tmp_path)
    record = make_dummy_record("20261024-080000-f3a1b2")

    base_time = 1792828800.0 # 2026-10-24T08:00:00Z

    # Insert 3 samples within minute 0 (t=0s, 10s, 20s)
    samples = [
        ProcessStats(
            record=record,
            process_count=2,
            thread_count=10,
            cpu_percent=10.0,
            cpu_percent_normalized=1.25,
            cpu_count=8,
            rss_bytes=100_000_000,
            read_bytes_per_second=10_000.0,
            write_bytes_per_second=5_000.0,
            gpu_memory_bytes=1024,
            sampled_at="2026-10-24T08:00:00Z",
        ),
        ProcessStats(
            record=record,
            process_count=2,
            thread_count=10,
            cpu_percent=20.0,
            cpu_percent_normalized=2.50,
            cpu_count=8,
            rss_bytes=200_000_000,
            read_bytes_per_second=20_000.0,
            write_bytes_per_second=10_000.0,
            gpu_memory_bytes=2048,
            sampled_at="2026-10-24T08:00:10Z",
        ),
        ProcessStats(
            record=record,
            process_count=2,
            thread_count=10,
            cpu_percent=30.0,
            cpu_percent_normalized=3.75,
            cpu_count=8,
            rss_bytes=300_000_000,
            read_bytes_per_second=30_000.0,
            write_bytes_per_second=15_000.0,
            gpu_memory_bytes=4096,
            sampled_at="2026-10-24T08:00:20Z",
        ),
    ]

    store.insert_process_samples(samples)

    with store.connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM telemetry_raw WHERE run_id = ?", (record.id,)).fetchone()[0]
        assert count == 3

    # Generate rollups at minute 2 (so minute 0 is completed)
    store.generate_rollups(now=base_time + 120.0)

    with store.connect() as conn:
        row = conn.execute("SELECT * FROM telemetry_rollup_1m WHERE run_id = ?", (record.id,)).fetchone()
        assert row is not None
        assert row["sample_count"] == 3
        assert pytest.approx(row["cpu_avg"]) == 20.0
        assert pytest.approx(row["cpu_min"]) == 10.0
        assert pytest.approx(row["cpu_max"]) == 30.0
        assert row["rss_avg"] == 200_000_000
        assert row["rss_max"] == 300_000_000
        assert pytest.approx(row["read_bytes_sec_avg"]) == 20_000.0
        assert pytest.approx(row["write_bytes_sec_avg"]) == 10_000.0
        assert row["gpu_memory_bytes_max"] == 4096


def test_query_process_history_continuous_boundary(tmp_path: Path) -> None:
    store = TelemetryStore(tmp_path, raw_retention_seconds=3600.0)
    record = make_dummy_record("20261024-080000-f3a1b2")
    base_time = 1792828800.0

    # Simulate older samples that were rolled up into telemetry_rollup_1m
    with store.connect() as conn:
        for m in range(10): # 10 minutes of rollups
            conn.execute(
                """
                INSERT INTO telemetry_rollup_1m VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (record.id, int(base_time + m * 60), 12, 15.0, 5.0, 25.0, 100_000_000, 150_000_000, 1000.0, 500.0, None),
            )

    # Simulate recent raw samples in telemetry_raw (from minute 10 to minute 12)
    raw_samples = []
    for s in range(600, 720, 10):
        t = base_time + s
        raw_samples.append(
            ProcessStats(
                record=record,
                process_count=1,
                thread_count=4,
                cpu_percent=18.0,
                cpu_percent_normalized=2.25,
                cpu_count=8,
                rss_bytes=110_000_000,
                read_bytes_per_second=2000.0,
                write_bytes_per_second=1000.0,
                sampled_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)),
            )
        )
    store.insert_process_samples(raw_samples)

    # Query spanning across the boundary (from minute 0 to minute 12)
    points = store.query_process_history(
        record.id,
        since=base_time,
        until=base_time + 720,
        max_points=300,
    )

    # Verify continuity: should have 10 rollup buckets + 2 live-aggregated raw buckets = 12 points total
    assert len(points) == 12
    epochs = [p.epoch for p in points]
    assert epochs == sorted(epochs)
    assert all(not p.is_gap for p in points)


def test_gap_detection_on_missed_interval(tmp_path: Path) -> None:
    store = TelemetryStore(tmp_path)
    record = make_dummy_record("20261024-080000-f3a1b2")
    base_time = 1792828800.0

    samples = [
        ProcessStats(
            record=record,
            process_count=1,
            thread_count=4,
            cpu_percent=10.0,
            cpu_percent_normalized=1.25,
            cpu_count=8,
            rss_bytes=100_000_000,
            read_bytes_per_second=1000.0,
            write_bytes_per_second=500.0,
            sampled_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(base_time)),
        ),
        # Gap of 60 seconds (nominal interval is 5s)
        ProcessStats(
            record=record,
            process_count=1,
            thread_count=4,
            cpu_percent=15.0,
            cpu_percent_normalized=1.87,
            cpu_count=8,
            rss_bytes=105_000_000,
            read_bytes_per_second=1000.0,
            write_bytes_per_second=500.0,
            sampled_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(base_time + 60.0)),
        ),
    ]
    store.insert_process_samples(samples)

    points = store.query_process_history(record.id, since=base_time, until=base_time + 65.0)
    # Must have point 1, gap marker, point 2
    assert len(points) == 3
    assert points[1].is_gap is True
    assert points[1].cpu_percent is None
    assert points[1].rss_bytes is None


def test_retention_pruning(tmp_path: Path) -> None:
    store = TelemetryStore(
        tmp_path,
        raw_retention_seconds=60.0,
        rollup_1m_retention_seconds=120.0,
        rollup_5m_retention_seconds=300.0,
    )
    record = make_dummy_record("20261024-080000-f3a1b2")
    t0 = 1792828800.0

    # Insert old sample
    old_sample = ProcessStats(
        record=record,
        process_count=1,
        thread_count=4,
        cpu_percent=10.0,
        cpu_percent_normalized=1.25,
        cpu_count=8,
        rss_bytes=100_000_000,
        read_bytes_per_second=0.0,
        write_bytes_per_second=0.0,
        sampled_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0)),
    )
    # Insert new sample
    new_sample = ProcessStats(
        record=record,
        process_count=1,
        thread_count=4,
        cpu_percent=15.0,
        cpu_percent_normalized=1.87,
        cpu_count=8,
        rss_bytes=100_000_000,
        read_bytes_per_second=0.0,
        write_bytes_per_second=0.0,
        sampled_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0 + 100.0)),
    )
    store.insert_process_samples([old_sample, new_sample])

    # Prune at t0 + 100s (cutoff is t0 + 40s)
    store.prune_retention(now=t0 + 100.0)

    with store.connect() as conn:
        rows = conn.execute("SELECT timestamp FROM telemetry_raw").fetchall()
        assert len(rows) == 1
        assert pytest.approx(rows[0][0]) == (t0 + 100.0)


def test_storage_budget_enforcement(tmp_path: Path) -> None:
    # Set a tiny budget of 100 KB
    store = TelemetryStore(tmp_path, max_budget_bytes=100 * 1024)
    record = make_dummy_record("20261024-080000-f3a1b2")

    # Insert 1,500 rows to exceed 100 KB
    samples = []
    base_time = 1792828800.0
    for i in range(1500):
        samples.append(
            ProcessStats(
                record=record,
                process_count=1,
                thread_count=4,
                cpu_percent=10.0 + (i % 10),
                cpu_percent_normalized=1.25,
                cpu_count=8,
                rss_bytes=100_000_000,
                read_bytes_per_second=1000.0,
                write_bytes_per_second=500.0,
                sampled_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(base_time + i * 5)),
            )
        )
    store.insert_process_samples(samples)

    # Enforce budget
    assert store.total_disk_bytes() > 50 * 1024
    success = store.enforce_storage_budget(max_bytes=100 * 1024)
    assert success is True


def test_database_corruption_quarantine_and_recovery(tmp_path: Path) -> None:
    store = TelemetryStore(tmp_path)
    assert store.check_integrity() is True

    # Corrupt the database file by overwriting header
    with open(store.db_path, "wb") as f:
        f.write(b"CORRUPTED INVALID SQLITE HEADER DATA")

    assert store.check_integrity() is False

    quarantined = store.quarantine_and_reset()
    assert quarantined is not None
    assert quarantined.is_file()
    assert "corrupt" in quarantined.name
    # New store must be healthy
    assert store.check_integrity() is True
