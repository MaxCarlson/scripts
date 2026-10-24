# Checklist — Runmux Phase 5C Historical Telemetry Architecture

**Plan Folder:** `modules/runmux/docs/plans/20261024-runmux-historical-telemetry/`  
**Branch:** `codex/runmux-historical-telemetry-20261024`  
**Base Commit:** `6fa307f3bd84761f6fe21f3700dceb9889fe090b`  
**Status:** Architecture Proposal Finalized (Awaiting Final User Approvals)

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
- [x] Prove 5s sampling with 5s TTL yields 0.0% hit rate (33.3 ms/proc)
- [x] Prove 5s sampling with 30s TTL yields 85.7% hit rate (4.76 ms/proc)
- [x] Measure actual on-disk row footprint: 140.7 bytes / row
- [x] Model CPU overhead across 10, 100, and 1,000 registered processes
- [x] Model RAM consumption under multi-process loads (reconciled at 720 points = 92.3 KB/run)
- [x] Model steady-state database size (1h raw + 24h 1m + 7d 5m = 395.1 KB/run)
- [x] Document enforceable 50 MB storage budget and maintenance cycles in `03_resource_budget_and_benchmarks.md`

---

## 4. Historical Data Correctness & Semantics

- [x] Guarantee immutable Run ID partitioning vs recycled numeric IDs
- [x] Enforce PID reuse protection via two-sided 5.0s creation tolerance (`PID_CREATION_TOLERANCE_SECONDS`)
- [x] Formalize `null` vs `0.0` semantics (never fabricate zero for missing metrics)
- [x] Define gap handling for process exits, pauses, and missing intervals
- [x] Document platform support boundaries (Windows, Linux, macOS I/O counters, NVIDIA GPUs)
- [x] Define lineage traversal (`restart_of`, `duplicate_of`) with explicit gap markers
- [x] Enforce strict scope isolation (process-tree vs host-wide metrics)
- [x] Verify CPU percentage and disk I/O rate semantics ($r = \Delta v / \Delta t$)

---

## 5. Collection Lifecycle & Storage Retention

- [x] Compare collection policies (On-demand, Web-server-scoped, Supervisor-driven, Daemon)
- [x] Formulate recommended default policy (Web-server-scoped, 5s background cadence, no focused burst initially)
- [x] Design 3-tier retention schedule (1h raw, 24h 1m rollup, 7d 5m rollup)
- [x] Design hard storage cap (50 MB default) and 15-minute maintenance cycle (WAL truncate + incremental vacuum)
- [x] Document collection lifecycle and retention in `01_architecture_specification.md`

---

## 6. API Proposal

- [x] Update REST endpoint `GET /api/runs/{run_id}/telemetry/history`
- [x] Update REST endpoint `GET /api/telemetry/history`
- [x] Correct examples to use genuine 22-character Run IDs (`20261024-080000-f3a1b2`)
- [x] Use consistent ISO 8601 UTC timestamps (`2026-10-24T08:00:00.000000Z`)
- [x] Include distinct monotonic elapsed-time measurements (`sample_interval_seconds: 5.002134`)
- [x] Define bounds: default 300 points, hard cap 1,000 points
- [x] Document API proposal in `04_api_proposal.md`

---

## 7. Implementation Roadmap & Staging

- [x] Stage 1: In-Memory Ring Buffer & Downsampling Engine
- [x] Stage 2: State-Directory-Local SQLite Storage & Rollups
- [x] Stage 3: In-Process Web Collection Worker
- [x] Stage 4: Authenticated REST Query API & Lineage
- [x] Stage 5: Enforceable Storage Budget & Maintenance Engine
- [x] Document implementation stages in `05_implementation_plan.md`

---

## 8. Approvals & Completion Gate

- [x] Update decision sheet with accepted directions and remaining items in `06_approval_decisions.md`
- [x] Maintain existing live telemetry backend and public API unchanged
- [x] Prepare comprehensive finalization completion report
- [x] Commit and push feature branch to remote (without merging)
