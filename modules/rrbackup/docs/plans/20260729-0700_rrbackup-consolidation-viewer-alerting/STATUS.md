# Status

## Overall

Stage 1 is verified. The Windows safety-foundation checkpoint passed package compilation, focused correctness lint, 199 tests, and both PowerShell checks; 8 environment-dependent tests skipped intentionally. The repository-root validation evidence workflow also works as intended.

Stage 2 remains split into bounded checkpoints. The current checkpoint is **2A — Single-CLI UX Foundation**. Its first Windows validation run completed and narrowed the remaining automated work to two attributable failures. Both failures are patched on the branch; the checkpoint now awaits one corrected local run plus manual UX acceptance.

No Checkpoint 2B wizard/apply work should begin until Checkpoint 2A passes and its manual observations are reviewed.

## Latest Checkpoint 2A Evidence

The pushed Windows run at commit `5e5c37a4cb3ae412f0a8848d6c93a27f06d08e21` recorded:

- dependency cleanup, uninstall, and editable installation: passed,
- package/test compilation: passed,
- focused correctness lint: passed,
- root `backup` help contract: passed,
- condensed `backup view` help contract: passed,
- pytest: 286 passed, 7 skipped, 2 failed,
- PowerShell installed-entry-point/environment smoke test: passed,
- production read-only test: safely skipped,
- package branch coverage: 60%.

The two pytest failures were:

1. `test_run_auto_json_lists_configured_backups_without_execution` used an incomplete fake profile that omitted the repository field required by the human-table renderer.
2. `test_missing_config_error_message` exposed a real semantic defect: an explicitly supplied missing `--config` path silently fell back to legacy defaults instead of returning an error.

Corrections now on the branch:

- the test fixture carries the complete profile fields used by presentation code,
- explicit missing config paths fail before command dispatch except for creation and migration flows where a new target is valid,
- pytest is invoked with forced color so the live root-dispatcher console retains its normal colored status output.

## Checkpoint Guardrail

Each checkpoint contains one closely related feature/correction group and should result in approximately 10–20 minutes between local pull/test/push cycles.

For every checkpoint:

1. source, tests, planning state, and static review are completed together,
2. implementation stops for local validation,
3. automated and manual results are reviewed before the next checkpoint,
4. failures remain attributable to the newest bounded change set.

Create/schedule wizard acceptance, scheduler/configuration apply, compatibility-shim removal, and production-write work are not part of Checkpoint 2A.

## Progress Assessment

### Successfully implemented and previously verified

- Shared safety engine and terminal-state handling
- Production repository and snapshot read-only access
- Snapshot timeline and health data
- Provenance and comprehensive audit collection
- Configuration/source attribution
- Root validation dispatcher and authoritative evidence handoff
- Single installed `backup` entry point
- Condensed task-oriented command/help hierarchy

### Implemented in Checkpoint 2A and substantially validated

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

### Deferred until Checkpoint 2A evidence is fully accepted

- Interactive create-wizard acceptance
- Interactive schedule-wizard acceptance
- Configuration and scheduler mutation
- Retention execution
- Cross-platform scheduler CRUD completion
- `backup_module` compatibility-shim conversion and duplicate-engine removal
- Production backup/restore mutation

### Current bugs and uncertainty

- The two automated failures from the first 2A run are patched but not yet locally revalidated.
- Live pytest color through the root dispatcher is configured but still needs visual confirmation.
- TUI navigation, resizing, and curses-failure fallback require manual Windows verification.
- The module root `README.md` still documents the historical `rrb` interface and remains deferred until the new UX passes acceptance.
- General CLI repository/password overrides are not yet covered by a non-default-repository manual test.

### Progress and loop assessment

Measurable progress occurred. The checkpoint advanced from 256 passing tests in the prior slice to 286 passing tests while replacing the public command surface and adding the new inventory/presentation layer. The two failures were distinct and attributable; this is not a repeating or stalled failure pattern. The correct next action is a small corrected validation run, not additional feature implementation.

## Checkpoint 2A Validation Target

From the repository root:

```powershell
./Invoke-Tests.ps1
```

The target performs:

1. RRBackup and TermDash metadata cleanup,
2. RRBackup uninstall to remove stale entry points,
3. editable TermDash installation,
4. editable RRBackup `2.0.0` installation,
5. package/test compilation,
6. focused correctness lint,
7. root help validation,
8. condensed view-help validation,
9. full pytest and branch coverage with colored live output,
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
