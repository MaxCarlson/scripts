# Implementation Plan: Runmux Historical Telemetry Architecture (Phase 5C)

**Plan Folder:** `modules/runmux/docs/plans/20261024-runmux-historical-telemetry/`  
**Branch:** `codex/runmux-historical-telemetry-20261024`  
**Base Commit:** `6fa307f3bd84761f6fe21f3700dceb9889fe090b`  
**Status:** Architecture Proposal & Planning Complete (Awaiting User Approval)  
**Date:** 2026-10-24

---

## 1. Executive Summary

This package delivers the complete architectural research, performance evaluation, storage design, and implementation roadmap for **Phase 5C: Historical Telemetry Architecture** in Runmux.

In accordance with user instructions, **this assignment is research, architecture, and planning only.** No production collection or persistence code has been activated; the existing Phase 5B live telemetry backend and public API remain untouched and fully passing.

### Document Index

1. [`01_architecture_specification.md`](01_architecture_specification.md): Components, data flow, schema, sampling algorithm, child-PID caching, and storage approach.
2. [`02_alternatives_analysis.md`](02_alternatives_analysis.md): Comparative evaluation of in-memory only, flat SQLite, and the recommended hybrid architecture across 8 operational criteria.
3. [`03_resource_budget_and_benchmarks.md`](03_resource_budget_and_benchmarks.md): Quantitative models and Windows 11 benchmark results for 10, 100, and 1,000 registered runs across multiple sampling intervals and retention horizons.
4. [`04_api_proposal.md`](04_api_proposal.md): Authenticated REST API contracts (`/api/runs/{id}/telemetry/history` and `/api/telemetry/history`), bounded responses, downsampling parameters, and lineage support.
5. [`05_implementation_plan.md`](05_implementation_plan.md): Five independently testable implementation stages with exact verification commands and acceptance criteria.
6. [`06_approval_decisions.md`](06_approval_decisions.md): Six explicit policy and architecture decisions submitted for user approval prior to implementation.
7. [`checklist.md`](checklist.md): Comprehensive progress and feature tracking ledger.
8. [`STATUS.md`](STATUS.md): Current operational status.
9. [`HANDOFF.md`](HANDOFF.md): Worktree and session handoff instructions.

---

## 2. Core Recommendations Summary

- **Architecture:** Hybrid In-Memory + Tiered SQLite.
  - In-memory circular buffer (30m high-resolution, 128 bytes/sample) for instantaneous active UI queries (< 0.05 ms).
  - Dedicated `telemetry.sqlite3` database in WAL mode with multi-tier pre-aggregated rollups (1h raw, 24h 1-minute, 7d 5-minute), slashing disk space by **> 95%** (< 25 MB for 50 runs over 7 days).
- **Sampling Engine:** Reuses Phase 5B `TelemetrySampler` with an added 5-second child-PID cache to eliminate Windows `CreateToolhelp32Snapshot` latency on intermediate ticks, cutting sampling CPU overhead by **> 80%**.
- **Collection Lifecycle:** In-process background worker inside `runmux web`, active only while the web UI server runs. No background daemon or permanent service installed.
- **Data Correctness:** Strict `null` vs `0.0` semantics. Missing measurements or failed metrics are never zeroed. PID reuse protected by two-sided 5.0s creation tolerance. Lifecycle events (`pause`, `resume`, `exit`) explicitly demarcate timeline gaps.
