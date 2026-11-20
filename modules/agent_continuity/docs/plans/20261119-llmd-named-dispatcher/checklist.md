# Checklist — Dispatcher and Terminal Launcher Integration

- [x] Verify the M2 base, dispatcher and terminal-launcher tips, common ancestry, and existing worktrees.
- [x] Preserve the already-created two-merge integration ancestry for both exact feature commits.
- [x] Wire `llmd open` and interactive Open All to the real `terminal_launcher` package.
- [x] Validate active-slot ordering, `PaneSpec` arguments, cwd propagation, grouped layouts, window targeting, and titles with a captured backend.
- [x] Add dispatcher integration acceptance for default 2-pane grouping, 4-pane grouping, `-k 4`, completed slots, pending identities, and backend failures.
- [x] Fix JSON serialization and exit-status propagation for structured terminal launch results.
- [x] Fix empty-plan preview so unresolved-only opens do not require an installed `wt.exe`.
- [x] Inspect M2 hooks and launch events for deterministic session-ID correlation; document why manual attachment remains necessary.
- [x] Run module suites, Ruff, compile checks, package-wheel builds, disposable combined installation, CLI help and JSON smoke.
- [x] Review and commit the final integration diff.
- [x] Leave live Windows Terminal layout verification unrun; it needs separate authorization and is explicitly reported as pending.
