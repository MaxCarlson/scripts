# Integration Handoff

This folder tracks the native Runmux TUI final integration. The implementation plan and current progress are in `00-implementation-plan.md`, `STATUS.md`, and `checklist.md`.

The base must remain the latest fetched `origin/main` (`f6bf043`). Port only Runmux-owned work from `codex/runmux-tui-integration`; that source branch also contains an older `cli_tui` implementation which must not be copied. Commit proven backend race fixes separately from the TUI. Run the focused checks in the assignment before pushing. The branch is for review and must not be merged into `main`.
