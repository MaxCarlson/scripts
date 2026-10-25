# Runmux Phase 6C Historical Explorer Frontend

**Date:** 2026-10-24
**Branch:** `codex/runmux-6c-history-frontend-local-pilot-20261024`
**Worktree:** `.worktrees/runmux-6c-history-frontend-local-pilot`
**Baseline:** `4591b3247bdfafe82f0b8d1a73f40002152a6c2b`
**Scope:** Browser implementation of Phase 6C historical run discovery, lifecycle event presentation, and explicit restart/duplicate lineage.

## Goal and boundaries

Add a bounded, paginated History workspace view using the existing authenticated Phase 6C endpoints. Preserve the current process explorer, process tabs, Output, Terminal, Details, lifecycle controls, and Phase 5C charts. Keep Run ID as the only run identity. Do not change API contracts, backend behavior, telemetry retention, event persistence, supervisor behavior, or other Phase 6 slices.

The browser must not disclose arguments, working directories, environment data, or credentials. Closing the History view or a process tab remains view-only. Persisted telemetry events and registry-derived timestamp markers must be visibly labeled by provenance; missing events or relationships remain explicitly empty/unavailable.

## Approaches considered

1. **Add filters to the live process explorer.** This would reuse its location, but risks replacing or overloading the active-run workflow and cannot cleanly represent cursor pages plus historical event/lineage detail.
2. **Open a modal history browser.** This would avoid changing workspace tabs, but gives a large table, filter controls, pagination, and event detail too little space and creates nested navigation.
3. **Add a dedicated History workspace tab (selected).** It preserves the process explorer and existing run tabs, provides adequate room for filters and a bounded table, and can open any row into the existing immutable Run ID view. The existing Details area will host per-run events and explicit lineage navigation.

## Data and interaction contract

- Query only `GET /api/runs/history`; default to 50 items and keep every response bounded. Use cursor history for Previous/Next navigation; never load the entire registry. Do not request exact totals by default.
- Use only API-supported filters and sort keys: status/state, name, inclusive `since`/`until` with `time_field`, exit code, failed/lost, restart/duplicate parent, and restart existence; sort by `created_at`, `started_at`, `ended_at`, `name`, or `numeric_id` with supported direction.
- Reset cursors on filter/sort changes. Abort or disregard stale requests when filters, page, selected Run ID, or workspace change. Render at most one server page (maximum 200) plus bounded event/lineage views.
- Opening a row selects/opens the existing run view using its full immutable Run ID. Duplicate names never share state. The History workspace tab and per-run tabs are view-only.
- Fetch `/api/runs/{run_id}/events` and `/lineage` only for the selected run's Details view. Label `telemetry_store` as recorded telemetry and `registry_record` as a registry timestamp/relationship marker. No inferred lifecycle events. Navigate only by explicit relationship Run IDs.
- Use text nodes/textContent for server values. The backend allowlist is the source for safe fields; never render private command arguments, cwd, environment, or secrets.
- Preserve the established dark IDE styling and responsive behavior. Do not modify Phase 5C chart semantics or address issue #11.

## Stages and acceptance

1. **Contract and plan:** verify endpoint parameters, cursor/filter binding, authentication inheritance, event provenance, lineage IDs, privacy allowlist, and Phase 5C integration. (Complete.)
2. **Presentational helper:** the worker received an isolated table-renderer/test task (`HIST-TABLE-01`) but spent about 14 minutes exploring the existing harness and produced no file changes. The coordinator cancelled it, recorded an unsuccessful delegation, then implemented `history_view.js` and its standalone focused test. The follow-up routing ledger records the missing concrete fixture/test-harness instructions and the effort-budget adjustment.
3. **Controller and markup:** add the History workspace view, supported filter/sort controls, cursor stack, request cancellation/generation guards, and safe navigation while retaining existing tabs and controls.
4. **Details integration:** implemented event provenance and explicit lineage in selected-run Details with missing-run, no-event, and API error states.
5. **Validation:** focused JS and Python API/adapter suites pass with explicit worktree `PYTHONPATH`; the complete real headless Chrome E2E passes against synthetic registry/telemetry state on loopback ports 8791/9444. Desktop screenshots were visually inspected; E2E exercised widths 390, 768, 1366, 1920, and 2560 pixels. Coverage includes duplicate names, request bounds, stale responses, unauthorized sessions, malformed filters, missing runs, no-event/no-lineage states, and existing process controls.
6. **Review and publication:** final diff/status review, exact validation and limitations, commit the feature branch, push it, and leave it unmerged for independent GPT-6.1 Sol Medium audit.

## Baseline evidence

- Branch/worktree at the pinned commit was clean before implementation.
- `node modules/runmux/tests/dashboard_test.js` passed on the baseline.
- `node modules/runmux/tests/browser_e2e_test.js` initially could not start its disposable loopback server inside the socket sandbox. The same command passed after an approved elevated run, using disposable state and real headless Chrome. This is an environment boundary, not an application defect.
- Backend history/API tests and handoff confirm a 1–200 run page cap, 1–1,000 event cap, supported sort/filter set, cursor-bound filters/sort, authenticated `/api`, safe metadata allowlists, explicit event provenance, and explicit restart/duplicate Run IDs. The backend does not provide a cross-request snapshot; status changes may affect later page membership.
