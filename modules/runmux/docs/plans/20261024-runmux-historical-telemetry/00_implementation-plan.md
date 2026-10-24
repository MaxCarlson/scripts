# Implementation Plan: Runmux Historical Telemetry Architecture (Phase 5C)

**Plan Folder:** `modules/runmux/docs/plans/20261024-runmux-historical-telemetry/`  
**Branch:** `codex/runmux-historical-telemetry-20261024`  
**Base Commit:** `6fa307f3bd84761f6fe21f3700dceb9889fe090b`  
**Status:** Architecture Proposal Finalized (Awaiting Final User Approvals)  
**Date:** 2026-10-24

---

## 1. Executive Summary

This package delivers the finalized architectural specification, empirical benchmarks, and implementation roadmap for **Phase 5C: Historical Telemetry Architecture** in Runmux.

In accordance with user instructions:
- **Research, architecture, and planning only:** No production collection or persistence code has been enabled; Phase 5B live telemetry and public APIs remain untouched.
- **Isolated environment:** Built and verified in `.worktrees/runmux-historical-telemetry` using native Windows 11 tooling.
- **Zero live state impact:** Disposable test databases and synthetic benchmarks only; live `%LOCALAPPDATA%\runmux` registry was not accessed.

### Document Index

1. [`01_architecture_specification.md`](01_architecture_specification.md): State-directory-local path resolution, write-through hybrid data flow, schema DDL, WAL settings, and 30s child-PID caching.
2. [`02_alternatives_analysis.md`](02_alternatives_analysis.md): Reevaluation of in-memory vs. SQLite-first coordination complexity, comparing pure memory, pure SQLite, dual-source merging, and write-through tiering.
3. [`03_resource_budget_and_benchmarks.md`](03_resource_budget_and_benchmarks.md): Corrected Windows 11 empirical benchmarks, exact cache hit-rate formulas, 140.7 B/row disk sizing, and enforceable 50 MB storage budget.
4. [`04_api_proposal.md`](04_api_proposal.md): Bounded authenticated REST contracts with genuine Runmux Run IDs (`YYYYMMDD-HHMMSS-xxxxxx`), ISO 8601 UTC timestamps, monotonic interval metadata, and lineage traversal.
5. [`05_implementation_plan.md`](05_implementation_plan.md): Five independently testable implementation stages with exact verification commands and acceptance criteria.
6. [`06_approval_decisions.md`](06_approval_decisions.md): Refined decision items submitted for final user approval prior to implementation.
7. [`checklist.md`](checklist.md): Comprehensive progress and feature tracking ledger.
8. [`STATUS.md`](STATUS.md): Current operational status.
9. [`HANDOFF.md`](HANDOFF.md): Worktree and session handoff instructions.

---

## 2. Reconciled Architectural Decisions

- **Architecture:** Write-Through Tiered Hybrid.
  - 1-hour circular ring buffer in RAM (`720 points`, `92.3 KB/run`) for microsecond active UI queries ($< 0.05\text{ ms}$).
  - Separate `telemetry.sqlite3` database in WAL mode with multi-tier pre-aggregated rollups (1h raw, 24h 1-minute, 7d 5-minute), slashing disk space by **> 95%** (< 25 MB for 50 active runs over 7 days).
  - No complex boundary merging: queries $\le 1\text{h}$ read from RAM; queries $> 1\text{h}$ read from SQLite rollups.
- **Sampling Engine:** Reuses Phase 5B `TelemetrySampler` with a 30-second child-PID cache (85.7% hit rate at 5s cadence), cutting CPU overhead by **> 85%** on native Windows.
- **Storage Budget:** Hard cap of **50 MB** enforced via 15-minute maintenance cycles (`wal_checkpoint(TRUNCATE)`, `incremental_vacuum`, and emergency rollup pruning).
- **Collection Lifecycle:** In-process background worker inside `runmux web`, active only while the web UI server runs. No background daemon or permanent service installed.
- **Data Correctness:** Strict `null` vs `0.0` semantics. Missing measurements are never zeroed. PID reuse is protected by two-sided 5.0s creation tolerance. Lifecycle events (`pause`, `resume`, `exit`) explicitly mark timeline gaps.
