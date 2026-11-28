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
- [ ] Review task-only diff, commit and push the feature branch.
- [ ] Fast-forward main, deploy a wheel built from the exact merged commit, and verify installed CLI identity against independent Git evidence.
- [ ] Merge/push and deploy only the qualified corrective candidate; preserve existing registry data and active sessions.
