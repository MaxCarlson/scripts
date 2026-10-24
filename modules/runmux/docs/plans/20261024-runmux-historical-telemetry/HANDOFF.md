# Handoff — Runmux Historical Telemetry Architecture (Phase 5C)

**Branch:** `codex/runmux-historical-telemetry-20261024`  
**Worktree:** `.worktrees/runmux-historical-telemetry`  
**Base Commit:** `6fa307f3bd84761f6fe21f3700dceb9889fe090b` (`origin/main`)  
**Assignment:** Phase 5C Research, Architecture, Benchmarks, and Implementation Planning.

---

## 1. Scope & Execution Rules Followed

1. **Research & Planning Only:** No production persistence or background collection code was modified or activated. Existing Phase 5B live telemetry and public APIs are untouched.
2. **Strict Isolation:** All work was conducted in `.worktrees/runmux-historical-telemetry`. User live state (`%LOCALAPPDATA%\runmux`) was untouched.
3. **No Frontend Edits:** `web_static/assets/dashboard.js`, CSS, and HTML were untouched to avoid collisions with parallel Phase 5A+ work.
4. **Empirical Grounding:** Quantitative metrics are backed by native Windows 11 benchmarks using Python 3.12 (`modules/runmux/benchmarks/benchmark_telemetry_history.py`).

---

## 2. Key Architecture Recommendations

1. **Recommended Model:** **Hybrid In-Memory + Tiered SQLite**.
   - 30-minute circular buffer in memory (128 bytes/sample) for instantaneous live UI chart queries (< 0.05 ms).
   - Dedicated `telemetry.sqlite3` database in WAL mode with multi-tier pre-aggregated rollups (1h raw, 24h 1-minute, 7d 5-minute), achieving a **> 95% storage reduction** (< 25 MB for 50 active runs over 7 days).
2. **Database Separation:** Place historical telemetry in `%LOCALAPPDATA%\runmux\telemetry.sqlite3`, completely independent of `registry.sqlite3`. This preserves `ReadOnlyRunmux` safety on the core registry and guarantees zero write-lock contention.
3. **Sampling Engine:** Reuses Phase 5B `TelemetrySampler` with an added 5-second child-PID cache. This eliminates Windows toolhelp snapshot overhead on intermediate ticks, cutting sampling CPU overhead by **> 80%**.
4. **Collection Lifecycle:** In-process worker inside `runmux web`, running only while the web UI server is active. No background daemon or permanent service installed.
5. **Data Correctness:** Strict `null` vs `0.0` semantics. Missing measurements are never zeroed. PID reuse is blocked by two-sided 5.0s tolerance. Process pauses, stops, and crashes are recorded as explicit gap events.

---

## 3. Resume / Implementation Order (Once Approved)

When the user approves the decisions in `06_approval_decisions.md`:
1. Execute **Stage 1**: In-memory ring buffer & downsampler (`telemetry_buffer.py`).
2. Execute **Stage 2**: Dedicated SQLite storage layer (`telemetry_store.py`).
3. Execute **Stage 3**: Web background collection worker (`telemetry_worker.py`).
4. Execute **Stage 4**: Authenticated REST API endpoints (`/api/runs/{id}/telemetry/history`).
5. Execute **Stage 5**: Pruning engine and size cap enforcement (`telemetry_pruner.py`).
