# Runmux Web UI — Phase 4A Lifecycle API Specification

This document details the backend REST API contract for process lifecycle controls (Phase 4A).

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

### A. Stop / Terminate Run
- **Route:** `POST /api/runs/{run_id}/stop`
- **Alias:** `POST /api/runs/{run_id}/kill`
- **Request Body (optional):**
  ```json
  {
    "force": false
  }
  ```
- **Response (200 OK):**
  ```json
  {
    "action": "stop",
    "status": "ok",
    "message": "Run stopped successfully.",
    "run": {
      "id": "20261024-051200-abcdef",
      "numeric_id": 3,
      "status": "killed",
      "connection": "not-active",
      ...
    }
  }
  ```
- **Idempotency & Race Handling:**
  - If the run is already in a terminal status (`finished`, `failed`, `killed`, `lost`), returns `200 OK` with `status: "already_terminated"` and `message: "Run '...' is already <status>."`.
  - If the supervisor process is unreachable (`IpcError`), falls back to terminating the child PID via OS signals (`taskkill /T` on Windows, `SIGTERM`/`SIGKILL` on POSIX) and updates status to `"killed"` in the SQLite store.

---

### B. Restart Run
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
    "message": "Run restarted as 20261024-051530-987654.",
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
- **Identity Invariants:**
  - Preserves established Runmux identity semantics: restarts do **not** mutate or overwrite the old run record.
  - A brand new run record is inserted with a new unique timestamp-based Run ID and new `numeric_id`.
  - `restart_of` points to the old run ID.
  - The historical output log of the old run is preserved in its directory.
- **Eligibility:**
  - Allowed **only** when the target run is in `TERMINAL_STATUSES` (`finished`, `failed`, `killed`, `lost`).
  - Attempting to restart an active run returns `409 Conflict`:
    `"Cannot restart active run. Stop the run first before restarting, or duplicate it."`

---

### C. Duplicate Run
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
    "message": "Run duplicated as 20261024-051600-112233.",
    "run": {
      "id": "20261024-051600-112233",
      "numeric_id": 5,
      "status": "running",
      "duplicate_of": "20261024-051200-abcdef",
      "connection": "connected",
      ...
    }
  }
  ```
- **Eligibility:** Allowed for both active and terminal runs, spawning an independent parallel managed run with identical arguments, working directory, and name.

---

### D. Pause Run
- **Route:** `POST /api/runs/{run_id}/pause`
- **Platform Constraint (Windows):**
  - Windows does not support `SIGSTOP`/`SIGCONT` without kernel debugging hooks or private NT APIs.
  - On Windows, returns `501 Not Implemented` with detail:
    `"Pause is not supported on Windows without an external process API."`
- **Response on Supported Platforms (POSIX) (200 OK):**
  ```json
  {
    "action": "pause",
    "status": "ok",
    "message": "Run paused.",
    "run": {
      "id": "20261024-051200-abcdef",
      "status": "paused",
      ...
    }
  }
  ```
- **Eligibility & Idempotency:**
  - Terminal runs cannot be paused -> returns `409 Conflict` (`"Cannot pause terminal run."`).
  - If already paused -> returns `200 OK` with `status: "already_paused"`.

---

### E. Resume Run
- **Route:** `POST /api/runs/{run_id}/resume`
- **Platform Constraint (Windows):**
  - On Windows, returns `501 Not Implemented` with detail:
    `"Resume is not supported on Windows without an external process API."`
- **Response on Supported Platforms (POSIX) (200 OK):**
  ```json
  {
    "action": "resume",
    "status": "ok",
    "message": "Run resumed.",
    "run": {
      "id": "20261024-051200-abcdef",
      "status": "running",
      ...
    }
  }
  ```
- **Eligibility & Idempotency:**
  - Terminal runs cannot be resumed -> returns `409 Conflict` (`"Cannot resume terminal run."`).
  - If already running -> returns `200 OK` with `status: "already_running"`.

---

## 3. Process Survival Invariant

Closing an attached browser session, closing a tab, or disconnecting the WebSocket `/api/runs/{run_id}/terminal` executes only an `op="detach"` IPC call to release the view session lease.
It **never** terminates, stops, or pauses the managed program. The supervised process continues executing in the background.

---

## 4. Frontend Integration Requirements (For Phase 3/4 UI Agent)

1. **Confirmation Dialogs:**
   - Destructive actions (Stop / Terminate) MUST prompt the user with a confirmation mentioning **both** the human-readable run name and the exact Run ID (`20261024-051200-abcdef`).
2. **Restart Tab Reconciliation:**
   - Since `POST /api/runs/{run_id}/restart` returns `201 Created` with a `new_run_id`, the frontend should update its tab model or navigate the active tab to the new Run ID, keeping the old run entry viewable in history.
3. **Platform Disabling:**
   - If operating on Windows, the UI should disable or hide "Pause" / "Resume" buttons with a tooltip indicating "Not supported on Windows".
4. **Action Pending & Error Handling:**
   - The UI should display pending states on button click to prevent double submissions.
   - On `409 Conflict` (e.g. attempting to restart a running process), display the returned server message: "Cannot restart an active run; stop the run first or duplicate it."
