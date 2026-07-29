# Status

## Overall

Stage 1 is in progress. The remote/local validation loop is proven, but the module-local runner exposed shared-repository pytest import collisions and interpreter drift. Validation has therefore been promoted to a reusable repository-root dispatcher with a target manifest, automatic dependency bootstrap, target working-directory isolation, pytest importlib mode, and timestamped tracked reports under `docs/test-results/`.

The six-area CLI and shell-audit replacement contract remain fixed for Stage 2.

## Completed

- [x] Provenance analysis
- [x] Static audit of both modules
- [x] Production compatibility contract
- [x] Dedicated feature branch
- [x] Canonical project documentation structure
- [x] Hybrid remote/local workflow documented at repository level
- [x] Repository-root `Invoke-Tests.ps1` dispatcher
- [x] Manifest-driven validation targets in `validation-targets.json`
- [x] RRBackup registered as the default validation target
- [x] Dependency bootstrap enabled by default
- [x] Repository virtual-environment Python resolution
- [x] Target working-directory isolation
- [x] Pytest `--import-mode=importlib`
- [x] Timestamped tracked reports under `docs/test-results/<target>/`
- [x] Full stdout/stderr capture for pytest and PowerShell tests
- [x] PowerShell environment/entry-point smoke test
- [x] Opt-in production read-only snapshot compatibility test
- [x] Project-local ignored temporary-test root
- [x] First Windows validation output committed and consumed remotely
- [x] Second Windows validation output analyzed from the user-provided report
- [x] User-config-dependent tests changed from mandatory failure to optional skip
- [x] Live Google Drive tests made explicitly opt-in
- [x] Top-level CLI configuration errors converted to stable nonzero return codes
- [x] Duplicate outer RRBackup package initializer removed
- [x] Canonical six-area CLI architecture defined
- [x] Useful shell-audit capabilities mapped to first-class module commands
- [x] `backup view audit` contract defined

## In Progress

- [ ] Validate the new repository-root dispatcher on Windows
- [ ] Correct remaining inherited test defects after dependency/bootstrap isolation is confirmed
- [ ] Shared safety foundation
- [ ] Stage 1 unit tests and coverage
- [ ] Temporary-repository integration harness

## Validation Evidence

### First committed baseline

- 130 tests collected
- 112 passed
- 4 skipped
- 10 failed
- 4 errored
- package-only branch coverage: 32%

The module-local runner successfully captured complete pytest and PowerShell output, proving the remote evidence handoff.

### Second local run

The module-local runner failed before collection with an `ImportPathMismatchError` because pytest resolved another module's `tests.conftest` from the shared repository environment.

A manual `pytest` command then used a different Python environment than the repository virtual environment. That interpreter lacked `pytest-mock` and `tomli-w`, producing missing `mocker` fixtures and TOML writer failures. Stale editable console entry points also failed after removal of the duplicate outer package initializer.

These are addressed by the new root dispatcher:

- it always resolves the repository `.venv` Python first,
- bootstraps target development dependencies unless explicitly skipped,
- runs from the target working directory,
- sets the target `PYTHONPATH`,
- uses pytest importlib mode and an explicit root directory,
- records every command and its complete output in a tracked dated report.

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

The dispatcher writes reports using:

```text
docs/test-results/rrbackup/YYYYMMDD-HHMMSS_rrbackup.txt
```
