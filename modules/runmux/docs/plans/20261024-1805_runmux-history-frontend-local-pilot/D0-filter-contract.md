# D0 — History Filter Contract and Task Notes

This is coordinator-prepared input for D1–D3. The backend/API contract is established; do not change it.

## Current source and test locations

- History controls: `modules/runmux/src/runmux/web_static/index.html`, section `#history-view` / `form#history-filter-form` (currently around lines 127–147).
- Existing filter styling: `modules/runmux/src/runmux/web_static/assets/dashboard.css`, `.history-filters` and its `max-width: 1100px` / `700px` rules (around lines 675–730).
- Request state and URL: `modules/runmux/src/runmux/web_static/assets/dashboard.js`, `runHistoryFilters`, `runHistoryQueryUrl`, `setHistoryFilter`, `readHistoryFiltersFromControls`, `applyHistoryFilters`, `applyHistoryPreset`, `refreshRunHistory`, `resetRunHistoryPages` (around lines 38, 124–216, 412–459).
- Existing DOM harness: `modules/runmux/tests/dashboard_test.js`, `dashboardHarness()` (around line 70) and history tests starting at `testHistoricalExplorerUsesBoundedCursorPages()` (around line 2059). Reuse this; do not add a new test framework.
- Existing live-browser tests: `modules/runmux/tests/browser_e2e_test.js`, Phase 6C section beginning around line 530; viewport loop around line 850.
- API contract: `modules/runmux/src/runmux/web.py`, authenticated `GET /api/runs/history` (around line 127), forwarding to the existing bounded `RunStore.query_runs()` implementation in `store.py` (around line 447).
- Representative backend cases: `modules/runmux/tests/historical_runs_api_test.py`, filter/identity tests around line 88, API allowlist/event cases around line 148, and 10,000-run bounded store query around line 224.

## Filter parameter schema

The endpoint accepts query parameters. `cursor`, `limit`, `sort_by`, and `sort_dir` are already implemented by the frontend. Existing UI filters are partial `name`, `status`, `since`, `until`, `time_field`, `failed_only`, and `lost_only`.

| Query parameter | Accepted value and behavior | Empty/default behavior | UI representation |
|---|---|---|---|
| `state` | Optional exact enum `active` or `terminal`. `active` covers pending/running/paused; `terminal` covers finished/failed/killed/lost. Anything else raises store `ValueError` and the HTTP route returns 400. | Omit when unset. | Select: Any state / Active / Terminal. Stable ID `history-state-filter` (distinct from the existing status-message element `#history-state`). |
| `name_exact` | Optional boolean; meaningful with `name`. When true, `name` is case-insensitive equality; otherwise `name` is an escaped case-insensitive substring. | Omit/false when no name is supplied. Never send `name_exact=true` by itself. | Checkbox `history-name-exact` alongside the existing name input. |
| `exit_code` | Optional integer equality against the stored SQLite INTEGER column. Negative and zero values are valid; do not use truthiness to omit zero. SQLite integer storage is signed 64-bit. | Omit when blank. Reject non-integer and out-of-storage-range input client-side. FastAPI rejects malformed integer query values with 422; validly typed queries reach the store. | Number input `history-exit-code-filter`, integer step; allow signed values. |
| `restart_of` | Optional string equality against a run's explicit restart-parent Run ID. The store does not infer a relation or resolve a name. | Omit when blank after trimming. | Text input `history-restart-parent-filter`; accept a full explicit Run ID, with no name/command/timestamp inference. |
| `duplicate_of` | Optional string equality against a run's explicit duplicate-parent Run ID. | Omit when blank after trimming. | Text input `history-duplicate-parent-filter`; accept a full explicit Run ID. |
| `has_restarts` | Optional boolean. `true` returns runs with at least one direct restart child; `false` means no filter, not “must have no restarts.” | Omit unless checked. There is no API `has_restarts=false` filter. | Checkbox `history-has-restarts`. |
| `failed_only` / `lost_only` | Existing booleans; backend rejects both true together with HTTP 400. `failed_only` includes status failed or finished with nonzero exit code; `lost_only` means status lost. | Both false unless corresponding preset is active. | Existing mutually exclusive Failures / LOST presets. |

`restart_of` and `duplicate_of` currently have no additional store-level format validation; they are exact string matches. Trim surrounding input whitespace and omit an empty result, but do not infer or rewrite IDs. Do not invent an API filter for “has duplicates.” `include_total` remains false/omitted by default.

## Canonical filter and preset state

Maintain one canonical object for effective server query values. Preset identity is UI state that must match its effective constraints:

- `recent` clears all filters to defaults. It must not leave either preset boolean set after manual edits or Clear.
- `completed` sets `status=finished`; that criterion is already visible in the status control.
- `failures` sets `failed_only=true`, `lost_only=false`; `lost` sets the inverse. These remain visibly active if combined with compatible manual filters such as name/date/exact-name/exit code.
- If a manual status/state edit conflicts with the active failures/LOST predicate (for example, failures + status=lost, or either preset + state=active), clear that preset boolean and its active button state. Compatible constraints may remain combined while the preset remains visibly active.
- Applying a manual exact-name or other compatible criterion must not silently clear the active preset. Clearing all filters resets every query field, preset boolean, and active-button indication.
- The two preset booleans are mutually exclusive. No UI path may send both true.
- Normalize controls before comparing effective state. A submission that does not change normalized filters should not dispatch another history request.
- Any effective server filter, sort, or page-size change resets the cursor stack and aborts/ignores older requests. The backend binds a cursor to the complete normalized filter set and sort; a mismatched cursor returns HTTP 400.

Date controls stay as previously implemented; do not change their meaning. Sort values remain `created_at`, `started_at`, `ended_at`, `name`, or `numeric_id`, with direction `asc`/`desc`; limit remains 50/100/200 in the UI (API accepts 1–200).

## Pagination mutation semantics for D4

The backend cursor is keyset pagination and captures an upper `(created_at, id)` boundary on the first page, preventing later/newer inserts from appearing in subsequent pages. It does not provide a full cross-request snapshot: deletes or updates that change filter membership can cause later pages to omit or shift records. D4 must test and document this behavior; it must not assert snapshot isolation.
