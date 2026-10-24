# Checklist — Runmux Process Lifecycle Backend (Phase 4A)

- [x] Stage 1: Planning and Specification Documentation
  - [x] Create dated plan folder `modules/runmux/docs/plans/20261024-runmux-lifecycle-backend/`.
  - [x] Verify existing CLI/TUI lifecycle semantics and restart identity preservation.
  - [x] Create `LIFECYCLE_API_SPEC.md`, `00_implementation-plan.md`, `STATUS.md`, `checklist.md`, and `HANDOFF.md`.
- [x] Stage 2: Core Lifecycle Service (`lifecycle.py`)
  - [x] Write failing unit tests in `modules/runmux/tests/lifecycle_test.py`.
  - [x] Implement `LifecycleManager` in `modules/runmux/src/runmux/lifecycle.py`.
  - [x] Verify unit tests pass and linter is clean.
- [x] Stage 3: Authenticated Web API Endpoints (`web.py`)
  - [x] Write failing integration tests in `modules/runmux/tests/lifecycle_api_test.py`.
  - [x] Implement endpoints `/api/runs/{run_id}/stop`, `/kill`, `/restart`, `/duplicate`, `/pause`, `/resume` in `modules/runmux/src/runmux/web.py`.
  - [x] Verify integration tests pass.
- [x] Stage 4: Compatibility, Regression & Platform Verification
  - [x] Run full Runmux and resource_metrics test suites.
  - [x] Verify CLI commands remain backward compatible.
  - [x] Confirm browser disconnect does not stop or pause process.
- [x] Stage 5: Documentation & Feature Branch Delivery
  - [x] Update `STATUS.md`, `checklist.md`, `HANDOFF.md`.
  - [x] Commit all changes to `codex/runmux-lifecycle-backend-20261024`.
  - [x] Push to `origin` without merging.
- [x] Stage 6: Final Lifecycle Safety Review & Hardening
  - [x] Fix termination failure handling in `LifecycleManager.stop_run`: never report success or mark killed on failure; preserve state and return HTTP 500 error.
  - [x] Harden fallback PID safety in `runner.kill_run`: validate process identity via `verify_run_process` before termination to prevent terminating recycled PIDs.
  - [x] Verify `taskkill` results on Windows: check exit codes and ensure non-zero exits (other than 128) raise `RunnerError` when PID remains alive.
  - [x] Clarify `/stop` vs `/kill` API semantics: separate endpoints with distinct defaults (`/stop` -> `force=False`, `action="stop"`; `/kill` -> `force=True`, `action="kill"`).
  - [x] Ensure restart/duplicate environment override parity: preserve `env_overrides_json` in `clone_run` and `create_managed_run`.
  - [x] Concurrency and repeated launch guards: reject in-flight operations and repeated restarts while active restart exists with HTTP 409 Conflict.
  - [x] Add focused regression tests for termination failure, reused PIDs, Windows taskkill errors, and API semantics.
  - [x] Run test suite and ruff checks cleanly.
  - [x] Push corrections to feature branch.
- [x] Stage 7: Final Integration Readiness
  - [x] Accurately distinguish pending/accepted asynchronous termination (`status="terminating"`) when process remains active after IPC.
  - [x] Ensure `POST /api/runs/{run_id}/kill` consistently defaults to forced termination (`force=True`) on empty body and `{}`.
  - [x] Add regression tests for asynchronous termination and forced kill default body handling.
  - [x] Fetch and merge latest `origin/main` into feature branch.
  - [x] Resolve any merge conflicts, preserving Phase 3 and telemetry backend.
  - [x] Confirm zero frontend files modified.
  - [x] Verify all test suites pass on Windows.
  - [x] Commit and push updated feature branch to `origin/codex/runmux-lifecycle-backend-20261024`.
