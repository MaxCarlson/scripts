# Validation Context: rrbackup

Generated: 2026-07-29T11:41:38.5204731-07:00
Branch: agent/merge-restic-backup-modules
Commit: 7639d2a5ea82c2e81acc5039ee32f930b13e354b
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
- [32m======================= [32m[1m289 passed[0m, [33m7 skipped[0m[32m in 14.46s[0m[32m =======================[0m
- RESULT: PASS - RRBackup pytest and coverage suite
- RESULT: PASS - PowerShell test: tests\powershell\environment_smoke_test.ps1
- RESULT: PASS - PowerShell test: tests\powershell\production_read_only_test.ps1
- TARGET RESULT: PASS

## Working Tree

```text
 M docs/test-results/rrbackup/LATEST.txt
 D docs/test-results/rrbackup/LATEST_CONTEXT.md
 D docs/test-results/rrbackup/LATEST_PROGRESS.diff
```

## Project Status Sources

### `docs/plans/20260729-0700_rrbackup-consolidation-viewer-alerting/STATUS.md`

# Status

## Overall

Stage 1 is verified. The Windows safety-foundation checkpoint passed package compilation, focused correctness lint, 199 tests, and both PowerShell checks; 8 environment-dependent tests skipped intentionally. The repository-root validation evidence workflow also works as intended.

Checkpoint **2A — Single-CLI UX Foundation** is now automated-test complete. The latest Windows run passed compilation, focused lint, root and view help contracts, 288 tests, and both PowerShell checks; 7 environment-dependent tests skipped intentionally. Package branch coverage remains 60%.

Manual acceptance found clear viewer and run-monitoring gaps. Work is now split into bounded checkpoints documented in:

```text
03_viewer-carousel-and-run-monitor__in-progress.md
```

The current patch is **2A.1a — Completed Versus Attempted Run Visibility**. Do not begin the viewer carousel, live monitor, or pause/resume implementation until this patch passes local validation.

## Latest Automated Evidence

The pushed Windows run at commit `3fdf0958692e2fb5b0209cfe6e44615d8a0d6b47` recorded:

- dependency cleanup, uninstall, and editable installation: passed,
- package/test compilation: passed,
- focused correctness lint: passed,
- root `backup` help contract: passed,
- condensed `backup view` help contract: passed,
- pytest: 288 passed, 7 skipped, 0 failed,
- PowerShell installed-entry-point/environment smoke test: passed,
- production read-only test: safely skipped,
- package branch coverage: 60%,
- pytest ANSI color sequences: preserved through the root dispatcher.

## Manual Checkpoint 2A Findings

### Viewer

- The interactive backup inventory opens and details/navigation work.
- A single real backup makes the screen visually sparse; varied synthetic records are needed for visual acceptance.
- Overview and Backups are interactive, but History, Repository, Schedules, Diagnostics, and Audit are disconnected static outputs.
- A multi-page viewer carousel is preferred, with a visible label such as `View: OVERVIEW — pg. 1/6` and page-switch hotkeys.
- Diagnostics and Audit default human output is oversized Markdown/JSON and should be replaced by compact human summaries; full data remains available through explicit structured/export modes.
- Future root-area switching inside one global TUI is recorded but deferred until per-command carousels are accepted.

### Run selector and execution

- `backup run auto` opens the expected selector.
- Pressing `R` currently exits the selector and immediately starts the backup without final confirmation.
- Restic JSON progress messages are printed raw to the terminal.
- Real backup execution should remain inside a themed progress monitor.
- The monitor should show aggregate progress, elapsed time, estimated remaining time, file/byte counts, current files, and active state.
- Active-run information must also be visible from `backup view` and both details pages.
- Stop must become an explicit confirmed UI action.
- Pause/resume and delayed resume are requested, but are a separate safety-sensitive checkpoint because Restic has no native portable pause command.
- Exact per-drive progress cannot be claimed from Restic's aggregate JSON without additional verified instrumentation.

### Interrupted-run visibility

- `Ctrl+C` successfully interrupted the manually started backup.
- The existing inventory continued to show only the 3-month-old successful snapshot.
- The UI must distinguish:
  - Last complete backup
  - Last attempted run
  - Attempt state
- The details page must show run ID, timestamps, exit code, reason, and snapshot ID when available.

## Current Patch — Checkpoint 2A.1a

Implemented on the branch:

- `backup view` and `backup run auto` now show Last complete, Last attempt, and Attempt state.
- Last complete uses successful snapshot evidence, preserving pre-merge history.
- Last attempt uses the latest structured run regardless of terminal state.
- Interrupted, failed, skipped, dry-run, running, waiting, queued, and successful states use the shared status-color policy.
- Backup details now include run ID, start/finish time, exit code, reason, and snapshot ID when available.
- History now labels completed snapshots separately from attempted runs.
- Focused presentation regression tests cover interrupted-run visibility.

Not implemented in this patch:

- viewer carousel,
- compact diagnostics,
- synthetic/demo mode,
- confirmation before execution,
- live progress monitor,
- clean Stop button,
- pause/resume or scheduled resume.

## Progress Assessment

### Accomplished

- Shared safety engine and terminal-state handling
- Production repository and snapshot read-only access
- Snapshot timeline and health data
- Provenance and comprehensive audit collection
- Configuration/source attribution
- Root validation dispatcher and authoritative evidence handoff
- Single installed `backup` entry point
- Seven task-oriented command areas
- Condensed view-help contract
- Unified canonical/legacy backup inventory
- Configured-backup run chooser
- Strict scheduler ownership filtering
- Backup-centric schedule table
- Combined repository summary
- Explicit cached storage refresh
- Shared TermDash presentation dependency
- Colored pytest output through the root dispatcher
- Explicit missing-config failure semantics
- Clean Checkpoint 2A automated validation: 288 passed, 7 skipped

### Current bugs and uncertainty

- Checkpoint 2A.1a has not yet been locally validated.
- The active backup selector still starts immediately after `R` in the currently installed build.
- The current installed build still prints raw Restic JSON during execution.
- Viewer carousel and compact diagnostics are not implemented yet.
- Live progress monitoring and active-run refresh are not implemented yet.
- Pause/resume feasibility and repository-lock safety require a dedicated design and controlled acceptance.
- The module root `README.md` still documents the historical `rrb` interface and remains deferred until the new UX passes acceptance.

### Stall/loop assessment

Measurable progress occurred. Checkpoint 2A moved from 256 to 286, 287, and finally 288 passing tests while replacing the public command surface and validating the new inventory and presentation foundation. Manual testing then exposed distinct UX limitations that automated tests could not judge. The project is not repeating the same implementation failure; it is proceeding through bounded, user-driven UX corrections.

## Next Validation

From the repository root:

```powershell
./Invoke-Tests.ps1
```

After automated validation, manually verify the interrupted-run display in both:

```text
backup view
backup run auto
```

Expected:

- Last complete still shows the April snapshot,
- Last attempt shows the recent interrupted attempt,
- Attempt state shows `INTERRUPTED`,
- Enter/details shows the interruption reason and run metadata.

## Last Known Production State

- Repository: `B:\ResticRepos\PC-Local`
- Known completed snapshots: `a1609113`, `022aad5b`
- Latest completed snapshot: 2026-04-14
- Latest attempted run: interrupted during manual Checkpoint 2A acceptance on 2026-07-29
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

