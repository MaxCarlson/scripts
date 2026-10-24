# Runmux Historical Telemetry — Decisions Requiring Approval (Phase 5C)

**Document ID:** RUNMUX-5C-APPROVAL | **Status:** Action Items for User Review | **Date:** 2026-10-24  
**Scope:** `modules/runmux/` | **Author:** Antigravity (AI Systems Architect)

---

## 1. Overview

Before beginning implementation of Phase 5C, explicit user approval is required on six architectural and operational decisions.

---

## 2. Decision Items for User Approval

### Decision 1: Background Collection Lifecycle Policy

| Option | Description | Pros | Cons | Recommendation |
| :--- | :--- | :--- | :--- | :--- |
| **Option A: On-Demand Only** | Samples only while a browser tab is actively viewing a run. | Zero background overhead when browser is closed. | Empty history on initial open; cannot diagnose what happened before an issue was opened. | Not recommended |
| **Option B: Web-Server-Scoped (Recommended)** | An in-process background worker runs inside `runmux web`, sampling active runs. | Immediate historical charts on tab selection; clean shutdown with web server; no daemon needed. | Telemetry only recorded while `runmux web` is running. | **Recommended** |
| **Option C: Supervisor-Driven** | Every per-run supervisor process samples its own child. | Continuous history even without web server running. | Multiplies sampling timers by $N$ processes; SQLite write contention; bloats supervisor footprint. | Not recommended |
| **Option D: Standalone Daemon Service** | A dedicated background OS service (`runmuxd`) samples continuously. | 24/7 background telemetry independent of web server. | Violates Runmux zero-daemon principle; requires service installation, autostart, and maintenance. | Not recommended |

> [!IMPORTANT]
> **Proposed Policy:** Adopt **Option B** as the default. Telemetry collection is active whenever `runmux web` is running. Users can opt out using the flag `runmux web --no-telemetry-history`.

---

### Decision 2: Multi-Tier Retention Window & Storage Limits

The proposal recommends a 3-tier retention model to keep disk usage strictly bounded while preserving long-term visibility:
1. **Raw samples (2–5s cadence):** Retained for **1 hour**.
2. **1-Minute rollups (avg, min, max):** Retained for **24 hours**.
3. **5-Minute rollups (avg, min, max):** Retained for **7 days**.
4. **Hard Database Cap:** Maximum database file size defaults to **50 MB**. If the database approaches 50 MB, the pruner aggressively drops the oldest 5-minute rollups.

*Do you approve this 1-hour / 24-hour / 7-day retention schedule and 50 MB cap, or should the default retention period or disk cap be adjusted?*

---

### Decision 3: High-Resolution Sampling Cadence & Focused View Burst

- **Background Cadence:** **5.0 seconds** for all active runs (measured CPU cost on Windows: ~0.7% for 5 runs, ~2.8% for 20 runs).
- **Focused View Burst (Optional):** When a user selects a specific run tab in the web UI, the browser can send an active tab heartbeat, allowing the sampler to boost sampling for that *single* process to **1.0 or 2.0 seconds** for higher-resolution real-time charting.

*Should we enable the focused-view burst mode (1–2s for the active tab only), or keep a uniform 5.0-second cadence across all runs?*

---

### Decision 4: Separate Database File (`telemetry.sqlite3`)

The proposal places historical telemetry in a dedicated database file `%LOCALAPPDATA%\runmux\telemetry.sqlite3` rather than adding tables to `registry.sqlite3`.
- **Reasoning:**
  1. Preserves `ReadOnlyRunmux`'s strict read-only guarantee over `registry.sqlite3`.
  2. Eliminates any possibility of telemetry writes causing lock contention with process lifecycle operations (`runmux run`, `kill`, `restart`).
  3. Enables disposable lifecycle: if `telemetry.sqlite3` is corrupted or deleted, the process manager and CLI continue functioning flawlessly.

*Do you approve creating a separate `telemetry.sqlite3` database file for metric history?*

---

### Decision 5: Host Telemetry Isolation

Host-level telemetry (`host_cpu_percent`, `host_memory_*`, `host_net_*`) will be stored in a dedicated table (`host_telemetry_raw`) and queried via `GET /api/telemetry/history`. It will **never** be copied or projected onto individual process rows.

*Do you approve this strict isolation of host-wide metrics from process-specific metrics?*

---

### Decision 6: Lineage Handling on Restarts

When a run is restarted via `POST /api/runs/{run_id}/restart`, a new Run ID is created.
The proposed API defaults to querying strictly the requested `run_id`. If `include_lineage=true` is passed, the API returns the chained series but includes an explicit `event: "restart"` marker, and frontend charts will render a visible curve break across the gap.

*Do you approve keeping Run IDs strictly partitioned by default, requiring an explicit `include_lineage=true` flag to view parent runs?*
