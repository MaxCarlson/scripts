# Telemetry Provenance and Metric Semantics (Phase 5B)

This document establishes the official metric definitions, scope, provenance, units, and failure states for Runmux resource telemetry.

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
| `gpu_devices` | `device` | `nvidia-smi --query-gpu` | structured list | Instantaneous command query | `[]` if no NVIDIA GPU | Device scope: `load` %, `mem_used`, `mem_total`, `temp`. |

---

## 2. Core Correctness Rules

1. **Unavailable is NOT zero:** If a process is terminated, permission is denied, or a platform lacks a metric, the value must be `None` (null) with an explicit `unavailable` reason string (e.g., `"process exited"`, `"permission denied"`, `"pid reused"`). Reporting 0.0 falsely implies zero resource utilization on an active process.
2. **Network Attribution Truth:** Operating system unprivileged process APIs (Windows, Linux, macOS) do not expose per-process socket byte rates without packet filtering/eBPF/driver support. Therefore, per-process network stats must NOT present host-wide network throughput as process throughput. Host network rates are placed in explicit `host_net_*` fields or a dedicated host telemetry object.
3. **Run Identity & PID Reuse Protection:** PIDs are recycled by the operating system. Before querying a PID, the collector verifies:
   - Run record status is not terminal (`finished`, `failed`, `killed`, `lost`).
   - The OS process `create_time` is compatible with `record.started_at` (i.e. not created after the run finished or before the run was created).
   - If PID reuse or mismatch is detected, the process is treated as dead/exited with `unavailable: "pid reused by another process"`.
4. **Non-blocking Sampling:** Web routes must never block the event loop with `time.sleep()`. Telemetry sampling relies on monotonic time differences between reads, or threadpool-isolated asynchronous sampling.
