# Runmux Historical Telemetry — Decisions Requiring Approval (Phase 5C)

**Document ID:** RUNMUX-5C-APPROVAL | **Status:** Action Items for User Review | **Date:** 2026-10-24  
**Scope:** `modules/runmux/` | **Author:** Antigravity (AI Systems Architect)

---

## 1. Overview & Accepted Baseline Decisions

The following architectural foundations have been **accepted in principle**:
- **Collection Lifecycle:** Web-server-scoped background sampling (active strictly while `runmux web` is running).
- **Storage Architecture:** Hybrid recent-memory buffering with a separate SQLite-backed historical database.
- **Cadence Default:** Uniform 5.0-second background sampling interval across all active runs; no focused-view burst initially.
- **Retention Schedule:** Multi-tier rollups: 1 hour raw, 24 hours 1-minute rollup, 7 days 5-minute rollup.
- **Path Resolution:** Separate `telemetry.sqlite3` database resolved within the active Runmux state directory (honoring `RUNMUX_HOME` and `--state-dir`).
- **Isolation & Provenance:** Strict host-level versus process-tree metric isolation; explicit lineage traversal on restarts.

---

## 2. Refined Decision Items for Final Approval

### Decision 1: Child-PID Discovery Cache TTL on Windows

On native Windows, tree traversal (`children()`) and thread enumeration take **33.3 ms**, whereas reading direct counters takes **0.007 ms**.
With a 5.0-second sampling cadence:
- **Option A (30-second TTL - Recommended):** 6 hits per miss $\rightarrow$ **85.7% cache hit rate**. Average sampling latency: **4.76 ms / process**. Total CPU cost for 20 active processes is **~1.9% of one core**. If a child terminates prematurely, a `NoSuchProcess` exception during counter inspection triggers an immediate cache refresh on the next tick.
- **Option B (15-second TTL):** 3 hits per miss $\rightarrow$ **75.0% cache hit rate**. Average sampling latency: **8.33 ms / process**. Total CPU cost for 20 active processes is **~3.3% of one core**.
- **Option C (No caching / 5s TTL):** **0.0% cache hit rate** (100% full tree refreshes). Average sampling latency: **33.3 ms / process**. Total CPU cost for 20 active processes is **~13.3% of one core**.

*Do you approve adopting a **30-second child-PID cache TTL** as the default on Windows?*

---

### Decision 2: Query Routing Simplification (Write-Through Hybrid vs. Pure SQLite-First)

- **Option A (Write-Through Tiered Hybrid - Recommended):**
  - Worker flushes samples to SQLite in 5-second batches AND keeps 720 points (1 hour) in an in-memory ring buffer (`92.3 KB/run`).
  - Queries for $\le 1\text{ hour}$ read directly from memory in $< 0.05\text{ ms}$.
  - Queries for $> 1\text{ hour}$ read directly from SQLite rollups in $< 1.2\text{ ms}$.
  - **Zero complex boundary stitching or deduplication:** The query router picks exactly one source based on the requested time range.
- **Option B (Pure SQLite-First):**
  - Eliminates the in-memory ring buffer entirely.
  - All queries read directly from SQLite (`0.98 ms` for 1 hour).
  - Slightly simpler code (~100 fewer LOC), but incurs continuous SQLite read queries and page-cache checks during high-frequency browser dashboard polling.

*Do you approve the **Write-Through Tiered Hybrid** (Option A) to provide microsecond live chart response without boundary-merging complexity?*

---

### Decision 3: Storage Budget & 15-Minute Maintenance Schedule

- **Hard Budget Limit:** **50 MB** total disk space (`telemetry.sqlite3` + `telemetry.sqlite3-wal`).
- **Maintenance Cadence:** Every **15 minutes**:
  1. Generate 1-minute and 5-minute rollups.
  2. Prune raw samples $> 1\text{h}$, 1m rollups $> 24\text{h}$, 5m rollups $> 7\text{d}$.
  3. Execute `PRAGMA wal_checkpoint(TRUNCATE)` to reset the WAL log to 0 bytes.
  4. Execute `PRAGMA incremental_vacuum(500)` if freelist pages exceed 500 pages (> 2 MB).
  5. If total file size exceeds 45 MB (90% threshold), prune oldest 5-minute rollups to guarantee the 50 MB budget is never violated.

*Do you approve this 15-minute maintenance schedule and 50 MB enforceable budget safeguard?*

---

### Decision 4: Lineage Traversal Default Behavior

When a run is restarted via `POST /api/runs/{run_id}/restart`, Runmux generates a new Run ID with `restart_of = old_run_id`.
- By default, `GET /api/runs/{run_id}/telemetry/history` queries strictly the specified `run_id`.
- When `include_lineage=true` is passed, the endpoint recursively resolves parent runs, returning them with an explicit `event: "restart"` marker and an `is_gap: true` point between process lifetimes.

*Do you approve keeping `include_lineage=false` as the default, requiring explicit opt-in to view parent runs?*
