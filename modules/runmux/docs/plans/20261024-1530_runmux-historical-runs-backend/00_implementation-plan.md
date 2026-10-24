# Implementation Plan - Runmux Phase 6C: Historical Run Discovery & Events Backend

**Date:** 2026-10-24
**Branch:** `codex/runmux-historical-runs-backend-20261024`
**Prerequisite:** Phase 5C integrated into `origin/main` at `8befeae3375740e21cdfe17a081387f0e3cf8f54`
**Status:** In Progress (Backend-only workstream)

---

## 1. Goal & Architectural Boundaries

Deliver a high-performance, bounded, and authenticated backend API for historical run discovery, filtering, cursor pagination, and lifecycle-event querying without altering existing process supervision or breaking existing frontend process-list API contracts.

### Strict File Ownership & Boundaries
- **Backend-Only Scope:** Python modules in `modules/runmux/src/runmux/` (`store.py`, `web_adapter.py`, `web.py`, `models.py`) and dedicated unit/integration tests in `modules/runmux/tests/`.
- **Frontend Protection:** Zero modifications to `dashboard.js`, `dashboard.css`, or `index.html`. (Agent B owns Phase 5C frontend charts and Phase 6 frontend integration).
- **Read-Only Invariant:** Historical run queries and event lookups must remain strictly read-only; they must never mutate the registry or restart/terminate processes.
- **Privacy & Security:** All run metadata outputs must pass through strict serialization allowlisting, omitting process arguments (`argv_json`), working directories (`cwd`), environment variables (`env_overrides_json`), and IPC credentials (`auth_token`, `port`).

---

## 2. Technical Design & Capabilities

### A. Indexing & Schema Upgrades (`registry.sqlite3`)
In `RunStore.migrate_db()`, introduce secondary composite indexes:
1. `idx_runs_created_at_id`: `(created_at, id)` for default reverse-chronological and forward pagination.
2. `idx_runs_status_created_at`: `(status, created_at, id)` for lifecycle state filtering (e.g. `failed`, `lost`, `running`).
3. `idx_runs_ended_at_id`: `(ended_at, id)` for filtering recent completions and failures.
4. `idx_runs_name_created_at`: `(name, created_at, id)` for name searches and duplicate process name resolution.
5. `idx_runs_restart_of`: `(restart_of)` for forward lineage queries.
6. `idx_runs_duplicate_of`: `(duplicate_of)` for duplicate tree queries.

### B. Keyset (Cursor) Pagination Engine
- **Cursor Structure:** Opaque URL-safe base64-encoded JSON containing `(sort_column, sort_value, run_id, sort_direction)`.
- **Deterministic Tie-Breaking:** `runs.id` is globally unique and immutable (22 characters). It acts as the final tie-breaker for all sort orders.
- **Query Structure:**
  ```sql
  WHERE (status IN (...))
    AND (created_at < :cursor_val OR (created_at = :cursor_val AND id < :cursor_id))
  ORDER BY created_at DESC, id DESC
  LIMIT :page_size + 1
  ```
- **Guarantees:**
  - No `OFFSET` scans: page traversal seeks after the last `(sort_value, id)` key.
  - A first-page `(created_at, id)` watermark excludes runs with a later creation timestamp. A same-second new run with a lower Run ID can still appear after the cursor.
  - Pages read current state independently; a status update may move a record into or out of a filtered result set. This is not a multi-request database snapshot.
  - A SQLite VM-step budget bounds pathological filter work; callers can narrow filters after a budget error.
  - Explicit bounded page sizes: default 50, maximum 200 items per response.
  - Bounded response memory: fetch at most `limit + 1` records; exact total counts are opt-in because they can scan all matches.
  - Invalid cursor handling: returns HTTP 400 with actionable validation detail.

### C. Rich Filtering Capabilities
- `status`: Single status or comma-separated list (`running,failed,killed`).
- `state`: Macro filter (`active` = pending/running/paused; `terminal` = finished/failed/killed/lost).
- `name`: Case-insensitive substring match or exact match.
- `since` / `until`: ISO 8601 UTC timestamp or Unix epoch float.
- `time_field`: Target field for time filtering (`created_at`, `started_at`, `ended_at`).
- `exit_code`: Specific exit code integer.
- `failed_only`: Boolean flag matching `status = 'failed'` or `(status = 'finished' AND exit_code != 0)`.
- `lost_only`: Boolean flag matching `status = 'lost'`.
- `restart_of` / `duplicate_of`: Exact parent run ID.
- `has_restarts`: Boolean flag finding parent runs that have been restarted.

### D. Genuine Lifecycle Events & Provenance
Expose `GET /api/runs/{run_id}/events` combining:
1. **Recorded Events (`provenance: "telemetry_store"`):** Discrete events recorded in `telemetry_events` table (e.g. pause, resume, worker recovery, checkpoint events), returned in bounded chronological cursor pages.
2. **Registry Markers (`provenance: "registry_record"`):** Structured timestamps and relationships from `runs` table:
   - `registered` at `created_at`
   - `started` at `started_at`
   - `terminated` at `ended_at` with `exit_code`, `status`
   - `restarted_from` / `restarted_by` with linked Run IDs
   - `duplicated_from` / `duplicated_by` with linked Run IDs
3. **Explicit Distinction:** Every event object has a `provenance` field (`"telemetry_store"`, `"registry_record"`). The registry is not an event log; missing transitions are not reconstructed. Free-text reasons and arbitrary event details are withheld without a safe schema.

### E. Endpoints & API Contracts
1. `GET /api/runs/history`:
   - Paginated historical discovery endpoint returning items, cursor, page metadata, and active filters.
2. `GET /api/runs`:
   - Existing browser process-list endpoint. Retains 100% backward compatibility (returns the existing `list[dict[str, Any]]`).
3. `GET /api/runs/{run_id}/events`:
   - Returns chronological list of genuine lifecycle events and registry state transitions with explicit provenance.
4. `GET /api/runs/{run_id}/lineage`:
   - Returns full ancestor and descendant tree of restarts and duplicates.

---

## 3. Staged Implementation Plan

- **Stage 1: Storage Layer & Pagination Engine (`store.py`, `models.py`)**
  - Add indexes in `migrate_db`.
  - Implement `query_runs_keyset` with cursor generation, validation, dynamic filtering, and stable tie-breaking.
  - Implement lineage traversal methods (`get_run_lineage`).
- **Stage 2: Web Adapter Integration (`web_adapter.py`)**
  - Add `ReadOnlyRunmux.query_runs_history()` and `ReadOnlyRunmux.get_run_events()`.
  - Implement secure allowlist serialization and provenance tagging.
- **Stage 3: Authenticated Web Endpoints (`web.py`)**
  - Expose `GET /api/runs/history`, `GET /api/runs/{run_id}/events`, `GET /api/runs/{run_id}/lineage`.
  - Maintain backward compatibility for `GET /api/runs`.
  - Add session authentication and validation error handlers.
- **Stage 4: Comprehensive Test Battery & Benchmarking**
  - Unit tests for cursor encoding/decoding, boundary handling, concurrent additions, collision tie-breaking.
  - Scalability benchmark with 10,000 synthetic runs; report first-page, next-page, and filtered-query latency.
- **Stage 5: Documentation & Integration Readiness**
  - Update roadmap, `STATUS.md`, `HANDOFF.md`, `checklist.md`.
  - Verify all combined backend tests.
