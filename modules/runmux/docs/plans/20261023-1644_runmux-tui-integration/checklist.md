# Checklist

## Stage 0: Architecture and baseline
- [x] Inspect repository/module instructions, current branch, worktrees, source, and tests.
- [x] Confirm safe read-only RunStore path and identify pruning CLI helper.
- [x] Identify CliTuiApp runner cleanup behavior and preserve direct-runner consumers.
- [x] Record current baseline and existing runmux failures.
- [x] Create architecture assessment and staged plan.

## Stage 1: Read-only process browser and view tabs
- [x] Add read-only adapter keyed by full run IDs.
- [x] Add bounded incremental log reader and background follow.
- [x] Add browser, explicit user-opened tabs, and root/app-scoped persistent view state.
- [x] Add runmux tui CLI entry, docs, package dependency/version, and help registry.
- [x] Add hotkey output capture to a user-selected file.
- [x] Verify close/quit and curses exception paths never invoke process termination.

## Stage 2: Launch/history/lifecycle/concurrency
- [x] Add exact argv/cwd launch adapter and JSON-array manual launch preview.
- [x] Use custom-state history and saved-command paths in the TUI adapter.
- [x] Add asynchronous chooser and lifecycle key handling; confirm destructive actions.
- [x] Add cross-process file locks and atomic history/ledger updates.
- [x] Test lifecycle API routing, confirmation refusal/acceptance, and concurrent isolated launches.

## Stage 3: Interactive attach and polish
- [x] Hand off from curses to runmux interact API and return to TUI.
- [x] Test detach return, IPC failure recovery, workspace restore, and input-lock API reuse.
- [x] Run full suites, focused lint, compile, and compare baseline failures.
- [x] Record Windows pseudo-terminal smoke and WSL2 dependency gap.

## Optional follow-up
- [ ] Evaluate registered module parser forms after core launcher is stable.

## Shared cli_tui follow-up
- [x] Add launch-root/app-scoped pane layout storage, save prompt, and explicit save hotkey.
- [x] Add pane output file dialog, overwrite confirmation, and process/console output subscriptions.
- [x] Run cli_tui suite (85 passed), Runmux suite (134 passed), and scripts_help suite (55 passed).
- [x] Resolve five initial Runmux baseline test failures and rerun the complete suite.
