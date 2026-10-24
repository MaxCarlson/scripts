# Runmux Web UI — Phase 5A+ Overview Modes and Live Telemetry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Phase 5A's four selectable process overview modes (Minimal, Inline, Dashboard, Expanded) and complete the frontend integration of Phase 5B's live telemetry endpoints with strict provenance, zero-vs-unavailable semantics, bounded polling, responsive layouts, and native Windows browser verification.

**Architecture:** Extend `index.html`, `dashboard.css`, and `dashboard.js` with an overview mode controller and telemetry manager that consumes authenticated `/api/runs/{run_id}/telemetry` and `/api/telemetry` endpoints. Preserve dark technical IDE aesthetics, isolate DOM updates, maintain tab/terminal/output state across mode transitions, pause polling when hidden, and cleanly label process-tree vs. host-wide metrics.

**Tech Stack:** Vanilla JavaScript (ES2022, no framework), CSS3 Grid & Flexbox, HTML5 Semantic Elements, FastAPI / SQLite backend, Node.js unit test runner (`node:assert/strict`), Chrome DevTools Protocol (CDP) for native browser E2E verification.

**Spec:** `modules/runmux/docs/plans/web-ui-handoff/PHASE_05A_OVERVIEW_MODES.md`, `modules/runmux/docs/plans/web-ui-handoff/PHASE_05B_LIVE_TELEMETRY.md`, `modules/runmux/docs/plans/20261024-runmux-telemetry-backend/TELEMETRY_PROVENANCE.md`

## Global Constraints

- Preserve all existing Phase 1–4B capabilities (process launch, terminal fidelity, explorer tabs, output search/filtering).
- Do not modify backend process lifecycle, supervisors, telemetry collectors, or database schemas.
- Do not introduce a generalized docking/layout framework or speculative chart libraries.
- Never label host-wide network rates as process-specific network usage.
- Never present GPU device utilization as if it measured the selected process.
- Distinguish unavailable / baseline data (`null`) from a valid `0.0` measurement.
- Persist global overview mode in `localStorage` across page reloads without storing sensitive information.
- Bounded polling: serialize requests, cancel on switch/close/Mode A, suspend when hidden.
- Native Windows tooling only; clean up all disposable test processes.

## Review Focus

1. **Zero vs. Unavailable distinction:** Rate fields on first poll ($N=1$) or unsupported platforms return `null` and must render as `—` or `Baseline`, never as `0.0%` or `0 B/s`.
2. **Attribution & Scope Integrity:** Host network throughput and GPU device stats must explicitly display system/device scope tags to prevent misleading operators.
3. **Mode switching non-disruption:** Toggling A/B/C/D must not re-render or reset Output buffer, Terminal WebSocket connection, active view tab, follow state, or search filter.
4. **Polling concurrency & cleanup:** Rapid run switching or navigating away must cancel in-flight telemetry requests and prevent timer leaks or zombie requests.
5. **Responsive viewport stability:** All four modes must remain legible and avoid horizontal overflow or broken layouts across mobile (390px), tablet (768px), desktop (1366px, 1920px), and ultrawide (2560px).

---

### Task 1: Overview Mode State, Controls, and Persistence (Phase 5A)

**Files:**
- Modify: `modules/runmux/src/runmux/web_static/index.html`
- Modify: `modules/runmux/src/runmux/web_static/assets/dashboard.js`
- Modify: `modules/runmux/src/runmux/web_static/assets/dashboard.css`
- Test: `modules/runmux/tests/dashboard_test.js`

**Interfaces:**
- Consumes: `localStorage` key `runmux-overview-mode-v1`
- Produces: `overviewMode` (`"minimal" | "inline" | "dashboard" | "expanded"`), `setOverviewMode(mode)`, `cycleOverviewMode()`, CSS classes `.mode-minimal`, `.mode-inline`, `.mode-dashboard`, `.mode-expanded` on `#run-inspector`.

- [ ] **Step 1: Write failing unit tests for mode switching, cycling, and persistence**
Add tests in `tests/dashboard_test.js` verifying:
  - Mode initialization from storage default.
  - Direct selection of A, B, C, D.
  - Cycle order: `minimal -> inline -> dashboard -> expanded -> minimal`.
  - Persistence to storage.
  - Preservation of active run, tabs, and output follow state.

- [ ] **Step 2: Run test to verify it fails**
Run: `node tests/dashboard_test.js`
Expected: FAIL on undefined mode controller functions or elements.

- [ ] **Step 3: Implement mode controls in HTML, CSS, and JS**
  - Add segmented control / buttons in `#run-inspector` header with accessible labels.
  - Add `overviewMode` management in `dashboard.js` with `setOverviewMode(mode)` and keyboard shortcut (`Alt+M`).
  - Add CSS mode classes defining header heights and visibility for Mode A (minimal, ~34px, no telemetry widgets), Mode B (inline, ~48px), Mode C (dashboard cards), and Mode D (expanded diagnostic layout).

- [ ] **Step 4: Run test to verify it passes**
Run: `node tests/dashboard_test.js`
Expected: PASS.

---

### Task 2: Live Telemetry Frontend Integration & Metric Provenance (Phase 5B)

**Files:**
- Modify: `modules/runmux/src/runmux/web_static/index.html`
- Modify: `modules/runmux/src/runmux/web_static/assets/dashboard.js`
- Modify: `modules/runmux/src/runmux/web_static/assets/dashboard.css`
- Test: `modules/runmux/tests/dashboard_test.js`

**Interfaces:**
- Consumes: `/api/runs/{run_id}/telemetry` and `/api/telemetry`
- Produces: `renderTelemetry(processStats, hostStats)`, formatters `formatPercent`, `formatBytesRate`, `formatBytes`, `formatUnavailableOrZero`.

- [ ] **Step 1: Write failing unit tests for telemetry rendering and provenance formatting**
Add tests in `tests/dashboard_test.js` verifying:
  - Correct rendering of CPU (single vs multicore, normalized percent).
  - Correct rendering of RSS memory, process count, thread count.
  - Disk I/O read/write rates formatting and null vs 0.0 B/s handling.
  - Process GPU memory vs Host GPU devices (scope tag verification).
  - Host network throughput explicit host-wide labeling (`HOST NETWORK (SYSTEM-WIDE)`).
  - First-sample baseline handling (`null` rates show `Baseline...` or `—`).
  - Terminal run / process exit handling (`unavailable` status display).

- [ ] **Step 2: Run test to verify it fails**
Run: `node tests/dashboard_test.js`
Expected: FAIL on missing telemetry elements or formatting functions.

- [ ] **Step 3: Implement telemetry DOM containers and rendering logic**
  - Mode B inline stats (CPU %, RSS).
  - Mode C resource cards (Process CPU, Process Memory, Process Tree, Disk I/O, Process GPU).
  - Mode D expanded diagnostic panels (Process Breakdown + Host CPU, Host Memory, Host Network, GPU Devices).
  - Add provenance labels, scope badges, and explicit unit notations.

- [ ] **Step 4: Run test to verify it passes**
Run: `node tests/dashboard_test.js`
Expected: PASS.

---

### Task 3: Bounded Polling Engine, Visibility Management, and Lifecycle Cleanup

**Files:**
- Modify: `modules/runmux/src/runmux/web_static/assets/dashboard.js`
- Test: `modules/runmux/tests/dashboard_test.js`

**Interfaces:**
- Consumes: DOM `document.visibilityState`, `AbortController`
- Produces: `startTelemetryPolling()`, `stopTelemetryPolling()`, `refreshTelemetry(generation, runId)`

- [ ] **Step 1: Write failing unit tests for polling bounds and lifecycle**
Add tests in `tests/dashboard_test.js` verifying:
  - Polling active only when a run is selected and mode != minimal.
  - In-flight request serialization (no overlapping polls).
  - AbortController triggered on run switch or view close.
  - Timer suspended when document is hidden and resumed on visible.
  - Cleanup on lock / deselect / process completion.

- [ ] **Step 2: Run test to verify it fails**
Run: `node tests/dashboard_test.js`
Expected: FAIL on polling assertion errors.

- [ ] **Step 3: Implement bounded polling engine in `dashboard.js`**
  - Implement 1800ms polling cadence with `inFlight` protection.
  - Add `AbortController` cancellation for superseded requests.
  - Add `document.addEventListener("visibilitychange", ...)` handler.
  - Add terminal state detection to avoid polling dead/exited processes.

- [ ] **Step 4: Run test to verify it passes**
Run: `node tests/dashboard_test.js`
Expected: PASS.

---

### Task 4: Responsive Styling and Visual Polish (Desktop, Ultrawide, Tablet, Mobile)

**Files:**
- Modify: `modules/runmux/src/runmux/web_static/assets/dashboard.css`
- Test: `modules/runmux/tests/dashboard_test.js`
- Test: `modules/runmux/tests/browser_e2e_test.js`

- [ ] **Step 1: Add media queries and flex/grid responsive rules**
  - Mobile (390px): compact stacked cards, scrollable or wrap stat pills.
  - Tablet (768px): 2-column card layout.
  - Desktop (1366px, 1920px): balanced card row / multi-column grid.
  - Ultrawide (2560px): bounded max-width card strip to maintain terminal/output priority.

- [ ] **Step 2: Run tests to verify layout styles and properties**
Run: `node tests/dashboard_test.js`
Expected: PASS.

---

### Task 5: End-to-End Native Browser Verification & Screenshot Capture

**Files:**
- Modify: `modules/runmux/tests/browser_e2e_test.js`
- Create: `modules/runmux/docs/plans/20261024-runmux-web-overview-telemetry/screenshots/`

- [ ] **Step 1: Extend `browser_e2e_test.js` with Phase 5A/5B validation**
  - Test mode selection & cycling in real Chrome instance.
  - Test live telemetry rendering with realistic mock data.
  - Test run switching while polling is active.
  - Test responsive viewports: 390px, 768px, 1366px, 1920px, 2560px.
  - Capture CDP screenshots for Modes A, B, C, D.

- [ ] **Step 2: Run `browser_e2e_test.js` and verify all checks pass**
Run: `node tests/browser_e2e_test.js`
Expected: PASS with 0 errors and generated screenshot PNGs.

- [ ] **Step 3: Run backend regressions and code checks**
Run: `python -m pytest tests/web_test.py tests/telemetry_test.py tests/web_adapter_test.py -q`
Expected: All pass.

---

### Task 6: Documentation, Status Ledger, and Git Branch Push

**Files:**
- Create/Update: `modules/runmux/docs/plans/20261024-runmux-web-overview-telemetry/HANDOFF.md`
- Create/Update: `modules/runmux/docs/plans/20261024-runmux-web-overview-telemetry/STATUS.md`
- Create/Update: `modules/runmux/docs/plans/20261024-runmux-web-overview-telemetry/checklist.md`
- Update: `modules/runmux/docs/plans/HANDOFF.md`
- Update: `modules/runmux/docs/plans/web-ui-handoff/RUNMUX_WEB_UI_MASTER_ROADMAP.md`

- [ ] **Step 1: Record completion, metrics provenance, polling parameters, and verification in docs**
- [ ] **Step 2: Commit all intended files on feature branch**
- [ ] **Step 3: Push feature branch to origin without merging**
