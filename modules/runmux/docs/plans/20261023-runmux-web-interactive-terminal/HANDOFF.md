# Runmux Web Interactive Terminal Handoff

## Goal

Deliver an authenticated, reconnectable browser terminal for supervised Runmux processes, with reusable WebSocket admission in `web_ui_tools` and process-specific IPC/attachment/input-lock handling in Runmux.

## Worktree

- Branch: `codex/runmux-web-terminal-20261023`
- Base: `origin/main` at `9e64c56977bb1db6469d77feaa2733130ce61023`
- Path: `C:\Users\mcarls\src\scripts\.worktrees\runmux-web-terminal-20261023`

## Decisions

- The existing read-only interface remains intact; the assignment explicitly authorizes interactive terminal support despite the older minimal spec deferring it.
- Shared WebSocket Host/Origin/session-cookie validation lives in `modules/web_ui_tools/`; Runmux terminal IPC and input ownership remain supervisor-authoritative.
- xterm.js is vendored and loaded locally. No CDN or new general-purpose UI framework was introduced.
- Process lifecycle controls, dashboard expansions, split logs, and metrics views remain deferred.

## Verification

See `STATUS.md` for exact focused test counts, packaging checks, and the four existing unrelated CLI-test failures.

## Delivery

Feature commit `25d3393abb042edd91d289cd2080f57ae22e03bf` is pushed to
`origin/codex/runmux-web-terminal-20261023`. The remote ref was verified, the
worktree is clean, and the branch is not merged.
