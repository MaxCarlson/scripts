# Stage 1 — Safety Foundation and Validation Harness

## Status

Implementation complete; local validation pending.

## Goal

Create the shared safety-critical primitives and a repeatable Windows validation loop before redirecting any public command to the merged engine.

## Deliverables

- [x] Canonical configuration and source-attribution model
- [x] Legacy production defaults adapter
- [x] Restic command model with redaction
- [x] Print-command-only execution barrier
- [x] Correct dry-run state behavior
- [x] CPU policy decision model
- [x] Atomic run-state store
- [x] Process-identity lock
- [x] Snapshot JSON and backup-summary parser
- [x] Shared backup execution engine
- [x] Repository-root `Invoke-Tests.ps1`
- [x] Manifest-driven target selection
- [x] RRBackup default target
- [x] Dependency bootstrap by default
- [x] Repository virtual-environment Python resolution
- [x] Target working-directory and pytest import isolation
- [x] Authoritative `LATEST.txt` report per target
- [x] Generated `LATEST_CONTEXT.md` and `LATEST_PROGRESS.diff`
- [x] Bounded prior-report history
- [x] Complete compile, lint, pytest, coverage, and PowerShell output capture
- [x] PowerShell environment/entry-point smoke test
- [x] Opt-in production read-only compatibility test
- [x] Initial Windows baseline run and failure triage
- [x] Shared-environment import collision diagnosed
- [x] Repository-root dispatcher validated on Windows
- [x] Clean inherited baseline: 126 passed, 8 intentionally skipped
- [x] Unit and lifecycle tests authored for Stage 1 public behavior
- [x] Remote static review pass
- [ ] Validate latest-first report migration and retention
- [ ] Validate generated context snapshot and progress diff
- [ ] Establish Stage 1 coverage result
- [ ] Pass local Windows validation after safety-foundation implementation
- [ ] Correct any local failures
- [ ] Mark Stage 1 verified

## Implemented Components

```text
rrbackup/engine.py
rrbackup/locking.py
rrbackup/models.py
rrbackup/policy.py
rrbackup/profile.py
rrbackup/restic.py
rrbackup/snapshots.py
rrbackup/state.py
```

The inherited public CLI has not yet been redirected. Stage 2 will use these primitives only after this checkpoint passes locally.

## Required Semantics

- Preview mode validates and renders the command without starting Restic, writing run state, creating logs, or acquiring a lock.
- Dry-run mode executes Restic with `--dry-run` but records `dry-run`, never `success`, and never advances last-success state.
- CPU gating completes before lock acquisition.
- Lock ownership uses PID plus process creation time and an ownership token.
- Invalid lock files are not silently removed.
- Active lock contention records a skipped attempt rather than false success.
- Wait, lock, execution, interruption, and result-finalization failures leave terminal persisted state.
- Real successful backups may update last-success and record a Restic snapshot ID.
- The legacy profile adapter preserves the production repository, password file, source/exclusion files, tag, VSS behavior, cache exclusion, and CPU policy defaults.

## Test Constraints

- Tests must not mutate `B:\ResticRepos\PC-Local`.
- Default validation must not open the production repository.
- Production read-only checks require an explicit switch.
- Integration tests create repositories only below `modules/rrbackup/.pytest_tmp_root/`.
- PowerShell tests must return nonzero on assertion failure.
- The repository-root dispatcher must capture complete stdout and stderr.
- Dependency installation and tests must use the same resolved repository Python interpreter.
- Pytest must run from the RRBackup working directory with importlib mode and an explicit root directory.
- `docs/test-results/rrbackup/LATEST.txt` is authoritative.
- `LATEST_CONTEXT.md` pairs the report with the active status/checklist.
- `LATEST_PROGRESS.diff` records project-progress changes since the previous validation.
- Prior artifacts are comparison-only and are bounded to three prior runs and 14 days by default.

## Prior Validation Evidence

### Initial baseline

- 112 passed
- 4 skipped
- 10 failed
- 4 errors
- package-only branch coverage: 32%

### Shared-environment failure

The module-local runner encountered a shared-repository `tests.conftest` import collision. A separate manual pytest invocation used an interpreter without `pytest-mock` or `tomli-w`.

### Latest clean inherited baseline

- 134 tests collected
- 126 passed
- 8 intentionally skipped
- 0 failed
- 0 errors
- package branch coverage: 36%
- PowerShell environment smoke test passed
- production read-only test safely skipped

The next validation establishes the first baseline containing the new safety engine and regression suite.

## Exit Criteria

Stage 1 is complete when:

1. Unit tests cover configuration resolution, command construction, preview, dry-run, CPU policy, locking, state, snapshot parsing, and complete engine lifecycles.
2. Repository-root `Invoke-Tests.ps1` completes bootstrap, compilation, focused correctness lint, pytest/coverage, and every configured PowerShell test.
3. The dispatcher creates valid `LATEST.txt`, `LATEST_CONTEXT.md`, and `LATEST_PROGRESS.diff` artifacts.
4. The user runs the dispatcher on Windows 11 and pushes current evidence with all required checks passing.
5. `STATUS.md`, `checklist.md`, and `HANDOFF.md` record the exact validation evidence.
