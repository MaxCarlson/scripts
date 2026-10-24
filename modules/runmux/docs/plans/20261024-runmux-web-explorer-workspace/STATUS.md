# Runmux Web Explorer and Workspace Status

Updated: 2026-10-24

## Current state

Phase 3 implementation is complete on `codex/runmux-web-phase3-20261024` in
`.worktrees/runmux-web-launch-20261024`. The branch includes a conflict-free
merge of `origin/main` at `9f01984d3dedf05781a19f8d131956662ee5b29d` (merge
commit `8184a3e9`), preserving Phase 2 terminal/log fixes and the Phase 5B
telemetry API. Phase 3 is not merged to `main`.

## Delivered

- Switchable status/ungrouped grouping, real status filters, supported sorts,
  complete-list search, and a 100-row bounded explorer page.
- Versioned `sessionStorage` preferences and valid Run-ID tab restoration;
  stale IDs are pruned and no credentials, full records, or output are saved.
- Duplicate-name distinction in rows and tabs, Run-ID keyed views, horizontal
  tab navigation, and close-view behavior that leaves the registry intact.
- Selected detail reconciliation by Run ID, registry connection distinction,
  safe metadata copy controls, and accessible explorer collapse/resize.
- Mobile explorer sizing that leaves a visible, scrollable run list.

## Privacy and remaining scope

- Full argv and working-directory disclosure (D01/D02) remains deferred. The
  existing API intentionally omits those fields and Phase 3 does not expand its
  disclosure policy.
- Category/workspace grouping, server-side pagination, last-activity sorting,
  lifecycle controls, metrics dashboards, and advanced workspace features are
  not part of this phase.

## Verification

- Windows: `node tests/dashboard_test.js` passed; `node --check
  src/runmux/web_static/assets/dashboard.js` passed; `git diff --check` passed.
- Windows headless Chromium with a disposable loopback registry passed at
  1920, 1366, 768, and 390 px: empty-registry entry points, 450 synthetic runs,
  100-row rendering, filtering, pagination, sorting, keyboard search/splitter,
  reload tab restoration, close-view registry survival, safe text rendering,
  and zero browser console errors.
- Windows: `python -m pytest tests/web_test.py -q` was stopped after 15 seconds
  with no output. The same Windows Proactor/event-loop startup hang was observed
  previously; backend tests therefore remain unverified on this host.
- Windows: `ruff check .` reports 42 lint issues in existing Python files;
  Phase 3 changes no Python files.

## Delivery

Phase 3 is committed and pushed on `codex/runmux-web-phase3-20261024`. The
branch remains intentionally unmerged.
