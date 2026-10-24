# Checklist — Runmux Phase 5C Historical Telemetry Architecture & Implementation

**Plan Folder:** `modules/runmux/docs/plans/20261024-runmux-historical-telemetry/`  
**Branch:** `codex/runmux-historical-telemetry-20261024`  
**Base Commit:** `6fa307f3bd84761f6fe21f3700dceb9889fe090b`  
**Status:** Implementation Complete & Fully Verified

---

## 1. Worktree & Isolation Requirements

- [x] Create dedicated Git worktree `.worktrees/runmux-historical-telemetry`
- [x] Create feature branch `codex/runmux-historical-telemetry-20261024` tracking `origin/main`
- [x] Confirm clean starting status at commit `6fa307f3`
- [x] Verify native Windows environment (no WSL, no Docker)
- [x] Verify live user registry (`%LOCALAPPDATA%\runmux`) is never accessed
- [x] Verify baseline tests pass (`tests/telemetry_test.py`, `tests/stats_test.py`)

---

## 2. Architecture Research & Component Audit

- [x] Audit `TelemetrySampler` in `modules/runmux/src/runmux/stats.py`
- [x] Audit `resource_metrics` package (`gpu.py`, `process.py`, `system.py`)
- [x] Audit SQLite registry schema in `modules/runmux/src/runmux/store.py`
- [x] Audit state directory resolution in `modules/runmux/src/runmux/platform_paths.py`
- [x] Resolve `telemetry.sqlite3` path relative to active state directory (`RUNMUX_HOME` / `--state-dir`)
- [x] Evaluate Pure In-Memory vs. Pure SQLite-First vs. Write-Through Hybrid
- [x] Reevaluate coordination complexity of in-memory buffering vs. SQLite-first
- [x] Formulate Write-Through Tiered Hybrid to eliminate dual-source boundary merging
- [x] Document alternatives analysis in `02_alternatives_analysis.md`

---

## 3. Quantitative Performance Evaluation & Benchmarking

- [x] Update synthetic benchmark harness (`modules/runmux/benchmarks/benchmark_telemetry_history.py`)
- [x] Benchmark realistic 22-character Run IDs (`YYYYMMDD-HHMMSS-xxxxxx`)
- [x] Benchmark full proposed schema (raw, 1m rollup, 5m rollup, host, events, secondary indexes)
- [x] Benchmark SQLite WAL checkpointing (`TRUNCATE`), deletion pruning, and incremental vacuum
- [x] Recalculate Windows sampling CPU overhead across intervals (1s, 2s, 5s, 10s) and TTLs (5s, 15s, 30s)
- [x] Correct cache-hit simulation: 5s cadence + 30s TTL yields 83.33% hit rate (5 hits per 6 ticks = 4.76 ms/proc)
- [x] Measure actual on-disk row footprint: 140.7 bytes / row
- [x] Model CPU overhead across 10, 100, and 1,000 registered processes
- [x] Model RAM consumption under multi-process loads (reconciled at 720 points = 92.3 KB/run)
- [x] Model steady-state database size (1h raw + 24h 1m + 7d 5m = 395.1 KB/run)
- [x] Document enforceable 50 MB storage budget and maintenance cycles in `03_resource_budget_and_benchmarks.md`

---

## 4. Historical Data Correctness & Semantics

- [x] Guarantee immutable Run ID partitioning vs recycled numeric IDs
- [x] Enforce PID reuse protection via `create_time()` verification on child processes
- [x] Formalize `null` vs `0.0` semantics (never fabricate zero for missing metrics)
- [x] Define gap handling for process exits, pauses, and missing intervals
- [x] Document platform support boundaries (Windows, Linux, macOS I/O counters, NVIDIA GPUs)
- [x] Define lineage traversal (`restart_of`, `duplicate_of`) with explicit gap markers
- [x] Enforce strict scope isolation (process-tree vs host-wide metrics)
- [x] Verify CPU percentage and disk I/O rate semantics ($r = \Delta v / \Delta t$)
- [x] Fix UTC epoch alignment: `2026-10-24T08:00:00Z` maps to Unix epoch `1792828800.0`

---

## 5. Storage Engine Implementation (`telemetry_store.py`)

- [x] Create separate `telemetry.sqlite3` in active Runmux state directory
- [x] Create tables: `telemetry_raw`, `telemetry_rollup_1m`, `telemetry_rollup_5m`, `host_telemetry_raw`, `host_telemetry_rollup_1m`, `telemetry_events`
- [x] Configure WAL mode, normal synchronous mode, 4 KB pages, and incremental auto-vacuum
- [x] Implement batch insertion: `insert_process_samples`, `insert_host_sample`, `record_event`
- [x] Implement rollup aggregations: `generate_rollups` (1m and 5m buckets)
- [x] Implement 3-tier retention pruning: `prune_retention` (1h raw, 24h 1m, 7d 5m)
- [x] Implement continuous boundary querying: `query_process_history` (SQL `UNION ALL` across raw and rollups)
- [x] Implement host history querying: `query_host_history`
- [x] Implement gap detection (> 3x nominal interval)
- [x] Implement multi-stage storage budget enforcement (`enforce_storage_budget`) with WAL truncation and incremental vacuum
- [x] Implement database integrity checking and corrupt quarantine/reset (`quarantine_and_reset`)
- [x] Verify with comprehensive test suite (`modules/runmux/tests/telemetry_store_test.py`)

---

## 6. Background Collection Worker (`telemetry_worker.py`)

- [x] Implement `TelemetryHistoryWorker` running strictly during `runmux web` lifetime
- [x] Periodic collection loop at configurable 5.0s cadence
- [x] Periodic maintenance loop at 15-minute cadence
- [x] Read-only run discovery guarding against non-existent state directory
- [x] Clean shutdown within 500 ms timeout
- [x] Verify survivability and persistence across server restarts (`modules/runmux/tests/telemetry_worker_test.py`)

---

## 7. Web Integration & REST API Endpoints

- [x] Extend `ReadOnlyRunmux` with `get_run_telemetry_history` and `get_overview_telemetry_history`
- [x] Implement lineage traversal: resolve `restart_of` parents, tag points with `run_id`, inject restart gaps and events
- [x] Add REST endpoint `GET /api/runs/{run_id}/telemetry/history`
- [x] Add REST endpoint `GET /api/telemetry/history`
- [x] Add `--no-telemetry-history` flag and `RUNMUX_NO_TELEMETRY_HISTORY` environment variable
- [x] Integrate worker lifecycle with FastAPI app via lifespan context manager
- [x] Enforce authentication (HTTP 401 on missing session) and HTTP 404 on missing runs
- [x] Verify with test suites (`telemetry_history_api_test.py`, `web_test.py`, `lifecycle_api_test.py`)

---

## 8. Final Verification & Completion Gate

- [x] 64 / 64 telemetry & web tests passing cleanly
- [x] Preserved existing Phase 5B live telemetry backend and all public APIs unchanged
- [x] Verified native Windows execution and isolation
- [x] Update plan documentation (`STATUS.md`, `HANDOFF.md`, `checklist.md`)
- [x] Git status clean and intended files staged
- [x] Commit and push feature branch `codex/runmux-historical-telemetry-20261024` to `origin` (do not merge)
