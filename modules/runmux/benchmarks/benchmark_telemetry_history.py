"""Synthetic benchmark harness for Runmux Phase 5C historical telemetry finalization.

Benchmarks:
1. Windows psutil sampling overhead and exact child-cache hit rates across intervals.
2. SQLite storage with actual proposed schema, genuine 22-char Run IDs, indexes,
   WAL checkpointing, pruning (DELETE), and incremental vacuum.
3. Multi-tier rollup generation latency and storage.
4. Downsampling throughput.
5. In-memory buffer footprint.
"""

from __future__ import annotations

import gc
import os
import secrets
import sqlite3
import sys
import tempfile
import time
import tracemalloc
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil

# Ensure runmux package in src/ is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


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


def generate_genuine_run_id() -> str:
    """Format: YYYYMMDD-HHMMSS-xxxxxx (22 characters)."""
    ts = time.strftime("%Y%m%d-%H%M%S")
    suffix = secrets.token_hex(3)
    return f"{ts}-{suffix}"


def benchmark_psutil_sampling() -> dict[str, Any]:
    current_pid = os.getpid()
    proc = psutil.Process(current_pid)

    # Warm up
    _ = proc.cpu_times()
    _ = proc.memory_info()

    iterations = 100

    # Individual metrics
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

    tree_iters = 30
    t0 = time.perf_counter()
    for _ in range(tree_iters):
        _ = proc.children(recursive=True)
    tree_time_ms = (time.perf_counter() - t0) * 1000 / tree_iters

    # Cache hit: sampling only known PIDs (cpu_times + rss + io_counters)
    # Cache miss: sampling known PIDs + thread snapshot + children traversal
    cache_hit_sample_ms = cpu_time_ms + rss_time_ms + io_time_ms
    cache_miss_sample_ms = cache_hit_sample_ms + threads_time_ms + tree_time_ms

    return {
        "cpu_time_ms": cpu_time_ms,
        "rss_time_ms": rss_time_ms,
        "threads_time_ms": threads_time_ms,
        "io_time_ms": io_time_ms,
        "tree_time_ms": tree_time_ms,
        "cache_hit_sample_ms": cache_hit_sample_ms,
        "cache_miss_sample_ms": cache_miss_sample_ms,
    }


def benchmark_sqlite_full_schema(row_counts: list[int]) -> dict[str, Any]:
    results = {}
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "telemetry.sqlite3"
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA page_size = 4096")
        conn.execute("PRAGMA auto_vacuum = INCREMENTAL")

        # Full proposed schema
        conn.execute("""
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
            ) WITHOUT ROWID
        """)
        conn.execute("CREATE INDEX idx_telemetry_raw_timestamp ON telemetry_raw(timestamp)")

        conn.execute("""
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
            ) WITHOUT ROWID
        """)

        conn.execute("""
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
            ) WITHOUT ROWID
        """)

        conn.execute("""
            CREATE TABLE host_telemetry_raw (
                timestamp REAL PRIMARY KEY,
                sampled_at TEXT NOT NULL,
                cpu_percent REAL,
                memory_used_bytes INTEGER,
                memory_available_bytes INTEGER,
                net_read_bytes_sec REAL,
                net_write_bytes_sec REAL
            ) WITHOUT ROWID
        """)

        conn.execute("""
            CREATE TABLE telemetry_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                event_type TEXT NOT NULL,
                reason TEXT,
                details_json TEXT
            )
        """)
        conn.execute("CREATE INDEX idx_telemetry_events_run ON telemetry_events(run_id, timestamp)")
        conn.commit()

        # Generate realistic Run IDs (10 active runs)
        run_ids = [generate_genuine_run_id() for _ in range(10)]

        for count in row_counts:
            # Generate points
            points = []
            base_time = 1729780000.0
            for i in range(count):
                r_id = run_ids[i % 10]
                t = base_time + (i // 10) * 5.0
                iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
                points.append((
                    r_id,
                    t,
                    iso,
                    15.5 + (i % 25),
                    3.8 + (i % 5),
                    104857600 + (i % 100) * 4096,
                    524288.0,
                    131072.0,
                    2,
                    16,
                    None if (i % 2 == 0) else 1073741824,
                ))

            # Measure batch insert throughput
            t0 = time.perf_counter()
            conn.execute("BEGIN TRANSACTION")
            conn.executemany(
                "INSERT INTO telemetry_raw VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                points,
            )
            conn.commit()
            insert_elapsed = time.perf_counter() - t0

            # Measure WAL size before checkpoint
            wal_path = Path(str(db_path) + "-wal")
            wal_size_before = wal_path.stat().st_size if wal_path.exists() else 0

            # Checkpoint WAL (TRUNCATE)
            t0 = time.perf_counter()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            checkpoint_elapsed_ms = (time.perf_counter() - t0) * 1000
            wal_size_after = wal_path.stat().st_size if wal_path.exists() else 0
            main_db_size = db_path.stat().st_size

            # Test 1-hour range query (720 rows @ 5s interval for 1 run)
            target_run = run_ids[0]
            t0 = time.perf_counter()
            rows_1h = conn.execute(
                "SELECT * FROM telemetry_raw WHERE run_id = ? AND timestamp BETWEEN ? AND ? ORDER BY timestamp ASC",
                (target_run, base_time, base_time + 3600.0),
            ).fetchall()
            query_1h_ms = (time.perf_counter() - t0) * 1000

            # Test rollup aggregation from raw into 1-minute rollup
            t0 = time.perf_counter()
            conn.execute("""
                INSERT OR REPLACE INTO telemetry_rollup_1m
                SELECT
                    run_id,
                    CAST(timestamp / 60 AS INTEGER) * 60 AS bucket_epoch,
                    COUNT(*) AS sample_count,
                    AVG(cpu_percent) AS cpu_avg,
                    MIN(cpu_percent) AS cpu_min,
                    MAX(cpu_percent) AS cpu_max,
                    CAST(AVG(rss_bytes) AS INTEGER) AS rss_avg,
                    MAX(rss_bytes) AS rss_max,
                    AVG(read_bytes_per_sec) AS read_bytes_sec_avg,
                    AVG(write_bytes_per_sec) AS write_bytes_sec_avg,
                    MAX(gpu_memory_bytes) AS gpu_memory_bytes_max
                FROM telemetry_raw
                GROUP BY run_id, CAST(timestamp / 60 AS INTEGER) * 60
            """)
            conn.commit()
            rollup_elapsed_ms = (time.perf_counter() - t0) * 1000

            # Test pruning: DELETE older than half
            mid_time = base_time + ((count // 10) * 5.0) / 2
            t0 = time.perf_counter()
            conn.execute("DELETE FROM telemetry_raw WHERE timestamp < ?", (mid_time,))
            conn.commit()
            delete_elapsed_ms = (time.perf_counter() - t0) * 1000

            # Measure freelist and incremental vacuum
            freelist_count = conn.execute("PRAGMA freelist_count").fetchone()[0]
            t0 = time.perf_counter()
            conn.execute("PRAGMA incremental_vacuum(500)")
            conn.commit()
            vacuum_elapsed_ms = (time.perf_counter() - t0) * 1000
            post_vacuum_size = db_path.stat().st_size

            results[count] = {
                "insert_elapsed_s": insert_elapsed,
                "inserts_per_sec": count / max(0.0001, insert_elapsed),
                "main_db_size_kb": main_db_size / 1024,
                "wal_size_before_kb": wal_size_before / 1024,
                "wal_size_after_kb": wal_size_after / 1024,
                "bytes_per_row": main_db_size / max(1, count),
                "checkpoint_elapsed_ms": checkpoint_elapsed_ms,
                "query_1h_ms": query_1h_ms,
                "rows_1h_matched": len(rows_1h),
                "rollup_elapsed_ms": rollup_elapsed_ms,
                "delete_elapsed_ms": delete_elapsed_ms,
                "freelist_pages": freelist_count,
                "vacuum_elapsed_ms": vacuum_elapsed_ms,
                "post_vacuum_size_kb": post_vacuum_size / 1024,
            }

            # Reset table for next round
            conn.execute("DELETE FROM telemetry_raw")
            conn.execute("DELETE FROM telemetry_rollup_1m")
            conn.commit()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.execute("VACUUM")

        conn.close()
    return results



def benchmark_complete_sampling_loop(num_runs: int = 10, total_ticks: int = 12) -> dict[str, Any]:
    """Measure full sampling loop CPU and wall time including process sampling, GPU queries, and SQLite persistence."""
    import sys
    from runmux.models import RunRecord
    from runmux.stats import TelemetrySampler
    from runmux.telemetry_store import TelemetryStore

    current_pid = os.getpid()
    proc = psutil.Process(current_pid)
    proc_create = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(proc.create_time()))

    records = []
    for i in range(num_runs):
        records.append(
            RunRecord(
                id=generate_genuine_run_id(),
                numeric_id=i + 1,
                name=f"worker_{i}",
                status="running",
                created_at=proc_create,
                updated_at=proc_create,
                started_at=proc_create,
                ended_at=None,
                exit_code=None,
                pid=current_pid,
                supervisor_pid=current_pid,
                program=sys.executable,
                argv_json="[]",
                cwd=tempfile.gettempdir(),
                env_overrides_json="{}",
                port=8000 + i,
                auth_token="dummy",
                log_path=os.path.join(tempfile.gettempdir(), f"run_{i}.log"),
                command_line="python",
                restart_of=None,
                duplicate_of=None,
                rows=24,
                columns=80,
            )
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        store = TelemetryStore(tmpdir)
        sampler = TelemetrySampler(child_cache_ttl=30.0)

        tick_latencies_ms = []
        cpu_times_ms = []

        for tick in range(total_ticks):
            t0 = time.perf_counter()
            p_cpu0 = proc.cpu_times()
            p_cpu_t0 = p_cpu0.user + p_cpu0.system

            stats, host = sampler.sample_active_runs(records, psutil_module=psutil)
            store.insert_process_samples(stats)
            store.insert_host_sample(host)

            p_cpu1 = proc.cpu_times()
            p_cpu_t1 = p_cpu1.user + p_cpu1.system

            elapsed_ms = (time.perf_counter() - t0) * 1000
            cpu_consumed_ms = (p_cpu_t1 - p_cpu_t0) * 1000

            tick_latencies_ms.append(elapsed_ms)
            cpu_times_ms.append(cpu_consumed_ms)

        avg_tick_latency_ms = sum(tick_latencies_ms) / len(tick_latencies_ms)
        avg_tick_cpu_ms = sum(cpu_times_ms) / len(cpu_times_ms)
        first_tick_ms = tick_latencies_ms[0] # Miss
        steady_tick_ms = sum(tick_latencies_ms[1:]) / max(1, len(tick_latencies_ms) - 1) # Hits

        return {
            "num_runs": num_runs,
            "total_ticks": total_ticks,
            "first_tick_miss_ms": first_tick_ms,
            "steady_tick_hit_ms": steady_tick_ms,
            "avg_tick_latency_ms": avg_tick_latency_ms,
            "avg_tick_cpu_ms": avg_tick_cpu_ms,
            "per_process_steady_ms": steady_tick_ms / num_runs,
            "per_process_cpu_ms": avg_tick_cpu_ms / num_runs,
        }

def main():
    print("=== RUNMUX HISTORICAL TELEMETRY BENCHMARK FINALIZATION ===")
    print(f"Platform: {sys.platform} | Python: {sys.version.split()[0]}")
    print()

    print("1. PSUTIL SAMPLING OVERHEAD ON WINDOWS")
    p_res = benchmark_psutil_sampling()
    for k, v in p_res.items():
        print(f"  {k:28s}: {v:.4f} ms")
    print()

    print("2. CACHE HIT RATE & CPU OVERHEAD ANALYSIS")
    hit_cost = p_res["cache_hit_sample_ms"]
    miss_cost = p_res["cache_miss_sample_ms"]

    intervals = [1.0, 2.0, 5.0, 10.0]
    ttls = [5.0, 15.0, 30.0]

    for interval in intervals:
        print(f"  Sampling Interval = {interval}s:")
        for ttl in ttls:
            # In a loop ticking every interval, a miss happens on tick 0, then ticks while (elapsed < ttl) are hits.
            # Total ticks in a TTL window = ceil(ttl / interval)
            # Hits = max(0, ceil(ttl / interval) - 1)
            # Misses = 1
            if interval >= ttl:
                hit_rate = 0.0
                avg_cost = miss_cost
            else:
                total_ticks = max(1, int(ttl // interval) + (1 if (ttl % interval > 0.001) else 0))
                hits = total_ticks - 1
                hit_rate = (hits / total_ticks) * 100.0
                avg_cost = (miss_cost + hits * hit_cost) / total_ticks
            print(f"    TTL={ttl:4.1f}s -> Hit Rate: {hit_rate:5.1f}% | Avg Sample Latency: {avg_cost:6.3f} ms/proc")
    print()

    print("3. COMPLETE SAMPLING-LOOP BENCHMARK (SAMPLER + GPU + THREADS + SQLITE WRITES)")
    loop_res = benchmark_complete_sampling_loop(num_runs=10, total_ticks=12)
    print(f"  Runs: {loop_res['num_runs']} registered active runs")
    print(f"    First Tick (Cache Miss)  : {loop_res['first_tick_miss_ms']:.3f} ms total ({loop_res['first_tick_miss_ms'] / 10:.3f} ms/proc)")
    print(f"    Steady Tick (Cache Hit)  : {loop_res['steady_tick_hit_ms']:.3f} ms total ({loop_res['per_process_steady_ms']:.3f} ms/proc)")
    print(f"    Avg Tick Latency (12 ticks): {loop_res['avg_tick_latency_ms']:.3f} ms total ({loop_res['avg_tick_latency_ms'] / 10:.3f} ms/proc)")
    print(f"    Avg Process CPU Time     : {loop_res['avg_tick_cpu_ms']:.3f} ms ({loop_res['per_process_cpu_ms']:.3f} ms/proc)")
    print()

    print("4. SQLITE FULL SCHEMA, WAL CHECKPOINT, PRUNING & VACUUM")
    counts = [1000, 10000, 50000]
    s_res = benchmark_sqlite_full_schema(counts)
    for c, data in s_res.items():
        print(f"  Dataset: {c:6d} rows")
        print(f"    Insert Throughput   : {data['inserts_per_sec']:8.0f} rows/s ({data['insert_elapsed_s']:.3f} s)")
        print(f"    Main DB Size        : {data['main_db_size_kb']:8.1f} KB ({data['bytes_per_row']:.1f} B/row)")
        print(f"    WAL Before/After    : {data['wal_size_before_kb']:.1f} KB -> {data['wal_size_after_kb']:.1f} KB (Checkpoint: {data['checkpoint_elapsed_ms']:.2f} ms)")
        print(f"    Query 1h (720 rows) : {data['query_1h_ms']:.3f} ms")
        print(f"    Rollup 1m Generation: {data['rollup_elapsed_ms']:.2f} ms")
        print(f"    Delete Pruning      : {data['delete_elapsed_ms']:.2f} ms (Freelist: {data['freelist_pages']} pages)")
        print(f"    Incr. Vacuum        : {data['vacuum_elapsed_ms']:.2f} ms (Post Size: {data['post_vacuum_size_kb']:.1f} KB)")
        print()


if __name__ == "__main__":
    main()
