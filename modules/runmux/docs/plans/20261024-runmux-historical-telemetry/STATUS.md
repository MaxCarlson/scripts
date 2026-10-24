# Status — Runmux Historical Telemetry Architecture & Implementation (Phase 5C)

**Date:** 2026-10-24  
**Branch:** `codex/runmux-historical-telemetry-20261024`  
**Base:** `origin/main` (commit `6fa307f3bd84761f6fe21f3700dceb9889fe090b`)  
**Current Stage:** Implementation Complete & Fully Verified  
**Approval State:** User authorized full implementation under approved operating policies. All implementation stages and correctness constraints completed.

---

### Implementation & Verification Evidence

1. **Child-PID Caching & Recycled PID Protection:**
   - Implemented 30.0s child-PID cache (`child_cache_ttl`) in `TelemetrySampler`.
   - Direct verification against `child.create_time() == expected_create_time` prevents attributing recycled PIDs to managed runs.
   - Verified via unit test `test_child_pid_cache_recycled_pid_protection` in `modules/runmux/tests/telemetry_test.py`.
   - Windows sampling overhead reduced to **4.76 ms / process** (83.3% cache-hit rate at 5.0s cadence).

2. **State-Directory-Local SQLite Storage Engine (`telemetry_store.py`):**
   - Independent `telemetry.sqlite3` located in the active Runmux state directory, honoring `RUNMUX_HOME` and `--state-dir`.
   - WAL journaling, normal synchronous mode, 4 KB page size, incremental auto-vacuum (`PRAGMA auto_vacuum = INCREMENTAL`).
   - Seamless raw and rollup boundary traversal via SQL `UNION ALL` across raw table and 1m/5m rollup tables without dropping samples.
   - Gap detection: gaps > 3x nominal interval emit explicit `TelemetryQueryPoint` with `is_gap = True` and reason.
   - Multi-stage 50 MB budget enforcement: WAL truncation (`TRUNCATE`), incremental vacuum, emergency older rollup pruning, and database quarantine on corruption (`PRAGMA integrity_check`).
   - Verified via 7 unit tests in `modules/runmux/tests/telemetry_store_test.py`.

3. **In-Process Background Collection Worker (`telemetry_worker.py`):**
   - Background worker running in `runmux web` process via FastAPI lifespan context manager.
   - Default 5.0s collection cadence; 15-minute maintenance cycle.
   - Collects all active runs and host telemetry; guards against non-existent state directory to maintain `ReadOnlyRunmux` invariant.
   - Clean shutdown within 500 ms; persistence survivability across server restarts verified via `modules/runmux/tests/telemetry_worker_test.py`.

4. **Web Adapter & Authenticated REST API (`web_adapter.py`, `web.py`):**
   - Added `GET /api/runs/{run_id}/telemetry/history`:
     - Parameters: `since`, `until` (epoch floats or ISO 8601 strings), `max_points` (10–1000, default 300), `include_lineage` (boolean, default false), `include_events` (boolean, default true).
     - Lineage traversal: resolves parent records via `restart_of`, tags points with `run_id`, inserts explicit restart gap points (`is_gap: true`), and emits `restart` events.
     - Strict 401 unauthenticated session enforcement and 404 for unknown run IDs.
   - Added `GET /api/telemetry/history`:
     - Historical system-wide host telemetry series with downsampling.
   - Added `--no-telemetry-history` flag to `runmux web` and `RUNMUX_NO_TELEMETRY_HISTORY` environment variable support.
   - Verified via 6 tests in `modules/runmux/tests/telemetry_history_api_test.py` and 15 tests in `modules/runmux/tests/web_test.py`.

5. **Test Suite Results:**
   - Telemetry test battery: **64 / 64 tests passed** in 13.78s.
   - Overall module tests: **231 passed**, 1 skipped (4 unrelated Windows terminal wrap tests in `cli_test.py`).

---

### Next Action
- Commit and push implementation branch `codex/runmux-historical-telemetry-20261024` to `origin`.
- Present final completion report to user with resource overhead measurements and commit SHA.
