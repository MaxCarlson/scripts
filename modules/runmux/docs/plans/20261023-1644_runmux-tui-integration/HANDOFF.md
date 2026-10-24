# Runmux TUI Integration Handoff

Read ARCHITECTURE_ASSESSMENT.md, 00_implementation-plan.md, STATUS.md, and checklist.md.

Current work is on branch codex/runmux-tui-integration in the managed worktree recorded in STATUS.md. The initial baseline was 90 passing and 5 failing Runmux tests, plus 69 passing cli_tui tests. The five failures were resolved during final stabilization; current suites pass in full.

Stages 1–3 are implemented: read-only full-ID discovery, bounded log following, root/app-scoped view persistence, launch/history/saved commands, lifecycle controls, output-file capture, and curses handoff to `interact_run`. Runmux has 134 passing tests; cli_tui has 85 passes after adding generic root/app-scoped pane persistence and output capture; scripts_help has 55 passes. The six-writer history test passed three consecutive runs after stabilizing Windows lock creation. See `STATUS.md` for platform limits and exact checks.

Run tests from `modules/runmux` with the worktree's source and cli_tui module available on `PYTHONPATH` (the default editable install points at the main checkout). The generic cli_tui follow-up is documented at `modules/cli_tui/docs/plans/20261023-pane-layout-output-capture/`. The earlier cli_tui worktree remains untouched and its uncommitted changes were not copied wholesale. No commit, push, or merge is authorized.
