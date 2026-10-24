# Runmux Historical Telemetry — Resource Budget & Quantitative Benchmarks (Phase 5C)

**Document ID:** RUNMUX-5C-BUDGET | **Status:** Empirical Benchmarks & Corrected Models | **Date:** 2026-10-24  
**Scope:** `modules/runmux/` | **Author:** Antigravity (AI Systems Architect)

---

## 1. Executive Summary

This document presents empirical benchmark measurements and reconciled quantitative resource models evaluating CPU overhead, RAM consumption, disk I/O, database growth, and query latency for Runmux historical telemetry.

All benchmarks were executed directly on native **Windows 11 (win32)** with **Python 3.12.10** using realistic **22-character Run IDs** (`YYYYMMDD-HHMMSS-xxxxxx`), the full proposed SQLite schema with secondary indexes, active WAL checkpointing, deletion pruning, incremental auto-vacuuming, thread-count caching, and automatic corruption recovery.

---

## 2. Empirical Benchmark Measurements (Windows 11 Native)

The following metrics were directly measured using the project-local benchmark harness ([`modules/runmux/benchmarks/benchmark_telemetry_history.py`](file:///C:/Users/mcarls/src/scripts/.worktrees/runmux-historical-telemetry/modules/runmux/benchmarks/benchmark_telemetry_history.py)):

### 2.1. Process Sampling Latency on Windows (`psutil`)

| Inspection Call | Win32 Underlying API | Measured Latency (ms) | Notes |
| :--- | :--- | :--- | :--- |
| `proc.cpu_times()` | `GetProcessTimes` | **0.0021 ms** | Kernel & user time counters |
| `proc.memory_info().rss` | `GetProcessMemoryInfo` | **0.0023 ms** | Working set size |
| `proc.io_counters()` | `GetProcessIoCounters` | **0.0025 ms** | Read/write byte counters |
| `proc.num_threads()` | `CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD)` | **14.8360 ms** | System-wide thread snapshot traversal |
| `proc.children(recursive=True)` | `CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS)` | **18.7325 ms** | System-wide process tree traversal |
| **Direct PID Counters (Cache Hit)** | CPU + RSS + I/O + Cached Threads | **0.0070 ms** | Instantaneous inspection of known PIDs |
| **Full Tree Discovery (Cache Miss)** | Direct counters + Threads + Children | **33.5754 ms** | Complete cold tree traversal |

> [!IMPORTANT]
> **Thread-Count Caching Optimization:** On Windows, `proc.num_threads()` takes ~14.8 ms per process due to `CreateToolhelp32Snapshot`. By caching thread counts alongside child-PID tree verification during the 30.0s cache TTL, this heavy snapshot is eliminated on cache hits, reducing per-process sampling latency to **0.0070 ms**.

---

### 2.2. Corrected Cache Hit Rate & Overhead Breakdown

The cache hit rate depends on both the **sampling cadence** ($\Delta t$) and the **child-PID cache TTL**. In a continuous loop where the cache expires at $\text{elapsed} \ge \text{TTL}$:

$$\text{Ticks per Cycle} = \left\lceil \frac{\text{TTL}}{\Delta t} \right\rceil, \quad \text{Hits} = \text{Ticks per Cycle} - 1, \quad \text{Hit Rate} = \frac{\text{Hits}}{\text{Ticks per Cycle}} \times 100\%$$

For a default **5.0-second sampling cadence** and a **30.0-second TTL**:
$$\text{Ticks per Cycle} = \frac{30.0}{5.0} = 6 \text{ ticks}, \quad \text{Hits} = 5, \quad \text{Hit Rate} = \frac{5}{6} \times 100\% = \mathbf{83.33\%}$$

$$\text{Average Latency} = (1 - 0.8333) \times 33.575\text{ ms} + 0.8333 \times 0.0070\text{ ms} = \mathbf{5.602\text{ ms / proc}}$$

#### Measured & Simulated Sampling Overhead across Cadences & TTLs

| Sampling Interval ($\Delta t$) | Cache TTL | Hit Rate (%) | Avg Latency per Process | 5 Active Processes | 20 Active Processes | 50 Active Processes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1.0 s** | 5.0 s | **80.0%** | 6.721 ms / proc | 33.6 ms (3.4% CPU) | 134.4 ms (13.4% CPU) | 336.1 ms (33.6% CPU) |
| **1.0 s** | 15.0 s | **93.3%** | 2.245 ms / proc | 11.2 ms (1.1% CPU) | 44.9 ms (4.5% CPU) | 112.3 ms (11.2% CPU) |
| **1.0 s** | 30.0 s | **96.7%** | 1.126 ms / proc | 5.6 ms (0.6% CPU) | 22.5 ms (2.3% CPU) | 56.3 ms (5.6% CPU) |
| **2.0 s** | 5.0 s | **66.7%** | 11.196 ms / proc | 56.0 ms (2.8% CPU) | 223.9 ms (11.2% CPU) | 559.8 ms (28.0% CPU) |
| **2.0 s** | 15.0 s | **87.5%** | 4.203 ms / proc | 21.0 ms (1.1% CPU) | 84.1 ms (4.2% CPU) | 210.2 ms (10.5% CPU) |
| **2.0 s** | 30.0 s | **93.3%** | 2.245 ms / proc | 11.2 ms (0.6% CPU) | 44.9 ms (2.2% CPU) | 112.3 ms (5.6% CPU) |
| **5.0 s (Default)** | **5.0 s** | **0.0%** | **33.575 ms / proc** | **167.9 ms (3.4% CPU)** | **671.5 ms (13.4% CPU)** | **1,678.8 ms (33.6% CPU)** |
| **5.0 s (Default)** | **15.0 s** | **66.7%** | **11.196 ms / proc** | **56.0 ms (1.1% CPU)** | **223.9 ms (4.5% CPU)** | **559.8 ms (11.2% CPU)** |
| **5.0 s (Default)** | **30.0 s (Approved)** | **83.3%** | **5.602 ms / proc** | **28.0 ms (0.56% CPU)** | **112.0 ms (2.24% CPU)** | **280.1 ms (5.60% CPU)** |
| **10.0 s** | 5.0 s | **0.0%** | 33.575 ms / proc | 167.9 ms (1.7% CPU) | 671.5 ms (6.7% CPU) | 1,678.8 ms (16.8% CPU) |
| **10.0 s** | 30.0 s | **66.7%** | 11.196 ms / proc | 56.0 ms (0.56% CPU) | 223.9 ms (2.24% CPU) | 559.8 ms (5.60% CPU) |

---

### 2.3. End-to-End Complete Sampling Loop Benchmark

Measured executing the complete sampling loop (`TelemetrySampler` + GPU query + Thread count caching + SQLite batch insert + Host insert):

| Benchmark Stage | Total Measured Latency (10 runs) | Normalized Latency per Process |
| :--- | :--- | :--- |
| **Cold First Tick (Cache Miss)** | **444.10 ms** | **44.41 ms / proc** |
| **Steady-State Tick (Cache Hit)** | **20.95 ms** | **2.095 ms / proc** |
| **Average Tick Latency (over 12 ticks)** | **56.21 ms** | **5.621 ms / proc** |
| **Average Process CPU Time Consumed** | **33.85 ms** | **3.385 ms / proc** |

At steady state with 10 active managed runs, the entire sampling loop finishes in **20.95 ms** every 5,000 ms, consuming less than **0.7% of one CPU core**.

---

### 2.4. SQLite Full-Schema Benchmark Measurements

Tested using genuine 22-character Run IDs across all 5 proposed tables, with composite primary key `(run_id, timestamp)` and secondary index on `timestamp`:

| Measured Operation | 1,000 Rows | 10,000 Rows | 50,000 Rows | Performance Implication |
| :--- | :--- | :--- | :--- | :--- |
| **Batch Insert Throughput** | 693,241 rows/s | 604,252 rows/s | **508,849 rows/s** | Flushing 100 rows takes $< 0.20\text{ ms}$ |
| **Main DB Size on Disk** | 168.0 KB | 1,412.0 KB | **6,836.0 KB** | Measured **140.0 bytes / row** on disk |
| **WAL File Growth before Checkpoint** | 205.2 KB | 1,436.4 KB | **6,892.2 KB** | WAL size mirrors uncheckpointed data |
| **WAL Checkpoint Latency (`TRUNCATE`)** | **1.17 ms** | **3.16 ms** | **0.58 ms** | Truncates WAL to 0 bytes instantly |
| **1-Hour Range Query (720 rows)** | **0.160 ms** | **0.974 ms** | **1.089 ms** | Sub-millisecond chart query response |
| **1-Minute Rollup Generation** | **0.70 ms** | **4.22 ms** | **29.49 ms** | Maintenance rollup aggregation is fast |
| **Delete Pruning Execution** | **0.47 ms** | **3.96 ms** | **27.76 ms** | Pruning 25,000 rows takes $< 28\text{ ms}$ |
| **Incremental Vacuum Execution** | **0.01 ms** | **0.04 ms** | **0.11 ms** | Freelist pages returned with zero stall |

---

## 3. Reconciled Resource Projections & Storage Budget

### 3.1. In-Memory Ring Buffer Capacity Reconciliation
Standardized configuration across all design documents:
- **Default Background Cadence:** **5.0 seconds**.
- **Buffer Capacity:** `maxlen = 720` samples.
- **Coverage:** Exactly **1.0 hour of continuous high-resolution history**.
- **Memory per Sample:** **128.2 bytes** (slotted dataclass).
- **RAM Footprint per Active Run:** $720 \times 128.2\text{ B} = \mathbf{92.3\text{ KB}}$.

| Active Runs | Ring Buffer RAM | Core Sampler Overhead | Total Telemetry RAM Footprint |
| :--- | :--- | :--- | :--- |
| **5 active runs** | 0.46 MB | 3.5 MB | **~4.0 MB** |
| **20 active runs** | 1.85 MB | 4.0 MB | **~5.9 MB** |
| **50 active runs** | 4.62 MB | 5.0 MB | **~9.6 MB** |
| **100 active runs** | 9.23 MB | 6.5 MB | **~15.7 MB** |

---

### 3.2. Steady-State Storage Projections (1h Raw / 24h 1m / 7d 5m)

Using measured on-disk row sizes:
- Raw table row: **140.0 bytes / row**.
- 1-minute rollup row: **85.0 bytes / row** (measured).
- 5-minute rollup row: **85.0 bytes / row** (measured).

#### Rows Retained per Run at Steady State
1. `telemetry_raw` (1 hour at 5s): 720 rows $\times$ 140.0 B = **100.8 KB**.
2. `telemetry_rollup_1m` (24 hours at 1m): 1,440 rows $\times$ 85.0 B = **122.4 KB**.
3. `telemetry_rollup_5m` (7 days at 5m): 2,016 rows $\times$ 85.0 B = **171.4 KB**.
- **Total Steady-State Data per Run for 7 Days:** $\mathbf{394.6\text{ KB / run}}$.

#### Disk Footprint across Workloads (including Indexes & WAL headroom)

| Workload | Active Runs | Steady-State DB Size | Peak WAL Size (between checkpoints) | Total Disk Footprint | % of 50 MB Target Budget |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Small** | 5 active | 1.97 MB | 0.5 MB | **~2.5 MB** | **5.0%** |
| **Medium** | 20 active | 7.89 MB | 2.0 MB | **~9.9 MB** | **19.8%** |
| **Large** | 50 active | 19.73 MB | 4.5 MB | **~24.2 MB** | **48.4%** |
| **Extreme** | 100 active | 39.46 MB | 8.0 MB | **~47.5 MB** | **95.0%** |

---

### 3.3. Target Storage Budget (50 MB) & Multi-Stage Overflow Policy

Because SQLite storage includes file allocation page boundaries, freelists, WAL file growth during heavy concurrent writes, and potential reader concurrency locks, the 50 MB ceiling is enforced as an **active target storage budget** with bounded overflow degradation:

1. **Scheduled Maintenance:** Every 15 minutes, the worker triggers:
   - Rollup generation (`generate_rollups`) with sample-count-weighted averages.
   - Standard retention pruning (`prune_retention`): 1h raw, 24h 1m rollups, 7d 5m rollups.
   - WAL Checkpoint (`PRAGMA wal_checkpoint(TRUNCATE)`).
   - Freelist reclamation (`PRAGMA incremental_vacuum`).
2. **Busy-Reader Resilience:** If a concurrent reader holds a shared lock, `wal_checkpoint(TRUNCATE)` catches `sqlite3.OperationalError` gracefully and defers truncation until the next cycle without interrupting collection or web serving.
3. **Multi-Stage Overflow Policy:**
   - **Stage 1 (> 50 MB):** Prune oldest half of 5-minute rollups (> 3.5 days), run incremental vacuum and checkpoint.
   - **Stage 2 (> 50 MB):** Prune all 5m rollups older than 24 hours and raw samples older than 30 minutes.
   - **Stage 3 (> 50 MB):** Prune raw samples down to 15 minutes, 1m rollups down to 6 hours, and run `VACUUM`.
   - **Stage 4 (> 50 MB Critical):** Emergency shed: prune older rollups down to 1 hour, raw down to 5 minutes, and reclaim all pages.
4. **Database Integrity & WAL Preservation:**
   - At startup and on database exceptions, `TelemetryStore.check_integrity()` verifies header and database pages.
   - If corrupted, `quarantine_and_reset()` moves `telemetry.sqlite3`, `telemetry.sqlite3-wal`, and `telemetry.sqlite3-shm` together to `*.corrupt.<timestamp>`, preserving all recoverable transactions for forensic recovery while re-initializing a clean store to maintain web server availability.
