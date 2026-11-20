# Checklist — llmd packaging release candidate

- [x] Create a fresh isolated worktree based on current local main.
- [x] Merge the verified integration candidate without changing its worktree.
- [x] Compare earlier and verified candidates; preserve the verified fixes and ancestry.
- [x] Confirm current main and dispatcher help registrations are both present.
- [x] Declare the runtime dependency, synchronize terminal-launcher versions, and add regression coverage.
- [x] Document local-source and wheel installation workflows plus harmless terminal smoke instructions.
- [x] Run package suites, static checks, module discovery, wheel and disposable-environment installation, CLI and TTY checks.
- [x] Review correlation limitations, terminal acceptance boundary, ancestry, and task-only diff.
- [x] Create one merge candidate commit on this branch; do not push or merge to main.
