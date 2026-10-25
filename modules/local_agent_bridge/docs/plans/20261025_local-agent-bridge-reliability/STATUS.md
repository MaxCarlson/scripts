# Status: Local Agent Bridge Reliability

## Current state

- [x] Baseline captured: `origin/main` / `b2ef5fb96ec1ef8cacb51962932f24b5069d49dc`.
- [x] Isolated branch created: `codex/local-agent-bridge-reliability-20261025`.
- [x] Model limits and read-only verification.
- [x] Coordinator/worker recovery and search-first resources.
- [x] Documentation, focused tests, and package validation.
- [ ] Commit and push; no merge.

## Constraints

No live inference, profile writes, server/model changes outside the requested local-agent runtime command, or edits to the monitor/Runmux modules. Preserve the known Codex CLI MCP discovery blocker until a permitted enabled CLI acceptance probe exists.

## Validation and remaining work

Focused regression tests: 31 passed. Full module suite: 92 passed, 1 skipped,
2 Git Bash shell-hook failures caused by Windows sandbox access denial; excluding
those two cases yielded 92 passed, 1 skipped, 2 deselected. Focused Ruff,
wheel/resource validation, CLI help/version checks, and `git diff --check` passed.
See [VALIDATION.md](../../VALIDATION.md) and [HANDOFF.md](../../HANDOFF.md).

No live inference, model operation, profile write, or Codex CLI acceptance probe
was performed. The only remaining local delivery step is review, commit, and
push of this branch; do not merge.
