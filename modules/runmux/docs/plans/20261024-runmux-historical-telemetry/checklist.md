# Checklist — Runmux Phase 5C Historical Telemetry Architecture

**Plan Folder:** `modules/runmux/docs/plans/20261024-runmux-historical-telemetry/`  
**Branch:** `codex/runmux-historical-telemetry-20261024`  
**Base Commit:** `6fa307f3bd84761f6fe21f3700dceb9889fe090b`  
**Status:** Architecture Proposal & Planning Complete

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
- [x] Audit supervisor architecture and IPC handlers in `modules/runmux/src/runmux/supervisor.py`
- [x] Audit web adapter and endpoints in `modules/runmux/src/runmux/web_adapter.py` and `web.py`
- [x] Evaluate Architecture A: Pure In-Memory ring buffers
- [x] Evaluate Architecture B: Pure Persistent SQLite time-series
- [x] Evaluate Architecture C: Hybrid In-Memory + Tiered SQLite rollups
- [x] Document alternatives analysis in `02_alternatives_analysis.md`

---

## 3. Quantitative Performance Evaluation & Benchmarking

- [x] Develop synthetic benchmark harness (`modules/runmux/benchmarks/benchmark_telemetry_history.py`)
- [x] Measure native Windows `psutil` sampling overhead per metric and tree traversal
- [x] Measure memory footprint of slotted dataclasses (128 B), tuples (136 B), and dicts (304 B)
- [x] Measure SQLite WAL insert throughput (> 700k rows/s) and on-disk row footprint (~52 B/row)
- [x] Measure downsampling throughput (86,400 raw points to 300 points in 1.51 ms)
- [x] Model CPU overhead across 10, 100, and 1,000 registered processes at 1s, 2s, 5s, 10s intervals
- [x] Model RAM consumption under multi-process loads
- [x] Model database size and daily write volume across retention horizons (1h, 24h, 7d)
- [x] Quantify downsampling storage savings (> 95% reduction via multi-tier rollups)
- [x] Model behavior with many disconnected and completed runs (zero-polling bypass)
- [x] Document resource budget and benchmark evidence in `03_resource_budget_and_benchmarks.md`

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
- [x] Formulate recommended default policy (Web-server-scoped with adaptive child-PID cache)
- [x] Design 3-tier retention schedule (1h raw, 24h 1m rollup, 7d 5m rollup)
- [x] Design hard storage cap (50 MB default) and automatic rolling purge during WAL checkpoints
- [x] Document collection lifecycle and retention in `01_architecture_specification.md`

---

## 6. API Proposal

- [x] Design authenticated REST endpoint `GET /api/runs/{run_id}/telemetry/history`
- [x] Design authenticated REST endpoint `GET /api/telemetry/history`
- [x] Specify request parameters (`since`, `until`, `max_points`, `fields`, `include_lineage`)
- [x] Define JSON response schemas with provenance metadata and explicit gap markers
- [x] Define bounds: default 300 points, hard cap 1,000 points
- [x] Document API proposal in `04_api_proposal.md`

---

## 7. Implementation Roadmap & Staging

- [x] Stage 1: In-Memory Ring Buffer & Downsampling Engine
- [x] Stage 2: Isolated SQLite Storage & Multi-Tier Rollups
- [x] Stage 3: In-Process Web Collection Worker
- [x] Stage 4: Authenticated REST Query API & Lineage
- [x] Stage 5: Pruning Engine, Storage Caps & Corruption Recovery
- [x] Document implementation stages in `05_implementation_plan.md`

---

## 8. Approvals & Completion Gate

- [x] Formulate explicit user decision questions in `06_approval_decisions.md`
- [x] Maintain existing live telemetry backend and public API unchanged
- [x] Prepare comprehensive completion report
- [x] Commit and push feature branch to remote (without merging)
