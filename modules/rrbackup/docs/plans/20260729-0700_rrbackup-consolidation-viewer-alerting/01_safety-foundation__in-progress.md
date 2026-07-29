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
- [x] Repository-root `Invoke-Tests.ps1`
- [x] Manifest-driven target selection
- [x] RRBackup default target
- [x] Dependency bootstrap by default
- [x] Repository virtual-environment Python resolution
- [x] Target working-directory and pytest import isolation
- [x] Authoritative `LATEST.txt` report per target
- [x] Bounded prior-report history
- [x] Complete pytest and PowerShell stdout/stderr capture
- [x] PowerShell environment/entry-point smoke test
- [x] Opt-in production read-only compatibility test
- [x] Initial Windows baseline run and failure triage
- [x] Shared-environment import collision diagnosed
- [x] Repository-root dispatcher validated on Windows
- [x] Clean inherited baseline: 126 passed, 8 intentionally skipped
- [ ] Validate latest-first report migration and retention
- [ ] Unit tests for all Stage 1 public behavior
- [ ] Coverage report in authoritative result file
- [ ] Static review pass
- [ ] Local Windows validation pass after safety-foundation implementation

## Test Constraints

- Tests must not mutate `B:\ResticRepos\PC-Local`.
- Default validation must not open the production repository.
- Production read-only checks require an explicit switch.
- Integration tests create repositories only below `modules/rrbackup/.pytest_tmp_root/`.
- PowerShell tests must return nonzero on assertion failure.
- The repository-root dispatcher must capture complete stdout and stderr.
- Dependency installation and tests must use the same resolved repository Python interpreter.
- Pytest must run from the RRBackup working directory with importlib mode and an explicit root directory.
- Reports are intentionally tracked so the user can commit and push validation evidence.
- `docs/test-results/rrbackup/LATEST.txt` is authoritative.
- Prior reports are comparison-only and are bounded to three reports and 14 days by default.

## Validation Evidence

### Initial baseline

- 112 passed
- 4 skipped
- 10 failed
- 4 errors
- package-only branch coverage: 32%

### Shared-environment failure

The module-local runner encountered a shared-repository `tests.conftest` import collision. A separate manual pytest invocation used an interpreter without `pytest-mock` or `tomli-w`.

### Latest clean Windows run

- 134 tests collected
- 126 passed
- 8 intentionally skipped
- 0 failed
- 0 errors
- package branch coverage: 36%
- PowerShell environment smoke test passed
- production read-only test safely skipped

## Exit Criteria

Stage 1 is complete when:

1. Unit tests cover configuration resolution, command construction, preview, dry-run, policy, locking, state, and snapshot parsing.
2. Repository-root `Invoke-Tests.ps1` selects RRBackup through `validation-targets.json`, bootstraps dependencies, executes pytest, and runs every configured `*_test.ps1` script.
3. The dispatcher records environment details, exact commands, complete native output, section results, coverage, and final failure summaries in `docs/test-results/rrbackup/LATEST.txt`.
4. The user runs the dispatcher on Windows 11 and pushes a current authoritative report with all required checks passing.
5. `STATUS.md`, `checklist.md`, and `HANDOFF.md` record the exact validation evidence.
