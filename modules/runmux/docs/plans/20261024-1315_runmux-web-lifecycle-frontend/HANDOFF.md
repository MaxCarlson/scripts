# Runmux Web UI — Phase 4A Lifecycle Frontend Handoff

**Phase:** RUNMUX-WEB-P4A-FRONTEND  
**Branch:** `codex/runmux-web-lifecycle-frontend-20261024`  
**Base:** `origin/main` at `a0028473523f6208ea298218e0e666d56d083c9c`  
**Status:** Verification Complete & Ready for Review  

---

## 1. Overview and Scope

Phase 4A Lifecycle Frontend implements selected-process browser controls for:
- **Stop:** Graceful termination (`force: false` default) with confirmation naming process name and full immutable Run ID.
- **Kill:** Forced termination (`force: true` default) with confirmation naming process name and full immutable Run ID.
- **Restart:** Terminated runs can be restarted as a **new immutable Run ID**, reconciling workspace tabs and explorer entries while preserving the original run.
- **Duplicate:** Any run can be duplicated as a **new parallel Run ID**, opening a new tab and preserving the source run.
- **Pause/Resume:** Accurately presented as unsupported on Windows hosts without OS process pause APIs (501 status); never simulates pausing by disconnecting terminal or suspending output follow.

---

## 2. Invariants & Safety Model

1. **Destructive Action Confirmation:** Stop and Kill require explicit user confirmation displaying both the human-readable run name and full 22-character immutable Run ID (`YYYYMMDD-HHMMSS-[0-9a-f]{6}`).
2. **Double-Click & In-Flight Protection:** Buttons transition to loading/busy state immediately; in-flight requests lock mutations for that Run ID.
3. **Stale Selection Guard:** If the user switches processes while a mutation request is in flight, the completed response does not mutate the newly selected run's inspector.
4. **View-Only Tab Closure:** Closing a browser tab or disconnecting the terminal WebSocket remains view-only and never affects process lifecycle.
5. **Preservation of Previous Phases:** Overview modes (A/B/C/D), live telemetry, Output search & filtering, PTY terminal attachment, and authentication are preserved.

---

## 3. Screenshots Captured

The following real headless Chrome screenshots were captured in `modules/runmux/docs/plans/20261024-1315_runmux-web-lifecycle-frontend/screenshots/`:
1. `lifecycle_confirm_modal.png` — Confirmation modal dialog showing process name ("e2e worker") and full immutable Run ID ("20261024-070000-e2e1a2") with destructive warning.
2. `lifecycle_feedback_banner.png` — Status banner showing request in-flight and termination feedback.
3. `lifecycle_controls_overview.png` — Workspace showing lifecycle controls, explorer list, tabs reconciled, and preserved process state after tab close.

---

## 4. Verification Evidence

- `node modules/runmux/tests/dashboard_test.js`: 36 suites passed (0 failures).
- `node modules/runmux/tests/browser_e2e_test.js`: 17 sections passed in real headless Chrome via CDP.
- `pytest tests/web_test.py tests/telemetry_test.py tests/web_adapter_test.py tests/lifecycle_api_test.py tests/lifecycle_test.py -q`: 74 passed (0 failures).
- `ruff check src/runmux/web.py src/runmux/lifecycle.py tests/lifecycle_api_test.py`: All checks passed.
