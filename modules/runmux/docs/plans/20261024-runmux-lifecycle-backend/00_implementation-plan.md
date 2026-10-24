# Phase 4A: Authorized Process Lifecycle Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the backend-only portion of Runmux Phase 4A, providing authenticated, same-origin protected browser REST APIs for process lifecycle controls (stop/terminate, restart, duplicate, and pause/resume) reusing existing supervisor IPC and runner capabilities.

**Architecture:** A dedicated lifecycle module (`runmux.lifecycle`) encapsulates lifecycle state transitions, idempotency, and platform capability checks. The FastAPI router in `runmux.web` exposes endpoints (`/api/runs/{run_id}/stop`, `restart`, `duplicate`, `pause`, `resume`) executed asynchronously via worker threadpools, backed by session authentication, same-origin verification, and exact Run ID validation.

**Tech Stack:** Python 3.12, FastAPI, Starlette, Pydantic, psutil, SQLite WAL (`runmux.store`), pytest, ruff.

**Spec:** `modules/runmux/docs/plans/web-ui-handoff/PHASE_04A_LIFECYCLE_CONTROLS.md`

## Global Constraints

- **Scope:** Backend-only. Zero modifications to browser UI HTML/CSS/JS (`dashboard.js`), explorer tabs, terminal WebSocket attachments, or supervisor FIFO input locks.
- **Runmux Identity Invariant:** Restarting a run always creates a brand new run with a new unique Run ID (`YYYYMMDD-HHMMSS-abcdef`) and new `numeric_id`, retaining the previous run's record in terminal status and recording `restart_of=source.id`.
- **Eligibility:** A run can only be restarted if it is in `TERMINAL_STATUSES` (`finished`, `failed`, `killed`, `lost`). Restarting an active run returns `409 Conflict`.
- **Platform Limitations:** Process pause/resume (`SIGSTOP`/`SIGCONT`) is not supported on Windows by the underlying supervisor. The API must explicitly return `501 Not Implemented` with an explanatory message rather than forging state.
- **Process Survival:** Closing a browser view, tab, or WebSocket must never terminate or pause the managed process.
- **Idempotency & Races:** Stopping an already-terminal run returns `200 OK` with `status="already_terminated"`. Stale or non-existent run IDs return `404 Not Found`. Dead supervisor fallback terminates the child PID via OS signals/taskkill.
- **Security:** Every mutating endpoint must enforce same-origin verification and session authentication. Direct unauthenticated requests return `401`, and wrong-origin requests return `403`.

## Review Focus

1. **Active run restart attempt:** Client calls `POST /api/runs/{run_id}/restart` on a run with status `running` -> returns `409 Conflict` explaining the run must be stopped before restarting.
2. **Windows pause/resume:** Client calls `POST /api/runs/{run_id}/pause` on Windows -> returns `501 Not Implemented` with `"Pause is not supported on Windows without an external process API."`
3. **Supervisor crash during stop:** Client calls `POST /api/runs/{run_id}/stop` when supervisor IPC is dead but child PID is alive -> `kill_run` catches `IpcError`, executes OS `terminate_pid`, marks run `"killed"` in SQLite, and returns `200 OK`.
4. **Already-terminated stop:** Client clicks stop on an already finished run -> returns `200 OK` with `status="already_terminated"` and current run record without failing.
5. **WebSocket disconnect survival:** Client connects to `/api/runs/{run_id}/terminal`, receives output, and disconnects -> child process continues running under supervisor.

---

## File Structure

- Create: `modules/runmux/src/runmux/lifecycle.py`
  - Defines `LifecycleManager`, `LifecycleResult`, and typed exceptions (`LifecycleError`, `InvalidLifecycleTransitionError`, `LifecyclePlatformError`, `LifecycleSupervisorUnavailableError`).
- Modify: `modules/runmux/src/runmux/web.py`
  - Adds `StopRequest`, `CloneRequest` models.
  - Adds endpoints `POST /api/runs/{run_id}/stop`, `POST /api/runs/{run_id}/kill`, `POST /api/runs/{run_id}/restart`, `POST /api/runs/{run_id}/duplicate`, `POST /api/runs/{run_id}/pause`, `POST /api/runs/{run_id}/resume`.
- Create: `modules/runmux/tests/lifecycle_test.py`
  - Unit tests for `LifecycleManager` lifecycle transitions, idempotency, error conditions, and Windows platform handling.
- Create: `modules/runmux/tests/lifecycle_api_test.py`
  - Integration tests for web API endpoints, authentication, CSRF/origin enforcement, error codes, and browser disconnect survival.
- Documentation:
  - `modules/runmux/docs/plans/20261024-runmux-lifecycle-backend/LIFECYCLE_API_SPEC.md`
  - `modules/runmux/docs/plans/20261024-runmux-lifecycle-backend/00_implementation-plan.md`
  - `modules/runmux/docs/plans/20261024-runmux-lifecycle-backend/STATUS.md`
  - `modules/runmux/docs/plans/20261024-runmux-lifecycle-backend/checklist.md`
  - `modules/runmux/docs/plans/20261024-runmux-lifecycle-backend/HANDOFF.md`

---

## Stage 1: Planning and Specification Documentation

- [x] Create dated plan folder `modules/runmux/docs/plans/20261024-runmux-lifecycle-backend/`.
- [x] Document REST API contract, status codes, platform constraints, and restart identity semantics in `LIFECYCLE_API_SPEC.md`.
- [x] Document operational state in `STATUS.md`, feature tracking in `checklist.md`, and resume guidance in `HANDOFF.md`.

---

## Stage 2: Core Lifecycle Service (`lifecycle.py`)

**Files:**
- Create: `modules/runmux/src/runmux/lifecycle.py`
- Create: `modules/runmux/tests/lifecycle_test.py`

**Interfaces:**
- `LifecycleManager(state_dir: Path)`
  - `stop_run(run_id: str, *, force: bool = False) -> LifecycleResult`
  - `restart_run(run_id: str, *, force_color: bool | None = None) -> LifecycleResult`
  - `duplicate_run(run_id: str, *, force_color: bool | None = None) -> LifecycleResult`
  - `pause_run(run_id: str) -> LifecycleResult`
  - `resume_run(run_id: str) -> LifecycleResult`
- `LifecycleResult`
  - `action: str`
  - `status: str` ("ok", "already_terminated", "already_paused", "already_running")
  - `run: RunRecord`
  - `message: str`
  - `new_run: RunRecord | None = None`

- [ ] **Step 1: Write failing unit tests in `modules/runmux/tests/lifecycle_test.py`**
  - Test stop of active run marks killed.
  - Test stop of already terminal run is idempotent.
  - Test stop with dead supervisor uses fallback PID termination.
  - Test restart of terminal run creates new run record with `restart_of` link and new run ID.
  - Test restart of active run raises `InvalidLifecycleTransitionError`.
  - Test duplicate of active run creates new run with `duplicate_of`.
  - Test pause and resume on Windows raises `LifecyclePlatformError`.
  - Test invalid full ID format raises `RunNotFoundError`.
- [ ] **Step 2: Run tests to verify failure**
- [ ] **Step 3: Implement `LifecycleManager` in `modules/runmux/src/runmux/lifecycle.py`**
- [ ] **Step 4: Verify unit tests pass**
- [ ] **Step 5: Run linter `ruff check modules/runmux/src/runmux/lifecycle.py modules/runmux/tests/lifecycle_test.py`**

---

## Stage 3: Authenticated Web API Endpoints (`web.py`)

**Files:**
- Modify: `modules/runmux/src/runmux/web.py`
- Modify: `modules/runmux/src/runmux/web_adapter.py` (if needed for serialization helpers)

**Endpoints:**
- `POST /api/runs/{run_id}/stop` -> returns `200 OK`
- `POST /api/runs/{run_id}/kill` -> alias for `/stop`
- `POST /api/runs/{run_id}/restart` -> returns `201 Created`
- `POST /api/runs/{run_id}/duplicate` -> returns `201 Created`
- `POST /api/runs/{run_id}/pause` -> returns `200 OK` (POSIX) or `501 Not Implemented` (Windows)
- `POST /api/runs/{run_id}/resume` -> returns `200 OK` (POSIX) or `501 Not Implemented` (Windows)

- [ ] **Step 1: Write failing API integration tests in `modules/runmux/tests/lifecycle_api_test.py`**
  - Test 401 unauthenticated for all POST lifecycle endpoints.
  - Test 403 wrong-origin for all POST lifecycle endpoints.
  - Test 404 for non-existent and prefix run IDs.
  - Test 200 stop on running run.
  - Test 200 stop on finished run.
  - Test 201 restart on finished run returning new run record and `old_run_id`.
  - Test 409 restart on active run.
  - Test 201 duplicate on running run.
  - Test 501 pause on Windows.
  - Test 501 resume on Windows.
  - Test browser terminal WebSocket disconnect leaves child process running.
- [ ] **Step 2: Run tests to verify failure**
- [ ] **Step 3: Implement endpoint handlers in `modules/runmux/src/runmux/web.py`**
  - Integrate `LifecycleManager` using `run_in_threadpool`.
  - Map `RunNotFoundError` -> 404.
  - Map `InvalidLifecycleTransitionError` -> 409.
  - Map `LifecyclePlatformError` -> 501.
  - Map `LifecycleSupervisorUnavailableError` -> 503.
- [ ] **Step 4: Verify integration tests pass**
- [ ] **Step 5: Run linter on changed files**

---

## Stage 4: Compatibility, Regression & Platform Verification

- [ ] **Step 1: Run full Runmux and resource_metrics test suite**
  - `pytest modules/runmux/tests/`
  - `pytest modules/resource_metrics/tests/`
- [ ] **Step 2: Verify existing CLI handlers remain intact**
  - Run `runmux restart`, `runmux kill`, `runmux pause`, `runmux resume` CLI tests.
- [ ] **Step 3: Run full linter check across repo**
  - `ruff check modules/runmux modules/resource_metrics`

---

## Stage 5: Documentation & Feature Branch Delivery

- [ ] Update `STATUS.md`, `checklist.md`, and `HANDOFF.md`.
- [ ] Verify `git status` shows only intended files.
- [ ] Commit with descriptive message `feat(runmux): implement Phase 4A authenticated process lifecycle backend`.
- [ ] Push branch `codex/runmux-lifecycle-backend-20261024` to `origin`.
- [ ] Report delivery summary with commit SHA, changed files, and test evidence. Do not merge.
