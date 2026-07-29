# Stage 1 — Safety Foundation and Validation Harness

## Status

In progress.

## Goal

Create the shared safety-critical primitives and a repeatable Windows validation loop before redirecting any public command to the merged engine.

## Deliverables

- [ ] Canonical configuration and source-attribution model
- [ ] Legacy production defaults adapter
- [ ] Restic command model with redaction
- [ ] Print-command-only execution barrier
- [ ] Correct dry-run state behavior
- [ ] CPU policy decision model
- [ ] Atomic run-state store
- [ ] Process-identity lock
- [ ] Snapshot JSON and summary parser
- [ ] Root `Invoke-RRBackupValidation.ps1`
- [ ] PowerShell environment/entry-point smoke test
- [ ] Opt-in production read-only compatibility test
- [ ] Unit tests for all Stage 1 public behavior
- [ ] Coverage report in validation transcript
- [ ] Static review pass
- [ ] Local Windows validation pass

## Test Constraints

- Tests must not mutate `B:\ResticRepos\PC-Local`.
- Default validation must not open the production repository.
- Production read-only checks require an explicit switch.
- Integration tests create repositories only below `modules/rrbackup/.pytest_tmp_root/`.
- PowerShell tests must return nonzero on assertion failure.
- All output must be captured in a single paste-ready transcript.

## Exit Criteria

Stage 1 is complete when:

1. Unit tests cover configuration resolution, command construction, preview, dry-run, policy, locking, state, and snapshot parsing.
2. The root validation runner bootstraps dependencies and executes pytest plus every `*_test.ps1` under `modules/rrbackup/tests/`.
3. The runner prints environment details, exact commands, section results, coverage, and a final failure summary.
4. The user runs the harness on Windows 11 and returns a transcript with all required checks passing.
5. `STATUS.md`, `checklist.md`, and `HANDOFF.md` record the exact validation evidence.
