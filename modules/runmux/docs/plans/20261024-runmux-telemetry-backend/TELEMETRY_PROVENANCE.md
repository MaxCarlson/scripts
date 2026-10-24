# Telemetry Provenance and Metric Semantics (Phase 5B)

This document establishes the official metric definitions, scope, provenance, units, failure states, and concurrency architecture for Runmux resource telemetry.

---

## 1. Metrics Provenance Table

| Metric Field | Scope | Source API / Collector | Units | Freshness / Sampling | Unavailable / Stale Representation | Notes / Caveats |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `cpu_percent` | `process_tree` | `psutil.Process.cpu_times` user+sys delta over monotonic elapsed | % (100% = 1 core) | Delta between consecutive requests (or configured interval) | `None` when baseline unestablished, process dead, or denied | Can exceed 100% on multi-core systems (e.g. 250% on 4 cores). |
| `cpu_percent_normalized` | `process_tree` | `cpu_percent / logical_cpu_count` | % (0.0% to 100.0%) | Same as `cpu_percent` | `None` if unestablished or `cpu_count` unavailable | Normalized to total system CPU capacity. |
| `cpu_count` | `host` | `psutil.cpu_count(logical=True)` | integer count | Static host property | Fallback to 1 if unavailable | Used as denominator for `cpu_percent_normalized`. |
| `rss_bytes` | `process_tree` | `psutil.Process.memory_info().rss` | bytes | Instantaneous snapshot | `None` if process dead or access denied | Summed across living tree. Shared memory/DLL pages may be counted per child process. |
| `threads` | `process_tree` | `psutil.Process.num_threads()` | integer count | Instantaneous snapshot | `None` if process dead or access denied | Summed across living processes in the run's tree. |
| `process_count` | `process_tree` | Length of living tree `[root, *children]` | integer count | Instantaneous snapshot | `0` or `None` if dead | Includes root plus all alive, accessible descendants. |
| `read_bytes_per_second` | `process_tree` | `psutil.Process.io_counters().read_bytes` delta over monotonic elapsed | bytes/sec | Delta between consecutive requests | `None` if baseline unestablished, platform unsupported, or access denied | On macOS/BSD or without OS I/O counters, this is `None`, not 0.0 B/s. |
| `write_bytes_per_second` | `process_tree` | `psutil.Process.io_counters().write_bytes` delta over monotonic elapsed | bytes/sec | Delta between consecutive requests | `None` if baseline unestablished, platform unsupported, or access denied | Same as read rate. |
| `gpu_memory_bytes` | `process_tree` | `nvidia-smi --query-compute-apps` | bytes | Instantaneous command query (1.0s timeout) | `None` if no NVIDIA GPU, CLI absent, or non-compute app | Attributed strictly to PIDs in the run's process tree. |
| `host_net_read_bytes_per_second` | `host` | `psutil.net_io_counters().bytes_recv` delta over monotonic elapsed | bytes/sec | Host-wide delta | `None` if unestablished | Explicitly labeled host/system scope. NEVER attributed to a single process. |
| `host_net_write_bytes_per_second` | `host` | `psutil.net_io_counters().bytes_sent` delta over monotonic elapsed | bytes/sec | Host-wide delta | `None` if unestablished | Explicitly labeled host/system scope. NEVER attributed to a single process. |
| `host_cpu_percent` | `host` | `psutil.cpu_percent()` | % (0.0% to 100.0%) | Instantaneous / interval | `None` if access error | Total host CPU utilization. |
| `host_memory_used_bytes` | `host` | `psutil.virtual_memory().used` | bytes | Instantaneous snapshot | `None` if access error | Total host RAM used. |
| `host_memory_total_bytes` | `host` | `psutil.virtual_memory().total` | bytes | Instantaneous snapshot | `None` if access error | Total host RAM installed. |
| `gpu_devices` | `device` | `nvidia-smi --query-gpu` | structured list | Instantaneous command query (cached with 1.5s TTL) | `[]` if no NVIDIA GPU | Device scope: `load` %, `mem_used`, `mem_total`, `temp`. |

---

## 2. Web Sampler vs. CLI Stats Architecture

Runmux provides two distinct sampling engines tailored to their operating environments:

### A. Non-blocking Web Telemetry Sampler (`TelemetrySampler`)
- **Invocation Context:** Serves HTTP GET requests for `/api/runs/{run_id}/telemetry` and `/api/telemetry`.
- **Concurrency & Timing:** **Zero `time.sleep()` calls.** Web route handlers must never block asyncio or worker threads. Instead, `TelemetrySampler` records monotonic process snapshots `(timestamp, cpu_time, read_bytes, write_bytes, pid)`.
- **Cadence & Deltas:**
  - On the first poll ($N=1$), the baseline snapshot is recorded. Rate-based fields (`cpu_percent`, `cpu_percent_normalized`, `read_bytes_per_second`, `write_bytes_per_second`) return `None`, while instantaneous fields (`rss_bytes`, `process_count`, `thread_count`) are populated immediately.
  - On subsequent polls ($N \ge 2$), rates are computed over the exact monotonic elapsed duration $\Delta t = t_N - t_{N-1}$.
  - The sampler thread-safely evicts dead or untracked run snapshots and caches expensive host calls.

### B. Interval-Based CLI Stats (`sample_active_stats`)
- **Invocation Context:** Used by interactive terminal commands (`runmux stats`) and batch output (`runmux stats --once --json`).
- **Concurrency & Timing:** Synchronous and interval-driven. It captures a baseline `before` snapshot, explicitly sleeps for the user-specified interval (`time.sleep(interval_seconds)`), and captures an `after` snapshot.
- **Cadence & Deltas:** Computes rates strictly across the requested sleep window. Both initial and refreshed views display non-null rates because each cycle explicitly waits for the measurement window.

---

## 3. Unavailable vs. Zero Metric Semantics

Accurate observability requires distinguishing between **zero utilization** and **unavailability/failure**.

| Condition | Field Representation (JSON) | CLI Table Display | Semantics |
| :--- | :--- | :--- | :--- |
| **Active process, no work performed** | `0.0` or `0` | `0.0%`, `0 B/s` | Process is running and healthy; zero CPU time or I/O bytes elapsed during window. |
| **First sample (baseline unestablished)** | `null` (`None`) | `--` | Process is running, but no previous monotonic point exists to compute delta. |
| **Process exited / killed** | `null` (`None`) | `--` (with reason) | Process is no longer executing; `unavailable: "process exited"`. |
| **Run terminal (`finished`, `failed`)** | `null` (`None`) | `--` | Run lifecycle complete; `unavailable: "run is finished"`. |
| **PID reused by OS** | `null` (`None`) | `--` | PID belongs to another process; `unavailable: "pid reused by another process"`. |
| **OS unsupported (e.g. macOS disk I/O)** | `null` (`None`) | `--` | Operating system does not expose per-process counter; `unavailable: null` or note. |
| **Access denied (permissions)** | `null` (`None`) | `--` | OS denied process inspection; `unavailable: "access denied"`. |

> [!IMPORTANT]
> A metric field must NEVER default to `0.0` when measurement is unavailable. Doing so masks crashes, dead supervisors, and platform incompatibilities as "idle" processes.

---

## 4. PID Reuse Protection & Creation Time Tolerance

Operating systems recycle Process Identifiers (PIDs). Without validation, a terminated run whose PID is assigned to an arbitrary new process (e.g. a browser or database) would falsely inherit that process's CPU and memory stats.

`verify_run_process` applies strict, multi-stage identity verification:
1. **Terminal Status Check:** If the run record is in a terminal status (`finished`, `failed`, `killed`, `lost`), process inspection is aborted immediately.
2. **PID Existence Check:** Confirms the PID exists and `root.is_running()` is True.
3. **Creation Time Bounds (`PID_CREATION_TOLERANCE_SECONDS = 5.0`):**
   - Reference timestamp: `record.started_at or record.created_at`.
   - **Recycled PID (Upper Bound):** If `proc_create > ref_epoch + 5.0`, the process was created after the run was initiated. The original process exited, and the OS assigned the PID to a newer process. Flagged as `pid reused by another process`.
   - **Older Pre-existing Process (Lower Bound):** If `proc_create < ref_epoch - 5.0`, the process was created prior to the run's registration. Flagged as `pid reused by another process`.
   - **Ended Run Boundary:** If `record.ended_at` exists and `proc_create > ended_epoch`, any process with that PID is flagged as reused.
4. **Tolerance Calibration:** Tightened from the initial 60.0s prototype down to 5.0s. This accommodates OS scheduling jitter and Windows `CreateProcess` latency under heavy load while offering strict protection against PID recycling.

---

## 5. Latency and Concurrency with Disconnected Runs

In distributed or dense execution environments, multiple runs may disconnect simultaneously (e.g., node shutdown, supervisor crashes, or terminated containers).

### Sequential Bottleneck Eliminated
- In previous architectures, sequentially checking $N$ disconnected supervisors over TCP sockets resulted in $N \times 250\text{ms}$ timeouts (e.g., 25 disconnected runs stalled overview queries for $>6.25\text{s}$).
- In `ReadOnlyRunmux.get_overview_telemetry`, supervisor status refreshes are executed in parallel across a worker pool (`ThreadPoolExecutor(max_workers=min(16, len(active)))`).
- Connection attempts to dead supervisor ports fail fast with `ECONNREFUSED` / `WSAECONNREFUSED` within $<1\text{ms}$, immediately transitioning the in-memory display status to `lost` without blocking.
- Latency test `test_overview_telemetry_latency_with_numerous_disconnected_runs` proves 25 disconnected runs complete in $<1.0\text{s}$ (typically $<30\text{ms}$).

### GPU Query Caching
- Querying NVIDIA hardware metrics (`nvidia-smi`) incurs substantial process-spawn overhead ($\sim 100\text{ms} - 300\text{ms}$).
- `TelemetrySampler` caches GPU device properties (`gpu_devices(timeout=1.0)`) and compute process mappings with a **1.5-second TTL**.
- Rapid successive polls from browser clients reuse cached device state, preventing GPU management subsystem thrashing.
