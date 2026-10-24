# Runmux Web UI UX Refinement

## Goal

Refine the integrated dashboard to follow the minimal dark process-workspace reference while preserving the existing Runmux and `web_ui_tools` contracts, especially browser authentication, terminal WebSocket and supervisor input-lock behavior.

## Gap assessment

| Area | Current state | Assessment |
| --- | --- | --- |
| Dark shell, process search, status, runtime, selection | Present | Satisfied; improve compactness and text sizing |
| Status-first explorer groups | Flat process list | Missing |
| Multiple open process views | Only one selected process at a time | Missing; add lightweight browser-only tabs |
| Output, interactive Terminal, Details views | Present | Satisfied; keep existing behavior |
| Compact header and log-first screen space | Large heading and three summary cards precede workspace | Partial; reclaim space for the workspace |
| Long values and metadata safety | Full run ID and process PID shown; sensitive arguments and cwd intentionally omitted | Partial; keep current allowlist and correct duplicated field label |
| Empty, disconnected, loading, output error states | Present | Satisfied |
| Deferred controls, metrics dashboards, split logs | Not present | Correctly deferred |

## Implementation

1. Replace the flat explorer rendering with collapsible groups keyed by actual backend status.
2. Add a horizontally scrollable strip of open process views. Closing a view changes only browser selection; switching reuses current selection and terminal cleanup paths.
3. Remove the redundant dashboard heading and summary cards, promote connection state to the top bar, and use the available height for explorer and workspace.
4. Improve selected-state, text legibility, and the Run ID/PID labels without expanding exposed process metadata.
5. Update this assessment with validation evidence and note any browser-visual limitations.

## Validation

- Run the Node dashboard harness and targeted Runmux/Web UI tests using disposable state.
- Syntax-check the dashboard JavaScript and inspect the final HTML/CSS diff.
- Attempt authenticated desktop screenshots against synthetic state at common resolutions; record any local-browser connectivity limitation.
- Confirm terminal input remains gated by the supervisor lock in the existing frontend test.

## Status

Implementation is complete on `codex/runmux-web-ux-20261024`, based on `origin/main` at `3e84e8c9a5de3c83b268c7988944e34da716fb2b`.
The implementation commit `479323a7` is pushed to `origin/codex/runmux-web-ux-20261024`; the branch is not merged.

## Validation evidence

- `node --check src/runmux/web_static/assets/dashboard.js` — passed.
- `node tests/dashboard_test.js` — passed, including grouped status ordering, multiple open views, closing a view, and the existing supervisor-lock input gate.
- `python -m pytest -p no:cacheprovider tests/web_test.py tests/web_adapter_test.py -q` — 18 passed. The command required local-socket access outside the restricted sandbox; the sandboxed TestClient run stalled before the first test.
- Authenticated browser smoke against synthetic registry state verified groups, opening and switching two process views, closing a tab while the process remained listed, and Run ID/PID details.
- Headless Playwright captured selected-process views at 1920×1080, 1366×768, and 768×1024. All had no horizontal overflow and the explorer/workspace remained visible.
- `git diff --check` — passed.

## Remaining gaps

- Command arguments and working directory remain hidden by the existing browser metadata allowlist; the visual examples show them, but exposing them would change the established privacy boundary.
- Advanced overview modes, metrics, right-side inspector, process creation/lifecycle actions, and split logs remain deferred as specified.
