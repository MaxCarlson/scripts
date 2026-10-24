# Runmux Web Explorer and Workspace Implementation Plan

**Phase:** RUNMUX-WEB-P3
**Branch:** `codex/runmux-web-phase3-20261024`
**Base:** updated `origin/main` at `9f01984d3dedf05781a19f8d131956662ee5b29d` (Phase 2 and Phase 5B integrated)
**Spec:** [`web-ui-handoff/PHASE_03_EXPLORER_AND_WORKSPACE.md`](../web-ui-handoff/PHASE_03_EXPLORER_AND_WORKSPACE.md)

## Goal and architecture

Make the existing Runmux browser explorer and process workspace usable with
large registries and many same-named runs. Keep the current dark HTML/CSS/JS
UI and read-only API. Compute grouping, filtering, sorting, and pagination in
the browser from the existing safe run summaries; use session storage only for
small UI preferences and Run IDs. Keep full argv, cwd, environment, and
supervisor credentials off the API and out of browser storage.

## Verified current contracts

- Run list/detail responses include full Run ID, display name, executable
  basename, status, connection, PID, exit code, runtime, and lifecycle times.
- `serialize_run` deliberately omits argv, cwd, environment overrides, IPC
  credentials, and log paths. Do not expand this allowlist in Phase 3.
- Current status groups and Run-ID-keyed tabs already exist. Search is a single
  text filter; grouping/sort controls and session restoration are absent.
- The process tab strip already scrolls horizontally. Preserve that behavior
  and make duplicate labels distinguishable by a short Run ID.
- `refreshSelected` updates Details but currently does not merge returned state
  into the explorer's in-memory summary; reconcile by Run ID without creating
  duplicate rows or changing supervisor state.

## Decisions and boundaries

- Offer only **Status** and **Ungrouped** grouping until the API supplies
  category/workspace metadata. Status remains the default.
- Filter by the real status enum. Sort by available fields only: newest
  created, start time, name, duration, or status. Do not offer last activity;
  it is not in the browser summary.
- Search only safe list fields: name, executable basename, status, and Run ID.
- Keep at most 100 explorer rows in the DOM at once with previous/next pages;
  filtering still searches the complete fetched list.
- Persist only validated explorer preferences and open/selected Run IDs in
  `sessionStorage`. Never store cookies, login codes, full records, argv, cwd,
  or output. Drop IDs that no longer exist after a registry refresh.
- Retain the API privacy boundary. D01/D02 command-argument and cwd disclosure
  is deferred pending a deliberate server-side authorization decision; an
  HTML reveal control is not authorization. Copy actions may target only
  metadata already exposed by the API.
- Keep lifecycle actions, category/tag editing, overview dashboards, metrics,
  and advanced workspace presets out of scope.

## Planned file responsibilities

- `src/runmux/web_static/index.html`: explorer controls, splitter/collapse
  affordance, tab identity, and safe metadata copy controls.
- `src/runmux/web_static/assets/dashboard.js`: validated preference state,
  derived filtering/sorting/paging, Run-ID reconciliation and restore.
- `src/runmux/web_static/assets/dashboard.css`: compact controls, splitter,
  collapsed/responsive explorer, readable tab identity and focus states.
- `tests/dashboard_test.js`: pure UI-state regressions for selection,
  filters/sorts/pages, storage validation/restoration and duplicate IDs.
- `tests/web_test.py`: API privacy and status/reconciliation contracts when a
  backend-level regression is demonstrated.
- `docs/plans/20261024-runmux-web-explorer-workspace/`: implementation status,
  checklist and handoff.
- `docs/HANDOFF.md`, `docs/plans/HANDOFF.md`, `docs/README.md`, and
  `docs/RUNMUX_WEB_UI_MASTER_ROADMAP.md`: active phase and evidence.

## Tasks and verification

1. Capture a fresh desktop baseline with a disposable registry. Add failing
   dashboard tests for status/ungrouped modes, one real status filter, each
   supported sort key, empty-search messaging, and bounded page size; implement
   the derived view and accessible controls. Run Node harness and inspect the
   browser screenshot.
2. Add failing tests for session preference validation, restore after registry
   load, pruning stale Run IDs, and no secret/full-record persistence. Implement
   versioned `sessionStorage` state and preserve current selection/tab behavior.
3. Add failing tests for same-name distinct row/tab identity, horizontal tab
   activation, and page navigation. Add short Run ID cues and keep only one
   view per Run ID; verify closing a view leaves the process listing intact.
4. Add failing tests for selected-run status reconciliation and connection
   state separation. Merge selected detail summaries by ID and keep registry
   disconnection distinct from a run's `lost` status.
5. Add accessible collapse and keyboard/pointer resize behavior for the
   explorer, compact header/timestamp/copy improvements using only allowed
   metadata, then verify at 1920, 1366, 768, and narrow mobile widths.
6. Run focused dashboard/API tests, Ruff and JavaScript checks. Use clean
   headless Chromium with a disposable registry containing hundreds of
   synthetic historical records, duplicate names and long Unicode labels.
   Record browser interactions, console errors, accessibility names, and
   process-state invariants. Update acceptance mapping and limitations.

## Review focus

- Malformed or stale session storage: must fall back safely without blocking
  authentication or exposing stored data.
- Many duplicate labels and hundreds of runs: Run IDs remain distinct and DOM
  row count stays bounded while search covers the full registry.
- Run status changes or registry disconnection: reconcile only by exact Run ID
  and do not conflate registry health with per-run `lost` state.
- Long/untrusted process names: render as text and truncate without overflow.
- Metadata disclosure: never surface fields omitted by `serialize_run`.

## Acceptance tracking

Track N01–N08, D01–D05, W01–W04/W12, S06–S07/S12, and supported H01–H04
evidence in `STATUS.md`. D01/D02 and unavailable metadata/sorts remain explicit
limitations unless their authorization/backend contracts are independently
verified. Do not begin Phase 4.
