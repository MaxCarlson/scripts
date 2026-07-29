# Status

## Overall

Stage 1 is in progress. The remote/local validation loop is proven: the user ran the module-local orchestrator, committed `TEST_RESULTS.txt`, and the complete pytest and PowerShell output was read remotely. The first inherited baseline fixes are committed. The six-area CLI and shell-audit replacement contract are also fixed for Stage 2.

## Completed

- [x] Provenance analysis
- [x] Static audit of both modules
- [x] Production compatibility contract
- [x] Dedicated feature branch
- [x] Canonical project documentation structure
- [x] Hybrid remote/local workflow documented
- [x] Module-local `Invoke-Tests.ps1` orchestrator
- [x] Tracked `TEST_RESULTS.txt` evidence handoff
- [x] Full stdout/stderr capture for pytest and PowerShell tests
- [x] PowerShell environment/entry-point smoke test
- [x] Opt-in production read-only snapshot compatibility test
- [x] Project-local ignored temporary-test root
- [x] First Windows validation output committed and consumed remotely
- [x] Initial failure triage
- [x] User-config-dependent tests changed from mandatory failure to optional skip
- [x] Live Google Drive tests made explicitly opt-in
- [x] Top-level CLI configuration errors converted to stable nonzero return codes
- [x] Duplicate outer RRBackup package initializer removed
- [x] Canonical six-area CLI architecture defined
- [x] Useful shell-audit capabilities mapped to first-class module commands
- [x] `backup view audit` contract defined

## In Progress

- [ ] Correct remaining inherited test defects
- [ ] Shared safety foundation
- [ ] Stage 1 unit tests and coverage
- [ ] Temporary-repository integration harness

## Committed Windows Baseline

The committed `TEST_RESULTS.txt` run collected 130 tests:

- 112 passed
- 4 skipped
- 10 failed
- 4 errored
- package-only branch coverage: 32%

The runner itself worked correctly:

- editable development install passed,
- complete pytest output was captured,
- environment smoke test passed,
- production read-only test was safely skipped because it was not enabled,
- the tracked result file was generated and pushed successfully.

Remaining inherited baseline issues:

- raw Restic options beginning with `-` require unambiguous `--extra=<value>` syntax or a redesigned pass-through interface,
- one CLI test incorrectly mocks `Path.open`, turning valid binary TOML loading into text-mode loading,
- one version-short-form test does not catch the expected successful `SystemExit`,
- platform tests mutate `os.name`, which breaks `pathlib` concrete path selection on Windows,
- path-expansion tests assume POSIX output on Windows,
- one no-expansion test contradicts its fixture, which explicitly supplies state and log directories,
- large legacy config/wizard modules have little coverage and are scheduled for replacement rather than superficial coverage inflation.

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

From `modules/rrbackup`:

```powershell
./Invoke-Tests.ps1 -Bootstrap
```

Optional production read-only validation:

```powershell
./Invoke-Tests.ps1 -IncludeProductionReadOnly
```

The runner overwrites the tracked file:

```text
TEST_RESULTS.txt
```
