# Status

## Overall

Stage 1 implementation is complete and awaiting local validation. The reusable repository-root validation dispatcher was previously proven on Windows with 126 passing tests and 8 intentional skips. This checkpoint adds the shared safety engine and a substantial regression suite before any existing public CLI is redirected.

Validation evidence now uses `LATEST.txt`, `LATEST_CONTEXT.md`, and `LATEST_PROGRESS.diff`, with bounded history. The six-area CLI and shell-audit replacement contract remain fixed for Stage 2.

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
- [x] Paired `LATEST_CONTEXT.md` and `LATEST_PROGRESS.diff`
- [x] Bounded prior-report history
- [x] Full stdout/stderr capture for compilation, lint, pytest, and PowerShell tests
- [x] PowerShell environment/entry-point smoke test
- [x] Opt-in production read-only snapshot compatibility test
- [x] Project-local ignored temporary-test root
- [x] Repository-root dispatcher validated on Windows
- [x] User-config-dependent tests changed from mandatory failure to optional skip
- [x] Live Google Drive tests made explicitly opt-in
- [x] Top-level CLI configuration errors converted to stable nonzero return codes
- [x] Duplicate outer RRBackup package initializer removed
- [x] Canonical six-area CLI architecture defined
- [x] Useful shell-audit capabilities mapped to first-class module commands
- [x] `backup view audit` contract defined
- [x] Canonical legacy `backup_module` profile adapter with source attribution
- [x] Production-compatible Restic backup command builder
- [x] Hard preview/print-only execution barrier
- [x] Distinct dry-run execution mode
- [x] Process-identity-aware lock with ownership token
- [x] Atomic current/history/last-success state store
- [x] CPU normal/overdue decision and wait policy
- [x] Snapshot and backup-summary JSON parsers
- [x] Shared backup execution engine
- [x] CPU gating occurs before lock acquisition
- [x] Dry runs never update last-success state
- [x] Lock, wait, execution, interruption, and finalization failures reach terminal state
- [x] RRBackup version bumped to `0.3.0`
- [x] `psutil` declared as a runtime dependency
- [x] Stage 1 unit and lifecycle regression tests authored

## Awaiting Validation

- [ ] Compile new package and tests on Windows
- [ ] Run focused correctness lint
- [ ] Run full pytest and coverage suite
- [ ] Run PowerShell smoke tests
- [ ] Verify first-run migration to `LATEST.*` validation artifacts
- [ ] Verify generated context snapshot and baseline progress diff
- [ ] Correct failures found by the local run
- [ ] Decide whether Stage 1 coverage is sufficient before Stage 2

## Latest Proven Baseline Before This Checkpoint

- 134 tests collected
- 126 passed
- 8 intentionally skipped
- 0 failed
- 0 errors
- package branch coverage: 36%
- environment smoke test: passed
- production read-only test: safely skipped

The next run adds the new Stage 1 tests and will establish the first safety-foundation baseline.

## New Stage 1 Components

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

The existing public `rrb` and `rrbackup` commands still use the inherited implementation. Stage 2 will redirect compatible commands only after this safety foundation passes locally.

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

The authoritative evidence is:

```text
docs/test-results/rrbackup/LATEST.txt
docs/test-results/rrbackup/LATEST_CONTEXT.md
docs/test-results/rrbackup/LATEST_PROGRESS.diff
```
