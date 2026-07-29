# Status

## Overall

Stage 1 is in progress. The canonical documentation structure, hybrid remote/local collaboration workflow, module-local test orchestrator, PowerShell smoke tests, and initial Windows baseline run are complete. Shared safety-foundation source work and replacement tests are next.

## Completed

- [x] Provenance analysis
- [x] Static audit of both modules
- [x] Production compatibility contract
- [x] Dedicated feature branch
- [x] Canonical project documentation structure
- [x] Hybrid remote/local workflow documented
- [x] Module-local `Invoke-Tests.ps1` orchestrator
- [x] Tracked `TEST_RESULTS.txt` evidence handoff
- [x] Full stdout/stderr capture design for pytest and PowerShell tests
- [x] PowerShell environment/entry-point smoke test
- [x] Opt-in production read-only snapshot compatibility test
- [x] Project-local ignored temporary-test root
- [x] Initial Windows baseline validation
- [x] Initial failure triage

## In Progress

- [ ] Correct or replace inherited tests that depend on user configuration or external services
- [ ] Shared safety foundation
- [ ] Stage 1 unit tests and coverage
- [ ] Temporary-repository integration harness

## Initial Windows Baseline

The first local run collected 130 tests:

- 112 passed
- 4 skipped
- 10 failed
- 4 errored
- reported coverage: 59%

Primary baseline issues:

- inherited integration tests fail when the user's RRBackup config is absent instead of skipping or using isolated fixtures,
- raw Restic options beginning with `-` are passed to `--extra` ambiguously in tests,
- top-level CLI configuration errors escape instead of becoming stable nonzero return codes,
- platform tests mutate `os.name` and make `pathlib` instantiate an unsupported concrete path type,
- path-expansion tests assume POSIX behavior while running on Windows,
- one no-expansion test contradicts the supplied fixture, which explicitly contains state and log directories,
- a CLI test mocks `Path.open` in a way that converts binary TOML loading into text-mode loading,
- coverage is inflated by test modules and diluted by large legacy wizard modules that will be rewritten or removed.

The complete baseline supplied by the user is recorded in the current conversation and will be superseded by the tracked `TEST_RESULTS.txt` workflow on the next run.

## Last Known Production State

- Repository: `B:\ResticRepos\PC-Local`
- Known snapshots: `a1609113`, `022aad5b`
- Latest snapshot: 2026-04-14
- Current backup schedule: absent
- Production mutation during automated validation: prohibited

## Validation Commands

From `modules/rrbackup`:

```powershell
./Invoke-Tests.ps1 -Bootstrap
```

Optional production read-only validation:

```powershell
./Invoke-Tests.ps1 -IncludeProductionReadOnly
```

The test runner overwrites the tracked file:

```text
TEST_RESULTS.txt
```
