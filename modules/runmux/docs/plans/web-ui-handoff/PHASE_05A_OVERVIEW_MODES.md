# Runmux Web UI — Phase 5A: Four Overview Density Modes

**Status:** Future separately assignable feature | **Priority:** P2 | **Backlog:** M01–M06

## Objective

Implement the approved global **A Minimal / B Inline / C Dashboard / D Expanded** process header/overview densities, starting from the existing compact header without inventing metric data.

The user must be able to cycle **A → B → C → D → A** or directly select a mode. The **last-used mode is global** across runs and browser reloads, not per-run. Modes adapt gracefully to data not yet provided by Phase 5B/5C; do not fabricate charts to fill space.

## Work and acceptance

- Inspect existing metadata and workspace state; retain dark style and the space priority of Output/Terminal.
- Add selector, mode layouts with honest unavailable states, small-screen fallback and safe local persistence of the global choice. Do not store credentials/commands/logs in browser preferences.
- Switching modes must not reset process tabs, active Output/Terminal/Details view, scroll/follow, input attachment or supervisor state.
- A = maximum log space; B = compact real fields when available; C = informational cards only where supported; D = expanded diagnostics only from real data, otherwise meaningful metadata/empty states.
- Validate cycle, direct select, reload, tab switch, narrow and ultrawide displays, and missing metric fields with synthetic fixtures.

**Not in this slice:** New telemetry collectors, historical charts, metrics storage, generic docking or alarms. Deliver tests, visual verification, docs and pushed branch; **do not merge**.
