# Status

- State: Runmux stages 0–3 and generic cli_tui follow-up implemented; awaiting user review
- Branch: codex/runmux-tui-integration
- Base commit: f5dc8a29a1af9b13703d9bd3f3a2199ba744f0d3 (current main at worktree creation)
- Worktree: C:\Users\mcarls\.codex\worktrees\59dc\scripts
- Root checkout: unrelated documentation changes preserved
- Prior cli_tui feature worktree: untouched; its uncommitted changes remain separate and were not copied wholesale
- Baseline: runmux 90 passed / 5 failed; cli_tui 69 passed
- Initial baseline failures resolved in the final stabilization pass: history shortcut order, stale list-row expectations, saved-command API fixture, and stats table alignment / misplaced JSON assertion.
- Current stage: Review pending; no commit or integration action authorized
- Design correction: workspace persistence is scoped to canonical launch root plus app identity, under the configured Runmux state directory.
- Verification: Runmux 134 passed; cli_tui 85 passed; scripts_help 55 passed. The initial five Runmux baseline failures were resolved during final stabilization. Focused Ruff and `compileall` pass. Four concurrent isolated launches pass; six concurrent history writers passed three consecutive Windows runs after fixing the lock-file creation race.
- Terminal acceptance: Windows pseudo-terminal launch/render/quit/save-prompt smoke passed using an isolated registry. This shell was not Windows Terminal (`WT_SESSION` absent). WSL2 Ubuntu is installed (version 2), but its Python lacks `psutil`; no dependencies were installed and no WSL TUI smoke was run.
- Remaining optional item: registered-module generated forms were deferred as specified; manual argv, history, and saved commands are supported.
- Next action: Review the combined isolated worktree diff; no commit, push, or merge is authorized.
- No commit, push, or merge is authorized.

- Generic cli_tui follow-up plan: `modules/cli_tui/docs/plans/20261023-pane-layout-output-capture/`.
