# Handoff - Runmux Phase 6C: Historical Run Discovery & Events Backend

**Branch:** `codex/runmux-historical-runs-backend-20261024`
**Worktree:** `.worktrees/runmux-historical-runs-backend`
**Base Commit:** `8befeae3375740e21cdfe17a081387f0e3cf8f54`
**Assignment:** Phase 6C Historical Run Discovery, Filtering, Keyset Pagination, and Lifecycle Events Backend.

---

## 1. Operating Boundaries & Invariants

- **Strict File Ownership:** Python backend only (`store.py`, `models.py`, `web_adapter.py`, `web.py`, test files). Do NOT touch frontend files (`dashboard.js`, `dashboard.css`, `index.html`) or Phase 5C charts (owned by Agent B).
- **Read-Only Invariant:** Historical discovery must never mutate the registry or restart/terminate managed processes.
- **Contract Preservation:** Existing `GET /api/runs` remains an unchanged `list[dict[str, Any]]`. Dedicated `GET /api/runs/history` provides bounded filtering and keyset pagination.
- **Privacy Allowlist:** Redact process arguments (`argv_json`), paths (`cwd`, `log_path`), environment variables (`env_overrides_json`), and credentials (`auth_token`, `port`).
- **Provenance Truthfulness:** Explicitly differentiate recorded events (`"telemetry_store"`) from authoritative registry transitions (`"registry_record"`). Never present an inferred state transition as a recorded event.

---

## 2. Delivered API Contract

| Endpoint | Response | Bounds / behavior |
| --- | --- | --- |
| `GET /api/runs` | Existing array of allowlisted run objects | Preserved unchanged for current consumers |
| `GET /api/runs/history` | `{items, next_cursor, has_more, page_size, total_count, sort_by, sort_dir, filters}` | `limit` defaults to 50, capped at 200; SQL filters; optional exact `total_count` with `include_total=true` |
| `GET /api/runs/{run_id}/events` | `{run_id, events, next_cursor, has_more}` | `limit` defaults to 200, capped at 1,000; chronological keyset pages combine recorded telemetry and timestamped registry markers with explicit provenance |
| `GET /api/runs/{run_id}/lineage` | `{run_id, root_run_id, ancestors, descendants, total_restarts, total_duplicates, truncated}` | `limit` defaults to 200, capped at 1,000 |

History filters include status lists, active/terminal state, case-insensitive exact or substring name search, inclusive timezone-aware `since`/`until` bounds for `created_at`/`started_at`/`ended_at`, exit code, failed/lost state, restart/duplicate parent IDs, and restart existence.

The cursor binds the sort, direction, and normalized filters. Ordering uses the selected value and immutable Run ID as a unique tie-breaker. A first-page `(created_at, id)` watermark excludes runs with a later creation timestamp; a same-second insertion with a lower Run ID may still appear. Pages read current state independently, so a run whose status changes may enter or leave a filtered result set; the API does not hold a database snapshot across requests. A SQLite VM-step budget bounds query work. Exact counts are opt-in because they can scan all matching rows.

Event objects expose event type, timestamp, provenance, optional telemetry event ID, linked Run ID, and registry status/exit code. Free-text reason and arbitrary telemetry details are omitted. Registry transitions are labeled `registry_record`; persisted telemetry rows are labeled `telemetry_store`. No new event capture or retention behavior was added.

## 3. Verification and Limitations

- Focused tests: `python -m pytest tests/historical_runs_api_test.py tests/store_test.py tests/web_adapter_test.py -q -s` — 28 passed.
- Synthetic 10,000-run registry: first page 19.26 ms, next keyset page 14.54 ms, status/name-filtered page 3.22 ms (latest recorded run; Windows, local disposable SQLite).
- Lint: `python -m ruff check src/runmux/store.py src/runmux/models.py src/runmux/web_adapter.py src/runmux/web.py tests/historical_runs_api_test.py` — passed.
- Compile: `python -m compileall -q src/runmux/store.py src/runmux/models.py src/runmux/web_adapter.py src/runmux/web.py` — passed.
- Version metadata is synchronized to 0.14.0 in `pyproject.toml` and `runmux.__version__`. The ambient editable install still resolves 0.13.0 unless the module source path is explicitly selected.
- HTTP TestClient execution was blocked by Windows sandbox asyncio loop initialization hanging while opening an internal socket pair. Adapter logic and route registration are covered; new routes use the existing authenticated `/api` router.
- Lineage output is capped. `total_restarts` and `total_duplicates` count direct relationships for the selected run. Registry transitions are reconstructable only at stored timestamps; the registry is not an event log.

## 4. Publication State

- Implementation commit `7c7360935242c6ed42bc3ac54040934b67520161` is pushed to `origin/codex/runmux-historical-runs-backend-20261024`.
- The feature branch remains unmerged. Do not merge into `main` as part of Phase 6C backend work.
- A future Phase 6C frontend assignment can consume these APIs after its own approval and integration planning.
