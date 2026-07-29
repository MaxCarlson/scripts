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
- [x] Module-root `Invoke-Tests.ps1`
- [x] Tracked `TEST_RESULTS.txt` evidence handoff
- [x] Complete pytest and PowerShell stdout/stderr capture
- [x] PowerShell environment/entry-point smoke test
- [x] Opt-in production read-only compatibility test
- [x] Initial Windows baseline run and failure triage
- [ ] Correct or replace inherited environment-dependent tests
- [ ] Unit tests for all Stage 1 public behavior
- [ ] Coverage report in tracked result file
- [ ] Static review pass
- [ ] Local Windows validation pass

## Test Constraints

- Tests must not mutate `B:\ResticRepos\PC-Local`.
- Default validation must not open the production repository.
- Production read-only checks require an explicit switch.
- Integration tests create repositories only below `modules/rrbackup/.pytest_tmp_root/`.
- PowerShell tests must return nonzero on assertion failure.
- The module-local runner must capture complete stdout and stderr in `TEST_RESULTS.txt`.
- The result file is intentionally tracked so the user can commit and push validation evidence.
- The result file is overwritten each run; timestamped output artifacts are not created.

## Initial Baseline

The initial local run produced:

- 112 passed
- 4 skipped
- 10 failed
- 4 errors
- 59% reported coverage

The failures expose inherited implementation and test defects. They are now inputs to Stage 1 rather than prerequisites the user must resolve locally.

## Exit Criteria

Stage 1 is complete when:

1. Unit tests cover configuration resolution, command construction, preview, dry-run, policy, locking, state, and snapshot parsing.
2. `Invoke-Tests.ps1` executes pytest plus every `*_test.ps1` under `tests/`.
3. The runner records environment details, exact commands, complete native output, section results, coverage, and a final failure summary in `TEST_RESULTS.txt`.
4. The user runs the harness on Windows 11 and pushes a result file with all required checks passing.
5. `STATUS.md`, `checklist.md`, and `HANDOFF.md` record the exact validation evidence.
