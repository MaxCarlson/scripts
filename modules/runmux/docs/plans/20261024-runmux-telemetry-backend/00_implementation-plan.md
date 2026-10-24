# Implementation Plan — Runmux Live Resource Telemetry Backend (Phase 5B)

**Feature Branch:** `codex/runmux-telemetry-backend-20261024`  
**Base:** `origin/main` (commit `97515f09`)  
**Scope:** Backend-only subset of `PHASE_05B_LIVE_TELEMETRY.md`.  
**Owner:** Telemetry Backend Agent  

---

## 1. Objectives & Boundaries

### Objectives
1. Perform a rigorous correctness audit and remediation of `runmux/stats.py` and `modules/resource_metrics/`.
2. Fix the known network attribution caveat: eliminate false attribution of host-wide network throughput to per-process records.
3. Replace blocking sleep-based sampling in HTTP routes with a non-blocking monotonic delta sampler (`TelemetrySampler`).
4. Ensure verified run identity binding: detect PID reuse, process exit, terminated/lost runs, and permission denial; report explicit `unavailable` states rather than false zero values.
5. Clarify CPU multi-core semantics (raw vs normalized) and RSS/IO units.
6. Provide a bounded, authenticated read-only API adapter (`GET /api/runs/{run_id}/telemetry` and `GET /api/telemetry`) in `runmux.web` / `web_adapter.py`.
7. Deliver comprehensive tests using disposable process state, a telemetry provenance table, and latency documentation.

### Strict Boundaries & Constraints
- Work exclusively in worktree `.worktrees/runmux-telemetry-backend`.
- Do NOT modify any file touched by the Phase 2 agent (`web_static/assets/dashboard.js`, `dashboard_test.js`, or Phase 2 docs).
- Do NOT modify Runmux Web UI HTML/CSS/JavaScript, WebSocket handlers, terminal attachments, or supervisor input-lock behavior.
- Do NOT implement dashboards, charts, or telemetry history.
- Use disposable process state and test resources. Never touch the real Runmux registry or original main checkout.
- Do NOT merge. Commit and push the branch when complete.

---

## 2. Architecture & Design

### Telemetry Sampler (`runmux.stats.TelemetrySampler`)
- Stores snapshot tuples `(monotonic_time, cpu_time, read_bytes, write_bytes)` keyed by `(run_id, pid)`.
- Calculates instantaneous deltas between consecutive reads without sleeping.
- Supports stale detection and timestamped freshness metadata.

### Data Models & Provenance
- `ProcessTelemetry`: Verified per-process-tree resource metrics.
- `HostTelemetry`: Explicit host-scoped metrics (system CPU, system memory, disk I/O, system network, GPU devices).
- Network rates are recorded in `HostTelemetry` (system scope) or omitted from process cards until OS-level per-socket attribution exists.
- CPU metrics explicitly provide both `cpu_percent` (multi-core sum) and `cpu_percent_normalized` (divided by logical CPU count).

### Read API
- `GET /api/runs/{run_id}/telemetry`: Read verified telemetry for a single run.
- `GET /api/telemetry`: Read overview telemetry for all active runs + host summary.
- Authenticated via existing session authentication; read-only; non-blocking.
