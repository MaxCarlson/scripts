# Runmux Web Interactive Terminal Checklist

- [x] Confirm latest `origin/main` base and isolated feature worktree.
- [x] Save the supporting detailed Web UI design specification in Runmux docs.
- [x] Add shared authenticated WebSocket middleware and declared transport in `web_ui_tools`.
- [x] Implement bounded ANSI streaming and supervisor-backed terminal attachments in Runmux.
- [x] Enforce supervisor input-lock ownership for terminal input and resizing.
- [x] Replay completed-run output without opening a dead supervisor attachment.
- [x] Add focused auth, output, attachment, lock, reconnect, and frontend tests.
- [x] Vendor xterm.js assets, licenses, and version notice.
- [x] Update Runmux and web-ui-tools usage documentation.
- [x] Run focused tests, lint, CLI/TUI compatibility checks, frontend checks, and wheel packaging.
- [x] Stop and remove manual disposable browser-smoke state.
- [x] Review final scoped diff and verify there are no whitespace errors.
- [x] Commit and push `codex/runmux-web-terminal-20261023`; verify the remote ref.
