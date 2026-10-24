# Runmux Historical Telemetry — Resource Budget & Quantitative Benchmarks (Phase 5C)

**Document ID:** RUNMUX-5C-BUDGET | **Status:** Empirical Benchmarks & Corrected Models | **Date:** 2026-10-24  
**Scope:** `modules/runmux/` | **Author:** Antigravity (AI Systems Architect)

---

## 1. Executive Summary

This document presents empirical benchmark measurements and reconciled quantitative resource models evaluating CPU overhead, RAM consumption, disk I/O, database growth, and query latency for Runmux historical telemetry.

All benchmarks were executed directly on native **Windows 11 (win32)** with **Python 3.12.10** using realistic **22-character Run IDs** (`YYYYMMDD-HHMMSS-xxxxxx`), the full proposed SQLite schema with secondary indexes, active WAL checkpointing, deletion pruning, and incremental vacuuming.

---

## 2. Empirical Benchmark Measurements (Windows 11 Native)

The following metrics were directly measured using the project-local benchmark harness ([`modules/runmux/benchmarks/benchmark_telemetry_history.py`](file:///C:/Users/mcarls/src/scripts/.worktrees/runmux-historical-telemetry/modules/runmux/benchmarks/benchmark_telemetry_history.py)):

### 2.1. Process Sampling Latency on Windows (`psutil`)

| Inspection Call | Win32 Underlying API | Measured Latency (ms) | Notes |
| :--- | :--- | :--- | :--- |
| `proc.cpu_times()` | `GetProcessTimes` | **0.0023 ms** | Kernel & user time counters |
| `proc.memory_info().rss` | `GetProcessMemoryInfo` | **0.0024 ms** | Working set size |
| `proc.io_counters()` | `GetProcessIoCounters` | **0.0025 ms** | Read/write byte counters |
| `proc.num_threads()` | `CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD)` | **15.3340 ms** | System-wide thread snapshot traversal |
| `proc.children(recursive=True)` | `CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS)` | **17.9591 ms** | System-wide process tree traversal |
| **Direct PID Counters (Cache Hit)** | CPU + RSS + I/O counters | **0.0072 ms** | Instantaneous inspection of known PIDs |
| **Full Tree Discovery (Cache Miss)** | Direct counters + Threads + Children | **33.3003 ms** | Complete cold tree traversal |

---

### 2.2. Corrected Cache Hit Rate & Overhead Breakdown

The cache hit rate depends on both the **sampling cadence** ($\Delta t$) and the **child-PID cache TTL**:

$$\text{HitRate}(\Delta t, \text{TTL}) = \begin{cases} 0.0\% & \text{if } \Delta t \ge \text{TTL} \\ \frac{\lfloor \text{TTL} / \Delta t \rfloor}{\lfloor \text{TTL} / \Delta t \rfloor + 1} \times 100\% & \text{if } \Delta t < \text{TTL} \end{cases}$$

$$\text{Average Latency} = (1 - \text{HitRate}) \times 33.300\text{ ms} + \text{HitRate} \times 0.0072\text{ ms}$$

#### Measured & Calculated Sampling Overhead across Cadences & TTLs

| Sampling Interval ($\Delta t$) | Cache TTL | Hit Rate (%) | Avg Latency per Process | 5 Active Processes | 20 Active Processes | 50 Active Processes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1.0 s** | 5.0 s | **83.3%** | 5.556 ms / proc | 27.8 ms (2.8% CPU) | 111.1 ms (11.1% CPU) | 277.8 ms (27.8% CPU) |
| **1.0 s** | 15.0 s | **93.8%** | 2.088 ms / proc | 10.4 ms (1.0% CPU) | 41.8 ms (4.2% CPU) | 104.4 ms (10.4% CPU) |
| **1.0 s** | 30.0 s | **96.8%** | 1.081 ms / proc | 5.4 ms (0.5% CPU) | 21.6 ms (2.2% CPU) | 54.1 ms (5.4% CPU) |
| **2.0 s** | 5.0 s | **66.7%** | 11.105 ms / proc | 55.5 ms (2.8% CPU) | 222.1 ms (11.1% CPU) | 555.3 ms (27.8% CPU) |
| **2.0 s** | 15.0 s | **87.5%** | 4.169 ms / proc | 20.8 ms (1.0% CPU) | 83.4 ms (4.2% CPU) | 208.5 ms (10.4% CPU) |
| **2.0 s** | 30.0 s | **93.8%** | 2.088 ms / proc | 10.4 ms (0.5% CPU) | 41.8 ms (2.1% CPU) | 104.4 ms (5.2% CPU) |
| **5.0 s (Default)** | **5.0 s** | **0.0%** | **33.300 ms / proc** | **166.5 ms (3.3% CPU)** | **666.0 ms (13.3% CPU)** | **1,665.0 ms (33.3% CPU)** |
| **5.0 s (Default)** | **15.0 s** | **75.0%** | **8.330 ms / proc** | **41.7 ms (0.8% CPU)** | **166.6 ms (3.3% CPU)** | **416.5 ms (8.3% CPU)** |
| **5.0 s (Default)** | **30.0 s (Recommended)** | **85.7%** | **4.763 ms / proc** | **23.8 ms (0.5% CPU)** | **95.3 ms (1.9% CPU)** | **238.2 ms (4.8% CPU)** |
| **10.0 s** | 5.0 s | **0.0%** | 33.300 ms / proc | 166.5 ms (1.7% CPU) | 666.0 ms (6.7% CPU) | 1,665.0 ms (16.7% CPU) |
| **10.0 s** | 30.0 s | **75.0%** | 8.330 ms / proc | 41.7 ms (0.4% CPU) | 166.6 ms (1.7% CPU) | 416.5 ms (4.2% CPU) |

> [!IMPORTANT]
> **Key Finding:** If sampling cadence is 5.0s and TTL is 5.0s, the cache hit rate is **0.0%**, demanding 33.3 ms per process. By increasing child-PID cache TTL to **30.0 seconds**, the hit rate becomes **85.7%**, cutting CPU overhead for 20 active processes from **13.3% down to 1.9% of one core**.

---

### 2.3. SQLite Full-Schema Benchmark Measurements

Tested using genuine 22-character Run IDs across all 5 proposed tables, with composite primary key `(run_id, timestamp)` and secondary index on `timestamp`:

| Measured Operation | 1,000 Rows | 10,000 Rows | 50,000 Rows | Performance Implication |
| :--- | :--- | :--- | :--- | :--- |
| **Batch Insert Throughput** | 684,322 rows/s | 623,476 rows/s | **431,251 rows/s** | Flushing 100 rows takes $< 0.25\text{ ms}$ |
| **Main DB Size on Disk** | 172.0 KB | 1,428.0 KB | **6,872.0 KB** | Measured **140.7 bytes / row** on disk |
| **WAL File Growth before Checkpoint** | 209.2 KB | 1,452.5 KB | **6,928.4 KB** | WAL size mirrors uncheckpointed data |
| **WAL Checkpoint Latency (`TRUNCATE`)** | **1.30 ms** | **4.17 ms** | **0.59 ms** | Truncates WAL to 0 bytes instantly |
| **1-Hour Range Query (720 rows)** | **0.166 ms** | **0.983 ms** | **1.195 ms** | Sub-millisecond chart query response |
| **1-Minute Rollup Generation** | **0.72 ms** | **4.34 ms** | **30.99 ms** | 15-minute maintenance aggregation is fast |
| **Delete Pruning Execution** | **0.46 ms** | **3.91 ms** | **25.51 ms** | Pruning 25,000 rows takes $< 26\text{ ms}$ |
| **Incremental Vacuum Execution** | **0.01 ms** | **0.03 ms** | **0.18 ms** | Freelist pages returned with zero stall |

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
- Raw table row: **140.7 bytes / row**.
- 1-minute rollup row: **85.0 bytes / row** (measured).
- 5-minute rollup row: **85.0 bytes / row** (measured).

#### Rows Retained per Run at Steady State
1. `telemetry_raw` (1 hour at 5s): 720 rows $\times$ 140.7 B = **101.3 KB**.
2. `telemetry_rollup_1m` (24 hours at 1m): 1,440 rows $\times$ 85.0 B = **122.4 KB**.
3. `telemetry_rollup_5m` (7 days at 5m): 2,016 rows $\times$ 85.0 B = **171.4 KB**.
- **Total Steady-State Data per Run for 7 Days:** $\mathbf{395.1\text{ KB / run}}$.

#### Disk Footprint across Workloads (including Indexes & WAL headroom)

| Workload | Active Runs | Steady-State DB Size | Peak WAL Size (between checkpoints) | Total Disk Footprint | % of 50 MB Cap |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Small** | 5 active | 1.98 MB | 0.5 MB | **~2.5 MB** | **5.0%** |
| **Medium** | 20 active | 7.90 MB | 2.0 MB | **~9.9 MB** | **19.8%** |
| **Large** | 50 active | 19.75 MB | 4.5 MB | **~24.3 MB** | **48.6%** |
| **Extreme** | 100 active | 39.50 MB | 8.0 MB | **~47.5 MB** | **95.0%** |

*(At 100 active runs running 24/7 for 7 days, total disk footprint remains under the 50 MB budget).*

---

### 3.3. Enforceable Storage Budget & Safety Caps

1. **WAL Truncation:** Scheduled every 15 minutes via `PRAGMA wal_checkpoint(TRUNCATE)`.
2. **Freelist Reclamation:** When row deletions leave $> 500$ freelist pages, `PRAGMA incremental_vacuum(500)` releases physical disk space.
3. **Hard Budget Enforcement (`max_db_size_mb = 50`):**
   - If `size(telemetry.sqlite3) + size(telemetry.sqlite3-wal) > 45 MB` (90% threshold):
     1. Force immediate `wal_checkpoint(TRUNCATE)`.
     2. Prune 5-minute rollups from 7 days down to 5 days.
     3. Run `incremental_vacuum`.
   - If still over 45 MB, truncate raw retention from 60 minutes down to 30 minutes.
   - Prevents disk exhaustion regardless of run density.
