# CLI TUI Handoff

Last updated: 2026-10-23

## Resume Here

Pane persistence and pane output capture are implemented on branch `codex/runmux-tui-integration` in `C:\Users\mcarls\.codex\worktrees\59dc\scripts`. See `plans/20261023-pane-layout-output-capture/` for the design, status, and checklist.

- Layout identity is canonical launch directory plus app ID (default parser program name).
- `Ctrl+S` saves; after confirming `q`, the app asks whether to save. `Q` keeps its immediate force-quit behavior.
- `Ctrl+O` captures current output and follows subsequent output for command and console panes, with overwrite confirmation.
- Saved running panes restore as static read-only output; commands are not restarted. Scroll position, forms, console directory/history, pane order, and active pane are restored.
- Existing direct subprocess cleanup remains in place. Runmux uses its own workspace store.

## Verification

- `modules/cli_tui/tests`: 85 passed.
- `modules/runmux/tests`: 134 passed.
- `modules/scripts_help/tests`: 55 passed.
- Focused Ruff checks passed; broad Runmux lint was run with `E501` and `SIM108` excluded because the touched legacy files contain unrelated instances of those rules.
- Windows pseudo-terminal startup/quit was exercised for Runmux; Windows Terminal and WSL2 interactive validation were not available.
- No commit, push, or merge is authorized.
