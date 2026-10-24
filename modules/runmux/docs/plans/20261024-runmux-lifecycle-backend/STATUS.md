# Status — Runmux Process Lifecycle Backend (Phase 4A)

**Date:** 2026-10-24  
**Branch:** `codex/runmux-lifecycle-backend-20261024`  
**Base:** `origin/main` (commit `5ce51607`)  
**Current Stage:** Complete & Merged to `main` (Both Backend and Frontend integrated).  
**Approval State:** User authorized execution and merge into `main` using an isolated integration worktree upon test passage. Fully integrated and published.  

### Completed Evidence
- Discovered and verified existing lifecycle operations (`runner.kill_run`, `restart_run`, `duplicate_run`, `pause_run`, `resume_run`).
- Verified restart identity semantics: restarts create new unique Run records and link `restart_of`, leaving original terminal records intact.
- Verified Windows platform limitation: `SIGSTOP`/`SIGCONT` pause/resume is unsupported on Windows without external private APIs (mapped to HTTP 501 Not Implemented).
- Formulated specification and implementation plan in `00_implementation-plan.md` and `LIFECYCLE_API_SPEC.md`.
- Implemented `LifecycleManager` in `runmux.lifecycle` with lazy store initialization, immutable ID enforcement, and OS fallback kill handling.
- Implemented authenticated endpoints in `runmux.web`: `POST /api/runs/{run_id}/stop`, `POST /api/runs/{run_id}/kill`, `POST /api/runs/{run_id}/restart`, `POST /api/runs/{run_id}/duplicate`, `POST /api/runs/{run_id}/pause`, and `POST /api/runs/{run_id}/resume`.
- Extended `web_adapter.serialize_run` to expose `restart_of` and `duplicate_of`.
- **Termination failure safety audit resolved:** `LifecycleManager.stop_run` now preserves actual process/store state and raises `LifecycleError` (HTTP 500) if termination fails; never falsely reports success or marks record killed.
- **Fallback PID safety audit resolved:** `runner.kill_run` invokes `verify_run_process` before direct PID termination. If PID reuse is detected, the recycled PID is never terminated. Inconclusive or unknown process identities fail safely with `RunnerError` without authorizing termination.
- **Supervisor PID reuse protection resolved:** `runner.cleanup_supervisor_process` invokes `verify_supervisor_process` before terminating `supervisor_pid`. It validates creation time bounds and command line arguments (`"runmux.supervisor"` and run ID), preventing termination of recycled supervisor PIDs.
- **Windows `taskkill` exit code validation:** Checked for non-zero exit codes (other than 128); if process remains alive, `RunnerError` is raised.
- **API semantics clarified:** `/kill` defaults to forced termination (`force=True`, `action="kill"`), while `/stop` defaults to graceful termination (`force=False`, `action="stop"`).
- **Restart/duplicate parity and concurrency guards:** `runner.create_managed_run` and `clone_run` preserve all environment overrides from `source.env_overrides_json`. Concurrency locks reject in-flight restarts/duplicates, and repeated restarts while an active restart exists are rejected with HTTP 409 Conflict.
- **Asynchronous termination status distinguished:** When supervisor IPC accepts termination but the process remains active across the synchronous deadline, `LifecycleManager.stop_run` and the API report `status="terminating"` with process shutdown in progress.
- 37 unit and API lifecycle tests in `lifecycle_test.py` and `lifecycle_api_test.py` pass (37/37 passed).
- 79 full integration tests in web, telemetry, stats, and TUI suites pass (79/79 passed).
- `dashboard_test.js` frontend tests pass cleanly (1/1 passed).
- `ruff check` and `ruff format` pass cleanly on all modified and created files.
