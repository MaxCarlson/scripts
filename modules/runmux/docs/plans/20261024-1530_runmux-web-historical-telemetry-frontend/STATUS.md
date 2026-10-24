# Runmux Web UI — Phase 5C Historical Telemetry Frontend Status

**Branch:** `codex/runmux-web-historical-telemetry-frontend-20261024`
**Base:** `origin/main` at `8befeae3375740e21cdfe17a081387f0e3cf8f54`
**State:** Complete, committed, pushed, and readiness-checked; not merged.
**Next:** No implementation work remains. Keep this feature branch separate; do not merge into `main`.

## Recovered Baseline

- Phase 5A/5B commits `d910ea42` and `10f601c0` are ancestors of `origin/main`; this worktree starts from the integrated frontend.
- The Phase 5C historical telemetry API and storage are already integrated. This branch changes frontend assets and tests only; it adds no backend collection or storage infrastructure.
- The interrupted worktree contained the plan only; no source changes were present when recovery began.

## Completed

- [x] Add responsive process and host history chart containers and 1h/6h/24h/7d controls.
- [x] Render bounded SVG series with real units, dynamic CPU scaling, null/unavailable states, explicit and temporal gaps, stale-point breaks, Run ID boundaries, and lifecycle/restart markers.
- [x] Request process history in Dashboard and Expanded modes; request host history only in Expanded. Minimal and Inline issue no history requests.
- [x] Bound requests to 300 points; abort obsolete range/selection requests and discard stale responses. Active runs refresh every 30 seconds; terminal runs are one-shot.
- [x] Preserve tabs, Output follow state, terminal visibility, and lifecycle controls when changing history ranges.
- [x] Add unit coverage for ranges, query caps, mode gating, cancellation, null values, CPU above 100%, and active-versus-terminal polling.
- [x] Extend Chrome E2E with a synthetic registry, disposable seeded SQLite telemetry, parent/child lineage, range changes, scope assertions, and Output/lifecycle regression checks.
- [x] Capture and visually inspect Dashboard, Expanded, and limited-retention screenshots under `screenshots/`.

## Verification

- `node --check modules/runmux/src/runmux/web_static/assets/dashboard.js` — passed.
- `node --check modules/runmux/tests/dashboard_test.js` — passed.
- `node --check modules/runmux/tests/browser_e2e_test.js` — passed.
- `node modules/runmux/tests/dashboard_test.js` — passed.
- `node modules/runmux/tests/browser_e2e_test.js` — passed again in real headless Chrome using a synthetic registry and disposable telemetry database; existing tabs, terminal attachment, Output, and lifecycle checks passed.
- The merged `/api/runs/{id}/telemetry/history` and `/api/telemetry/history` contracts were verified against this Chrome run, including range, process/host scope, lineage, gaps, and null I/O handling.

## Limitations

- The history API reports range resolution (`raw`, `1m_rollup`, or `5m_rollup`); a long-window response may contain mixed raw and rolled-up points.
- Missing event annotations degrade to no markers; absent/null metric values render unavailable without fabricated zeros.
- Browser E2E was run on the current Windows/Chrome host; other operating systems were not browser-tested.
