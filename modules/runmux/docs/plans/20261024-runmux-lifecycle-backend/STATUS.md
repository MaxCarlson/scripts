# Status — Runmux Process Lifecycle Backend (Phase 4A)

**Date:** 2026-10-24  
**Branch:** `codex/runmux-lifecycle-backend-20261024`  
**Base:** `origin/main` (commit `9f01984d`)  
**Current Stage:** Final Integration Readiness completed; ready for merge from `origin/main`.  
**Approval State:** User authorized execution; merge `origin/main`, commit and push without merge into `main`.  

### Completed Evidence
- Discovered and verified existing lifecycle operations (`runner.kill_run`, `restart_run`, `duplicate_run`, `pause_run`, `resume_run`).
- Verified restart identity semantics: restarts create new unique Run records and link `restart_of`, leaving original terminal records intact.
- Verified Windows platform limitation: `SIGSTOP`/`SIGCONT` pause/resume is unsupported on Windows without external private APIs (mapped to HTTP 501 Not Implemented).
- Formulated specification and implementation plan in `00_implementation-plan.md` and `LIFECYCLE_API_SPEC.md`.
- Implemented `LifecycleManager` in `runmux.lifecycle` with lazy store initialization, immutable ID enforcement, and OS fallback kill handling.
- Implemented authenticated endpoints in `runmux.web`: `POST /api/runs/{run_id}/stop`, `POST /api/runs/{run_id}/kill`, `POST /api/runs/{run_id}/restart`, `POST /api/runs/{run_id}/duplicate`, `POST /api/runs/{run_id}/pause`, and `POST /api/runs/{run_id}/resume`.
- Extended `web_adapter.serialize_run` to expose `restart_of` and `duplicate_of`.
- **Termination failure safety audit resolved:** `LifecycleManager.stop_run` now preserves actual process/store state and raises `LifecycleError` (HTTP 500) if termination fails; never falsely reports success or marks record killed.
- **Fallback PID safety audit resolved:** `runner.kill_run` invokes `verify_run_process` before direct PID termination. If PID reuse is detected, the recycled PID is never terminated. On Windows, `taskkill` exit codes are checked (non-zero exits other than 128 raise `RunnerError` if PID is still alive). Termination outcomes are verified within a bounded deadline.
- **API semantics clarified:** `/kill` defaults to forced termination (`force=True`, `action="kill"`), while `/stop` defaults to graceful termination (`force=False`, `action="stop"`).
- **Restart/duplicate parity and concurrency guards:** `runner.create_managed_run` and `clone_run` preserve all environment overrides from `source.env_overrides_json`. Concurrency locks reject in-flight restarts/duplicates, and repeated restarts while an active restart exists are rejected with HTTP 409 Conflict.
- **Asynchronous termination status distinguished:** When supervisor IPC accepts termination but the process remains active across the synchronous deadline, `LifecycleManager.stop_run` and the API report `status="terminating"` with process shutdown in progress, preventing false confirmed termination claims.
- **Consistent forced kill defaults:** `POST /api/runs/{run_id}/kill` defaults to `force=True` on requests with no body, `{}` empty JSON, and explicit `{"force": true}`.
- 34 unit and API lifecycle tests in `lifecycle_test.py` and `lifecycle_api_test.py` pass (34/34 passed).
- 31 TUI adapter, runtime, readiness, and launch concurrency tests pass (31/31 passed).
- Verified full web, adapter, and telemetry test suites pass cleanly.
- `ruff check` and `ruff format` pass cleanly on all modified and created files.
