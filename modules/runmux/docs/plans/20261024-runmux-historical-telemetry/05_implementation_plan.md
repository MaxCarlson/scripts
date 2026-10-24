# Runmux Historical Telemetry — Implementation Plan (Phase 5C)

**Document ID:** RUNMUX-5C-PLAN | **Status:** Proposed Implementation Stages | **Date:** 2026-10-24  
**Scope:** `modules/runmux/` | **Author:** Antigravity (AI Systems Architect)

---

## 1. Overview & Phased Roadmap

This plan breaks down the implementation of the approved Phase 5C architecture into **five independently testable stages**. Each stage contains verifiable acceptance criteria, requires no frontend edits, and preserves existing Phase 5B live telemetry and the Runmux CLI unchanged.

---

## 2. Stage Breakdown

### Stage 1: In-Memory Ring Buffer & Downsampling Engine
**Goal:** Implement the slotted circular buffer and high-throughput downsampling engine.
- **Files Affected:**
  - `modules/runmux/src/runmux/telemetry_buffer.py` (New)
  - `modules/runmux/tests/test_telemetry_buffer.py` (New)
- **Key Tasks:**
  1. Define slotted data container `TelemetryPointSlots` (`128.2 B/sample`).
  2. Implement `TelemetryRingBuffer` wrapping `collections.deque(maxlen=720)` (1 full hour at 5s interval).
  3. Implement gap detection logic (inserting `is_gap: True` when $\Delta t > 15.0\text{s}$).
  4. Implement `bucket_downsample(points, target_count)` computing min, avg, max, and last values per bucket.
- **Verification Commands:**
  ```powershell
  python -m pytest tests/test_telemetry_buffer.py -q
  ```
- **Acceptance Criteria:**
  - 86,400 synthetic points downsampled to 300 points in $< 5 \text{ ms}$.
  - Slotted memory footprint $\le 130 \text{ B/sample}$.
  - Gaps correctly identified and marked; no NaN or null exceptions.

---

### Stage 2: State-Directory-Local SQLite Storage & Rollups
**Goal:** Build the dedicated, disposable `telemetry.sqlite3` persistence layer with WAL mode and multi-tier rollup tables.
- **Files Affected:**
  - `modules/runmux/src/runmux/telemetry_store.py` (New)
  - `modules/runmux/tests/test_telemetry_store.py` (New)
- **Key Tasks:**
  1. Resolve database path via `ensure_state_tree(state_dir or get_state_dir()) / "telemetry.sqlite3"`, honoring `RUNMUX_HOME` and `--state-dir`.
  2. Initialize `telemetry.sqlite3` with `PRAGMA journal_mode = WAL`, `PRAGMA synchronous = NORMAL`, and `PRAGMA auto_vacuum = INCREMENTAL`.
  3. Implement schema creation for `telemetry_raw`, `telemetry_rollup_1m`, `telemetry_rollup_5m`, `host_telemetry_raw`, and `telemetry_events`.
  4. Implement batch insert API `store.insert_process_samples(batch)`.
  5. Implement SQL rollup queries for 1-minute and 5-minute bucket rollups.
- **Verification Commands:**
  ```powershell
  python -m pytest tests/test_telemetry_store.py -q
  ```
- **Acceptance Criteria:**
  - Batch insert throughput $> 300,000 \text{ rows/second}$.
  - Primary key `(run_id, timestamp)` prevents duplicate point insertion.
  - Zero connection or lock contention with `registry.sqlite3`.

---

### Stage 3: In-Process Web Collection Worker
**Goal:** Integrate the background telemetry sampling worker into the `runmux web` server lifecycle.
- **Files Affected:**
  - `modules/runmux/src/runmux/telemetry_worker.py` (New)
  - `modules/runmux/src/runmux/stats.py` (Child-PID cache additions)
  - `modules/runmux/src/runmux/web.py` (FastAPI lifespan integration)
  - `modules/runmux/tests/test_telemetry_worker.py` (New)
- **Key Tasks:**
  1. Add 30-second child-PID cache to `TelemetrySampler` (85.7% hit rate at 5s interval, cutting CPU overhead by > 80%).
  2. Implement `TelemetryHistoryWorker` running as an asyncio background task inside `runmux web`.
  3. Sample active runs every 5.0 seconds (no focused burst initially); bypass terminal runs.
  4. Write-through: append to `TelemetryRingBuffer` and commit to `TelemetryStore` in 5-second batches.
  5. Hook worker startup and clean shutdown into FastAPI `lifespan` context.
- **Verification Commands:**
  ```powershell
  python -m pytest tests/test_telemetry_worker.py -q
  ```
- **Acceptance Criteria:**
  - Worker starts and stops cleanly with `runmux web` (stops in $< 500\text{ ms}$).
  - Completed runs evict their active samplers after 10 minutes; zero ghost polling.
  - Zero blocking of the FastAPI event loop during sampling ticks.

---

### Stage 4: Authenticated REST Query API & Lineage
**Goal:** Expose bounded, authenticated REST endpoints for process and host telemetry history.
- **Files Affected:**
  - `modules/runmux/src/runmux/web_adapter.py` (`HistoricalTelemetryReader`)
  - `modules/runmux/src/runmux/web.py` (Route definitions)
  - `modules/runmux/tests/test_telemetry_history_api.py` (New)
- **Key Tasks:**
  1. Implement `GET /api/runs/{run_id}/telemetry/history` with `since`, `until`, `max_points`, `include_lineage`.
  2. Implement `GET /api/telemetry/history` for host-wide series.
  3. Integrate ring-buffer fast-path for queries within the last 1 hour ($< 0.05\text{ ms}$).
  4. Query SQLite rollups for queries $> 1\text{ hour}$ ($< 1.2\text{ ms}$).
  5. Validate genuine Runmux Run ID format (`YYYYMMDD-HHMMSS-xxxxxx`).
- **Verification Commands:**
  ```powershell
  python -m pytest tests/test_telemetry_history_api.py -q
  ```
- **Acceptance Criteria:**
  - Returns HTTP 401 for unauthenticated requests.
  - Query response time $< 1\text{ ms}$ for 1-hour window; $< 5\text{ ms}$ for 7-day window.
  - Response point count hard-capped at 1,000 points; default 300 points.
  - Gaps explicitly labeled with reason; no fabricated zero values.

---

### Stage 5: Enforceable Storage Budget & Maintenance Engine
**Goal:** Implement automatic rolling window retention cleanup, WAL truncation, and 50 MB budget safeguards.
- **Files Affected:**
  - `modules/runmux/src/runmux/telemetry_pruner.py` (New)
  - `modules/runmux/tests/test_telemetry_pruning.py` (New)
- **Key Tasks:**
  1. Implement 15-minute maintenance task:
     - Generate 1-minute and 5-minute rollups.
     - Prune `telemetry_raw` older than 1 hour.
     - Prune `telemetry_rollup_1m` older than 24 hours.
     - Prune `telemetry_rollup_5m` older than 7 days.
  2. Execute `PRAGMA wal_checkpoint(TRUNCATE)` every 15 minutes to reset WAL file size.
  3. Execute `PRAGMA incremental_vacuum(500)` when freelist exceeds 500 pages.
  4. Enforce 50 MB hard cap: if `db_size + wal_size > 45 MB`, prune oldest rollups.
  5. Add corrupt DB recovery: If `telemetry.sqlite3` fails `PRAGMA integrity_check`, quarantine file to `.corrupt` and reinitialize empty database with zero impact on running processes.
- **Verification Commands:**
  ```powershell
  python -m pytest tests/test_telemetry_pruning.py -q
  ```
- **Acceptance Criteria:**
  - Database file strictly respects 50 MB cap under simulated multi-process volume.
  - Corrupted DB test proves Runmux survives and continues monitoring without crashing.
