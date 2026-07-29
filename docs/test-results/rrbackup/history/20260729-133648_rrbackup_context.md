# Validation Context: rrbackup

Generated: 2026-07-29T13:37:15.1104059-07:00
Branch: agent/merge-restic-backup-modules
Commit: a8b2b5fb14f5b015315ae6d03b953921138ae976
Validation report: docs\test-results\rrbackup\LATEST.txt

## Validation Highlights

- RESULT: PASS - Clean stale RRBackup and TermDash editable metadata
- RESULT: PASS - Uninstall prior RRBackup entry points
- RESULT: PASS - Install shared TermDash dependency
- RESULT: PASS - Install RRBackup editable development dependencies
- RESULT: PASS - Compile RRBackup package and tests
- RESULT: PASS - Lint RRBackup checkpoint 2A.1b
- RESULT: PASS - Canonical backup CLI help contract
- RESULT: PASS - Condensed backup view help contract
- [32m======================= [32m[1m297 passed[0m, [33m7 skipped[0m[32m in 15.20s[0m[32m =======================[0m
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

Checkpoint **2A — Single-CLI UX Foundation** and Checkpoint **2A.1a — Completed Versus Attempted Run Visibility** are accepted.

Checkpoint **2A.1b — Interactive Viewer Carousel** passed automated Windows validation with 295 tests passing and 7 intentional skips. Manual testing confirmed the interactive History page, concise run-selector rows, and compact default Audit summary. Manual testing also showed that the original Overview page duplicated the old per-backup list closely enough that bare `backup view` appeared unchanged.

The current validation-ready correction keeps the six-page carousel but replaces page 1 with a true aggregate dashboard. Do not begin the live run monitor, Stop action, or pause/resume work until this correction passes automated and manual review.

Detailed scope is tracked in:

```text
03_viewer-carousel-and-run-monitor__in-progress.md
```

## Latest Automated Evidence

The pushed Windows run at commit `e9b4aea5c3b51be3a9adaf94394ce0cb33c1d172` recorded:

- dependency cleanup, uninstall, and editable installation: passed,
- package/test compilation: passed,
- focused correctness lint: passed,
- root `backup` help contract: passed,
- condensed `backup view` help contract: passed,
- pytest: 295 passed, 7 skipped, 0 failed,
- PowerShell installed-entry-point/environment smoke test: passed,
- production read-only test: safely skipped,
- package branch coverage: 61%,
- pytest ANSI color sequences: preserved through the root dispatcher.

## Accepted Manual Findings

### Completed versus attempted runs

- `backup view` shows:
  - Last complete: April snapshot
  - Last attempt: recent interrupted run
  - Attempt state: `INTERRUPTED`
- `backup view --section history` showed both:
  - attempted interrupted run
  - completed snapshot `022aad5b`
- `backup run auto` displayed the same separation.
- The plain post-selector table was readable and correctly separated completion from attempt state.

### Viewer carousel

- `backup view --section history` entered the interactive carousel on `View: HISTORY — pg. 3/6`.
- The History page displayed the interrupted attempt and completed snapshot correctly.
- `backup view --section audit` produced a concise human summary instead of raw Markdown/JSON.
- `backup view --section audit --json` intentionally produced the complete, large machine-readable audit.
- `backup run auto` used the cleaner unlabeled row layout.
- Bare `backup view` appeared unchanged because the original Overview page was another per-backup inventory table rather than an aggregate dashboard.

### Run selector and execution

- `backup run auto` opens the expected selector.
- Pressing `R` still immediately starts a real backup in the current build.
- Restic JSON progress messages are printed raw.
- The future monitor must show aggregate progress, elapsed time, ETA, file/byte counts, current files, active state, and a confirmed Stop action.
- Active-run information must also be visible from `backup view` and both details pages.
- Pause/resume and delayed resume remain a separate safety-sensitive checkpoint.
- Exact per-drive progress cannot be claimed from Restic's aggregate JSON without additional verified instrumentation.

## Current Correction — Checkpoint 2A.1b

Implemented on the branch:

- Bare `backup view` remains page 1 of the six-page carousel.
- Page 1 is now an aggregate dashboard rather than a duplicate backup list.
- The aggregate Overview contains expandable rows for:
  - backup health,
  - current/recent activity,
  - completion coverage,
  - schedule state and missed runs,
  - repository grouping.
- Page 2 remains the detailed per-backup inventory.
- Plain Overview output uses the same aggregate semantics.
- Runtime regression coverage proves that bare `backup view` routes into the carousel with `start_page="overview"`.
- Focused tests distinguish the aggregate Overview from the detailed Backups page.
- The new controller is included in compile, Ruff, and pytest validation.

Already implemented and awaiting complete manual acceptance:

- pages:
  1. Overview
  2. Backups
  3. History
  4. Repository
  5. Schedules
  6. Diagnostics
- persistent page labels such as `View: OVERVIEW — pg. 1/6`,
- `[`/`]`, Tab, and `1`–`6` page controls,
- lazy Repository and Diagnostics loading,
- safe `backup view --demo` fixtures,
- compact Diagnostics and default Audit summaries,
- concise run-selector formatting.

Not implemented in this checkpoint:

- confirmation before pressing `R`,
- live progress monitor,
- active-run refresh,
- explicit Stop action,
- pause/resume,
- scheduled resume,
- global switching between root command areas.

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
- Unified canonical/legacy inventory
- Strict scheduler ownership filtering
- Backup-centric schedule table
- Combined repository summary and explicit cached storage refresh
- Shared TermDash presentation dependency
- Colored pytest output through the root dispatcher
- Explicit missing-config failure semantics
- Clean Checkpoint 2A validation: 288 passed, 7 skipped
- Clean Checkpoint 2A.1a validation: 289 passed, 7 skipped
- Clean initial Checkpoint 2A.1b validation: 295 passed, 7 skipped
- Manual acceptance of completed-versus-attempted run visibility
- Manual acceptance of History carousel entry, compact Audit summary, and concise run-selector rows

### Current bugs and uncertainty

- The aggregate Overview correction has not yet been locally compiled, linted, or tested.
- `backup view --demo` visual density and all page-switch keys still need manual Windows verification.
- Repository, Schedules, Diagnostics, terminal resize, filter persistence expectations, and detail usefulness need manual review.
- Lazy repository collection may pause briefly when the Repository page is first opened; it remains read-only.
- `R` in `backup run auto` still begins execution immediately. Do not press it during this checkpoint.
- The installed build still prints raw Restic JSON during execution until Checkpoint 2A.2.
- Pause/resume feasibility and repository-lock safety require a dedicated design and controlled acceptance.
- The module root `README.md` still documents the historical `rrb` interface and remains deferred until the new UX passes acceptance.

### Stall/loop assessment

Measurable progress continues. Automated 2A.1b validation passed, and manual review identified a presentation-model issue rather than a broken carousel. The correction separates aggregate Overview information from detailed Backups information and adds direct runtime coverage. The project is not looping or stuck.

## Next Validation

From the repository root:

```powershell
./Invoke-Tests.ps1
```

After automated validation, manually exercise:

```text
backup view
backup view --demo
backup view --section backups
backup view --section repository
backup view --section schedules
backup view --section diagnostics
backup run auto
```

Do not press `R` in the run selector during this checkpoint.

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

### Checkpoint 2A — Single-CLI UX Foundation — Accepted

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
- [x] Pass corrected Windows validation: 288 passed, 7 skipped
- [x] Complete the bounded 2A manual review and record follow-up UX checkpoints

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
- [ ] Add and manually verify final selected-run confirmation

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

### Checkpoint 2A.1a — Completed Versus Attempted Run Visibility — Accepted

- [x] Show Last complete independently from Last attempt
- [x] Show attempt state for queued/waiting/running/success/failure/interrupted/skipped/dry-run
- [x] Preserve snapshots as completed-backup evidence for pre-merge history
- [x] Add run ID, timestamps, exit code, reason, and snapshot ID to details
- [x] Distinguish attempted runs from completed snapshots in History
- [x] Pass local validation: 289 passed, 7 skipped
- [x] Manually verify the July interrupted attempt and April completed snapshot appear separately

### Checkpoint 2A.1b — Interactive Viewer Carousel — Awaiting Local Validation

- [x] Add six-page interactive viewer controller
- [x] Add persistent `View: <PAGE> — pg. n/6` header
- [x] Add `[`/`]`, Tab, and `1`–`6` page switching
- [x] Preserve navigation, filtering, details, paging, horizontal scrolling, and resize behavior
- [x] Make `--section` select the starting interactive page
- [x] Keep explicit plain, JSON, and Markdown noninteractive modes
- [x] Load repository and diagnostics pages lazily
- [x] Replace default diagnostics JSON/Markdown dump with compact human rows and details
- [x] Replace default audit dump with a compact human index
- [x] Add `backup view --demo` safe synthetic visual fixtures
- [x] Include healthy, warning, failed, interrupted, running, disabled-schedule, multi-repository, and multi-source demo states
- [x] Ensure demo mode does not load real configuration, inspect host state, invoke Restic, or write files
- [x] Remove redundant inline `complete`, `attempt`, `next`, and `missed` row labels
- [x] Route `backup run auto` through the concise selector
- [x] Add non-curses tests for page builders, switching, lazy loading, demo diversity, diagnostics, audit summary, and selector formatting
- [x] Add new viewer/runtime modules and tests to root compilation/lint/pytest validation
- [ ] Pass local automated validation
- [ ] Manually accept demo carousel visuals, hotkeys, details, filters, and resizing
- [ ] Manually accept real carousel and compact diagnostics
- [ ] Manually accept concise run-selector formatting without pressing `R`

### Checkpoint 2A.2 — Confirmed In-TUI Run Monitor — Deferred

- [ ] Add a final confirmation page before real execution
- [ ] Keep execution inside the themed TUI
- [ ] Parse Restic JSON status rather than printing it raw
- [ ] Show aggregate percentage, files, bytes, elapsed time, ETA, and current files
- [ ] Show active-run state from both `backup run auto` and `backup view`
- [ ] Add richer live/persisted details pages
- [ ] Show completion state and snapshot ID without leaving the TUI
- [ ] Add confirmed graceful Stop
- [ ] Preserve Ctrl+C as an emergency graceful-stop path
- [ ] Investigate trustworthy per-source/per-drive instrumentation without changing snapshot semantics

### Checkpoint 2A.3 — Pause, Resume, and Scheduled Resume — Deferred

- [ ] Design a safe Windows process-suspension boundary
- [ ] Preserve process identity and repository lock ownership
- [ ] Persist and display paused state
- [ ] Add manual resume
- [ ] Add pause-now/resume-after-duration
- [ ] Define UI-exit and reboot behavior for scheduled resume
- [ ] Add crash/stale-process recovery
- [ ] Add stop-while-paused handling
- [ ] Add injected-clock and Windows controlled-acceptance tests

### Checkpoint 2B — Create and Schedule Wizard Preview — Deferred Until Viewer/Monitor Work Passes

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

