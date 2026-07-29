# RRBackup Consolidation Handoff

## Current State

Active branch:

```text
agent/merge-restic-backup-modules
```

Active plan:

```text
docs/plans/20260729-0700_rrbackup-consolidation-viewer-alerting/
```

Active stage:

```text
docs/plans/20260729-0700_rrbackup-consolidation-viewer-alerting/02_compatibility-merge-and-cli__in-progress.md
```

Stage 1 is verified. Stage 2 now contains the first canonical hierarchical CLI, viewer/audit foundation, repository inspection, Windows schedule discovery, restore preview/run gating, packaging repair, and expanded tests.

Historical facts remain:

- `B:\ResticRepos\PC-Local` contains snapshots `a1609113` and `022aad5b`.
- Those snapshots predate the committed `backup_module` implementation.
- The direct-Restic/`backup_module` behavior is the production compatibility authority.
- The old RRBackup repository config targets an unrelated Google Drive repository.
- No current local backup schedule is installed.
- Production retention/prune operations remain prohibited during consolidation.

## Collaboration Loop

1. The browser/app agent implements source, tests, documentation, and static review remotely.
2. The user pulls with the normal `gl` alias and runs repository-root `Invoke-Tests.ps1`.
3. The dispatcher cleans stale target metadata, bootstraps dependencies, compiles, lints, runs canonical CLI help, pytest/coverage, and PowerShell checks.
4. The user commits and pushes generated evidence under `docs/test-results/rrbackup/`.
5. The browser/app agent reads `LATEST.txt`, `LATEST_CONTEXT.md`, and `LATEST_PROGRESS.diff`, then patches failures or continues the stage.

Do not have multiple agents independently edit this branch. Local agents should primarily provide authoritative environment-dependent execution evidence unless assigned a separate patch branch.

## Validation Safety

Default validation must not access or mutate the production repository.

```powershell
./Invoke-Tests.ps1
```

Production read-only checks require:

```powershell
./Invoke-Tests.ps1 -IncludeProductionReadOnly
```

Automated validation may not run production backup, restore, init, unlock, forget, prune, cache cleanup, stale-lock removal, or retention application.

## Authoritative Evidence

```text
../../../docs/test-results/rrbackup/LATEST.txt
../../../docs/test-results/rrbackup/LATEST_CONTEXT.md
../../../docs/test-results/rrbackup/LATEST_PROGRESS.diff
```

Prior artifacts under `history/` are comparison-only and bounded to three prior artifacts and 14 days by default.

## Verified Stage 1 Baseline

- 207 tests collected
- 199 passed
- 8 intentionally skipped
- 0 failed
- 0 errors
- package branch coverage: 55%
- compilation: passed
- focused correctness lint: passed
- PowerShell smoke test: passed
- production read-only check: safely skipped

## Installed Entry-Point Regression

A manual `rrb -h` after the Stage 1 run failed with:

```text
ImportError: cannot import name '__version__' from 'rrbackup' (unknown location)
```

The old smoke test inherited `PYTHONPATH={target_root}`, which masked repository namespace resolution. The branch now:

- restores `modules/rrbackup/__init__.py` as an intentional repository-path compatibility shim,
- extends the package path to the installable inner package,
- stores version data in `rrbackup/version.py`,
- tests both legacy and canonical imports with `modules` on `PYTHONPATH`,
- removes injected `PYTHONPATH` before installed-entry-point smoke checks,
- invokes the real `backup`, `rrb`, and `rrbackup` executables,
- cleans stale `*.egg-info`, `build`, and `dist` artifacts before installation.

Before editable reinstall, the old `rrb`/`rrbackup` entry points should import successfully through the shim. After reinstall, all three entry points target `rrbackup.application:main`.

## Canonical CLI Checkpoint

```text
backup run
backup view
backup config
backup schedule
backup restore
backup repository
```

`backup edit` translates to `backup config`.

Implemented viewer operations include:

```text
backup view
backup view dashboard
backup view timeline
backup view snapshots
backup view snapshot <id>
backup view runs
backup view run <id>
backup view logs
backup view storage
backup view gaps
backup view health
backup view schedules
backup view setup
backup view system
backup view provenance
backup view alerts
backup view audit
backup view export
backup view search <pattern>
```

The comprehensive read-only diagnostic replacement is:

```text
backup view audit
```

Current audit coverage includes executable/runtime resolution, effective configuration and attribution, safe environment metadata, configuration discovery, path metadata, source/exclusion entries, repository config and keys, snapshots, run state, logs, locks, Windows schedules, health, provenance, and recommendations.

## Stage 2 Remaining

- Pass expanded Windows validation.
- Add TOML/named-set conversion to the canonical engine.
- Preserve all `backup_module` commands through the shared engine.
- Reduce `modules/backup_module` to a compatibility shim.
- Add snapshot tag/host/path filters.
- Implement audit path redaction.
- Add detailed scheduler history and other launcher discovery.
- Add restore history and hash verification.
- Verify production snapshots through canonical read-only commands.
