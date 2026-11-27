# Status — llmd packaging release candidate

- **Branch:** `integration/llmd-release-candidate-20261119`
- **Worktree:** `.worktrees/llmd-release-candidate-20261119`
- **Initial base main:** `2edd36334d7d34074e03830b8896e8c9c8377da5`
- **Latest main:** `719e2e70a7fb9c3b3b530fe09b013ef3a6e3f0df` (merged into this candidate after main advanced during validation)
- **Integrated commit:** `4cddb9a60c92e59a61740eee6f4fee416df06cc9`
- **Final state:** The candidate includes the verified integration and latest main; the final synchronization merge commit is ready after its post-merge checks.
- **Dependency:** `agent-continuity` requires `terminal-launcher>=0.1.1,<0.2`; no reverse dependency exists.
- **Versions:** `agent-continuity` metadata and module remain 1.1.0; terminal-launcher metadata and `__version__` are 0.1.1.
- **Registry merge:** New `privileged_execution` main registration and `agents`/`llmd` entries are present. Git auto-merged the disjoint changes without conflicts.
- **Validation:** agent_continuity 78 passed; terminal_launcher 41 passed; scripts_help on latest main 59 passed, 1 skipped (sibling W11-powershell repo unavailable); runtime_lifecycle 58 passed; snips 34 passed, 1 skipped (WinError 623 GUI sandbox). Scoped Ruff and compileall passed. CRLF-aware diff checks passed. Broad scripts_help Ruff found four existing findings outside dispatcher/terminal code.
- **Packaging:** Both wheels built; paired no-index wheel install and local editable source install passed with `pip check`. Terminal launcher installs alone. Dispatcher-only wheel installation fails clearly when the local terminal wheel is unavailable and leaves the dispatcher uninstalled. Installed CLI help, JSON smoke, and no-argument TTY selector checks passed.
- **Native session correlation:** Not implemented automatically. M2 hook events contain provider native session IDs but no dispatcher launch ID; pending launches still require verified manual `llmd attach`.
- **Windows Terminal acceptance:** Not run. Command capture is validated; live tab/pane geometry and child startup remain unverified and require a later harmless-process desktop check.
- **Approval boundary:** No push, provider launches, hook installation, or Windows Terminal GUI launch was performed. The latest-main merge is confined to this release-candidate worktree.
