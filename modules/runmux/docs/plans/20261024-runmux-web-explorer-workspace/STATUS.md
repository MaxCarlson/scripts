# Runmux Web Explorer and Workspace Status

Updated: 2026-10-24

## Current state

Phase 3 is active on `codex/runmux-web-phase3-20261024`, based on Phase 2
merged to `origin/main` at `bc2975c410c2f1eb71da9975d4fd27e8f895cfa9`.
The implementation plan is in `00-implementation-plan.md`; scope is
`plans/web-ui-handoff/PHASE_03_EXPLORER_AND_WORKSPACE.md`.

## Reconnaissance

- The current explorer groups by status and searches name, executable basename,
  status, and Run ID; it has no grouping selector, status filter, sort control,
  or list pagination.
- Run views are keyed by immutable Run ID and closing a tab only removes the
  browser view. The tab bar scrolls horizontally, but duplicate names have no
  visible identity cue and views are not restored after reload.
- `sessionStorage`/`localStorage` are not currently used by the dashboard.
- The API allowlist includes Run ID, display name, executable basename, status,
  connection, PID, exit code, runtime, and timestamps. It omits full arguments,
  cwd, environment, IPC auth token, and log path.
- Selected-run detail refresh can return updated status, but the current client
  does not merge that response back into the explorer row.
- The registry list API returns all records. Client-side filtering can cover the
  fetched list while rendering only a bounded page at a time.

## Decisions

- Status is the default grouping; ungrouped is the only other grouping until
  category/workspace metadata exists.
- Filters and sort choices use only actual API fields/enums. No last-activity
  sort or metadata search is offered where the API has no safe source.
- Persist only UI preferences and exact Run IDs in tab-scoped `sessionStorage`;
  never store authentication material, full run records, or log contents.
- Preserve the existing API privacy allowlist. Defer full command/argv and cwd
  disclosure (D01/D02) until there is an explicit server-side authorization
  policy. Expose no HTML-only reveal.

## Verification

Not yet run for Phase 3. Baseline browser capture and TDD implementation are the
next steps. Phase 2 validation remains recorded in
`../20261024-runmux-web-terminal-log-correctness/STATUS.md`.

## Next action

Capture a fresh baseline with disposable synthetic state, then add and verify
the explorer filter/group/sort/page regressions before implementing UI behavior.
