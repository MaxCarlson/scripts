# Validation Context: rrbackup

Generated: 2026-07-29T11:05:00.5640196-07:00
Branch: agent/merge-restic-backup-modules
Commit: 9743f4247e78a5f6bf93d782b712fca56ed4b16c
Validation report: docs\test-results\rrbackup\LATEST.txt

## Validation Highlights

- RESULT: PASS - Clean stale RRBackup and TermDash editable metadata
- RESULT: PASS - Uninstall prior RRBackup entry points
- RESULT: PASS - Install shared TermDash dependency
- RESULT: PASS - Install RRBackup editable development dependencies
- RESULT: PASS - Compile RRBackup package and tests
- RESULT: PASS - Lint RRBackup checkpoint 2A
- RESULT: PASS - Canonical backup CLI help contract
- RESULT: PASS - Condensed backup view help contract
- [31m================== [31m[1m1 failed[0m, [32m287 passed[0m, [33m7 skipped[0m[31m in 14.33s[0m[31m ==================[0m
- RESULT: FAIL - RRBackup pytest and coverage suite
- RESULT: PASS - PowerShell test: tests\powershell\environment_smoke_test.ps1
- RESULT: PASS - PowerShell test: tests\powershell\production_read_only_test.ps1
- TARGET RESULT: FAIL
- Failure count: 1

## Working Tree

```text
 M docs/test-results/rrbackup/LATEST.txt
 D docs/test-results/rrbackup/LATEST_CONTEXT.md
 D docs/test-results/rrbackup/LATEST_PROGRESS.diff
 D docs/test-results/rrbackup/history/20260729-090444_rrbackup.txt
 D docs/test-results/rrbackup/history/20260729-090444_rrbackup_context.md
 D docs/test-results/rrbackup/history/20260729-090444_rrbackup_progress.diff
?? docs/test-results/rrbackup/history/20260729-105729_rrbackup.txt
?? docs/test-results/rrbackup/history/20260729-105729_rrbackup_context.md
?? docs/test-results/rrbackup/history/20260729-105729_rrbackup_progress.diff
```

## Project Status Sources

### `docs/plans/20260729-0700_rrbackup-consolidation-viewer-alerting/STATUS.md`

# Status

## Overall

Stage 1 is verified. The Windows safety-foundation checkpoint passed package compilation, focused correctness lint, 199 tests, and both PowerShell checks; 8 environment-dependent tests skipped intentionally. The repository-root validation evidence workflow also works as intended.

Stage 2 remains split into bounded checkpoints. The current checkpoint is **2A — Single-CLI UX Foundation**. Its second Windows validation run improved to 287 passing tests, 7 intentional skips, and one remaining test-double failure. That final test-double field omission is patched on the branch; the checkpoint now awaits one corrected local run plus manual UX acceptance.

No Checkpoint 2B wizard/apply work should begin until Checkpoint 2A passes and its manual observations are reviewed.

## Latest Checkpoint 2A Evidence

The pushed Windows run at commit `1b09c80ccffb8d5840ea8861cf7a7ce9a4abd732` recorded:

- dependency cleanup, uninstall, and editable installation: passed,
- package/test compilation: passed,
- focused correctness lint: passed,
- root `backup` help contract: passed,
- condensed `backup view` help contract: passed,
- pytest: 287 passed, 7 skipped, 1 failed,
- PowerShell installed-entry-point/environment smoke test: passed,
- production read-only test: safely skipped,
- package branch coverage: 60%,
- pytest ANSI color sequences: preserved through the root dispatcher and captured in the raw report.

The remaining pytest failure was:

1. `test_run_auto_json_lists_configured_backups_without_execution` used an incomplete fake definition that omitted `source_summary`, `schedule_text`, and `retention_text`, which are consumed by the human-table renderer before JSON emission.

Correction now on the branch:

- the fake definition carries the complete presentation-facing interface used by `render_backup_table`.

The prior explicit-config semantic defect is verified fixed. Running:

```text
backup --config .\does-not-exist.toml config show --json
```

returns `Config file not found` and exit code `2`, with no legacy-default fallback output.

The alternative invocation:

```text
backup config .\does-not-exist.toml config show --json
```

is intentionally invalid because `--config <path>` is a root/global option and must appear before the `config` command area.

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
- Explicit missing-config failure semantics
- Colored pytest output through the root dispatcher

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

- The final test-double correction is patched but not yet locally revalidated.
- TUI navigation, resizing, and curses-failure fallback require manual Windows verification.
- The module root `README.md` still documents the historical `rrb` interface and remains deferred until the new UX passes acceptance.
- General CLI repository/password overrides are not yet covered by a non-default-repository manual test.

### Progress and loop assessment

Measurable progress occurred. Checkpoint 2A advanced from 256 passing tests to 286 and then 287 passing tests. The real missing-config semantic defect is fixed and manually verified; the only remaining failure was a distinct, attributable test-double interface omission. This is not a repeating product failure or stalled loop. The correct next action is one final corrected validation run, not additional feature implementation.

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

### `docs/plans/20260729-0700_rrbackup-consolidation-viewer-alerting/checklist.md`

# Consolidation Checklist

## Stage 1 — Safety Foundation

- [x] Create canonical plan structure
- [x] Document hybrid remote/local workflow
- [x] Add repository-root validation dispatcher and target manifest
- [x] Add authoritative `LATEST.txt`, context snapshot, progress diff, and bounded history
- [x] Add PowerShell environment smoke and opt-in production read-only tests
- [x] Add canonical profile and source attribution
- [x] Add legacy `backup_module` JSON/default adapter
- [x] Add Restic command boundary and secret redaction
- [x] Add print-command-only hard barrier
- [x] Correct dry-run state semantics
- [x] Add CPU normal/overdue policy
- [x] Ensure CPU waiting precedes lock acquisition
- [x] Add atomic run-state store
- [x] Add process-identity lock and ownership token
- [x] Add stale-lock replacement race protection
- [x] Add snapshot and backup-summary parsers
- [x] Add shared backup execution engine
- [x] Add terminal-state handling for all failure paths
- [x] Add unit and lifecycle regression tests
- [x] Add compile and correctness-lint gates
- [x] Pass local Windows validation: 199 passed, 8 skipped
- [x] Validate `LATEST.*` migration and bounded history
- [x] Mark Stage 1 verified

## Stage 2 — Unified CLI, Inventory, and Terminal UX

Stage 2 is split into bounded checkpoints. Do not begin the next checkpoint until the current checkpoint's automated and manual evidence has been reviewed.

### Checkpoint 2A — Single-CLI UX Foundation — Awaiting Local Validation

#### Validation and progress evidence

- [x] Add canonical `backup` entry point
- [x] Fix repository namespace/import behavior for installed entry points
- [x] Run first expanded Windows checkpoint
- [x] Confirm 256 tests pass
- [x] Identify two obsolete integration assertions for historical `rrb` help
- [x] Replace obsolete integration assertions with canonical `backup` checks
- [x] Record manual feedback on view fragmentation, raw JSON, scheduler noise, and slow storage statistics
- [x] Add bounded Checkpoint 2A scope and stop rule to the active plan
- [x] Add compile, focused lint, help, pytest/coverage, and PowerShell gates for Checkpoint 2A
- [ ] Pass corrected Windows validation for Checkpoint 2A
- [ ] Complete Checkpoint 2A manual acceptance

#### Public command surface

- [x] Approve one public executable: `backup`
- [x] Remove `rrb` and `rrbackup` console entry points from package metadata
- [x] Bump package to `2.0.0` for the entry-point-breaking change
- [x] Add uninstall/reinstall validation so retired wrappers are removed
- [x] Keep internal `rrbackup` package naming only where needed for migration
- [x] Expose exactly seven task-oriented root areas:
  - [x] `backup create`
  - [x] `backup run`
  - [x] `backup view`
  - [x] `backup schedule`
  - [x] `backup restore`
  - [x] `backup repo`
  - [x] `backup config`
- [x] Replace public `repository` spelling with `repo`
- [x] Update root and nested help text
- [x] Remove compatibility-command references from public help
- [x] Preserve selected old spellings only as hidden translations

#### Unified backup inventory

- [x] Add schedule model support for minute/hour/day/week/month/year/custom/manual
- [x] Add schedule description, next-run, and missed-run calculations
- [x] Add one inventory model for canonical TOML sets and legacy `local-main`
- [x] Enrich inventory records with sources, tags, repository, schedule, retention, snapshots, runs, health, next run, missed runs, and scheduler state
- [x] Add stable module-owned scheduler task names
- [x] Convert canonical TOML backup sets into shared-engine profiles
- [x] Preserve VSS, cache exclusion, one-filesystem, tags, dry-run default, and raw Restic arguments during conversion
- [x] Keep read-only inventory loading from creating state/log/input directories
- [x] Add canonical and multi-backup inventory tests
- [x] Add schedule-math tests for minute/hour/day/week/month/year
- [x] Add missed-run boundary tests
- [ ] Add explicit timezone/DST transition tests
- [ ] Improve per-backup repository-error isolation if local evidence shows one failing repository hides other records

#### `backup view`

- [x] Replace the long display-specific help tree with one task-oriented dashboard command
- [x] Add six primary dashboard sections:
  - [x] Overview
  - [x] Backups
  - [x] History
  - [x] Repository
  - [x] Schedules
  - [x] Diagnostics
- [x] Keep audit as an explicit structured section
- [x] Add noninteractive section selection with `--section`
- [x] Keep explicit `--plain`, `--json`, and `--markdown` modes
- [x] Hide old display-specific commands from normal help
- [x] Preserve selected old read-only spellings as hidden translation aliases
- [x] Render compact one- or two-line backup rows
- [x] Add expandable/collapsible detail content through TermDash
- [x] Support Up/Down, `j`/`k`, Page Up/Page Down, filtering, Enter/details, and horizontal scrolling through the shared component
- [x] Add presentation and callback tests without launching curses
- [ ] Verify TUI navigation, resizing, and terminal fallback manually on Windows
- [ ] Add snapshot tag/host/path filtering to structured modes
- [ ] Add file browsing inside snapshots
- [ ] Add optional path redaction for audit output

#### `backup run`

- [x] Support `backup run`, `backup run auto`, and `backup run <backup-name>`
- [x] Show configured backup inventory when no name or `auto` is supplied
- [x] Display backup name, source summary, repository, health, latest snapshot, schedule, next run, and missed-run count
- [x] Allow interactive multi-selection for early/manual runs
- [x] Run selected backups without requiring source-file, tag, exclude, or repository knowledge
- [x] Preserve direct named execution for automation
- [x] Preserve preview, dry-run, CPU-policy bypass, extra tags, exclusions, and raw Restic arguments
- [x] Keep print-command-only as a hard no-side-effect barrier
- [x] Add run-selection, direct-run, skipped-exit, and no-materialization preview tests
- [ ] Manually verify chooser cancellation and selected-run confirmation behavior

#### `backup schedule`

- [x] Restrict Windows scheduler discovery to module-owned canonical or legacy invocations
- [x] Exclude unrelated operating-system tasks containing `Backup`
- [x] Make `backup schedule` default to a backup-centric schedule table
- [x] Render one compact line per backup plus one indented schedule/retention line
- [x] Show enabled/manual/missing state, last run, next run, and missed-run count
- [x] Add strict scheduler-ownership regression tests
- [ ] Validate schedule table readability against the real Windows machine

#### `backup repo`

- [x] Combine status, keys, locks, snapshot count, latest snapshot, and cached storage information into one labeled human summary
- [x] Replace default raw JSON with formatted human output
- [x] Keep JSON only behind explicit `--json`
- [x] Never invoke full restore-size statistics implicitly
- [x] Add explicit `backup repo --refresh-storage`
- [x] Add a loading indicator for explicit expensive repository operations when TermDash is available
- [x] Cache full storage statistics with generated time and command metadata
- [x] Add `backup repo check` with readable output
- [x] Format key metadata and lock state as labeled sections
- [x] Add tests proving default repo view never calls slow statistics and cached results are reused
- [ ] Manually verify default repo summary completes quickly against `B:\ResticRepos\PC-Local`
- [ ] Manually verify explicit storage refresh remains opt-in and clearly signposted

#### Shared terminal UI and presentation

- [x] Select and declare `termdash>=0.5.0` as the shared list/detail dependency
- [x] Add Windows curses dependency for the interactive interface
- [x] Add one shared RRBackup palette and status-style policy
- [x] Green = healthy/success/enabled
- [x] Yellow = warning/due/manual/preview
- [x] Red = failure/critical/missed/disabled
- [x] Cyan = headings/identifiers/selected values
- [x] Dim = secondary metadata
- [x] Magenta = active interactive/automatic mode
- [x] Use shared table, detail, footer, keyboard, filter, paging, horizontal-scroll, and multi-select conventions
- [x] Ensure explicit plain, JSON, and Markdown output contains no ANSI escapes
- [x] Add graceful non-TTY plain rendering paths
- [x] Add formatter, details, selection callback, color, and ANSI-stripping tests
- [ ] Manually verify fallback behavior when curses cannot initialize

### Checkpoint 2B — Create and Schedule Wizard Preview — Deferred Until 2A Passes

- [x] Add preview-first wizard data and scheduler-plan scaffolding
- [ ] Validate the creation wizard interactively without applying
- [ ] Validate the schedule editor interactively without applying
- [ ] Validate selecting one or more backups
- [ ] Validate minute/hour/day/week/month/year inputs
- [ ] Validate retention inputs for latest/hourly/daily/weekly/monthly/yearly
- [ ] Validate complete proposed configuration and scheduler previews
- [ ] Ensure no writes occur without a later explicit apply checkpoint

### Checkpoint 2C — Configuration and Scheduler Apply — Deferred

- [ ] Add and validate atomic canonical configuration writes through the wizard
- [ ] Add and validate Windows Task Scheduler create/update/delete/run/export/import
- [ ] Require explicit confirmation or `--apply`
- [ ] Export existing scheduler definitions before replacement
- [ ] Add rollback behavior
- [ ] Add no-overlap, retry, wake, and start-when-available behavior
- [ ] Add scheduler/run/snapshot correlation and schedule history
- [ ] Add systemd user timer CRUD
- [ ] Add cron compatibility CRUD

### Checkpoint 2D — Compatibility Shim and Duplicate-Engine Removal — Deferred

- [ ] Preserve required historical `backup_module` behavior through `backup`
- [ ] Replace `modules/backup_module` internals with a thin compatibility shim
- [ ] Remove duplicate engine only after compatibility tests pass
- [ ] Add optional legacy shell-history evidence adapter
- [ ] Add detailed scheduler event, service, startup, systemd, and cron discovery
- [ ] Add structured restore history and hash verification

### Checkpoint 2E — Production and Controlled Acceptance — Deferred

- [ ] Verify known production snapshots through canonical CLI
- [ ] Run explicit production read-only validation
- [ ] Complete controlled production backup only after explicit approval
- [ ] Complete small restore and hash verification
- [ ] Complete scheduled execution acceptance
- [ ] Complete final viewer, repository-summary, audit, and documentation acceptance

## Stage 3 — Scheduler Management

Scheduler work is folded into Stage 2 checkpoints where it is required for `run`, `schedule`, and `create`. Cross-platform backend completion remains tracked here.

- [ ] Windows Task Scheduler CRUD complete
- [ ] systemd user timer CRUD complete
- [ ] cron compatibility CRUD complete
- [ ] Schedule health and history complete
- [ ] No-overlap, retry, wake, and start-when-available complete
- [ ] Scheduler/run/snapshot correlation complete

## Stage 4 — Viewer Expansion

- [x] Dashboard data foundation
- [x] Timeline data foundation
- [x] Snapshot listing and details foundation
- [x] Search foundation
- [x] Runs and logs foundation
- [x] Schedules and setup/system diagnostics foundation
- [x] Provenance and comprehensive audit foundation
- [x] Storage and health foundation
- [ ] Task-oriented full-screen TUI accepted
- [ ] File browsing inside snapshots
- [ ] Rich backup/profile views
- [ ] Expected-run gap engine
- [ ] Detailed missed-backup timeline
- [ ] JSON Lines and CSV output
- [ ] Alert-state view

## Stage 5 — Alerts

- [ ] Alert persistence and fingerprints
- [ ] Deduplication and acknowledge/resolve/reopen states
- [ ] Stable health exit codes
- [ ] Alert log
- [ ] Generic webhook
- [ ] Windows notification
- [ ] Email/external command
- [ ] Schedule-compatible health check

## Stage 6 — Retention

- [ ] Ownership tags
- [ ] Preview by default
- [ ] Explicit apply confirmation
- [ ] Legacy snapshot adoption
- [ ] Mixed-repository isolation tests

## Stage 7 — Acceptance

- [ ] Temporary repository suite
- [ ] Production read-only suite
- [ ] Controlled production backup
- [ ] Small restore and hash verification
- [ ] Scheduled execution
- [ ] Viewer acceptance
- [ ] Create-wizard acceptance
- [ ] Schedule-wizard acceptance
- [ ] Repository-summary acceptance
- [ ] Audit-command acceptance
- [ ] Alert acceptance
- [ ] Documentation cleanup
- [ ] Compatibility-period documentation

