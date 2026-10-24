# Handoff — Runmux Process Lifecycle Backend (Phase 4A)

**Branch:** `codex/runmux-lifecycle-backend-20261024`  
**Worktree:** `.worktrees/runmux-lifecycle-backend`  
**Base Commit:** `5ce51607` (`origin/main`)  
**Assignment:** Backend-only subset of `PHASE_04A_LIFECYCLE_CONTROLS.md`.  
**Status:** Complete & Merged to `origin/main` (Both Backend and Frontend integrated).  

## Scope & Non-Goals
- **Scope:** Backend lifecycle management service (`runmux/lifecycle.py`), core process control hardening (`runmux/runner.py`, `runmux/stats.py`), authenticated browser REST API endpoints in `runmux/web.py` (`/api/runs/{run_id}/stop`, `/kill`, `/restart`, `/duplicate`, `/pause`, `/resume`), comprehensive tests in `tests/lifecycle_test.py` and `tests/lifecycle_api_test.py`, and specification documentation in `docs/plans/20261024-runmux-lifecycle-backend/`.
- **Non-Goals:** Zero frontend modifications (`dashboard.js`, CSS, HTML), no changes to explorer tab behavior or terminal attachments, no WebSocket input-lock modifications, no WSL execution.

## Endpoints Implemented & Action Semantics
- `POST /api/runs/{run_id}/stop` -> HTTP 200 OK (graceful termination by default; `action="stop"`, defaults `force=False` for missing body or `{}`). Returns `status="ok"` on confirmed termination or `status="terminating"` when shutdown is in progress.
- `POST /api/runs/{run_id}/kill` -> HTTP 200 OK (forced termination by default; `action="kill"`, defaults `force=True` for missing body or `{}`). Returns `status="ok"` on confirmed termination or `status="terminating"` when shutdown is in progress.
- `POST /api/runs/{run_id}/restart` -> HTTP 201 Created (target must be terminal; active run returns 409 Conflict; active restart returns 409 Conflict; in-flight restart returns 409 Conflict)
- `POST /api/runs/{run_id}/duplicate` -> HTTP 201 Created (in-flight duplicate returns 409 Conflict)
- `POST /api/runs/{run_id}/pause` & `POST /api/runs/{run_id}/resume` -> HTTP 200 OK on POSIX, HTTP 501 Not Implemented on Windows

## Key Safety Invariants & Process Identity Protection
- **Termination Failure:** Never report successful termination or write a terminal status if termination failed. Actual running state is preserved in the store and HTTP 500 is returned.
- **Asynchronous Termination:** If supervisor accepted termination but the process remains active after deadline, return `status="terminating"` rather than claiming confirmed completion.
- **Fallback PID Safety:** When supervisor IPC fails, process identity is verified (`verify_run_process`) before direct PID termination. If a PID was reused by another process, the innocent process is never killed.
- **Inconclusive Process Identity:** If `verify_run_process` cannot confirm identity, fallback termination is aborted and `RunnerError` is raised. Unknown identities never authorize termination.
- **Supervisor PID Reuse Protection:** `runner.cleanup_supervisor_process()` validates `supervisor_pid` identity via `verify_supervisor_process()` before issuing OS kill commands, checking creation time bounds and command line arguments.
- **Windows taskkill Checks:** Checked for non-zero exit codes (other than 128); if process remains alive, `RunnerError` is raised.
- **Environment Overrides:** Preserved across both restart and duplicate.

## Verification
- Unit & API tests: `python -m pytest modules/runmux/tests/lifecycle_test.py modules/runmux/tests/lifecycle_api_test.py -v` (37 passed)
- Full integration & stats: `python -m pytest modules/runmux/tests/web_test.py modules/runmux/tests/web_adapter_test.py modules/runmux/tests/telemetry_test.py modules/runmux/tests/stats_test.py -v` (48 passed)
- TUI & CLI compatibility: `python -m pytest modules/runmux/tests/test_tui_adapter.py modules/runmux/tests/test_tui.py modules/runmux/tests/runtime_test.py modules/runmux/tests/readiness_test.py modules/runmux/tests/test_launch_concurrency.py -v` (31 passed)
- Frontend suite: `node --test modules/runmux/tests/dashboard_test.js` (1 passed)
- Lint check: `ruff check` and `ruff format` passed cleanly on all modified and new files.
