# Checklist — Native Session Bootstrap and Resume

- [x] Verify repository state, preserve prior review worktree, and create isolated feature worktree from the intact integration candidate.
- [x] Verify installed Codex/AGY CLI syntax and provider structured-output contract.
- [x] Add deterministic per-process Codex and AGY session-ID capture.
- [x] Persist bootstrap attempt/captured-ID/failure observations through the existing event spool.
- [x] Resolve launch association before interactive resume; do not retry uncertain bootstrap attempts automatically.
- [x] Add mocked Codex, AGY, failure-recovery, exact resume, concurrency, and rebuild tests.
- [x] Run initial affected regression suites, lint, compile and disposable package/CLI smoke.
- [x] Run one authorized initialization-only live prompt per provider and verify exact IDs through native metadata discovery.
- [x] Verify Codex explicit resume without sending another prompt; leave AGY interactive resume unverified because its CLI requested project trust and decline is required absent authorization.
- [ ] Reconcile this feature branch with the updated `c623464b` release-candidate baseline and rerun affected regressions.
- [ ] Review final task-only diff, update status, and create the final feature checkpoint commit.
