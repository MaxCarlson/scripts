# Runmux Web UI — Phase 5C Historical Telemetry Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Implement responsive, accurate historical resource time-series charts in Runmux's browser interface for Process CPU, Memory/RSS, Disk I/O, and Host resources across Dashboard and Expanded overview modes, consuming the Phase 5C backend API.

**Architecture:** Pure vanilla JavaScript SVG time-series engine directly rendered into DOM containers, styled with existing dark IDE CSS tokens. Decoupled dual polling cadences with AbortController cancellation, selection generation guards, explicit gap preservation, multi-core CPU handling, and lifecycle/restart event annotations.

**Tech Stack:** JavaScript (ES2022, vanilla DOM & SVG), CSS3, Python 3.12 (FastAPI/Starlette test harness), Node.js (test runner), Chrome DevTools Protocol (CDP E2E).

**Spec:** `modules/runmux/docs/plans/20261024-runmux-historical-telemetry/04_api_proposal.md` and user assignment prompt.

## Global Constraints
- Target branch: `codex/runmux-web-historical-telemetry-frontend-20261024` from `origin/main` at `8befeae3375740e21cdfe17a081387f0e3cf8f54`.
- Zero backend modifications (Agent A owns backend; Phase 5C backend is already merged).
- Zero external charting NPM dependencies (native SVG rendering).
- Mode A (Minimal) and Mode B (Inline) must contain zero historical charts and perform zero history network requests.
- Mode C (Dashboard) renders high-value process charts (CPU, RSS, and Disk I/O).
- Mode D (Expanded) renders detailed process charts with time-range controls (1h, 6h, 24h, 7d), lineage toggle, resolution labels, and system-wide host resource charts (Host CPU, Host RAM, Host Network).
- Never render false zeros for missing or unavailable metrics; preserve collection gaps (`is_gap: true` or temporal discontinuity) by breaking line segments.
- Destructive lifecycle actions, Output follow, and Terminal WebSocket sessions must not be disrupted.

## Review Focus
1. Discontinuous data and restart gaps: when `is_gap: true` or a large interval occurs, SVG path must disconnect (`M x y` after gap) rather than drawing misleading interpolation lines.
2. Rapid run / range switching: in-flight history requests must be aborted via `AbortController` and rejected if `generation !== selectionGeneration`.
3. Multi-core CPU utilization: CPU percentages can legitimately exceed 100% on multi-core systems (e.g. 250% on 4 cores); chart Y-axis must scale to max observed data or core ceiling without clipping.
4. Missing per-process Disk I/O on platforms like Windows: represented as "Unavailable" rather than fabricated 0 B/s.
5. Incomplete retention: when requesting 24h or 7d but backend only has 30 minutes of telemetry, charts render available points accurately and display the actual retention start without inventing observations.

---

### Task 1: UI Elements and Styling (HTML & CSS)

**Files:**
- Modify: `modules/runmux/src/runmux/web_static/index.html`
- Modify: `modules/runmux/src/runmux/web_static/assets/dashboard.css`
- Test: `modules/runmux/tests/dashboard_test.js`

**Interfaces:**
- Consumes: Existing `#telemetry-panel`, `#process-telemetry-section`, `#host-telemetry-section` in `index.html`.
- Produces: Chart containers (`#chart-proc-cpu`, `#chart-proc-rss`, `#chart-proc-io`, `#chart-host-cpu`, `#chart-host-ram`, `#chart-host-net`), range controls (`#history-range-controls`), lineage toggle (`#history-lineage-toggle`), and chart metadata badges.

- [x] **Step 1: Write the failing unit test for DOM structure in `dashboard_test.js`**
- [x] **Step 2: Run test to verify it fails**
- [x] **Step 3: Add chart containers, range toolbar, and CSS in `index.html` and `dashboard.css`**
- [x] **Step 4: Run test to verify it passes**
- [x] **Step 5: Record UI scaffolding verification**

---

### Task 2: SVG Time-Series Chart Rendering Engine

**Files:**
- Modify: `modules/runmux/src/runmux/web_static/assets/dashboard.js`
- Test: `modules/runmux/tests/dashboard_test.js`

**Interfaces:**
- Consumes: Telemetry series points (`epoch`, `timestamp`, metric values, `is_gap`, `run_id`), `events` array, container element, configuration (unit, color, label, yMin, yMax).
- Produces: `renderTimeSeriesChart(container, options)`: lightweight, responsive, accessible SVG chart with grid, axes, segmented curve, area fill, gap breaks, and event markers.

- [x] **Step 1: Write failing unit tests for `renderTimeSeriesChart` covering gaps, nulls, rollups, and multi-core scaling in `dashboard_test.js`**
- [x] **Step 2: Run tests to verify they fail**
- [x] **Step 3: Implement SVG path generator and axis renderer in `dashboard.js`**
- [x] **Step 4: Run tests to verify they pass**
- [x] **Step 5: Record SVG renderer verification**

---

### Task 3: Historical Telemetry Controller & State Management

**Files:**
- Modify: `modules/runmux/src/runmux/web_static/assets/dashboard.js`
- Test: `modules/runmux/tests/dashboard_test.js`

**Interfaces:**
- Consumes: `/api/runs/{run_id}/telemetry/history` and `/api/telemetry/history`.
- Produces: `refreshHistoryTelemetry(generation, runId)`, `updateHistoryView()`, range selector event handlers (`1h`, `6h`, `24h`, `7d`), lineage toggle handler, and overview mode gating (A/B disabled, C process-only, D full).

- [x] **Step 1: Write failing unit tests for history fetching, range switching, mode gating, and request cancellation in `dashboard_test.js`**
- [x] **Step 2: Run tests to verify they fail**
- [x] **Step 3: Implement history controller, range selectors, and mode hooks in `dashboard.js`**
- [x] **Step 4: Run tests to verify they pass**
- [x] **Step 5: Record controller verification**

---

### Task 4: Real Headless Chrome CDP Verification & Screenshot Capture

**Files:**
- Modify: `modules/runmux/tests/browser_e2e_test.js`
- Create: `modules/runmux/docs/plans/20261024-1530_runmux-web-historical-telemetry-frontend/screenshots/mode_c_dashboard_charts.png`
- Create: `modules/runmux/docs/plans/20261024-1530_runmux-web-historical-telemetry-frontend/screenshots/mode_d_expanded_charts.png`
- Create: `modules/runmux/docs/plans/20261024-1530_runmux-web-historical-telemetry-frontend/screenshots/limited_retention_charts.png`

**Interfaces:**
- Consumes: Real Chrome headless CDP instance, synthetic process registry, and pre-seeded `TelemetryStore` records.
- Produces: Verified end-to-end chart rendering in real Chrome, range switching, lineage traversal, and 3 captured screenshots.

- [x] **Step 1: Extend `browser_e2e_test.js` with historical telemetry seeding and chart assertions**
- [x] **Step 2: Run `node modules/runmux/tests/browser_e2e_test.js` and capture screenshots**
- [x] **Step 3: Verify all 18+ sections pass and inspect screenshots**
- [x] **Step 4: Record E2E evidence and inspect screenshots**

---

### Task 5: Documentation, Verification Ledger, and Feature Branch Push

**Files:**
- Create: `modules/runmux/docs/plans/20261024-1530_runmux-web-historical-telemetry-frontend/STATUS.md`
- Create: `modules/runmux/docs/plans/20261024-1530_runmux-web-historical-telemetry-frontend/HANDOFF.md`
- Create: `modules/runmux/docs/plans/20261024-1530_runmux-web-historical-telemetry-frontend/checklist.md`
- Modify: `modules/runmux/docs/plans/HANDOFF.md`

- [x] **Step 1: Run focused frontend verification (`node --check` for changed JavaScript, `dashboard_test.js`, and real Chrome `browser_e2e_test.js`)**
- [x] **Step 2: Write `STATUS.md`, `HANDOFF.md`, and `checklist.md`**
- [ ] **Step 3: Commit all feature changes and push `codex/runmux-web-historical-telemetry-frontend-20261024` without merging**
- [x] **Step 4: Prepare final completion report with screenshots, test results, and limitations**
