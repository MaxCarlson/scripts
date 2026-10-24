# CLI TUI Handoff

Last updated: 2026-10-23

## Resume Here

Pane persistence and pane output capture are implemented on branch `codex/runmux-tui-integration` in `C:\Users\mcarls\.codex\worktrees\59dc\scripts`. See `plans/20261023-pane-layout-output-capture/` for the design, status, and checklist.

Argparse compatibility and parser-only imports were then validated on the same
branch. See `argparse-and-browser-boundary.md` for the supported action subset,
verified import seam, and provisional browser metadata proposal. The separate
`codex/unified-ui-runmux-web-20261023` worktree remains untouched; its browser
forms are a later stage, so no shared JSON schema was finalized.

Next: when the web agent begins browser forms, review this proposal with that
agent, agree only the JSON fields needed by the actual consumer, then add a
small serializer and parser-round-trip fixture. Keep validation and invocation
in the MangaDL/application backend; do not add `ui_core` or move the other
worktree's changes. Run the affected suites and commit/push each completed
feature phase as requested; merge remains separately authorized.

- Layout identity is canonical launch directory plus app ID (default parser program name).
- `Ctrl+S` saves; after confirming `q`, the app asks whether to save. `Q` keeps its immediate force-quit behavior.
- `Ctrl+O` captures current output and follows subsequent output for command and console panes, with overwrite confirmation.
- Saved running panes restore as static read-only output; commands are not restarted. Scroll position, forms, console directory/history, pane order, and active pane are restored.
- Existing direct subprocess cleanup remains in place. Runmux uses its own workspace store.

## Verification

- `modules/cli_tui/tests`: 97 passed, including argparse round-trips, unsupported
  custom action rejection, parser-only imports, and invalid argv handling.
- `modules/mangadl/tests/tui_test.py`: 7 passed.
- `modules/runmux/tests/test_tui.py modules/runmux/tests/test_tui_adapter.py`: 23 passed.
- `modules/runmux/tests`: 134 passed.
- `modules/scripts_help/tests`: 55 passed.
- Focused Ruff checks for changed cli_tui source/tests and `git diff --check` passed.
- Windows pseudo-terminal startup/quit was exercised for Runmux; Windows Terminal and WSL2 interactive validation were not available.
- Completed feature/test phases should be committed and pushed per the user's
  standing instruction. Merge remains separately authorized.
