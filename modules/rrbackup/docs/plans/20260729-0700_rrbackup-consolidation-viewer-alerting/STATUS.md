# Status

## Overall

Stage 1 is verified. The Windows checkpoint passed package compilation, focused correctness lint, 199 tests, and both PowerShell checks; 8 environment-dependent tests skipped intentionally. The repository-root validation evidence workflow also works as intended.

Stage 2 is split into bounded checkpoints. The current checkpoint is **2A — Single-CLI UX Foundation**, and it is ready for local automated and manual validation. No additional Stage 2 feature group should begin until the resulting evidence is reviewed.

The prior Stage 2 checkpoint collected 266 tests: 256 passed, 8 skipped, and 2 failed because inherited integration assertions still expected obsolete `rrb` help text. Those assertions have been replaced with canonical `backup` checks in Checkpoint 2A.

Manual acceptance of the prior CLI identified:

- an over-fragmented `backup view` command tree,
- raw JSON as default human-facing repository/diagnostic output,
- unrelated Windows tasks in schedule discovery,
- an implicit restore-size calculation that took about 72 seconds,
- a run command that required too much Restic/configuration knowledge,
- missing shared color and interactive presentation conventions.

Checkpoint 2A directly targets those findings.

## Checkpoint Guardrail

Each checkpoint contains one closely related feature/correction group and should result in approximately 10–20 minutes between local pull/test/push cycles.

For every checkpoint:

1. source, tests, planning state, and static review are completed together,
2. implementation stops for local validation,
3. automated and manual results are reviewed before the next checkpoint,
4. failures must remain attributable to the newest bounded change set.

Create/schedule wizard acceptance, scheduler/configuration apply, compatibility-shim removal, and production-write work are not part of Checkpoint 2A.

## Progress Assessment

### Successfully implemented and previously verified

- Shared safety engine and terminal-state handling
- Production repository and snapshot read-only access
- Snapshot timeline and health data
- Provenance and comprehensive audit collection
- Configuration/source attribution
- Root validation dispatcher and authoritative evidence handoff
- 256 passing tests in the last Stage 2 report

### Implemented in Checkpoint 2A and awaiting local validation

- Package version `2.0.0`
- Only one declared public console entry point: `backup`
- Uninstall/reinstall validation that removes retired `rrb` and `rrbackup` wrappers
- Seven task-oriented areas: `create`, `run`, `view`, `schedule`, `restore`, `repo`, and `config`
- Condensed `view --section` interface
- Unified canonical-TOML/legacy backup inventory
- Canonical backup-set conversion through the shared engine
- Preservation of VSS/fs-snapshot, cache exclusion, one-filesystem, dry-run, tags, and raw Restic options
- Read-only inventory loading without creating generated state/input directories
- Configured-backup `run auto` chooser and direct named execution
- Hard print-only no-materialization/no-execution behavior
- Backup-centric schedule table
- Strict scheduler ownership filtering
- Shared TermDash dependency and Windows curses dependency
- Shared color policy, ANSI-aware tables, compact rows, details, filtering, paging, scrolling, and multi-select adapter
- Combined human-readable repository summary
- Explicit `--refresh-storage` and atomic storage-statistics cache
- Focused tests for parser, packaging, inventory, schedule math, presentation, repository caching, scheduler filtering, and integration behavior
- Updated compile, lint, help, pytest/coverage, and PowerShell validation gates

### Deferred until Checkpoint 2A evidence is reviewed

- Interactive create-wizard acceptance
- Interactive schedule-wizard acceptance
- Configuration and scheduler mutation
- Retention execution
- Cross-platform scheduler CRUD completion
- `backup_module` compatibility-shim conversion and duplicate-engine removal
- Production backup/restore mutation

### Current bugs and uncertainty

- No Checkpoint 2A code has yet run in the local Windows environment.
- The module root `README.md` still documents the historical `rrb` interface and is intentionally deferred until the new UX passes acceptance.
- TUI resizing and curses-failure fallback require manual Windows verification.
- General CLI repository/password overrides are not yet covered by a non-default-repository manual test.

### Progress and loop assessment

Measurable progress occurred. This is not a repeated safety-engine pass: Checkpoint 2A visibly changes the public command surface, human output, schedule filtering, run selection, and repository behavior in response to manual feedback. The checkpoint is now frozen. Continuing feature work before local validation would constitute poor progress control.

## Checkpoint 2A Validation Target

From the repository root:

```powershell
./Invoke-Tests.ps1
```

The target performs:

1. RRBackup metadata cleanup,
2. RRBackup uninstall to remove stale entry points,
3. editable TermDash installation,
4. editable RRBackup `2.0.0` installation,
5. package/test compilation,
6. focused correctness lint,
7. root help validation,
8. condensed view-help validation,
9. full pytest and branch coverage,
10. PowerShell installed-entry-point and environment checks.

Authoritative evidence:

```text
docs/test-results/rrbackup/LATEST.txt
docs/test-results/rrbackup/LATEST_CONTEXT.md
docs/test-results/rrbackup/LATEST_PROGRESS.diff
```

## Last Known Production State

- Repository: `B:\ResticRepos\PC-Local`
- Known snapshots: `a1609113`, `022aad5b`
- Latest snapshot: 2026-04-14
- Current module-owned backup schedule: absent
- Automated production mutation: prohibited
