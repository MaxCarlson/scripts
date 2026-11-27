# Checklist — Native Session Bootstrap and Resume

- [x] Verify repository state, preserve prior review worktree, and create isolated feature worktree from the intact integration candidate.
- [x] Verify installed Codex/AGY CLI syntax and provider structured-output contract.
- [x] Add deterministic per-process Codex and AGY session-ID capture.
- [x] Persist bootstrap attempt/captured-ID/failure observations through the existing event spool.
- [x] Resolve launch association before interactive resume; do not retry uncertain bootstrap attempts automatically.
- [x] Add mocked Codex, AGY, failure-recovery, exact resume, concurrency, and rebuild tests.
- [x] Run initial affected regression suites, lint, compile and disposable package/CLI smoke.
- [x] Run one authorized initialization-only live prompt per provider and verify exact IDs through native metadata discovery.
- [x] Verify Codex explicit resume without sending another prompt.
- [x] After explicit user approval, resume the existing AGY ID and verify that its initialization request and `READY` response remain in the conversation.
- [x] Reconcile this feature branch with the updated `c623464b` release-candidate baseline (clean merge; no conflicts).
- [x] Run complete affected package suites, static checks, compile checks, wheel installation, dependency, CLI-entry-point, and import smoke checks.
- [x] Record the unrelated baseline Ruff findings and platform-related skipped tests without changing those files.
- [x] Review the task-only documentation update and create the final feature checkpoint commit.
- [x] Preview and submit both approved harmless Windows Terminal layout plans; verify that the current environment has no registered Windows Terminal package, process, or window.
- [ ] Repeat live pane geometry and child startup verification in an environment with Windows Terminal installed and registered.
