# Runmux Current Handoff

Last updated: 2026-10-23

## Resume Here

Active work: `runmux tui` persistent process workspace integration.

- Branch: `codex/runmux-tui-integration`
- Worktree: `C:\Users\mcarls\.codex\worktrees\59dc\scripts`
- Plan: `plans/20261023-1644_runmux-tui-integration/`
- Status: Runmux TUI plus generic cli_tui persistence/capture implementation complete; awaiting user review.
- Preserve the main checkout's unrelated documentation changes and leave the older cli_tui worktree untouched.
- No commit, push, or merge is authorized.

Read the active plan's `HANDOFF.md`, `STATUS.md`, `checklist.md`,
`ARCHITECTURE_ASSESSMENT.md`, and `00_implementation-plan.md` before resuming.

## Implemented

- Read-only full-ID process adapter and transient status projection.
- Bounded incremental byte-log reader, background followers, ANSI output capture.
- Root/app-scoped saved workspace state, browser, output tabs, and `runmux tui` CLI entry.
- Manual JSON argv launch, history/saved command chooser, lifecycle actions, and confirmations.
- Per-file cross-process JSON locks and atomic replacements for run history and unique-command ledger.
- SQLite run creation now reserves an immediate write transaction before allocating reusable numeric IDs.
- Curses-to-`interact_run` handoff with workspace restoration and IPC error recovery.

## Verification So Far

- Baseline: Runmux 90 passed / 5 failed; cli_tui 69 passed.
- Current Runmux suite: 134 passed; cli_tui 85 passed; scripts_help 55 passed. The five initial Runmux baseline failures were resolved in the final stabilization pass. The cli_tui follow-up adds root/app-scoped layout restore, save-on-exit prompt, Ctrl+S save, and Ctrl+O output capture.
- scripts_help suite: 55 passed.
- Four concurrent isolated managed launches pass; six concurrent history writers pass three consecutive Windows runs after locking.
- The worktree's default editable install points to the main checkout. Set `PYTHONPATH` to the worktree Runmux `src` and `modules/cli_tui` when testing.
- Windows pseudo-terminal startup/render/quit prompt smoke passed using isolated state. This shell was not Windows Terminal (`WT_SESSION` absent).
- WSL2 Ubuntu is installed, but its Python lacks `psutil`; no package installation or WSL TUI smoke was performed.

## Next Action

Review the isolated worktree diff, including `modules/cli_tui/docs/plans/20261023-pane-layout-output-capture/`, and decide whether to integrate it later. No commit, push, or merge is authorized.

## Prior Runmux Work

The 2026-06 multi-attach, input-lock, and history work remains documented in
`plans/20260622-0551_runmux-multi-attach-input-lock-history/` as historical
implementation context.
