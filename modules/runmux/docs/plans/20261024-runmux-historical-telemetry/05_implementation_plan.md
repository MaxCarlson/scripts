# Runmux Historical Telemetry — Implementation Plan (Phase 5C)

**Document ID:** RUNMUX-5C-PLAN | **Status:** Proposed Implementation Stages | **Date:** 2026-10-24  
**Scope:** `modules/runmux/` | **Author:** Antigravity (AI Systems Architect)

---

## 1. Overview & Phased Roadmap

This plan breaks down the implementation of the approved Phase 5C architecture into **five independently testable stages**. Each stage contains verifiable acceptance criteria and can be built and reviewed without breaking existing Phase 5B live telemetry or the public Runmux CLI.

---

## 2. Stage Breakdown

### Stage 1: In-Memory Ring Buffer & Downsampling Engine
**Goal:** Implement the low-overhead circular buffer and dynamic downsampling algorithms with zero disk I/O.
- **Files Affected:**
  - `modules/runmux/src/runmux/telemetry_buffer.py` (New)
  - `modules/runmux/tests/test_telemetry_buffer.py` (New)
- **Key Tasks:**
  1. Define slotted data container `TelemetryPointSlots` for 128-byte footprint.
  2. Implement `TelemetryRingBuffer` wrapping `collections.deque(maxlen=K)`.
  3. Implement gap detection logic (inserting `is_gap: True` when $\Delta t > 3 \times \text{interval}$).
  4. Implement `bucket_downsample(points, target_count)` computing min, avg, max, and last values per bucket.
- **Verification Commands:**
  ```powershell
  python -m pytest tests/test_telemetry_buffer.py -q
  ```
- **Acceptance Criteria:**
  - Ring buffer strictly evicts oldest samples on overflow.
  - 86,400 synthetic points downsampled to 300 points in $< 5 \text{ ms}$.
  - Gaps correctly identified and marked; no NaN or null exceptions.

---

### Stage 2: Isolated SQLite Storage & Multi-Tier Rollups
**Goal:** Build the dedicated, disposable `telemetry.sqlite3` persistence layer with WAL mode and multi-tier rollup tables.
- **Files Affected:**
  - `modules/runmux/src/runmux/telemetry_store.py` (New)
  - `modules/runmux/tests/test_telemetry_store.py` (New)
- **Key Tasks:**
  1. Initialize `telemetry.sqlite3` with `PRAGMA journal_mode = WAL` and `PRAGMA synchronous = NORMAL`.
  2. Implement schema creation for `telemetry_raw`, `telemetry_rollup_1m`, `telemetry_rollup_5m`, `host_telemetry_raw`, and `telemetry_events`.
  3. Implement asynchronous batch insert API `store.insert_process_samples(batch)`.
  4. Implement rollup aggregation query generating 1-minute and 5-minute bucket rollups.
- **Verification Commands:**
  ```powershell
  python -m pytest tests/test_telemetry_store.py -q
  ```
- **Acceptance Criteria:**
  - Batch insert throughput $> 100,000 \text{ rows/second}$.
  - Primary key `(run_id, timestamp)` prevents duplicate point insertion.
  - Zero connection to `registry.sqlite3`; completely separate database handle.

---

### Stage 3: In-Process Web Collection Worker
**Goal:** Integrate the background telemetry sampling worker into the `runmux web` server lifecycle.
- **Files Affected:**
  - `modules/runmux/src/runmux/telemetry_worker.py` (New)
  - `modules/runmux/src/runmux/stats.py` (Child-PID cache additions)
  - `modules/runmux/src/runmux/web.py` (FastAPI lifespan integration)
  - `modules/runmux/tests/test_telemetry_worker.py` (New)
- **Key Tasks:**
  1. Add 5-second child-PID cache to `TelemetrySampler` to eliminate Windows toolhelp overhead on intermediate ticks.
  2. Implement `TelemetryHistoryWorker` running on an `asyncio` task or daemon thread inside `runmux web`.
  3. Sample active runs every 5.0 seconds (configurable); bypass terminal runs.
  4. Push samples to `TelemetryRingBuffer` and queue for batched `TelemetryStore` flushing.
  5. Hook worker startup and clean shutdown into FastAPI `lifespan` context.
- **Verification Commands:**
  ```powershell
  python -m pytest tests/test_telemetry_worker.py -q
  ```
- **Acceptance Criteria:**
  - Background loop terminates cleanly within 500 ms on server shutdown.
  - Completed runs evict their active samplers; zero ghost polling.
  - Zero blocking of the FastAPI event loop during sampling ticks.

---

### Stage 4: Authenticated REST Query API & Lineage
**Goal:** Expose bounded, authenticated REST endpoints for process and host telemetry history.
- **Files Affected:**
  - `modules/runmux/src/runmux/web_adapter.py` (`HistoricalTelemetryReader`)
  - `modules/runmux/src/runmux/web.py` (Route definitions)
  - `modules/runmux/tests/test_telemetry_history_api.py` (New)
- **Key Tasks:**
  1. Implement `GET /api/runs/{run_id}/telemetry/history` with `since`, `until`, `max_points`.
  2. Implement `GET /api/telemetry/history` for host-wide series.
  3. Integrate ring-buffer fast-path for requests within the last 30 minutes.
  4. Support optional `include_lineage=true` parameter traversing `restart_of` links.
- **Verification Commands:**
  ```powershell
  python -m pytest tests/test_telemetry_history_api.py -q
  ```
- **Acceptance Criteria:**
  - Returns HTTP 401 for unauthenticated requests.
  - Query response time $< 5 \text{ ms}$ for 1-hour window; $< 20 \text{ ms}$ for 7-day window.
  - Hard response cap enforced at 1,000 points; default 300 points.
  - Gaps explicitly labeled with reason; no fabricated zero values.

---

### Stage 5: Pruning Engine, Storage Caps & Corruption Recovery
**Goal:** Implement automatic rolling window retention cleanup and disaster recovery safeguards.
- **Files Affected:**
  - `modules/runmux/src/runmux/telemetry_pruner.py` (New)
  - `modules/runmux/tests/test_telemetry_pruning.py` (New)
- **Key Tasks:**
  1. Implement rolling retention cleanup:
     - Purge `telemetry_raw` older than 1 hour.
     - Purge `telemetry_rollup_1m` older than 24 hours.
     - Purge `telemetry_rollup_5m` older than 7 days.
  2. Implement hard database size cap enforcement (e.g. 50 MB default):
     - If file size exceeds cap, incrementally drop oldest rollups.
  3. Schedule pruning job every 15 minutes during WAL checkpointing.
  4. Add corrupt DB recovery: If `telemetry.sqlite3` fails `PRAGMA integrity_check`, quarantine file to `.corrupt` and reinitialize empty database with zero impact on running processes.
- **Verification Commands:**
  ```powershell
  python -m pytest tests/test_telemetry_pruning.py -q
  ```
- **Acceptance Criteria:**
  - Database file strictly respects configured size cap under simulated high-volume load.
  - Corrupted DB test proves Runmux survives and continues monitoring without crashing.
