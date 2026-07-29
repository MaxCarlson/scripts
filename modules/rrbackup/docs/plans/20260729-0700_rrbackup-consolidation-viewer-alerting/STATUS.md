# Status

## Overall

Stage 1 is verified. The Windows checkpoint passed package compilation, focused correctness lint, 199 tests, and both PowerShell checks; 8 environment-dependent tests skipped intentionally. The repository-root validation evidence workflow also works as intended.

Stage 2 is in progress. The first canonical CLI/data slice proved that the merged engine can inspect the production repository, snapshots, health, provenance, configuration, and scheduler state. The latest automated checkpoint collected 266 tests: 256 passed, 8 skipped, and 2 failed because inherited integration assertions still expected obsolete `rrb` help text. Installed entry-point smoke checks passed.

Manual acceptance then identified design defects that automated tests did not reveal:

- `backup view` is over-fragmented into too many display-specific commands.
- Human-facing repository and diagnostic output defaults to raw JSON.
- `backup schedule list` matches unrelated Windows tasks containing the word `Backup`.
- `backup view storage` silently performs an expensive full restore-size calculation and took about 72 seconds on the production repository.
- `backup run` requires too much knowledge of sources, tags, and paths instead of presenting configured backups.
- A creation wizard, backup-centric schedule wizard, consistent color policy, and shared interactive UI are still missing.

The active Stage 2 plan and checklist now contain the complete requested UX, command, wizard, schedule, retention, repository, and TUI specification so the requirements are not lost.

## Progress Assessment

### Successfully implemented and verified

- Shared safety engine and terminal-state handling
- Canonical `backup` executable
- Installed-entry-point packaging/import correction
- Production repository and snapshot read-only access
- Snapshot timeline and health data
- Provenance and comprehensive audit data collection
- Configuration/source attribution
- Initial repository and schedule adapters
- Root validation dispatcher and authoritative evidence handoff
- 256 passing tests in the latest Stage 2 checkpoint

### Implemented but not yet locally verified

- Expanded schedule model for minute/hour/day/week/month/year/custom/manual schedules
- Schedule description, next-run, and missed-run calculations
- Unified inventory for canonical TOML sets and legacy `local-main`
- Inventory enrichment with snapshots, runs, health, scheduler state, next run, and missed runs
- Strict scheduler ownership matching for canonical `backup` invocations and `RRBackup::` tasks

### Not yet implemented

- One-public-command packaging (`backup` only)
- Seven-area task-oriented root CLI
- Condensed interactive `backup view`
- Interactive/default `backup run` chooser
- Backup-centric schedule table and schedule editor wizard
- Themed creation wizard
- Combined human-readable `backup repo` summary
- Explicit cached storage refresh
- Shared color/table/TUI presentation layer
- Removal of duplicate `backup_module` engine

### Bugs and failing tests

- Two inherited integration tests assert obsolete `rrb` help wording and wizard exposure.
- No current evidence of a functional engine regression.
- The newly added inventory/schedule work has not yet been run locally.

### Progress and loop assessment

Measurable progress occurred. The work is not looping: Stage 1 is complete, the Stage 2 data layer works against production, and manual feedback has redirected the next bounded implementation toward usability rather than repeating safety work. The next checkpoint must show visible CLI simplification and human-output improvements; another checkpoint containing only internal refactoring would be insufficient progress.

## Active Stage 2 Command Target

Only one public executable is required:

```text
backup
```

Target root areas:

```text
backup create
backup run
backup view
backup schedule
backup restore
backup repo
backup config
```

`repo` replaces the public `repository` spelling. The internal package may retain the `rrbackup` name during migration.

## Current Implementation Target

The current pass is implementing:

1. one unified configured-backup inventory,
2. strict module-owned scheduler discovery,
3. shared colored human renderers,
4. a condensed `view` dashboard,
5. a configured-backup chooser for `run`,
6. backup-centric schedule output,
7. a combined repository summary that never runs expensive statistics implicitly,
8. parser and packaging changes for the single `backup` command.

The schedule editor and creation wizard models follow immediately after the inventory/presentation checkpoint, using the same shared TUI conventions.

## Last Known Production State

- Repository: `B:\ResticRepos\PC-Local`
- Known snapshots: `a1609113`, `022aad5b`
- Latest snapshot: 2026-04-14
- Current module-owned backup schedule: absent
- Automated production mutation: prohibited

## Validation

From the repository root:

```powershell
./Invoke-Tests.ps1
```

Authoritative evidence:

```text
docs/test-results/rrbackup/LATEST.txt
docs/test-results/rrbackup/LATEST_CONTEXT.md
docs/test-results/rrbackup/LATEST_PROGRESS.diff
```
