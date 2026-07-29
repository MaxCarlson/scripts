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
- A creation wizard, backup-centric schedule wizard, consistent color policy, and shared interactive UI were missing from the validated build.

The active Stage 2 plan and checklist contain the complete requested UX, command, wizard, schedule, retention, repository, and TUI specification so the requirements are not lost.

## Checkpoint Guardrail

Stage 2 is split into bounded checkpoints sized for roughly 10–20 minutes between local pull/test/push cycles.

The current checkpoint is **2A — Single-CLI UX Foundation**. Work stops for local validation after its tests and documentation are complete. No additional Stage 2 feature group begins until the newest automated and manual results are reviewed.

Checkpoint 2A includes:

1. one installed `backup` command,
2. seven task-oriented root areas,
3. unified configured-backup inventory,
4. concise human tables and shared color policy,
5. condensed `view`,
6. configured-backup selection for `run`,
7. backup-centric schedule display and strict task filtering,
8. combined repository summary with explicit cached storage refresh,
9. tests for these exact boundaries.

Checkpoint 2A excludes production configuration writes, scheduler mutation acceptance, retention execution, and duplicate-engine removal. Create/schedule wizard and scheduler-apply code currently present on the branch is unaccepted scaffolding for later checkpoints and must not be manually applied during 2A validation.

## Progress Assessment

### Successfully implemented and verified

- Shared safety engine and terminal-state handling
- Canonical `backup` executable in the last validated package
- Installed-entry-point packaging/import correction
- Production repository and snapshot read-only access
- Snapshot timeline and health data
- Provenance and comprehensive audit data collection
- Configuration/source attribution
- Initial repository and schedule adapters
- Root validation dispatcher and authoritative evidence handoff
- 256 passing tests in the latest Stage 2 checkpoint

### Implemented but not yet locally verified

- Package configuration with only the `backup` console entry point
- Seven-area task-oriented parser: `create`, `run`, `view`, `schedule`, `restore`, `repo`, and `config`
- Expanded schedule model for minute/hour/day/week/month/year/custom/manual schedules
- Schedule description, next-run, and missed-run calculations
- Unified inventory for canonical TOML sets and legacy `local-main`
- Inventory enrichment with snapshots, runs, health, scheduler state, next run, and missed runs
- Strict scheduler ownership matching for canonical `backup` invocations and `RRBackup::` tasks
- Shared ANSI-aware human tables, status palette, plain fallback, and TermDash selection/details adapter
- Condensed view sections and configured-backup run selection
- Backup-centric schedule rendering
- Combined repository summary and explicit cached storage refresh
- Canonical TOML preservation of VSS, cache exclusion, one-file-system, tags, and raw Restic options
- Preview-oriented create/schedule wizard and scheduler-management scaffolding

### Remaining before Checkpoint 2A validation handoff

- Complete focused unit tests for inventory, presentation, repository summary/cache, scheduler filtering, and preview safety
- Update validation manifest lint targets and smoke commands
- Complete static review of new parser/runtime modules
- Update checklist/handoff state
- Stop implementation and request one local root validation run

### Deferred to later checkpoints

- Interactive create and schedule wizard acceptance
- Production configuration writes
- Scheduler create/update/delete acceptance
- Retention execution
- Cross-platform scheduler CRUD completion
- Removal of duplicate `backup_module` engine

### Bugs and failing tests from the last pushed report

- Two inherited integration tests assert obsolete `rrb` help wording and wizard exposure.
- No current evidence of a functional engine regression.
- The new Checkpoint 2A implementation has not yet been run locally.

### Progress and loop assessment

Measurable progress occurred. The work is not looping: Stage 1 is complete, the Stage 2 data layer works against production, and manual feedback redirected Checkpoint 2A toward visible usability improvements. The scope is now frozen until local validation; continuing into another feature group before that run would violate the checkpoint guardrail.

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
