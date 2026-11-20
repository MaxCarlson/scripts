# Status — llmd packaging release candidate

- **Branch:** `integration/llmd-release-candidate-20261119`
- **Worktree:** `.worktrees/llmd-release-candidate-20261119`
- **Base main:** `2edd36334d7d34074e03830b8896e8c9c8377da5`
- **Integrated commit:** `4cddb9a60c92e59a61740eee6f4fee416df06cc9`
- **Final state:** Release candidate is validated and ready for its single merge commit on this branch.
- **Dependency:** `agent-continuity` requires `terminal-launcher>=0.1.1,<0.2`; no reverse dependency exists.
- **Versions:** `agent-continuity` metadata and module remain 1.1.0; terminal-launcher metadata and `__version__` are 0.1.1.
- **Registry merge:** New `privileged_execution` main registration and `agents`/`llmd` entries are present. Git auto-merged the disjoint changes without conflicts.
- **Validation:** agent_continuity 78 passed; terminal_launcher 41 passed; scripts_help 58 passed, 1 skipped (sibling W11-powershell repo unavailable); runtime_lifecycle 58 passed; snips 34 passed, 1 skipped (WinError 623 GUI sandbox). Scoped Ruff, compileall, and diff checks passed. Broad scripts_help Ruff found four pre-existing findings outside the changed registry.
- **Packaging:** Both wheels built; paired no-index wheel install and local editable source install passed with `pip check`. Terminal launcher installs alone. Dispatcher-only wheel installation fails clearly when the local terminal wheel is unavailable and leaves the dispatcher uninstalled. Installed CLI help, JSON smoke, and no-argument TTY selector checks passed.
- **Native session correlation:** Not implemented automatically. M2 hook events contain provider native session IDs but no dispatcher launch ID; pending launches still require verified manual `llmd attach`.
- **Windows Terminal acceptance:** Not run. Command capture is validated; live tab/pane geometry and child startup remain unverified and require a later harmless-process desktop check.
- **Approval boundary:** No push, main merge, provider launches, hook installation, or Windows Terminal GUI launch was performed.
