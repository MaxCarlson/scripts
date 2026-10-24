# Phase 4A Lifecycle Frontend Checklist

## Task 1: UI Elements and Styling (HTML & CSS)
- [x] Add `#lifecycle-controls` container with Stop, Kill, Restart, Duplicate, and Pause buttons to `index.html`
- [x] Add `#lifecycle-feedback` status banner to `index.html`
- [x] Add accessible `#lifecycle-confirm-modal` dialog to `index.html` with run name and immutable Run ID placeholders
- [x] Add CSS styling in `dashboard.css` for buttons, modal, feedback banner, and responsive viewport wrapping

## Task 2: Lifecycle Control Engine & State Management (JavaScript)
- [x] Implement `updateLifecycleControls(run)` in `dashboard.js` to enable/disable buttons based on run status
- [x] Implement confirmation modal handlers: `showLifecycleConfirm(action, run)`, `closeLifecycleConfirm()`, `submitLifecycleConfirm()`
- [x] Implement lifecycle API callers: `executeLifecycleAction(action, runId, options)` consuming `/api/runs/{run_id}/stop`, `/kill`, `/restart`, `/duplicate`, `/pause`, `/resume`
- [x] Enforce in-flight locking and selection generation guards to prevent stale-run mutation and double-clicks
- [x] Reconcile Restart/Duplicate outcomes: trigger `refreshRuns()`, open new tab, select new run ID, preserve previous run
- [x] Handle error responses (401 session expired, 404 missing, 409 conflict, 501 platform unsupported, 503 supervisor offline)

## Task 3: Unit Testing Suite (`dashboard_test.js`)
- [x] Test button eligibility matrix across active and terminal statuses
- [x] Test confirmation modal populates process name and full immutable Run ID
- [x] Test graceful Stop (`force: false`) and forced Kill (`force: true`)
- [x] Test status transitions: request-in-progress, terminating-pending, already-terminated, completed
- [x] Test 404, 409, 501, 503 error feedback
- [x] Test Restart and Duplicate create new Run IDs, open new workspace tabs, and preserve original run tabs
- [x] Test stale-selection and in-flight guard protections
- [x] Test tab closing remains view-only and never stops processes

## Task 4: Real Headless Chrome CDP Verification (`browser_e2e_test.js`)
- [x] Extend `browser_e2e_test.js` to spawn disposable worker processes
- [x] Test UI button interactions, confirmation modal workflow, and live feedback in real Chrome
- [x] Test process termination and status update in explorer and inspector
- [x] Capture screenshots of lifecycle controls, confirmation modal, and terminating states

## Task 5: Initial Documentation & Branch Push
- [x] Update `checklist.md`, `STATUS.md`, `HANDOFF.md`, and `modules/runmux/docs/plans/HANDOFF.md`
- [x] Run linter and backend test suites (`pytest`, `ruff check`, `node dashboard_test.js`, `node browser_e2e_test.js`)
- [x] Commit and push feature branch `codex/runmux-web-lifecycle-frontend-20261024` (`fc26899f`)

## Task 6: Final Acceptance Corrections
- [x] Add `GET /api/capabilities` endpoint in `web.py` to expose platform execution capabilities
- [x] Implement Resume action for paused processes in `dashboard.js` and styling in `dashboard.css`
- [x] Make Pause/Resume capability-aware from backend rather than inferring from browser OS
- [x] Present Pause/Resume as unavailable when unsupported (e.g. Windows backend) rather than enabling a control that cannot succeed
- [x] Correct Run ID length description in documentation (22 characters)
- [x] Add unit tests in `dashboard_test.js` and `lifecycle_api_test.py` covering supported Pause → Resume transitions and unsupported Windows behavior
- [x] Validate in headless Chrome CDP test (`browser_e2e_test.js`)
- [ ] Commit and push corrections commit to `origin/codex/runmux-web-lifecycle-frontend-20261024`
