# Status — Runmux Historical Telemetry Architecture & Implementation (Phase 5C)

**Date:** 2026-10-24  
**Branch:** `codex/runmux-historical-telemetry-20261024`  
**Base:** `origin/main` (commit `a0028473`)  
**Current Stage:** Phase 5C Complete and Merged into main  
**Approval State:** Fully approved, verified, and merged into main.


10. **Final Integration Verification & Rollback Invariant:**
    - **Atomic Quarantine Rollback:** Verified that partial quarantine failures (e.g. locked WAL/SHM files) roll back database renames and strictly prevent replacement database initialization against leftover WAL/SHM files (`test_quarantine_rollback_on_partial_failure_avoids_leftover_wal_and_data_loss`).
    - **Live Telemetry Non-Regression:** Verified that the 30-second child-PID cache in `TelemetrySampler` continuously computes live CPU percentage, fresh RSS bytes, and thread counts on every sub-30s poll while immediately purging dead or recycled PIDs (`test_live_telemetry_accuracy_and_sub_tick_updates_with_child_cache`).
    - **Integration Merge:** Merged into `main` with Phase 4A lifecycle frontend/backend, passing all combined Python unit/integration tests, Node dashboard tests, and real headless Chrome CDP browser E2E tests.

---

### Implementation & Verification Evidence

1. **Child-PID Caching & Thread Enumeration Optimization:**
   - Implemented 30.0s child-PID and thread-count cache in `TelemetrySampler`.
   - Direct verification against `child.create_time() == expected_create_time` prevents attributing recycled PIDs to managed runs.
   - Eliminates Windows `CreateToolhelp32Snapshot` (~14.8 ms) on every tick during cache hits.
   - Cache hit rate: **83.33%** at 5.0s cadence. Steady-state sampling overhead reduced to **2.095 ms / process**.
   - Verified via unit test `test_child_pid_cache_recycled_pid_protection` in `modules/runmux/tests/telemetry_test.py`.

2. **Three-Tier Historical Querying (`telemetry_store.py`):**
   - Implemented 3-tier continuous querying for both process (`query_process_history`) and host (`query_host_history`):
     - Tier 3: 5-minute rollups for $t < b_{5m\_1m}$ (interval = 300s).
     - Tier 2: 1-minute rollups for $b_{5m\_1m} \le t < \text{raw\_boundary}$ (interval = 60s).
     - Tier 1: Raw samples aggregated into 1m buckets for $t \ge \text{raw\_boundary}$ (or raw samples if query $\le 3600$s).
   - Strict non-overlapping boundaries aligned to multiples of 300s and 60s guarantee zero duplicate and zero missing samples.
   - Truthful missing data representation: gap intervals emit explicit gap points; missing metrics remain NULL (never fabricated as 0.0).
   - Verified via `test_query_process_history_seven_day_three_tier` and `test_query_host_history_seven_day_three_tier`.

3. **Sample-Count-Weighted Aggregation & Gap Downsampling:**
   - 5-minute rollups aggregate 1-minute rollups using sample-count-weighted averages:
     `SUM(CASE WHEN metric IS NOT NULL THEN metric * sample_count END) * 1.0 / NULLIF(SUM(CASE WHEN metric IS NOT NULL THEN sample_count ELSE 0 END), 0)`.
   - Strict NULL semantics: if all samples in a bucket are NULL, the rollup metric is NULL.
   - Corrected downsampler (`_downsample_points` and `_downsample_host_points`): retains gap markers and restart boundaries chronologically while aggregating valid measurements, without silently dropping either.
   - Verified via `test_five_minute_rollup_sample_count_weighted_averages`, `test_five_minute_rollup_strict_null_preservation`, and `test_downsample_points_preserves_gap_markers_and_valid_points`.

4. **Target Storage Budget (50 MB) & Multi-Stage Overflow Policy:**
   - Designated 50 MB as an active **target storage budget**.
   - Multi-stage emergency pruning:
     - Stage 1: Prune oldest half of 5m rollups (> 3.5 days).
     - Stage 2: Prune all 5m rollups older than 24h and raw older than 30m.
     - Stage 3: Prune raw older than 15m, 1m rollups older than 6h, full `VACUUM`.
     - Stage 4: Critical shed: prune oldest rollups down to 1 hour, raw down to 5 minutes.
   - Busy-reader resilience: `wal_checkpoint(TRUNCATE)` catches `sqlite3.OperationalError` gracefully and defers without failing.
   - `VACUUM` executed with `isolation_level=None` outside active transactions.
   - Verified via `test_storage_budget_enforcement`.

5. **Worker Lifecycle Corruption Detection & WAL Preservation:**
   - `TelemetryHistoryWorker` checks `check_integrity()` at startup and upon database write/maintenance errors.
   - If corrupted: `quarantine_and_reset()` quarantines `telemetry.sqlite3`, `telemetry.sqlite3-wal`, and `telemetry.sqlite3-shm` together to `*.corrupt.<timestamp>`, preserving all recoverable WAL transactions.
   - Fresh store is initialized, and collection continues without dropping future telemetry or disrupting Runmux operations.
   - Verified via `test_worker_lifecycle_detects_and_recovers_corrupt_database` and `test_quarantine_preserves_recoverable_wal_data`.

6. **Web Adapter & API Endpoints (`web_adapter.py`, `web.py`):**
   - `GET /api/runs/{run_id}/telemetry/history` and `GET /api/telemetry/history`.
   - Consistent resolution labeling: `"raw"` ($\le 1$h), `"1m_rollup"` ($1\text{h} - 24\text{h}$), `"5m_rollup"` ($> 24\text{h}$).
   - Lineage traversal with restart gap markers and discrete events.
   - Preserved Phase 5B live endpoints (`/api/runs/{id}/telemetry`, `/api/telemetry`) and all Phase 5A+ frontend assets untouched.


8. **Final Schema & Aggregation Corrections:**
   - **Schema Migration Safety:** Specified explicit destination column lists on all `INSERT OR REPLACE INTO` statements (`telemetry_rollup_1m`, `telemetry_rollup_5m`, `host_telemetry_rollup_1m`, `host_telemetry_rollup_5m`, `telemetry_raw`, `host_telemetry_raw`). Dynamic `ensure_columns()` applies `ALTER TABLE ... ADD COLUMN` for `cpu_min` and `_count` columns on pre-existing databases without column ordinal misalignment. Verified via `test_schema_migration_preserves_column_order_and_values`.
   - **Partial-Null Observation-Weighted Averages:** Process and host rollups now track per-metric non-null observation counts (`cpu_count`, `rss_count`, `read_bytes_count`, `write_bytes_count`, `memory_count`, `net_read_count`, `net_write_count`). 5m rollups weight averages strictly by valid observation counts rather than total ticks, avoiding distortion when buckets contain unequal sizes and mixed missing data. Includes backwards-compatible fallback for pre-migration rollups. Verified via `test_partial_null_weighted_averages_unequal_buckets` and `test_host_partial_null_weighted_averages`.
   - **Windows File Lock Recovery Resilience:** Handled `PermissionError` / `OSError` in `quarantine_and_reset()` when active reader handles hold `telemetry.sqlite3` open on Windows. Defers quarantine safely without crashing or corrupting files, and cleanly self-heals on subsequent checks once locks release. Verified via `test_quarantine_resilience_to_open_reader_and_locked_wal` and `test_worker_graceful_degradation_when_database_locked`.

9. **Updated Test Battery:**
   - Telemetry store & worker battery: **21 / 21 tests passed**.
   - Full telemetry, history, web adapter, and web battery: **79 / 79 tests passed** in 14.07s.

7. **Test Suite Verification:**
   - Telemetry test battery: **45 / 45 tests passed** in 3.95s.
   - Web & adapter test battery: **26 / 26 tests passed** in 10.40s.
   - Total telemetry & web tests: **79 / 79 passed cleanly**.

---

### Next Action
- Update plan documentation (`HANDOFF.md`, `checklist.md`).
- Stage intended changes and verify `git status`.
- Commit and push to feature branch `codex/runmux-historical-telemetry-20261024` on `origin`.
