"""Synthetic benchmark script for Runmux Phase 5C historical telemetry research.

Tests psutil inspection latency, memory footprint of ring buffers,
SQLite insert/query performance, and downsampling throughput on native Windows.
Does not touch live Runmux state or user configuration.
"""

from __future__ import annotations

import gc
import os
import sqlite3
import sys
import tempfile
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil


@dataclass(slots=True)
class TelemetryPointSlots:
    timestamp: float
    cpu_percent: float | None
    rss_bytes: int | None
    read_rate: float | None
    write_rate: float | None
    threads: int
    procs: int
    gpu_mem: int | None


def benchmark_psutil_sampling() -> dict[str, Any]:
    current_pid = os.getpid()
    proc = psutil.Process(current_pid)

    # 1. Warm up
    _ = proc.cpu_times()
    _ = proc.memory_info()

    iterations = 100

    # Test individual metrics
    t0 = time.perf_counter()
    for _ in range(iterations):
        _ = proc.cpu_times()
    cpu_time_ms = (time.perf_counter() - t0) * 1000 / iterations

    t0 = time.perf_counter()
    for _ in range(iterations):
        _ = proc.memory_info().rss
    rss_time_ms = (time.perf_counter() - t0) * 1000 / iterations

    t0 = time.perf_counter()
    for _ in range(iterations):
        _ = proc.num_threads()
    threads_time_ms = (time.perf_counter() - t0) * 1000 / iterations

    t0 = time.perf_counter()
    for _ in range(iterations):
        _ = proc.io_counters()
    io_time_ms = (time.perf_counter() - t0) * 1000 / iterations

    # Tree traversal (children)
    tree_iters = 30
    t0 = time.perf_counter()
    for _ in range(tree_iters):
        _ = proc.children(recursive=True)
    tree_time_ms = (time.perf_counter() - t0) * 1000 / tree_iters

    # Total combined sample for 1 process
    t0 = time.perf_counter()
    for _ in range(iterations):
        _ = proc.cpu_times()
        _ = proc.memory_info().rss
        _ = proc.num_threads()
        _ = proc.io_counters()
    combined_sample_ms = (time.perf_counter() - t0) * 1000 / iterations

    return {
        "cpu_time_ms": cpu_time_ms,
        "rss_time_ms": rss_time_ms,
        "threads_time_ms": threads_time_ms,
        "io_time_ms": io_time_ms,
        "tree_time_ms": tree_time_ms,
        "combined_single_proc_ms": combined_sample_ms,
        "combined_with_tree_ms": combined_sample_ms + tree_time_ms,
    }


def benchmark_memory_buffers(sample_counts: list[int]) -> dict[str, Any]:
    results = {}
    for count in sample_counts:
        gc.collect()
        tracemalloc.start()
        # 1. dataclass with slots
        t0 = time.perf_counter()
        buffer_slots = [
            TelemetryPointSlots(
                timestamp=1729780000.0 + i,
                cpu_percent=12.5,
                rss_bytes=104857600,
                read_rate=102400.0,
                write_rate=51200.0,
                threads=14,
                procs=1,
                gpu_mem=None,
            )
            for i in range(count)
        ]
        mem_slots_bytes, _ = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        del buffer_slots
        gc.collect()

        # 2. Tuples
        tracemalloc.start()
        buffer_tuples = [
            (1729780000.0 + i, 12.5, 104857600, 102400.0, 51200.0, 14, 1, None)
            for i in range(count)
        ]
        mem_tuples_bytes, _ = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        del buffer_tuples
        gc.collect()

        # 3. Standard dicts
        tracemalloc.start()
        buffer_dicts = [
            {
                "timestamp": 1729780000.0 + i,
                "cpu_percent": 12.5,
                "rss_bytes": 104857600,
                "read_rate": 102400.0,
                "write_rate": 51200.0,
                "threads": 14,
                "procs": 1,
                "gpu_mem": None,
            }
            for i in range(count)
        ]
        mem_dicts_bytes, _ = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        del buffer_dicts
        gc.collect()

        results[count] = {
            "slots_bytes": mem_slots_bytes,
            "slots_kb": mem_slots_bytes / 1024,
            "slots_bytes_per_sample": mem_slots_bytes / count,
            "tuples_bytes": mem_tuples_bytes,
            "tuples_bytes_per_sample": mem_tuples_bytes / count,
            "dicts_bytes": mem_dicts_bytes,
            "dicts_bytes_per_sample": mem_dicts_bytes / count,
        }
    return results


def benchmark_sqlite_storage(counts: list[int]) -> dict[str, Any]:
    results = {}
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_telemetry.sqlite3"
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("""
            CREATE TABLE process_telemetry (
                run_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                cpu_percent REAL,
                rss_bytes INTEGER,
                read_bytes_per_sec REAL,
                write_bytes_per_sec REAL,
                process_count INTEGER,
                thread_count INTEGER,
                gpu_memory_bytes INTEGER,
                PRIMARY KEY (run_id, timestamp)
            ) WITHOUT ROWID
        """)
        conn.commit()

        for count in counts:
            # Generate synthetic data for 10 distinct runs
            run_ids = [f"run_{i:04d}" for i in range(10)]
            points = []
            base_time = 1729780000.0
            for i in range(count):
                r_id = run_ids[i % 10]
                t = base_time + (i // 10)
                points.append((
                    r_id,
                    t,
                    15.2 + (i % 20),
                    100_000_000 + (i % 1000) * 1024,
                    50_000.0,
                    25_000.0,
                    2,
                    8,
                    None if (i % 2 == 0) else 1073741824,
                ))

            # Benchmark batch insert
            t0 = time.perf_counter()
            conn.execute("BEGIN TRANSACTION")
            conn.executemany(
                "INSERT INTO process_telemetry VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                points,
            )
            conn.commit()
            insert_elapsed = time.perf_counter() - t0

            # Measure DB file size
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            file_size_bytes = db_path.stat().st_size

            # Benchmark query performance
            # Query 1 hour (360 samples) for run_0001
            t0 = time.perf_counter()
            rows_1h = conn.execute(
                "SELECT * FROM process_telemetry WHERE run_id = ? AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp ASC",
                ("run_0001", base_time, base_time + 360),
            ).fetchall()
            query_1h_ms = (time.perf_counter() - t0) * 1000

            # Query 24 hours (8640 samples) for run_0001
            t0 = time.perf_counter()
            rows_24h = conn.execute(
                "SELECT * FROM process_telemetry WHERE run_id = ? AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp ASC",
                ("run_0001", base_time, base_time + 86400),
            ).fetchall()
            query_24h_ms = (time.perf_counter() - t0) * 1000

            results[count] = {
                "insert_elapsed_s": insert_elapsed,
                "inserts_per_sec": count / max(0.0001, insert_elapsed),
                "total_db_bytes": file_size_bytes,
                "bytes_per_sample": file_size_bytes / max(1, count),
                "query_1h_ms": query_1h_ms,
                "rows_1h": len(rows_1h),
                "query_24h_ms": query_24h_ms,
                "rows_24h": len(rows_24h),
            }

            # Clean table for next round
            conn.execute("DELETE FROM process_telemetry")
            conn.commit()
            conn.execute("VACUUM")

        conn.close()
    return results


def benchmark_downsampling_algorithms() -> dict[str, Any]:
    # Simulate 86,400 raw points (24 hours at 1s interval)
    count = 86400
    timestamps = [1729780000.0 + i for i in range(count)]
    values = [10.0 + (i % 50) + (i % 7) * 2.5 for i in range(count)]

    # Downsample to target 300 points using fixed time buckets (min, avg, max)
    target_points = 300
    bucket_size = count // target_points

    t0 = time.perf_counter()
    downsampled = []
    for b in range(target_points):
        start_idx = b * bucket_size
        end_idx = min(count, start_idx + bucket_size)
        sub_vals = values[start_idx:end_idx]
        sub_times = timestamps[start_idx:end_idx]
        mid_time = sub_times[len(sub_times) // 2]
        avg_val = sum(sub_vals) / len(sub_vals)
        min_val = min(sub_vals)
        max_val = max(sub_vals)
        downsampled.append((mid_time, avg_val, min_val, max_val))
    elapsed_ms = (time.perf_counter() - t0) * 1000

    return {
        "raw_points": count,
        "target_points": target_points,
        "bucket_size": bucket_size,
        "downsampling_elapsed_ms": elapsed_ms,
        "downsampling_rate_points_per_sec": count / (elapsed_ms / 1000),
    }


def main():
    print("=== RUNMUX HISTORICAL TELEMETRY SYNTHETIC BENCHMARK ===")
    print(f"Platform: {sys.platform} | Python: {sys.version.split()[0]}")
    print()

    print("1. PSUTIL INSPECTION OVERHEAD (per process)")
    psutil_res = benchmark_psutil_sampling()
    for k, v in psutil_res.items():
        print(f"  {k:25s}: {v:.3f} ms")
    print()

    print("2. IN-MEMORY BUFFER SIZING")
    counts = [360, 1800, 7200, 86400]  # 1h@10s, 1h@2s, 1h@0.5s / 24h@10s, 24h@1s
    mem_res = benchmark_memory_buffers(counts)
    for c, data in mem_res.items():
        print(f"  Samples: {c:6d} | Slots: {data['slots_kb']:8.2f} KB ({data['slots_bytes_per_sample']:.1f} B/sample) | Tuples: {data['tuples_bytes_per_sample']:.1f} B/sample | Dicts: {data['dicts_bytes_per_sample']:.1f} B/sample")
    print()

    print("3. SQLITE WAL STORAGE & QUERY PERFORMANCE")
    db_counts = [1000, 10000, 50000]
    db_res = benchmark_sqlite_storage(db_counts)
    for c, data in db_res.items():
        print(f"  Rows: {c:6d} | Insert: {data['inserts_per_sec']:8.0f} rows/s | Total Size: {data['total_db_bytes']/1024:8.1f} KB ({data['bytes_per_sample']:.1f} B/row) | Query 1h: {data['query_1h_ms']:.3f} ms | Query 24h: {data['query_24h_ms']:.3f} ms")
    print()

    print("4. DOWNSAMPLING LATENCY")
    ds_res = benchmark_downsampling_algorithms()
    print(f"  Downsampled {ds_res['raw_points']} -> {ds_res['target_points']} in {ds_res['downsampling_elapsed_ms']:.2f} ms ({ds_res['downsampling_rate_points_per_sec']:.0f} points/sec)")
    print()


if __name__ == "__main__":
    main()
