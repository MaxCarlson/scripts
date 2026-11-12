# Integration Review Checklist

- [x] Refresh refs and verify `main` → Part 2 → Part 3 ancestry.
- [x] Preserve original Part 2/Part 3 worktrees and verify V3 hash/blob.
- [x] Review durable writer serialization, revision/CAS behavior, single-instance assumption, and rollback export.
- [x] Validate rollback snapshot with the actual v0.14.0 parser.
- [x] Review recovery fence, admission checks, request-evidence ordering, and miner lifecycle protections.
- [x] Reproduce and fix post-commit recovery-sync marker ordering defect.
- [x] Add and pass deterministic recovery-sync and concurrent-recovery regressions.
- [x] Rerun original GPU-idle/manual-hold and maintenance-startup lifecycle checks in the targeted safety selection.
- [x] Rerun the timing-sensitive simulated acceptance test three times with isolated roots.
- [ ] Run Mining H3 tests against the exact combined review candidate and record JUnit/JSON evidence.
- [x] Prepare the H4 operational readiness ledger without host mutations.
- [ ] Run final scoped Ruff, compilation, provenance, and diff checks.
- [ ] Publish final review branch and verify its remote tip; leave `main` unchanged.
