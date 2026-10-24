# Runmux Historical Telemetry — Resource Budget & Quantitative Benchmarks (Phase 5C)

**Document ID:** RUNMUX-5C-BUDGET | **Status:** Empirical Benchmarks & Analytical Models | **Date:** 2026-10-24  
**Scope:** `modules/runmux/` | **Author:** Antigravity (AI Systems Architect)

---

## 1. Executive Summary

This document presents empirical benchmarks and quantitative analytical models evaluating the CPU, RAM, disk I/O, database size, and query latency of the proposed historical telemetry system.

All benchmarks were executed directly on native **Windows 11 (win32)** using **Python 3.12.10** under isolated conditions, completely decoupled from live Runmux registries or production workloads.

---

## 2. Empirical Benchmark Measurements (Windows 11 Native)

The following metrics were measured using the project-local benchmark harness (`modules/runmux/benchmarks/benchmark_telemetry_history.py`):

### 2.1. Process Sampling Overhead (`psutil` Inspection Latency)

| Metric / Inspection Call | Windows API Invoked | Measured Latency (ms) | Notes |
| :--- | :--- | :--- | :--- |
| `proc.cpu_times()` | `GetProcessTimes` | **0.002 ms** | Instantaneous kernel time query |
| `proc.memory_info().rss` | `GetProcessMemoryInfo` | **0.002 ms** | Instantaneous working set query |
| `proc.io_counters()` | `GetProcessIoCounters` | **0.002 ms** | Instantaneous I/O counter query |
| `proc.num_threads()` | `CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD)` | **16.087 ms** | System-wide thread snapshot traversal |
| `proc.children(recursive=True)` | `CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS)` | **18.068 ms** | System-wide process snapshot traversal |
| **Combined Single Process (with threads)** | Win32 APIs + Toolhelp thread | **17.147 ms** | Standard single-PID sample |
| **Combined Process Tree (root + children)** | Full tree discovery + sample | **35.215 ms** | Complete recursive tree inspection |

> [!CRITICAL]
> **Key Finding on Windows:** Basic process counters (`cpu_times`, `rss`, `io_counters`) take only **0.006 ms** combined. However, thread enumeration and child discovery take **~34 ms** because the Windows OS requires a full system toolhelp snapshot.  
> **Architectural Mitigation:** The proposed engine caches child PIDs for 5 seconds. On intermediate ticks (1s or 2s cadence), only known PIDs are inspected (0.006 ms), reducing sampling CPU overhead by **> 80%**.

---

### 2.2. In-Memory Data Structure Sizing

| Data Representation | Memory per Sample (Bytes) | 360 Samples (1h @ 10s) | 1,800 Samples (1h @ 2s) | 86,400 Samples (24h @ 1s) |
| :--- | :--- | :--- | :--- | :--- |
| **Python Dict (`dict`)** | **304.2 B** | 109.5 KB | 547.6 KB | 26.3 MB |
| **Standard Tuple (`tuple`)** | **136.2 B** | 49.0 KB | 245.2 KB | 11.8 MB |
| **Dataclass with `__slots__`** | **128.2 B** | **45.5 KB** | **226.9 KB** | **10.8 MB** |

*Measured via Python `tracemalloc` heap tracking across 86,400 allocated instances.*

---

### 2.3. SQLite WAL Storage & Query Performance

Measurements using a dedicated SQLite database (`telemetry.sqlite3`) in WAL mode with `PRAGMA synchronous = NORMAL`:

| Dataset Size (Rows) | Batch Insert Rate (rows/s) | Total DB Size on Disk | Disk Footprint per Row | Query 1-Hour Range (360 rows) | Query 24-Hour Range (8,640 rows) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1,000 rows** | **692,377 rows/s** | 56.0 KB | **57.3 B / row** | 0.182 ms | 0.133 ms |
| **10,000 rows** | **872,547 rows/s** | 512.0 KB | **52.4 B / row** | 0.559 ms | 1.369 ms |
| **50,000 rows** | **829,563 rows/s** | 2,504.0 KB | **51.3 B / row** | 0.600 ms | 5.780 ms |

---

### 2.4. Downsampling Algorithm Throughput

- **Input:** 86,400 raw data points (simulating 24 hours of 1-second samples).
- **Target:** 300 data points (optimal for web canvas/chart rendering).
- **Algorithm:** Bucketed Min/Avg/Max downsampling.
- **Measured Latency:** **1.51 ms** total execution time.
- **Processing Rate:** **57,040,998 points / second**.

---

## 3. Workload Modeling & Resource Projections

We model four system configurations across four sampling intervals (1s, 2s, 5s, 10s) and three retention horizons (1h, 24h, 7d):
- **Workload A:** 10 registered processes (5 active, 5 finished/lost).
- **Workload B:** 100 registered processes (20 active, 80 finished/lost).
- **Workload C:** 1,000 registered processes (50 active, 950 finished/lost).
- **Workload D (High Density):** 1,000 registered processes (100 active, 900 finished/lost).

---

### 3.1. CPU Overhead & Sampling Latency Model

*Note: In `TelemetrySampler`, finished/lost processes are bypassed immediately ($< 0.001\text{ ms}$). Only active processes are sampled.*

| Active Processes | Sampling Interval | Child-Cache Hit (80% ticks) | Full Tree Refresh (20% ticks) | Average Cycle Time (ms) | Effective CPU % of 1 Core |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **5 active** | 5.0 s (Default) | 0.03 ms | 176 ms | **35.2 ms / cycle** | **0.7%** |
| **5 active** | 2.0 s | 0.03 ms | 176 ms | **35.2 ms / cycle** | **1.8%** |
| **5 active** | 1.0 s | 0.03 ms | 176 ms | **35.2 ms / cycle** | **3.5%** |
| **20 active** | 5.0 s (Default) | 0.12 ms | 704 ms | **140.9 ms / cycle** | **2.8%** |
| **20 active** | 2.0 s | 0.12 ms | 704 ms | **140.9 ms / cycle** | **7.0%** |
| **50 active** | 5.0 s (Default) | 0.30 ms | 1,760 ms | **352.2 ms / cycle** | **7.0%** |
| **50 active** | 2.0 s | 0.30 ms | 1,760 ms | **352.2 ms / cycle** | **17.6%** |
| **100 active** | 10.0 s | 0.60 ms | 3,520 ms | **704.5 ms / cycle** | **7.0%** |
| **100 active** | 5.0 s | 0.60 ms | 3,520 ms | **704.5 ms / cycle** | **14.1%** |

*(Estimates use measured single-thread Windows latencies. Parallelizing across a 4-worker thread pool reduces wall-clock sampling duration by ~3.5×).*

---

### 3.2. RAM Consumption Model (In-Memory Ring Buffers)

Ring buffers hold high-resolution slotted samples for active runs (30-minute buffer: 900 samples at 2s interval, or 360 samples at 5s interval).

| Active Processes | Buffer Depth (Points/Run) | RAM per Run | Total Ring Buffer RAM | Process Overhead & Cache | Total Telemetry RAM Footprint |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **5 active** | 360 (5s cadence) | 46 KB | 230 KB | 4.0 MB | **~4.2 MB** |
| **5 active** | 900 (2s cadence) | 115 KB | 575 KB | 4.0 MB | **~4.6 MB** |
| **20 active** | 900 (2s cadence) | 115 KB | 2.3 MB | 5.0 MB | **~7.3 MB** |
| **50 active** | 900 (2s cadence) | 115 KB | 5.75 MB | 6.0 MB | **~11.8 MB** |
| **100 active** | 900 (2s cadence) | 115 KB | 11.5 MB | 8.0 MB | **~19.5 MB** |

*Even at 100 concurrent active runs, total RAM consumption is capped under **20 MB**.*

---

### 3.3. Database Size & Daily Write Volume Model

Comparison between **Flat Storage** (every raw point kept) vs. **Tiered Rollup Storage** (raw kept for 1h, 1m rollups for 24h, 5m rollups for 7d):

#### Daily Write Volume (Disk Writes / Day)

| Active Runs | Cadence | Flat Writes/Day | Flat Volume/Day | Tiered Rollup Writes/Day | Tiered Write Volume/Day |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **5 active** | 5.0 s | 86,400 rows | 4.5 MB / day | 93,600 rows | **4.8 MB / day** |
| **20 active** | 5.0 s | 345,600 rows | 18.0 MB / day | 374,400 rows | **19.5 MB / day** |
| **20 active** | 2.0 s | 864,000 rows | 45.0 MB / day | 892,800 rows | **46.4 MB / day** |
| **50 active** | 5.0 s | 864,000 rows | 45.0 MB / day | 936,000 rows | **48.7 MB / day** |
| **100 active** | 10.0 s | 864,000 rows | 45.0 MB / day | 936,000 rows | **48.7 MB / day** |

#### Steady-State Database Size on Disk (after Pruning & Rollups)

| Active Runs | Retention Policy | Flat Storage Size (7 Days) | Tiered Storage Size (7 Days) | Storage Savings (%) |
| :--- | :--- | :--- | :--- | :--- |
| **5 active** | 1h Raw + 24h 1m + 7d 5m | 31.5 MB | **1.36 MB** | **95.7%** |
| **20 active** | 1h Raw + 24h 1m + 7d 5m | 126.0 MB | **5.46 MB** | **95.7%** |
| **50 active** | 1h Raw + 24h 1m + 7d 5m | 315.0 MB | **13.65 MB** | **95.7%** |
| **100 active** | 1h Raw + 24h 1m + 7d 5m | 630.0 MB | **27.30 MB** | **95.7%** |

*(Tiered storage sizes include B-tree primary key indices and WAL overhead).*

---

### 3.4. Behavior under Disconnected and Completed Runs

In long-running development environments, hundreds of completed runs accumulate in the registry:
- **Registry Inspection:** `ReadOnlyRunmux.list_runs()` filters runs where `status in TERMINAL_STATUSES`. Terminal runs are skipped from live sampling loops.
- **Zero Polling Waste:** Completed runs incur **zero CPU overhead** during sampling cycles.
- **Ring Buffer Eviction:** Completed runs have their in-memory ring buffers evicted after a 10-minute grace window, releasing RAM immediately.
- **Historical Querying:** Historical charts for completed runs are read directly from SQLite without touching supervisors or processes.
