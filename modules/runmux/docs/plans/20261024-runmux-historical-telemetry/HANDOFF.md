# Handoff — Runmux Historical Telemetry Architecture & Implementation (Phase 5C)

**Branch:** `codex/runmux-historical-telemetry-20261024`  
**Worktree:** `.worktrees/runmux-historical-telemetry`  
**Base Commit:** `6fa307f3bd84761f6fe21f3700dceb9889fe090b` (`origin/main`)  
**Assignment:** Phase 5C Historical Telemetry Implementation & Verification.

---

## 1. Scope & Execution Rules Followed

1. **Staged Implementation Complete:** Historical telemetry collection, SQLite-based time-series storage, downsampled rollups, retention pruning, storage budget enforcement, and authenticated REST APIs are fully implemented.
2. **Preserved Existing APIs:** Existing Phase 5B live telemetry endpoints (`/api/runs/{id}/telemetry` and `/api/telemetry`), supervisor IPC, and runner behavior are 100% untouched and functional.
3. **Strict Isolation:** All work was conducted in dedicated worktree `.worktrees/runmux-historical-telemetry`. Live user registry (`%LOCALAPPDATA%\runmux`) was never accessed or modified.
4. **No Frontend Conflicts:** Avoided editing `web_static/assets/dashboard.js`, CSS, or HTML, preventing conflicts with concurrent Phase 5A+ work.
5. **Native Windows Tooling:** All benchmarks and test executions ran via native Windows PowerShell and Python 3.12 (`.venv`).

---

## 2. Architectural Components Implemented

1. **Child-PID Caching with Recycled PID Protection:**
   - In `modules/runmux/src/runmux/stats.py`: `TelemetrySampler` caches discovered child PIDs and their creation timestamps for 30.0s (`child_cache_ttl`).
   - On cache hits, validates `child.is_running()` and `child.create_time() == expected_create_time` before attributing metrics to the managed run.
   - At 5.0s cadence and 30.0s TTL, achieves 83.33% cache-hit rate, reducing Windows sampling overhead to **4.76 ms / process**.

2. **Dedicated Time-Series Database (`modules/runmux/src/runmux/telemetry_store.py`):**
   - Independent `telemetry.sqlite3` in the active state directory (honoring `RUNMUX_HOME` and `--state-dir`).
   - Tables:
     - `telemetry_raw` / `host_telemetry_raw`: High-resolution samples (1h retention).
     - `telemetry_rollup_1m` / `host_telemetry_rollup_1m`: 1-minute bucket aggregations (24h retention).
     - `telemetry_rollup_5m`: 5-minute bucket aggregations (7d retention).
     - `telemetry_events`: Discrete lifecycle events (`pause`, `resume`, `exit`, `restart`).
   - `PRAGMA auto_vacuum = INCREMENTAL`, `PRAGMA journal_mode = WAL`, `PRAGMA synchronous = NORMAL`.
   - Continuous time-series querying via `query_process_history`: Uses seamless SQL `UNION ALL` across raw and rollup tables to guarantee zero dropped points at raw/rollup boundaries.
   - Explicit gap detection: intervals exceeding 3x nominal cadence inject an explicit `is_gap: true` point.
   - Enforceable 50 MB budget: WAL truncation (`TRUNCATE`), incremental vacuum, emergency older rollup pruning, and automatic corrupt database quarantine/reset (`PRAGMA integrity_check`).

3. **Background Sampling Worker (`modules/runmux/src/runmux/telemetry_worker.py`):**
   - In-process `TelemetryHistoryWorker` running strictly during `runmux web` lifetime via FastAPI lifespan context manager.
   - Default cadence: 5.0s sampling, 15-minute maintenance cycle.
   - Collects active runs via read-only inspection; safely skips collection if the state directory does not yet exist.
   - Clean shutdown within 500 ms; persistence survivability across web server restarts verified.

4. **Authenticated REST API & Lineage Traversal (`modules/runmux/src/runmux/web.py`, `web_adapter.py`):**
   - `GET /api/runs/{run_id}/telemetry/history`:
     - Parameters: `since`, `until` (epoch float or ISO 8601 string), `max_points` (10–1000, default 300), `include_lineage` (boolean, default false), `include_events` (boolean, default true).
     - Lineage traversal: walks `restart_of` backwards to chain parent runs, tagging points with `run_id`, injecting restart gap points (`is_gap: true`), and emitting `restart` events.
     - Strict session authentication (HTTP 401 on missing session) and 404 on missing runs.
   - `GET /api/telemetry/history`: Host-wide metrics series with provenance and downsampling.
   - `--no-telemetry-history` CLI flag and `RUNMUX_NO_TELEMETRY_HISTORY` environment variable.

---

## 3. Test Verification Battery

- `modules/runmux/tests/telemetry_history_api_test.py`: 6/6 passed.
- `modules/runmux/tests/telemetry_store_test.py`: 7/7 passed.
- `modules/runmux/tests/telemetry_worker_test.py`: 2/2 passed.
- `modules/runmux/tests/telemetry_test.py`: 12/12 passed.
- `modules/runmux/tests/stats_test.py`: 11/11 passed.
- `modules/runmux/tests/web_adapter_test.py`: 11/11 passed.
- `modules/runmux/tests/web_test.py`: 15/15 passed.
- Total telemetry & web suite: **64 / 64 passed**.
