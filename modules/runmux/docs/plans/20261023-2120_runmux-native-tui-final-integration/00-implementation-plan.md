# Runmux Native TUI Final Integration

**Goal:** Port the existing Runmux native TUI onto current `origin/main`, preserving the consolidated `cli_tui` package and read-only Web UI.

**Approach:** Copy only Runmux-owned TUI files and focused tests from `codex/runmux-tui-integration`. Evaluate history and numeric-ID concurrency fixes independently and commit any justified backend corrections separately. Keep browser and terminal optional import boundaries intact.

**Base:** `f6bf043bee4cf9a694f52ce7c2845510f3cde5d0`

**Constraints:** Do not port the older `modules/cli_tui` implementation. Do not change supervised process ownership, web authentication, or read-only discovery behavior. Do not merge into `main`.

## Work

1. Port and adapt native TUI, adapter, log follower, workspace state, tests, CLI command, dependency metadata, and README instructions.
2. Independently verify and integrate history-update and process-ID concurrency fixes with their focused tests, or document a reason to defer them.
3. Run requested Runmux, CLI TUI compatibility, Web UI, lifecycle, Ruff, and diff checks; review final branch and publish it.

## Acceptance

- `runmux tui` and `runmux web` remain available with lazy, separate imports.
- Tests cover TUI actions, stable full run IDs, read-only discovery, bounded log following, workspace persistence, concurrency, Web UI auth/API, and process survival after UI shutdown.
- `cli_tui` and `web_ui_tools` remain unchanged from the integration base.
- Branch is pushed for review and is not merged.
