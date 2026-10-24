# Handoff — Runmux Process Lifecycle Backend (Phase 4A)

**Branch:** `codex/runmux-lifecycle-backend-20261024`  
**Worktree:** `.worktrees/runmux-lifecycle-backend`  
**Base Commit:** `9f01984d3dedf05781a19f8d131956662ee5b29d` (`origin/main`)  
**Assignment:** Backend-only subset of `PHASE_04A_LIFECYCLE_CONTROLS.md`.  

## Scope & Non-Goals
- **Scope:** Backend lifecycle management service (`runmux/lifecycle.py`), authenticated browser REST API endpoints in `runmux/web.py` (`/api/runs/{run_id}/stop`, `/kill`, `/restart`, `/duplicate`, `/pause`, `/resume`), comprehensive tests in `tests/lifecycle_test.py` and `tests/lifecycle_api_test.py`, and specification documentation in `docs/plans/20261024-runmux-lifecycle-backend/`.
- **Non-Goals:** Zero frontend modifications (`dashboard.js`, CSS, HTML), no changes to explorer tab behavior or terminal attachments, no WebSocket input-lock modifications, no WSL execution.

## Coordination with Parallel Agents
- Another agent is developing Phase 3 browser workspace changes in `.worktrees/runmux-web-launch-20261024` on branch `codex/runmux-web-phase3-20261024` modifying `dashboard.js` and `dashboard_test.js`.
- This Phase 4A backend branch touches **zero frontend files**, ensuring completely orthogonal work with zero merge conflicts.

## Endpoints Implemented
- `POST /api/runs/{run_id}/stop` & `POST /api/runs/{run_id}/kill` -> HTTP 200 OK
- `POST /api/runs/{run_id}/restart` -> HTTP 201 Created (target must be terminal; active run returns 409 Conflict)
- `POST /api/runs/{run_id}/duplicate` -> HTTP 201 Created
- `POST /api/runs/{run_id}/pause` & `POST /api/runs/{run_id}/resume` -> HTTP 200 OK on POSIX, HTTP 501 Not Implemented on Windows

## Verification
- Unit & API tests: `python -m pytest modules/runmux/tests/lifecycle_test.py modules/runmux/tests/lifecycle_api_test.py -v` (19 passed)
- Web, adapter, and telemetry suites: `python -m pytest modules/runmux/tests/web_test.py modules/runmux/tests/web_adapter_test.py modules/runmux/tests/web_cli_test.py modules/runmux/tests/stats_test.py modules/runmux/tests/telemetry_test.py -v` (51 passed; 70 passed combined)
- Lint check: `ruff check` passed cleanly on all modified and new files.
