"""Unit tests for TelemetryStore persistence, rollups, pruning, and budget enforcement."""

from __future__ import annotations

import datetime
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
                INSERT INTO telemetry_rollup_1m (
                    run_id, bucket_epoch, sample_count, cpu_avg, cpu_min, cpu_max,
                    rss_avg, rss_max, read_bytes_sec_avg, write_bytes_sec_avg, gpu_memory_bytes_max
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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


def test_query_process_history_seven_day_three_tier(tmp_path: Path) -> None:
    store = TelemetryStore(tmp_path)
    record = make_dummy_record("20261024-080000-f3a1b2")
    now = 1792828800.0  # 2026-10-24T08:00:00Z
    seven_days_ago = now - 604800.0
    one_day_ago = now - 86400.0

    # 1. Populate 5m rollups for [seven_days_ago, one_day_ago) - 5 buckets
    with store.connect() as conn:
        for t in range(int(seven_days_ago), int(seven_days_ago + 1500), 300):
            conn.execute(
                """
                INSERT INTO telemetry_rollup_5m (run_id, bucket_epoch, sample_count, cpu_avg, cpu_min, cpu_max, rss_avg, rss_max, read_bytes_sec_avg, write_bytes_sec_avg, gpu_memory_bytes_max)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (record.id, t, 60, 25.0, 10.0, 40.0, 50_000_000, 60_000_000, 1000.0, 500.0, None),
            )

        # 2. Populate 1m rollups for [one_day_ago, one_day_ago + 300) - 5 buckets
        for t in range(int(one_day_ago), int(one_day_ago + 300), 60):
            conn.execute(
                """
                INSERT INTO telemetry_rollup_1m (run_id, bucket_epoch, sample_count, cpu_avg, cpu_min, cpu_max, rss_avg, rss_max, read_bytes_sec_avg, write_bytes_sec_avg, gpu_memory_bytes_max)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (record.id, t, 12, 35.0, 20.0, 50.0, 70_000_000, 80_000_000, 2000.0, 1000.0, None),
            )

    # 3. Populate raw samples for [now - 120, now] - 2 minutes of raw samples
    raw_samples = []
    for s in range(0, 120, 10):
        t = (now - 120) + s
        raw_samples.append(
            ProcessStats(
                record=record,
                process_count=1,
                thread_count=4,
                cpu_percent=15.0,
                cpu_percent_normalized=1.875,
                cpu_count=8,
                rss_bytes=100_000_000,
                read_bytes_per_second=1000.0,
                write_bytes_per_second=500.0,
                sampled_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)),
                sampled_epoch=t,
            )
        )
    store.insert_process_samples(raw_samples)

    points = store.query_process_history(
        record.id,
        since=seven_days_ago,
        until=now,
        max_points=1000,
    )

    assert len(points) > 0
    p_5m = [p for p in points if p.sample_interval_seconds == 300.0]
    assert len(p_5m) == 5
    p_1m = [p for p in points if p.sample_interval_seconds == 60.0]
    assert len(p_1m) >= 5
    epochs = [p.epoch for p in points]
    assert epochs == sorted(epochs)
    assert len(epochs) == len(set(epochs))


def test_query_host_history_seven_day_three_tier(tmp_path: Path) -> None:
    store = TelemetryStore(tmp_path)
    now = 1792828800.0
    seven_days_ago = now - 604800.0
    one_day_ago = now - 86400.0

    # 1. 5m host rollups
    with store.connect() as conn:
        for t in range(int(seven_days_ago), int(seven_days_ago + 1500), 300):
            conn.execute(
                """
                INSERT INTO host_telemetry_rollup_5m (bucket_epoch, sample_count, cpu_avg, cpu_min, cpu_max, memory_used_avg, memory_used_max, net_read_sec_avg, net_write_sec_avg)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (t, 60, 20.0, 5.0, 35.0, 8_000_000_000, 9_000_000_000, 5000.0, 2500.0),
            )
        # 2. 1m host rollups
        for t in range(int(one_day_ago), int(one_day_ago + 300), 60):
            conn.execute(
                """
                INSERT INTO host_telemetry_rollup_1m (bucket_epoch, sample_count, cpu_avg, cpu_min, cpu_max, memory_used_avg, memory_used_max, net_read_sec_avg, net_write_sec_avg)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (t, 12, 30.0, 15.0, 45.0, 10_000_000_000, 11_000_000_000, 8000.0, 4000.0),
            )

    # 3. Raw host samples
    for s in range(0, 120, 10):
        t = (now - 120) + s
        store.insert_host_sample(
            HostTelemetry(
                cpu_percent=18.0,
                cpu_count=8,
                memory_used_bytes=12_000_000_000,
                memory_available_bytes=20_000_000_000,
                memory_total_bytes=32_000_000_000,
                memory_percent=37.5,
                net_read_bytes_per_second=1000.0,
                net_write_bytes_per_second=2000.0,
                gpu_devices=[],
                sampled_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)),
                sampled_epoch=t,
            )
        )

    series = store.query_host_history(
        since=seven_days_ago,
        until=now,
        max_points=1000,
    )

    assert len(series) > 0
    s_5m = [s for s in series if s.get("sample_interval_seconds") == 300.0]
    assert len(s_5m) == 5
    epochs = [s["epoch"] for s in series]
    assert epochs == sorted(epochs)
    assert len(epochs) == len(set(epochs))


def test_five_minute_rollup_sample_count_weighted_averages(tmp_path: Path) -> None:
    store = TelemetryStore(tmp_path)
    record = make_dummy_record("20261024-080000-f3a1b2")
    base_epoch = 1792828800  # multiple of 300

    # Insert two 1-minute rollups into the same 5m bucket (bucket_epoch = base_epoch)
    # Minute 0: sample_count=12, cpu_avg=100.0, rss_avg=1000, read=2000, write=1000
    # Minute 1: sample_count=4, cpu_avg=20.0, rss_avg=500, read=400, write=200
    # Expected weighted averages:
    # cpu_avg = (12*100 + 4*20) / 16 = 1280 / 16 = 80.0
    # rss_avg = (12*1000 + 4*500) / 16 = 14000 / 16 = 875
    # read_avg = (12*2000 + 4*400) / 16 = 25600 / 16 = 1600.0
    with store.connect() as conn:
        conn.execute(
            """
            INSERT INTO telemetry_rollup_1m (run_id, bucket_epoch, sample_count, cpu_avg, cpu_min, cpu_max, rss_avg, rss_max, read_bytes_sec_avg, write_bytes_sec_avg, gpu_memory_bytes_max)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (record.id, base_epoch, 12, 100.0, 80.0, 100.0, 1000, 1200, 2000.0, 1000.0, 1024),
        )
        conn.execute(
            """
            INSERT INTO telemetry_rollup_1m (run_id, bucket_epoch, sample_count, cpu_avg, cpu_min, cpu_max, rss_avg, rss_max, read_bytes_sec_avg, write_bytes_sec_avg, gpu_memory_bytes_max)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (record.id, base_epoch + 60, 4, 20.0, 10.0, 30.0, 500, 600, 400.0, 200.0, 512),
        )

    store.generate_rollups(now=float(base_epoch + 360))

    with store.connect() as conn:
        row = conn.execute(
            "SELECT * FROM telemetry_rollup_5m WHERE run_id = ? AND bucket_epoch = ?",
            (record.id, base_epoch),
        ).fetchone()
        assert row is not None
        assert row["sample_count"] == 16
        assert pytest.approx(row["cpu_avg"]) == 80.0
        assert pytest.approx(row["cpu_min"]) == 10.0
        assert pytest.approx(row["cpu_max"]) == 100.0
        assert row["rss_avg"] == 875
        assert row["rss_max"] == 1200
        assert pytest.approx(row["read_bytes_sec_avg"]) == 1600.0
        assert pytest.approx(row["write_bytes_sec_avg"]) == 800.0
        assert row["gpu_memory_bytes_max"] == 1024


def test_five_minute_rollup_strict_null_preservation(tmp_path: Path) -> None:
    store = TelemetryStore(tmp_path)
    record = make_dummy_record("20261024-080000-f3a1b2")
    base_epoch = 1792828800

    # Insert 1m rollup with all null resource metrics
    with store.connect() as conn:
        conn.execute(
            """
            INSERT INTO telemetry_rollup_1m (run_id, bucket_epoch, sample_count, cpu_avg, cpu_min, cpu_max, rss_avg, rss_max, read_bytes_sec_avg, write_bytes_sec_avg, gpu_memory_bytes_max)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (record.id, base_epoch, 5, None, None, None, None, None, None, None, None),
        )

    store.generate_rollups(now=float(base_epoch + 360))

    with store.connect() as conn:
        row = conn.execute(
            "SELECT * FROM telemetry_rollup_5m WHERE run_id = ? AND bucket_epoch = ?",
            (record.id, base_epoch),
        ).fetchone()
        assert row is not None
        assert row["sample_count"] == 5
        assert row["cpu_avg"] is None
        assert row["cpu_min"] is None
        assert row["rss_avg"] is None
        assert row["read_bytes_sec_avg"] is None


def test_downsample_points_preserves_gap_markers_and_valid_points() -> None:
    store = TelemetryStore(Path("C:/test_dummy"), auto_init=False)
    from runmux.telemetry_store import TelemetryQueryPoint

    points = []
    for i in range(20):
        t = 1000.0 + i * 10
        if i == 10:
            points.append(
                TelemetryQueryPoint(
                    timestamp=f"T{i}",
                    epoch=t,
                    sample_interval_seconds=60.0,
                    cpu_percent=None,
                    cpu_percent_normalized=None,
                    rss_bytes=None,
                    read_bytes_per_second=None,
                    write_bytes_per_second=None,
                    process_count=1,
                    thread_count=1,
                    gpu_memory_bytes=None,
                    is_gap=True,
                    gap_reason="restart marker",
                )
            )
        else:
            points.append(
                TelemetryQueryPoint(
                    timestamp=f"T{i}",
                    epoch=t,
                    sample_interval_seconds=10.0,
                    cpu_percent=20.0 + i,
                    cpu_percent_normalized=2.5,
                    rss_bytes=1000 + i * 100,
                    read_bytes_per_second=100.0,
                    write_bytes_per_second=50.0,
                    process_count=1,
                    thread_count=1,
                    gpu_memory_bytes=None,
                    is_gap=False,
                )
            )

    downsampled = store._downsample_points(points, target_count=5)
    gaps = [p for p in downsampled if p.is_gap]
    assert len(gaps) == 1
    assert gaps[0].gap_reason == "restart marker"
    valid = [p for p in downsampled if not p.is_gap]
    assert len(valid) == 5
    epochs = [p.epoch for p in downsampled]
    assert epochs == sorted(epochs)


def test_quarantine_preserves_recoverable_wal_data(tmp_path: Path) -> None:
    store = TelemetryStore(tmp_path)
    store.db_path.write_bytes(b"CORRUPT DB")
    store.wal_path.write_bytes(b"CRITICAL RECOVERABLE WAL TRANSACTIONS")
    shm_path = tmp_path / "telemetry.sqlite3-shm"
    shm_path.write_bytes(b"SHM BYTES")

    quarantine = store.quarantine_and_reset()
    assert quarantine is not None
    assert quarantine.is_file()
    assert quarantine.read_bytes() == b"CORRUPT DB"

    wal_quarantines = list(tmp_path.glob("telemetry.sqlite3-wal.corrupt.*"))
    assert len(wal_quarantines) == 1
    assert wal_quarantines[0].read_bytes() == b"CRITICAL RECOVERABLE WAL TRANSACTIONS"

    shm_quarantines = list(tmp_path.glob("telemetry.sqlite3-shm.corrupt.*"))
    assert len(shm_quarantines) == 1
    assert shm_quarantines[0].read_bytes() == b"SHM BYTES"

    assert store.check_integrity() is True


def test_schema_migration_preserves_column_order_and_values(tmp_path: Path) -> None:
    """Verify that migrating older telemetry schemas (where cpu_min was added via ALTER TABLE to the end)
    preserves correct column order and values when running rollups and history queries."""
    db_path = tmp_path / "telemetry.sqlite3"
    legacy_conn = sqlite3.connect(str(db_path))
    legacy_conn.executescript("""
        CREATE TABLE telemetry_raw (
            run_id TEXT NOT NULL,
            timestamp REAL NOT NULL,
            sampled_at TEXT NOT NULL,
            cpu_percent REAL,
            cpu_percent_normalized REAL,
            rss_bytes INTEGER,
            read_bytes_per_sec REAL,
            write_bytes_per_sec REAL,
            process_count INTEGER NOT NULL,
            thread_count INTEGER NOT NULL,
            gpu_memory_bytes INTEGER,
            PRIMARY KEY (run_id, timestamp)
        ) WITHOUT ROWID;

        CREATE TABLE telemetry_rollup_1m (
            run_id TEXT NOT NULL,
            bucket_epoch INTEGER NOT NULL,
            sample_count INTEGER NOT NULL,
            cpu_avg REAL,
            cpu_min REAL,
            cpu_max REAL,
            rss_avg INTEGER,
            rss_max INTEGER,
            read_bytes_sec_avg REAL,
            write_bytes_sec_avg REAL,
            gpu_memory_bytes_max INTEGER,
            PRIMARY KEY (run_id, bucket_epoch)
        ) WITHOUT ROWID;

        CREATE TABLE telemetry_rollup_5m (
            run_id TEXT NOT NULL,
            bucket_epoch INTEGER NOT NULL,
            sample_count INTEGER NOT NULL,
            cpu_avg REAL,
            cpu_max REAL,
            rss_avg INTEGER,
            rss_max INTEGER,
            read_bytes_sec_avg REAL,
            write_bytes_sec_avg REAL,
            gpu_memory_bytes_max INTEGER,
            PRIMARY KEY (run_id, bucket_epoch)
        ) WITHOUT ROWID;

        CREATE TABLE host_telemetry_raw (
            timestamp REAL PRIMARY KEY,
            sampled_at TEXT NOT NULL,
            cpu_percent REAL,
            memory_used_bytes INTEGER,
            memory_available_bytes INTEGER,
            net_read_bytes_sec REAL,
            net_write_bytes_sec REAL
        ) WITHOUT ROWID;

        CREATE TABLE host_telemetry_rollup_1m (
            bucket_epoch INTEGER PRIMARY KEY,
            sample_count INTEGER NOT NULL,
            cpu_avg REAL,
            cpu_min REAL,
            cpu_max REAL,
            memory_used_avg INTEGER,
            memory_used_max INTEGER,
            net_read_sec_avg REAL,
            net_write_sec_avg REAL
        ) WITHOUT ROWID;

        CREATE TABLE host_telemetry_rollup_5m (
            bucket_epoch INTEGER PRIMARY KEY,
            sample_count INTEGER NOT NULL,
            cpu_avg REAL,
            cpu_max REAL,
            memory_used_avg INTEGER,
            memory_used_max INTEGER,
            net_read_sec_avg REAL,
            net_write_sec_avg REAL
        ) WITHOUT ROWID;

        CREATE TABLE telemetry_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            timestamp REAL NOT NULL,
            event_type TEXT NOT NULL,
            reason TEXT,
            details_json TEXT
        );
    """)

    base_epoch = 1792828800
    legacy_conn.execute(
        """
        INSERT INTO telemetry_rollup_1m (
            run_id, bucket_epoch, sample_count, cpu_avg, cpu_min, cpu_max,
            rss_avg, rss_max, read_bytes_sec_avg, write_bytes_sec_avg, gpu_memory_bytes_max
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("migrated-run-1", base_epoch, 12, 45.0, 15.0, 60.0, 50_000_000, 70_000_000, 5000.0, 2500.0, 1024),
    )
    legacy_conn.execute(
        """
        INSERT INTO host_telemetry_rollup_1m (
            bucket_epoch, sample_count, cpu_avg, cpu_min, cpu_max,
            memory_used_avg, memory_used_max, net_read_sec_avg, net_write_sec_avg
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (base_epoch, 12, 30.0, 10.0, 50.0, 8_000_000_000, 9_000_000_000, 10000.0, 4000.0),
    )
    legacy_conn.commit()
    legacy_conn.close()

    store = TelemetryStore(tmp_path)

    with store.connect() as conn:
        cols_5m = [r[1] for r in conn.execute("PRAGMA table_info(telemetry_rollup_5m)").fetchall()]
        assert cols_5m[-1] == "cpu_min", f"Expected cpu_min to be appended at the end of migrated table, got {cols_5m}"

        cols_host_5m = [r[1] for r in conn.execute("PRAGMA table_info(host_telemetry_rollup_5m)").fetchall()]
        assert cols_host_5m[-1] == "cpu_min", f"Expected cpu_min to be appended at the end of migrated host table, got {cols_host_5m}"

    store.generate_rollups(now=float(base_epoch + 360))

    with store.connect() as conn:
        p_row = conn.execute("SELECT * FROM telemetry_rollup_5m WHERE run_id = ?", ("migrated-run-1",)).fetchone()
        assert p_row is not None
        assert pytest.approx(p_row["cpu_avg"]) == 45.0
        assert pytest.approx(p_row["cpu_min"]) == 15.0
        assert pytest.approx(p_row["cpu_max"]) == 60.0
        assert p_row["rss_avg"] == 50_000_000
        assert p_row["rss_max"] == 70_000_000
        assert pytest.approx(p_row["read_bytes_sec_avg"]) == 5000.0
        assert pytest.approx(p_row["write_bytes_sec_avg"]) == 2500.0
        assert p_row["gpu_memory_bytes_max"] == 1024

        h_row = conn.execute("SELECT * FROM host_telemetry_rollup_5m WHERE bucket_epoch = ?", (base_epoch,)).fetchone()
        assert h_row is not None
        assert pytest.approx(h_row["cpu_avg"]) == 30.0
        assert pytest.approx(h_row["cpu_min"]) == 10.0
        assert pytest.approx(h_row["cpu_max"]) == 50.0
        assert h_row["memory_used_avg"] == 8_000_000_000
        assert h_row["memory_used_max"] == 9_000_000_000
        assert pytest.approx(h_row["net_read_sec_avg"]) == 10000.0
        assert pytest.approx(h_row["net_write_sec_avg"]) == 4000.0


def test_partial_null_weighted_averages_unequal_buckets(tmp_path: Path) -> None:
    """Verify that five-minute rollups compute mathematically exact weighted averages
    when 1-minute buckets have unequal sizes and heterogeneous NULL observations."""
    store = TelemetryStore(tmp_path)
    record = make_dummy_record("20261024-080000-f3a1b2")
    base_epoch = 1792828800.0

    samples = []
    # Minute 0: 10 raw samples. Only 2 samples have valid CPU, RSS, and Read I/O. None have Write I/O.
    for i in range(10):
        t = base_epoch + (i * 5.0)
        has_obs = (i < 2)
        samples.append(
            ProcessStats(
                record=record,
                sampled_at=datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat(),
                sampled_epoch=t,
                cpu_percent=80.0 if has_obs else None,
                cpu_percent_normalized=40.0 if has_obs else None,
                rss_bytes=1000 if has_obs else None,
                read_bytes_per_second=200.0 if has_obs else None,
                write_bytes_per_second=None,
                process_count=1,
                thread_count=1,
            )
        )

    # Minute 1: 5 raw samples. All 5 have valid CPU, RSS, and Write I/O. None have Read I/O.
    for i in range(5):
        t = base_epoch + 60.0 + (i * 5.0)
        samples.append(
            ProcessStats(
                record=record,
                sampled_at=datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat(),
                sampled_epoch=t,
                cpu_percent=20.0,
                cpu_percent_normalized=10.0,
                rss_bytes=2000,
                read_bytes_per_second=None,
                write_bytes_per_second=400.0,
                process_count=1,
                thread_count=1,
            )
        )

    store.insert_process_samples(samples)
    store.generate_rollups(now=base_epoch + 360.0)

    with store.connect() as conn:
        r1m_0 = conn.execute(
            "SELECT * FROM telemetry_rollup_1m WHERE run_id = ? AND bucket_epoch = ?",
            (record.id, int(base_epoch)),
        ).fetchone()
        assert r1m_0["sample_count"] == 10
        assert r1m_0["cpu_count"] == 2
        assert pytest.approx(r1m_0["cpu_avg"]) == 80.0
        assert r1m_0["rss_count"] == 2
        assert r1m_0["rss_avg"] == 1000
        assert r1m_0["read_bytes_count"] == 2
        assert pytest.approx(r1m_0["read_bytes_sec_avg"]) == 200.0
        assert r1m_0["write_bytes_count"] == 0
        assert r1m_0["write_bytes_sec_avg"] is None

        r1m_1 = conn.execute(
            "SELECT * FROM telemetry_rollup_1m WHERE run_id = ? AND bucket_epoch = ?",
            (record.id, int(base_epoch + 60)),
        ).fetchone()
        assert r1m_1["sample_count"] == 5
        assert r1m_1["cpu_count"] == 5
        assert pytest.approx(r1m_1["cpu_avg"]) == 20.0
        assert r1m_1["rss_count"] == 5
        assert r1m_1["rss_avg"] == 2000
        assert r1m_1["read_bytes_count"] == 0
        assert r1m_1["read_bytes_sec_avg"] is None
        assert r1m_1["write_bytes_count"] == 5
        assert pytest.approx(r1m_1["write_bytes_sec_avg"]) == 400.0

        r5m = conn.execute(
            "SELECT * FROM telemetry_rollup_5m WHERE run_id = ? AND bucket_epoch = ?",
            (record.id, int(base_epoch)),
        ).fetchone()
        assert r5m is not None
        assert r5m["sample_count"] == 15
        # Total valid CPU observations = 2 + 5 = 7
        # Observation-weighted CPU average: (80.0 * 2 + 20.0 * 5) / 7 = 260.0 / 7 = 37.142857%
        assert pytest.approx(r5m["cpu_avg"]) == (260.0 / 7.0)
        assert pytest.approx(r5m["cpu_min"]) == 20.0
        assert pytest.approx(r5m["cpu_max"]) == 80.0

        # Total valid RSS observations = 2 + 5 = 7
        # Observation-weighted RSS average: (1000 * 2 + 2000 * 5) / 7 = 12000 / 7 = 1714
        assert r5m["rss_avg"] == round(12000 / 7)
        assert r5m["rss_max"] == 2000

        # Total valid Read I/O observations = 2 + 0 = 2
        assert pytest.approx(r5m["read_bytes_sec_avg"]) == 200.0

        # Total valid Write I/O observations = 0 + 5 = 5
        assert pytest.approx(r5m["write_bytes_sec_avg"]) == 400.0


def test_host_partial_null_weighted_averages(tmp_path: Path) -> None:
    """Verify that 5-minute host rollups correctly weight by valid observation counts
    when host samples contain mixed nulls and unequal bucket counts."""
    store = TelemetryStore(tmp_path)
    base_epoch = 1792828800.0

    # Minute 0: 6 raw samples. 1 sample has valid CPU (50%), Memory (8 GB), Net Read (1000). None have Net Write.
    for i in range(6):
        t = base_epoch + (i * 10.0)
        has_obs = (i == 0)
        store.insert_host_sample(
            HostTelemetry(
                sampled_at=datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat(),
                sampled_epoch=t,
                cpu_percent=50.0 if has_obs else None,
                cpu_count=8,
                memory_used_bytes=8_000_000_000 if has_obs else None,
                memory_available_bytes=8_000_000_000 if has_obs else None,
                memory_total_bytes=16_000_000_000,
                memory_percent=50.0,
                net_read_bytes_per_second=1000.0 if has_obs else None,
                net_write_bytes_per_second=None,
                gpu_devices=[],
            )
        )

    # Minute 1: 3 raw samples. All 3 have valid CPU (10%), Memory (16 GB), Net Write (2000). None have Net Read.
    for i in range(3):
        t = base_epoch + 60.0 + (i * 10.0)
        store.insert_host_sample(
            HostTelemetry(
                sampled_at=datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat(),
                sampled_epoch=t,
                cpu_percent=10.0,
                cpu_count=8,
                memory_used_bytes=16_000_000_000,
                memory_available_bytes=16_000_000_000,
                memory_total_bytes=32_000_000_000,
                memory_percent=50.0,
                net_read_bytes_per_second=None,
                net_write_bytes_per_second=2000.0,
                gpu_devices=[],
            )
        )

    store.generate_rollups(now=base_epoch + 360.0)

    with store.connect() as conn:
        h5m = conn.execute(
            "SELECT * FROM host_telemetry_rollup_5m WHERE bucket_epoch = ?",
            (int(base_epoch),),
        ).fetchone()
        assert h5m is not None
        assert h5m["sample_count"] == 9
        # Valid CPU observations = 1 (at 50%) + 3 (at 10%) = 4
        # Weighted average: (50.0 * 1 + 10.0 * 3) / 4 = 80.0 / 4 = 20.0%
        assert pytest.approx(h5m["cpu_avg"]) == 20.0
        assert pytest.approx(h5m["cpu_min"]) == 10.0
        assert pytest.approx(h5m["cpu_max"]) == 50.0

        # Memory: (8GB * 1 + 16GB * 3) / 4 = 56GB / 4 = 14 GB
        assert h5m["memory_used_avg"] == 14_000_000_000
        assert h5m["memory_used_max"] == 16_000_000_000

        # Net read: 1 observation at 1000.0
        assert pytest.approx(h5m["net_read_sec_avg"]) == 1000.0
        # Net write: 3 observations at 2000.0
        assert pytest.approx(h5m["net_write_sec_avg"]) == 2000.0


def test_quarantine_resilience_to_open_reader_and_locked_wal(tmp_path: Path) -> None:
    """Verify that quarantine_and_reset degrades safely when an open reader holds a file lock,
    preventing worker crashes, and then completes recovery once the lock is released."""
    store = TelemetryStore(tmp_path)
    store.db_path.write_bytes(b"CORRUPTED INVALID SQLITE FILE HEADER")

    # Open reader handle to simulate an active concurrent query holding the file on Windows
    reader_handle = open(store.db_path, "rb")
    try:
        # With active reader handle, rename fails with PermissionError / OSError.
        # quarantine_and_reset() must catch this, defer quarantine, and return None without raising.
        quarantine_result = store.quarantine_and_reset()
        assert quarantine_result is None
        # Verify the corrupt file was not deleted or partially damaged
        assert store.db_path.exists()
        assert store.db_path.read_bytes() == b"CORRUPTED INVALID SQLITE FILE HEADER"
    finally:
        reader_handle.close()

    # Now that reader handle is closed, quarantine_and_reset must succeed
    quarantine_result = store.quarantine_and_reset()
    assert quarantine_result is not None
    assert quarantine_result.is_file()
    assert quarantine_result.read_bytes() == b"CORRUPTED INVALID SQLITE FILE HEADER"
    # Fresh database initialized and integrity passes
    assert store.check_integrity() is True
