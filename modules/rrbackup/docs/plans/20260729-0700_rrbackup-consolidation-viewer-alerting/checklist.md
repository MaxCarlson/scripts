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
- [ ] Manually verify final selected-run confirmation and monitored execution

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

### Checkpoint 2A.1b — Interactive Viewer Carousel — Accepted

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
- [x] Pass local automated validation: 297 passed, 7 skipped
- [x] Manually accept demo carousel visuals, page layouts, and compact diagnostics
- [x] Manually accept the real six-page carousel and aggregate Overview
- [x] Manually accept concise run-selector formatting
- [ ] Carry remaining expansion/navigation refinements through Checkpoint 2A.2

### Checkpoint 2A.2 — Expandable Live Viewer and Confirmed In-TUI Run Monitor — Awaiting Local Validation

#### Viewer interaction

- [x] Add inline expand/collapse for the selected row with `e` and `c`
- [x] Add expand-all/collapse-all with `E` and `C`
- [x] Keep expanded detail rows adjacent to their parent during sorting
- [x] Add reliable previous/next alternatives: `p`/`n` and `-`/`+`
- [x] Preserve Tab and `1`–`6` direct page navigation
- [x] Add live State, Progress, Speed, and ETA columns to the Backups page
- [x] Add active progress to Overview Activity details
- [x] Refresh persisted active-run state without repeatedly probing Restic repositories
- [x] Add focused expansion, navigation, and live-progress tests
- [ ] Pass local automated validation
- [ ] Manually accept expansion density, filtering, scrolling, navigation, and resize behavior

#### Run confirmation and monitoring

- [x] Add a final confirmation page before interactive execution
- [x] Keep interactive execution inside the curses monitor
- [x] Parse Restic JSON status rather than printing it raw
- [x] Show aggregate percentage, files, bytes, speed, elapsed time, ETA, and current files
- [x] Persist throttled progress for live display from `backup view`
- [x] Show active-run state from both `backup run auto` and `backup view`
- [x] Add richer live/persisted details to the Backups page
- [x] Show terminal completion state without leaving the monitor
- [ ] Show a successful terminal snapshot ID prominently without leaving the monitor
- [x] Add confirmed graceful Stop
- [x] Preserve Ctrl+C as an emergency graceful-stop path
- [x] Cancel remaining selected backups after confirmed Stop
- [x] Preserve noninteractive, scheduled, JSON/plain/Markdown, and print-command-only behavior
- [x] Add progress parser, streaming executor, stop-control, monitor-model, routing, and persistence tests
- [ ] Pass local automated validation
- [ ] Manually verify confirmation cancellation has no side effects
- [ ] Manually verify live progress and no raw JSON output
- [ ] Manually verify `backup view` refreshes active progress
- [ ] Manually verify graceful Stop and interrupted-history persistence
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
