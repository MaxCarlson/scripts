# Handoff — Runmux Historical Telemetry Architecture (Phase 5C)

**Branch:** `codex/runmux-historical-telemetry-20261024`  
**Worktree:** `.worktrees/runmux-historical-telemetry`  
**Base Commit:** `6fa307f3bd84761f6fe21f3700dceb9889fe090b` (`origin/main`)  
**Assignment:** Phase 5C Architecture Proposal Finalization & Corrected Benchmarks.

---

## 1. Scope & Execution Rules Followed

1. **Design Finalization Only:** No production persistence or background collection code was modified or activated. Existing Phase 5B live telemetry and public APIs are untouched.
2. **Strict Isolation:** All work was conducted in `.worktrees/runmux-historical-telemetry`. User live state (`%LOCALAPPDATA%\runmux`) was untouched.
3. **No Frontend Edits:** `web_static/assets/dashboard.js`, CSS, and HTML were untouched to avoid collisions with parallel Phase 5A+ work.
4. **Empirical Grounding:** Corrected metrics are backed by native Windows 11 benchmarks using Python 3.12 (`modules/runmux/benchmarks/benchmark_telemetry_history.py`) with genuine 22-char Run IDs and full schema.

---

## 2. Reconciled Architectural Blueprint

1. **Recommended Model:** **Write-Through Tiered Hybrid**.
   - 1-hour circular buffer in RAM (720 points, 92.3 KB/run) for microsecond live UI chart queries (< 0.05 ms).
   - Dedicated `telemetry.sqlite3` database in WAL mode with multi-tier pre-aggregated rollups (1h raw, 24h 1-minute, 7d 5-minute), achieving a **> 95% storage reduction** (< 25 MB for 50 active runs over 7 days).
   - Clean query routing: $\le 1\text{h}$ reads RAM; $> 1\text{h}$ reads SQLite rollups. Zero boundary stitching.
2. **Database Location:** `%LOCALAPPDATA%\runmux\telemetry.sqlite3` (or `$RUNMUX_HOME/telemetry.sqlite3`), completely independent of `registry.sqlite3`. Preserves `ReadOnlyRunmux` read-only guarantee.
3. **Sampling Engine:** Reuses Phase 5B `TelemetrySampler` with a 30-second child-PID cache (85.7% hit rate at 5s cadence), reducing sampling CPU overhead by **> 85%** on native Windows.
4. **Collection Lifecycle:** In-process worker inside `runmux web`, running only while the web UI server is active.
5. **Enforceable Storage Budget:** 50 MB hard budget enforced via 15-minute maintenance cycles (`wal_checkpoint(TRUNCATE)`, `incremental_vacuum`, and emergency rollup pruning).

---

## 3. Resume / Implementation Order (Once Approved)

When the user approves the decisions in `06_approval_decisions.md`:
1. Execute **Stage 1**: In-memory ring buffer & downsampler (`telemetry_buffer.py`).
2. Execute **Stage 2**: State-directory-local SQLite storage layer (`telemetry_store.py`).
3. Execute **Stage 3**: Web background collection worker (`telemetry_worker.py`).
4. Execute **Stage 4**: Authenticated REST API endpoints (`/api/runs/{id}/telemetry/history`).
5. Execute **Stage 5**: Pruning engine, WAL maintenance, and size cap enforcement (`telemetry_pruner.py`).
