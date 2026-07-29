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

Stage 1 is verified. Stage 2 is split into bounded checkpoints. The current checkpoint is **2A — Single-CLI UX Foundation**, and remote implementation must stop for local validation before create/schedule wizard acceptance, scheduler mutation, compatibility-shim removal, or production-write work begins.

Historical facts remain:

- `B:\ResticRepos\PC-Local` contains snapshots `a1609113` and `022aad5b`.
- Those snapshots predate the committed `backup_module` implementation.
- The direct-Restic/`backup_module` behavior is the production compatibility authority.
- The old RRBackup repository config targets an unrelated Google Drive repository.
- No current module-owned local backup schedule is installed.
- Production retention/prune operations remain prohibited during consolidation.

## Collaboration Loop

1. The browser/app agent implements one bounded checkpoint with source, tests, documentation, and static review.
2. The user pulls with the normal `gl` alias and runs repository-root `Invoke-Tests.ps1`.
3. The dispatcher uninstalls the prior RRBackup package, installs shared TermDash, reinstalls RRBackup, compiles, lints, checks root/view help, runs pytest/coverage, and runs PowerShell checks.
4. The user performs the small manual acceptance list supplied for that checkpoint.
5. The user commits and pushes generated evidence under `docs/test-results/rrbackup/` and reports manual observations.
6. The browser/app agent reads `LATEST.txt`, `LATEST_CONTEXT.md`, and `LATEST_PROGRESS.diff`, reports success/failure/progress/loop state, and either patches Checkpoint 2A or begins Checkpoint 2B.

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

Automated validation may not run production backup, restore, init, unlock, forget, prune, cache cleanup, stale-lock removal, scheduler mutation, configuration migration apply, or retention application.

Create/schedule wizard and scheduler-apply code is present only as later-checkpoint scaffolding. Do not use `--apply` during Checkpoint 2A acceptance.

## Authoritative Evidence

```text
../../../docs/test-results/rrbackup/LATEST.txt
../../../docs/test-results/rrbackup/LATEST_CONTEXT.md
../../../docs/test-results/rrbackup/LATEST_PROGRESS.diff
```

Prior artifacts under `history/` are comparison-only and bounded to three prior artifacts and 14 days by default.

## Last Pushed Stage 2 Baseline

- 266 tests collected
- 256 passed
- 8 intentionally skipped
- 2 failed because inherited integration tests still expected obsolete `rrb` help text
- installed entry-point checks passed
- manual production read-only commands proved snapshot, health, timeline, provenance, repository, and audit data access

The two stale integration assertions have been replaced in Checkpoint 2A. No current evidence indicates a shared-engine regression.

## Checkpoint 2A Implementation

### Public command

Only one console entry point is declared:

```text
backup
```

The package is version `2.0.0` because removing `rrb` and `rrbackup` changes generated entry points. Validation performs an uninstall/reinstall and verifies the retired wrappers are absent.

Root areas:

```text
backup create
backup run
backup view
backup schedule
backup restore
backup repo
backup config
```

`repository` and selected prior read-only view spellings remain hidden input translations but are not advertised.

### Unified inventory

The inventory combines canonical TOML backup sets and legacy `local-main`, then enriches each backup with:

- sources and exclusions,
- tags and repository,
- schedule and retention descriptions,
- latest relevant snapshot,
- latest structured run,
- health,
- matched module-owned scheduler task,
- next expected run,
- missed-run count.

Canonical conversion preserves VSS/fs-snapshot behavior, cache exclusions, one-filesystem behavior, dry-run default, tags, and raw Restic options. Read-only loading does not create state, log, or generated input directories.

### Human and interactive presentation

Shared presentation now provides:

- ANSI-aware compact tables,
- consistent green/yellow/red/cyan/dim/magenta policy,
- plain/JSON/Markdown output modes,
- TermDash list/details integration,
- Up/Down and `j`/`k`, Page Up/Page Down, filtering, horizontal scrolling, Enter/details, and multi-select.

### Condensed commands

- `backup view` uses sections rather than a long display-command tree.
- `backup run` and `backup run auto` present configured backups; named execution remains available.
- `backup schedule` renders one backup row plus one schedule/retention row and excludes unrelated Windows tasks.
- `backup repo` combines status, keys, locks, snapshots, and cached storage into one human report.
- Full restore-size statistics run only with `backup repo --refresh-storage` and are cached.

### Test coverage added

Checkpoint 2A adds or rewrites tests for:

- seven-area parser and condensed help,
- single installed console entry point,
- hidden aliases,
- print-only no-materialization/no-execution behavior,
- canonical and multi-backup inventory,
- schedule descriptions, next runs, and missed runs,
- strict scheduler ownership filtering,
- palette, tables, details, callbacks, and ANSI stripping,
- repository summary and explicit/cached storage refresh,
- canonical temporary-repository backup/view/repo-check integration.

## Deferred Checkpoints

### 2B — Wizard Preview

Interactive create and schedule wizard acceptance, multi-backup editing, schedule and retention input validation, and full preview review.

### 2C — Apply

Atomic configuration writes, Windows Task Scheduler create/update/delete/run/export/import, confirmation, rollback, and controlled acceptance.

### 2D — Compatibility

Replace `modules/backup_module` internals with a thin shared-engine adapter and remove duplicate engine code.

### 2E — Production Acceptance

Canonical production read-only verification, controlled backup, restore/hash verification, scheduled execution, and final documentation.

## Known Documentation Debt

The module root `README.md` still documents the historical `rrb` interface. It is intentionally not rewritten in Checkpoint 2A before the new UX passes local and manual acceptance. Documentation cleanup remains required before Stage 2 completion.
