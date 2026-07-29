# Status

## Overall

Stage 1 is in progress. The reusable repository-root validation dispatcher is now proven on Windows: the latest complete run collected 134 tests, passed 126, intentionally skipped 8 environment-dependent tests, and produced no failures or errors. Both PowerShell validation scripts passed or safely skipped as designed.

Validation reports now use an unambiguous latest-first layout with bounded history. The six-area CLI and shell-audit replacement contract remain fixed for Stage 2.

## Completed

- [x] Provenance analysis
- [x] Static audit of both modules
- [x] Production compatibility contract
- [x] Dedicated feature branch
- [x] Canonical project documentation structure
- [x] Hybrid remote/local workflow documented at repository level
- [x] One-time hybrid reminder documented for local agents
- [x] Repository-root `Invoke-Tests.ps1` dispatcher
- [x] Manifest-driven validation targets in `validation-targets.json`
- [x] RRBackup registered as the default validation target
- [x] Dependency bootstrap enabled by default
- [x] Repository virtual-environment Python resolution
- [x] Target working-directory isolation
- [x] Pytest `--import-mode=importlib`
- [x] Authoritative `docs/test-results/<target>/LATEST.txt`
- [x] Bounded prior-report history
- [x] Full stdout/stderr capture for pytest and PowerShell tests
- [x] PowerShell environment/entry-point smoke test
- [x] Opt-in production read-only snapshot compatibility test
- [x] Project-local ignored temporary-test root
- [x] Initial Windows validation output committed and consumed remotely
- [x] Shared-environment pytest failure diagnosed
- [x] Repository-root dispatcher validated on Windows
- [x] User-config-dependent tests changed from mandatory failure to optional skip
- [x] Live Google Drive tests made explicitly opt-in
- [x] Top-level CLI configuration errors converted to stable nonzero return codes
- [x] Duplicate outer RRBackup package initializer removed
- [x] Canonical six-area CLI architecture defined
- [x] Useful shell-audit capabilities mapped to first-class module commands
- [x] `backup view audit` contract defined

## In Progress

- [ ] Shared safety foundation
- [ ] Stage 1 unit tests and coverage
- [ ] Temporary-repository integration harness expansion
- [ ] Validation of latest-first report migration and retention

## Validation Evidence

### Initial baseline

- 130 tests collected
- 112 passed
- 4 skipped
- 10 failed
- 4 errored
- package-only branch coverage: 32%

### Shared-environment failure

The module-local runner imported another module's `tests.conftest` from the shared repository environment. A manual pytest command used a different Python environment without `pytest-mock` or `tomli-w`.

This was corrected structurally through the repository-root dispatcher, target working-directory isolation, dependency bootstrap, explicit repository Python resolution, target `PYTHONPATH`, and pytest importlib mode.

### Latest clean Windows run

- 134 tests collected
- 126 passed
- 8 intentionally skipped
- 0 failed
- 0 errors
- package branch coverage: 36%
- environment smoke test: passed
- production read-only test: safely skipped

The skipped tests require either a user RRBackup configuration or explicitly enabled Google Drive access.

## CLI Contract

The canonical command will be `backup` with six major areas:

```text
backup run
backup view
backup config
backup schedule
backup restore
backup repository
```

`backup edit` aliases `backup config`. Existing `rrb`, `rrbackup`, `backup_module`, and `python -m backup_module` interfaces remain during the compatibility period.

The complete contract and shell-audit mapping are in:

```text
docs/CLI_ARCHITECTURE_AND_AUDIT_COVERAGE.md
```

The comprehensive read-only diagnostic replacement is:

```text
backup view audit
```

## Last Known Production State

- Repository: `B:\ResticRepos\PC-Local`
- Known snapshots: `a1609113`, `022aad5b`
- Latest snapshot: 2026-04-14
- Current backup schedule: absent
- Production mutation during automated validation: prohibited

## Validation Commands

From the repository root:

```powershell
./Invoke-Tests.ps1
```

Optional production read-only validation:

```powershell
./Invoke-Tests.ps1 -IncludeProductionReadOnly
```

The authoritative report is:

```text
docs/test-results/rrbackup/LATEST.txt
```

Prior reports are retained only under `history/`, with default limits of three reports and 14 days.
