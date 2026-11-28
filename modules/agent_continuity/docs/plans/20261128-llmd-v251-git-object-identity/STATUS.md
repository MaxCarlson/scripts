# LLMD v2.5.1 Git identity correction

## Objective

Report branch and full commit identity independently in launch previews and portable workspace metadata. Treat malformed historical commit values as unverified without rewriting stored events.

## Status

- [x] Base isolated worktree on `origin/main` at `4dcfd482d35102815c3eb89802fc697e620a71e3`.
- [x] Add regressions for attached/detached/unborn repositories, linked worktrees, SHA-256 object IDs, failures/timeouts, WSL argv, CLI previews, portable snapshots, and malformed historical values.
- [x] Implement independent Git observations and validate historical consumers.
- [x] Bump package, README, and help-registry release metadata to 2.5.1.
- [x] Focused regressions: 54 passed. Full `agent_continuity` xdist: 584 collected, exit 0. `terminal_launcher`: 79 passed. `scripts_help`: 72 passed, 1 skipped (adjacent W11-PowerShell checkout absent).
- [x] Ruff and source version consistency checks passed. Registry validation retains only the three known unrelated import errors (`diff`, `func_replacer`, `rgcodeblock`).
- [x] Review task-only diff and publish the corrective branch at `9699344c4f029b822d8b9c980af06c393d0d1fe8`.
- [x] Fast-forward and push `main` at the qualified correction checkpoint.
- [x] Preserve a 2.5.0 rollback wheel from `4dcfd482d35102815c3eb89802fc697e620a71e3`; install the 2.5.1 wheel built from merged main with `--no-deps`.
- [x] Installed `llmd --version`, import path, help, pip dependencies, and disposable start/continue previews passed. Both previews matched independent branch, full commit ID, and worktree queries exactly.
- [x] Production registry fingerprint and counts were unchanged across installation; no production registry migration/rebuild or provider invocation occurred. Codex/AGY native allocation remains readiness-gated and disabled.

## Delivery

- Code qualification passed before release: `agent_continuity` xdist 584 collected/exit 0; `terminal_launcher` 79 passed; `scripts_help` 72 passed/1 skipped. Ruff and version consistency passed. Registry validation still has only the three known unrelated import errors.
- Production package: `agent-continuity` 2.5.1 in `C:\Users\mcarls\src\scripts\.venv\Lib\site-packages`; wheel SHA-256 `164f9ab8e544bbf6d7b5f662e895fc0b7e8d4c8efc09b2c6e0a12c7817f946e8`.
- Production registry SHA-256 before and after: `1e96f7bdbe4e5e46f60075e1d72973974f080a3eaa78c412dc7478eea35c75e7`.
- [ ] Merge/push and deploy only the qualified corrective candidate; preserve existing registry data and active sessions.
