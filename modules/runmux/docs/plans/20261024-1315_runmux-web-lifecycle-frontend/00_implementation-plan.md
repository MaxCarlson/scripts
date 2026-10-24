# Runmux Web UI — Phase 4A Lifecycle Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Overview

Implement selected-process browser controls for Stop, Kill, Restart, Duplicate, and Pause/Resume in the Runmux Web UI, consuming the existing authenticated lifecycle endpoints (`/api/runs/{run_id}/stop`, `kill`, `restart`, `duplicate`, `pause`, `resume`).
Ensure destructive actions require user confirmation naming both the process name and full immutable Run ID, display request-in-progress, termination-pending, completed, and error states accurately, reconcile newly spawned runs with Phase 3 workspace tabs and explorer entries, and preserve all Phase 5A+ overview modes, live telemetry, Phase 4B output search, terminal attachment, and view-only tab closure invariants.

---

## File Structure

- [`modules/runmux/src/runmux/web_static/index.html`](file:///C:/Users/mcarls/src/scripts/.worktrees/runmux-web-lifecycle-frontend-20261024/modules/runmux/src/runmux/web_static/index.html):
  - Add `#lifecycle-controls` group to `#run-inspector` (Stop, Kill, Restart, Duplicate, Pause buttons).
  - Add `#lifecycle-feedback` notification banner for request-in-progress, pending termination, error, and success states.
  - Add `#lifecycle-confirm-modal` dialog displaying run name, full immutable Run ID, and action description.
- [`modules/runmux/src/runmux/web_static/assets/dashboard.css`](file:///C:/Users/mcarls/src/scripts/.worktrees/runmux-web-lifecycle-frontend-20261024/modules/runmux/src/runmux/web_static/assets/dashboard.css):
  - Add button styles for lifecycle actions (`.lifecycle-btn`, `.lifecycle-btn-danger`, `.lifecycle-btn-warning`).
  - Add confirmation modal styles (`.modal-backdrop`, `.modal-box`, `.modal-actions`).
  - Add feedback banner styling (`.lifecycle-feedback`, `.lifecycle-feedback-error`, `.lifecycle-feedback-pending`).
  - Add responsive layout handling for lifecycle controls across viewports.
- [`modules/runmux/src/runmux/web_static/assets/dashboard.js`](file:///C:/Users/mcarls/src/scripts/.worktrees/runmux-web-lifecycle-frontend-20261024/modules/runmux/src/runmux/web_static/assets/dashboard.js):
  - Add lifecycle state tracking (`lifecycleInFlightRunId`, `pendingConfirmAction`).
  - Implement button eligibility updates based on selected run status (`pending`, `running`, `paused`, `finished`, `failed`, `killed`, `lost`).
  - Implement confirmation modal logic (open, confirm, cancel, keyboard trap).
  - Implement API mutation calls with generation guards and error handling (`401`, `404`, `409`, `501`, `503`, `500`).
  - Implement Restart and Duplicate reconciliation: refresh run list, open new workspace tab, select new run, preserve old run record.
  - Implement Pause/Resume unsupported feedback on Windows host.
- [`modules/runmux/tests/dashboard_test.js`](file:///C:/Users/mcarls/src/scripts/.worktrees/runmux-web-lifecycle-frontend-20261024/modules/runmux/tests/dashboard_test.js):
  - Add unit tests for button eligibility by status.
  - Add unit tests for confirmation modal requirements (process name + full immutable ID).
  - Add unit tests for graceful Stop (`force: false`) and forced Kill (`force: true`).
  - Add unit tests for error handling (404, 409 conflict, 501 unsupported, 503 supervisor unavailable).
  - Add unit tests for Restart and Duplicate tab/explorer reconciliation and identity preservation.
  - Add unit tests for concurrent request prevention and stale-selection guards.
- [`modules/runmux/tests/browser_e2e_test.js`](file:///C:/Users/mcarls/src/scripts/.worktrees/runmux-web-lifecycle-frontend-20261024/modules/runmux/tests/browser_e2e_test.js):
  - Add headless Chrome CDP E2E validation with disposable synthetic processes testing Stop, Kill confirmation, Restart new identity, Duplicate, and tab preservation.

---

## Tasks

### Task 1: UI Elements and Styling (HTML & CSS)
- [ ] Add `#lifecycle-controls` container with Stop, Kill, Restart, Duplicate, and Pause buttons to `index.html`.
- [ ] Add `#lifecycle-feedback` status banner to `index.html`.
- [ ] Add accessible `#lifecycle-confirm-modal` dialog to `index.html` with run name and immutable Run ID placeholders.
- [ ] Add CSS styling in `dashboard.css` for buttons, modal, feedback banner, and responsive viewport wrapping.

### Task 2: Lifecycle Control Engine & State Management (JavaScript)
- [ ] Implement `updateLifecycleControls(run)` in `dashboard.js` to enable/disable buttons based on run status.
- [ ] Implement confirmation modal handlers: `showLifecycleConfirm(action, run)`, `cancelLifecycleConfirm()`, `submitLifecycleConfirm()`.
- [ ] Implement lifecycle API callers: `executeStop(runId, force)`, `executeRestart(runId)`, `executeDuplicate(runId)`, `executePause(runId)`.
- [ ] Enforce in-flight locking and selection generation guards to prevent stale-run mutation and double-clicks.
- [ ] Reconcile Restart/Duplicate outcomes: trigger `refreshRuns()`, open new tab, select new run ID, preserve previous run.
- [ ] Handle error responses (401 session expired, 404 missing, 409 conflict, 501 platform unsupported, 503 supervisor offline).

### Task 3: Unit Testing Suite (`dashboard_test.js`)
- [ ] Test button eligibility matrix across active and terminal statuses.
- [ ] Test confirmation modal populates process name and full immutable Run ID.
- [ ] Test graceful Stop (`force: false`) and forced Kill (`force: true`).
- [ ] Test status transitions: request-in-progress, terminating-pending, already-terminated, completed.
- [ ] Test 404, 409, 501, 503 error feedback.
- [ ] Test Restart and Duplicate create new Run IDs, open new workspace tabs, and preserve original run tabs.
- [ ] Test stale-selection and in-flight guard protections.
- [ ] Test tab closing remains view-only and never stops processes.

### Task 4: Real Headless Chrome CDP Verification (`browser_e2e_test.js`)
- [ ] Extend `browser_e2e_test.js` to spawn disposable worker processes.
- [ ] Test UI button interactions, confirmation modal workflow, and live feedback in real Chrome.
- [ ] Test process termination and status update in explorer and inspector.
- [ ] Capture screenshots of lifecycle controls, confirmation modal, and terminating states.

### Task 5: Documentation & Branch Push
- [ ] Update `checklist.md`, `STATUS.md`, `HANDOFF.md`, and `modules/runmux/docs/plans/HANDOFF.md`.
- [ ] Run linter and backend test suites.
- [ ] Commit and push feature branch `codex/runmux-web-lifecycle-frontend-20261024`.
