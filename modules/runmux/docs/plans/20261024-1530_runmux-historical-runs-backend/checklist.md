# Checklist - Runmux Phase 6C Historical Run Discovery & Events Backend

**Branch:** `codex/runmux-historical-runs-backend-20261024`
**Base Commit:** `8befeae3375740e21cdfe17a081387f0e3cf8f54`
**Status:** Complete (Backend only; branch remains unmerged)

---

## 1. Inspection & Architecture

- [x] Inspect persistent process registry (`store.py`, `models.py`)
- [x] Inspect existing history/list/detail APIs (`web.py`, `web_adapter.py`)
- [x] Differentiate 3 data categories: Run History, Metric History, Lifecycle Events
- [x] Produce existing capabilities matrix (`01_existing_capabilities_matrix.md`)
- [x] Formulate keyset pagination and filtering architecture (`00_implementation-plan.md`)

---

## 2. Storage Layer & Pagination Engine (`store.py`, `models.py`)

- [x] Add secondary composite indexes in `RunStore.migrate_db()`:
  - `(created_at, id)`
  - `(status, created_at, id)`
  - `(ended_at, id)`
  - `(name, created_at, id)`
  - `(restart_of)`
  - `(duplicate_of)`
- [x] Implement cursor serialization/deserialization (URL-safe base64 JSON)
- [x] Implement `RunStore.query_runs()` with keyset pagination:
  - Stable sort order by `created_at`, `started_at`, `ended_at`, `name`, `numeric_id`
  - Global `id` tie-breaker
  - Deterministic behavior when records are added or mutated during pagination
  - Bounded page sizes (`limit`: 1 to 200, default 50)
  - Return `items`, `next_cursor`, `has_more`, `total_count`
- [x] Implement multi-attribute filtering:
  - `status`, `state` (active/terminal)
  - `name` (exact / substring)
  - `since` / `until` with `time_field` selection
  - `exit_code`, `failed_only`, `lost_only`
  - `restart_of`, `duplicate_of`, `has_restarts`
- [x] Implement `RunStore.get_run_lineage()` (ancestor and descendant chains)

---

## 3. Web Adapter & Serialization (`web_adapter.py`)

- [x] Implement `ReadOnlyRunmux.query_runs_history()`
- [x] Implement `ReadOnlyRunmux.get_run_events()`:
  - Query discrete `telemetry_events` from `telemetry.sqlite3`
  - Bound chronological results with a keyset cursor
  - Extract structured lifecycle transitions from `runs` record
  - Explicit provenance tagging (`"telemetry_store"` vs `"registry_record"`)
  - Chronological ordering and metadata separation
- [x] Implement `ReadOnlyRunmux.get_run_lineage()`
- [x] Ensure strict allowlist serialization (no paths, args, env, tokens)

---

## 4. Authenticated Web APIs (`web.py`)

- [x] Expose `GET /api/runs/history` with query parameters:
  - `cursor`, `limit`, `sort_by`, `sort_dir`
  - `status`, `state`, `name`, `since`, `until`, `time_field`
  - `exit_code`, `failed_only`, `lost_only`, `restart_of`
- [x] Preserve existing `GET /api/runs` contract (returns `list[dict[str, Any]]`)
- [x] Expose `GET /api/runs/{run_id}/events`
- [x] Expose `GET /api/runs/{run_id}/lineage`
- [x] Reuse API session authentication and origin protections
- [x] Handle invalid cursor, invalid filter, out-of-range parameters (HTTP 400/422)
- [x] Handle missing run IDs (HTTP 404)

---

## 5. Verification & Testing

- [x] Unit tests for keyset pagination:
  - Empty and small registries
  - Boundary conditions (first page, middle, last page)
  - Invalid cursor handling
  - Collision tie-breaking on identical timestamps
  - Concurrent registry additions during pagination
- [x] Filtering tests:
  - Lifecycle states (running, finished, failed, killed, lost)
  - Time-range filters (`since`, `until`, `time_field`)
  - Name searches (including duplicate process names with distinct IDs)
  - Exit code and failure filters
- [x] Event & lineage tests:
  - Recorded events vs derived transitions with explicit provenance
  - Multi-hop restart and duplicate ancestry
- [x] Security & privacy tests:
  - Unauthenticated access rejection (HTTP 401)
  - Verification that args, environment, paths, tokens are not leaked
- [x] Performance benchmark:
  - Synthetic registry of 10,000 runs
  - Latency measurement for first page, next keyset page, and filtered query

---

## 6. Master Roadmap & Plan Updates

- [x] Update `modules/runmux/docs/plans/web-ui-handoff/RUNMUX_WEB_UI_MASTER_ROADMAP.md`
- [x] Update `STATUS.md`, `HANDOFF.md`, and this checklist
- [x] Update `modules/runmux/docs/plans/HANDOFF.md`

## Implementation Notes

- Query pages use SQL filters, stable `(sort_value, Run ID)` ordering, a created-time watermark, page limits of 1–200, and a bounded SQLite VM instruction budget. A new same-second record with a lower Run ID can still fall within the watermark.
- `total_count` is nullable unless `include_total=true`; exact counts can scan the matching records.
- Status changes between requests are reflected in each page, so a record may move into or out of a filtered result set. The cursor prevents offset row shifts; it does not create a multi-request SQLite snapshot.
- API route execution could not be exercised through TestClient in this Windows sandbox because asyncio loop initialization stalled while creating its internal socket pair. Adapter tests and route registration passed.
