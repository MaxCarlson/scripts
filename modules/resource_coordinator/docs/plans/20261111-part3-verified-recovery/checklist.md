# Part 3 Checklist

- [x] Verify Part 2 remote checkpoint, current main ancestry, scoped diff, and H3 maintenance-protocol equivalence.
- [x] Create isolated Part 3 worktree from the pushed Part 2 checkpoint and verify the unchanged V3 copy.
- [x] Capture targeted baseline test evidence, including the known idle/manual-override failure.
- [x] Implement journal transaction serialization, revisions, compatible loading, and rollback/export behavior.
- [x] Implement idempotent startup holder canonicalization and fail-closed restoration.
- [x] Classify process access denial and PID reuse without treating unverifiable processes as absent.
- [x] Add reconciliation phases/dispositions and atomic exact-holder recovery transaction.
- [x] Add recovery fence, bounded external observation, revision/generation revalidation, and authenticated auto-recovery endpoint.
- [x] Keep automatic eligibility limited to proven not-forwarded or actual protocol-terminal evidence; retain holds for unsupported forwarded cases.
- [x] Repair and regress GPU-idle/manual-hold restart behavior; classify the historical gateway failure.
- [x] Integrate `rc recover --apply` without changing `--force`, maintenance reconciliation, or offline semantics.
- [x] Run focused fault-injection, regression, Ruff, compilation, and provenance checks.
- [x] Update final evidence and review the implementation diff.
- [x] Final diff check, task-only stage/commit, and publish the feature branch.
- [x] Verify the pushed feature ref and final clean worktree after status finalization.
