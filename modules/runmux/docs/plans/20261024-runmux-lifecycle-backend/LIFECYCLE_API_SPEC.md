# Runmux Web UI — Phase 4A Lifecycle API Specification



This document details the backend REST API contract for process lifecycle controls (Phase 4A), including safety constraints, failure handling, concurrency protections, and platform guarantees.



---



## 1. Security & Protection Model



1. **Authentication:**

   - Every mutating endpoint requires an active session cookie (`web_ui_session`) established via `/auth/login`.

   - Requests without a valid session cookie return `401 Unauthorized`.

2. **Same-Origin Protection (CSRF Prevention):**

   - Implemented via `web_ui_tools.app.secure_local_requests` middleware.

   - Enforces matching `Origin` / `Referer` headers against loopback host bindings (`127.0.0.1`, `localhost`, `[::1]`).

   - Cross-origin and wrong-origin mutation requests return `403 Forbidden`.

3. **Exact Immutable Run ID Requirement:**

   - All lifecycle routes accept only full immutable Run IDs matching `^\d{8}-\d{6}-[0-9a-f]{6}$` (e.g., `20261024-051200-abcdef`).

   - Short prefixes or numeric IDs are rejected with `404 Not Found` to prevent accidental destructive operations on misidentified processes.



---



## 2. Supported Endpoints



### A. Stop Run (Graceful Termination)

- **Route:** `POST /api/runs/{run_id}/stop`

- **Semantics:** Requests graceful termination (`force=False` by default; SIGTERM on POSIX, Ctrl-Break/close on Windows). Both empty request body and `{}` consistently default to `force=False`. An explicit `{"force": true}` can be supplied to request forced termination.

- **Request Body (optional):**

  ```json

  {

    "force": false

  }

  ```

- **Response (200 OK):**

  When termination completes synchronously:

  ```json

  {

    "action": "stop",

    "status": "ok",

    "message": "Run '...' stopped successfully.",

    "run": {

      "id": "20261024-051200-abcdef",

      "numeric_id": 3,

      "status": "killed",

      "connection": "not-active",

      ...

    }

  }

  ```

  When supervisor accepts termination but process shutdown is asynchronous / in progress:

  ```json

  {

    "action": "stop",

    "status": "terminating",

    "message": "Termination requested for run '...'; process shutdown is in progress.",

    "run": {

      "id": "20261024-051200-abcdef",

      "numeric_id": 3,

      "status": "running",

      "connection": "connected",

      ...

    }

  }

  ```

- **Idempotency & Race Handling:**

  - If the run is already in a terminal status (`finished`, `failed`, `killed`, `lost`), returns `200 OK` with `status: "already_terminated"` and `message: "Run '...' is already <status>."`.



---



### B. Kill Run (Forced Termination)

- **Route:** `POST /api/runs/{run_id}/kill`

- **Semantics:** Requests immediate, forced termination (`force=True` by default; SIGKILL on POSIX, `/F` on Windows taskkill). Both empty request body and `{}` consistently default to `force=True`. An explicit `{"force": false}` can be supplied to request graceful termination.

- **Request Body (optional):**

  ```json

  {

    "force": true

  }

  ```

- **Response (200 OK):**

  When termination completes synchronously:

  ```json

  {

    "action": "kill",

    "status": "ok",

    "message": "Run '...' killed successfully.",

    "run": {

      "id": "20261024-051200-abcdef",

      "numeric_id": 3,

      "status": "killed",

      "connection": "not-active",

      ...

    }

  }

  ```

  When supervisor accepts kill IPC but process shutdown is asynchronous / in progress:

  ```json

  {

    "action": "kill",

    "status": "terminating",

    "message": "Termination requested for run '...'; process shutdown is in progress.",

    "run": {

      "id": "20261024-051200-abcdef",

      "numeric_id": 3,

      "status": "running",

      "connection": "connected",

      ...

    }

  }

  ```

- **Idempotency:**

  - Returns `200 OK` with `status: "already_terminated"` if the run was already finished/killed.



---



### C. Termination Safety & Fallback PID Rules

1. **Supervisor IPC First:**
   - Termination is first requested through the live supervisor over loopback IPC (`op="kill"`, payload `force=bool`).
2. **Supervisor Failure & Process Identity Verification:**
   - If supervisor IPC fails (e.g. supervisor process died or connection refused), fallback PID termination is executed.
   - **PID Reuse Protection:** Before sending any OS kill command to `record.pid`, `runner.kill_run` invokes `verify_run_process` to validate the process creation timestamp against `record.started_at` / `record.created_at`.
   - If the PID has been recycled by the OS and belongs to another process (`"pid reused by another process"`), **the PID is never terminated**. The run record is updated as dead, preventing destructive termination of innocent host processes.
   - **Inconclusive Identity Fails Safely:** If `verify_run_process` returns an inconclusive identity (`proc is None` or unknown reason), termination is aborted and `RunnerError` is raised. An unknown or unverified process identity must never authorize termination.
3. **Supervisor PID Cleanup Protection:**
   - In `runner.cleanup_supervisor_process()`, before terminating `supervisor_pid`, `verify_supervisor_process()` validates that the PID still belongs to the intended Runmux supervisor via process creation time bounds and command line verification (`"runmux.supervisor"` and matching run ID).
   - Recycled supervisor PIDs or unconfirmed supervisor identities are never terminated.
4. **Windows `taskkill` Verification:**
   - On Windows, `terminate_pid` runs `taskkill /PID <pid> /T [/F]` and checks exit codes. Exit code 128 (process not found) is accepted as process already exited. Any non-zero exit code where the process remains alive raises `OSError` rather than silently failing.
5. **Termination Outcome Verification:**
   - After issuing termination, `runner.kill_run` polls to verify process exit within a bounded deadline. If the process remains alive after deadline, `RunnerError` is raised.
6. **No False Success or Premature Terminal Status:**
   - `LifecycleManager.stop_run()` never writes a terminal status solely because termination failed. If `kill_run` raises `RunnerError`, the run's actual state is preserved in SQLite, and `HTTP 500 Internal Server Error` is returned to the client.

---

### D. Restart Run

- **Route:** `POST /api/runs/{run_id}/restart`

- **Request Body (optional):**

  ```json

  {

    "force_color": true

  }

  ```

- **Response (201 Created):**

  ```json

  {

    "action": "restart",

    "status": "ok",

    "old_run_id": "20261024-051200-abcdef",

    "new_run_id": "20261024-051530-987654",

    "message": "Run '20261024-051200-abcdef' restarted as '20261024-051530-987654'.",

    "run": {

      "id": "20261024-051530-987654",

      "numeric_id": 4,

      "status": "running",

      "restart_of": "20261024-051200-abcdef",

      "connection": "connected",

      ...

    }

  }

  ```

- **Identity Invariants & State Guards:**

  - Restarts do **not** mutate or overwrite the old run record. A brand new record is created with a new unique Run ID, new `numeric_id`, and `restart_of` pointing to the source.

  - Allowed **only** when target run is in `TERMINAL_STATUSES` (`finished`, `failed`, `killed`, `lost`).

  - Active runs cannot be restarted (`409 Conflict: Cannot restart active run`).

- **Duplicate Launch Prevention:**

  - **In-flight Guard:** Concurrent restart requests for the same run ID are locked and rejected with `409 Conflict: Restart is already in progress`.

  - **Active Restart Guard:** Repeated restart requests while a previously restarted run is currently active (`pending`, `running`, `paused`) are rejected with `409 Conflict: Cannot restart run '...': active restart '...' is already running. Use duplicate for concurrent runs.`

- **Environment Override Parity:**

  - All custom environment variables recorded in `source.env_overrides_json` are faithfully preserved in the new restarted run.



---



### E. Duplicate Run

- **Route:** `POST /api/runs/{run_id}/duplicate`

- **Request Body (optional):**

  ```json

  {

    "force_color": true

  }

  ```

- **Response (201 Created):**

  ```json

  {

    "action": "duplicate",

    "status": "ok",

    "source_run_id": "20261024-051200-abcdef",

    "new_run_id": "20261024-051600-112233",

    "message": "Run '20261024-051200-abcdef' duplicated as '20261024-051600-112233'.",

    "run": {

      "id": "20261024-051600-112233",

      "numeric_id": 5,

      "status": "running",

      "duplicate_of": "20261024-051200-abcdef",

      ...

    }

  }

  ```

- **Semantics:**

  - Allowed from both active and terminal states.

  - Preserves program arguments, working directory, and all environment overrides.

  - In-flight concurrency lock rejects rapid duplicate clicks (`409 Conflict: Duplicate is already in progress`).



---



### F. Pause & Resume (POSIX Only)

- **Routes:**

  - `POST /api/runs/{run_id}/pause`

  - `POST /api/runs/{run_id}/resume`

- **Response (200 OK on POSIX):**

  ```json

  {

    "action": "pause",

    "status": "ok",

    "message": "Run paused successfully.",

    "run": { ... }

  }

  ```

- **Platform Limitation on Windows:**

  - Windows does not support native `SIGSTOP`/`SIGCONT`.

  - On Windows host, both endpoints return **`501 Not Implemented`**:

    ```json

    {

      "detail": "Pause/resume is not supported on Windows without an external process API."

    }

    ```

- **Idempotency:**

  - Pausing an already paused run returns `200 OK` with `status: "already_paused"`.

  - Resuming an already running run returns `200 OK` with `status: "already_running"`.



---



## 3. Browser View & Disconnect Invariants



- **Closing browser tabs / WebSocket disconnect:** Closing a browser window, disconnecting the terminal WebSocket, or reloading the dashboard **never** terminates or pauses the supervised process.

- The WebSocket cleanup handler only releases the browser viewer lease via `op="detach"`.

