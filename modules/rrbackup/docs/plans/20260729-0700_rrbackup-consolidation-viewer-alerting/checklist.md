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

### Validation and progress evidence

- [x] Add canonical `backup` entry point
- [x] Fix repository namespace/import behavior for installed entry points
- [x] Pass installed `backup`, `rrb`, and `rrbackup` smoke checks
- [x] Run first expanded Windows checkpoint
- [x] Confirm 256 tests pass
- [x] Identify two obsolete integration assertions for historical `rrb` help
- [x] Record manual feedback on view fragmentation, raw JSON, scheduler noise, and slow storage statistics
- [ ] Pass the corrected Windows validation checkpoint with no stale help assertions

### Public command surface

- [x] Approve one public executable: `backup`
- [ ] Remove `rrb` and `rrbackup` console entry points
- [ ] Keep internal package naming only where needed for migration
- [ ] Expose exactly seven task-oriented root areas:
  - [ ] `backup create`
  - [ ] `backup run`
  - [ ] `backup view`
  - [ ] `backup schedule`
  - [ ] `backup restore`
  - [ ] `backup repo`
  - [ ] `backup config`
- [ ] Replace public `repository` spelling with `repo`
- [ ] Update all root and nested help text
- [ ] Remove compatibility-command references from public help

### Unified backup inventory

- [x] Add schedule model support for minute/hour/day/week/month/year/custom/manual
- [x] Add schedule description, next-run, and missed-run calculations
- [x] Add one inventory model for canonical TOML sets and legacy `local-main`
- [x] Enrich inventory records with sources, tags, repository, schedule, retention, snapshots, runs, health, next run, missed runs, and scheduler state
- [x] Add stable module-owned scheduler task names
- [ ] Add inventory unit tests for canonical and legacy definitions
- [ ] Add schedule-math tests across all supported frequencies
- [ ] Add missed-run boundary and timezone tests
- [ ] Ensure inventory errors are reported per backup without hiding other records

### `backup view`

- [ ] Replace the long display-specific subcommand list with one task-oriented dashboard
- [ ] Add six top-level dashboard sections:
  - [ ] Overview
  - [ ] Backups
  - [ ] History
  - [ ] Repository
  - [ ] Schedules
  - [ ] Diagnostics
- [ ] Add noninteractive section selection with `--section`
- [ ] Keep explicit `--plain`, `--json`, and `--markdown` modes
- [ ] Hide or remove old display-specific commands from normal help
- [ ] Preserve required old operations as internal translation aliases only during migration
- [ ] Render compact one- or two-line backup rows
- [ ] Add expandable/collapsible detail blocks
- [ ] Support Up/Down, `j`/`k`, Page Up/Page Down, filtering, Enter/details, and horizontal scrolling
- [ ] Add snapshot tag/host/path filtering to structured modes
- [ ] Add file browsing inside snapshots
- [ ] Add optional path redaction for audit output
- [ ] Keep audit/export as explicit structured sections rather than default human output

### `backup run`

- [ ] Support `backup run`, `backup run auto`, and `backup run <backup-name>`
- [ ] Show the configured backup inventory when no name or `auto` is supplied
- [ ] Display backup name, source summary, repository, health, latest snapshot, schedule, next run, and missed-run count
- [ ] Allow interactive single or multi-selection for early/manual runs
- [ ] Run selected backups without requiring source-file, tag, exclude, or repository knowledge
- [ ] Preserve direct named execution for automation
- [ ] Preserve preview, dry-run, CPU-policy bypass, extra tags, exclusions, and raw Restic arguments
- [ ] Keep print-command-only as a hard no-side-effect barrier
- [ ] Add run-selection and direct-run tests

### `backup schedule`

- [x] Restrict Windows scheduler discovery to module-owned canonical invocations
- [ ] Ensure unrelated operating-system tasks containing `Backup` are excluded
- [ ] Make `backup schedule` default to a backup-centric schedule table
- [ ] Render one compact line per backup plus one indented schedule/retention line
- [ ] Show enabled state, last run, next run, last result, and missed-run count
- [ ] Add `backup schedule wizard`
- [ ] Add `backup schedule edit <backup-name>`
- [ ] Support selecting one or more backups in the wizard
- [ ] Support minute/hour/day/week/month/year scheduling
- [ ] Support interval, time of day, weekday, day of month, and month of year fields
- [ ] Support retention counts for latest/hourly/daily/weekly/monthly/yearly snapshots
- [ ] Preview scheduler and configuration changes before applying
- [ ] Require explicit confirmation or `--apply`
- [ ] Preserve Windows Task Scheduler create/update/delete/run/export/import
- [ ] Add systemd user timer CRUD
- [ ] Add cron compatibility CRUD
- [ ] Add no-overlap, retry, wake, and start-when-available behavior
- [ ] Add scheduler/run/snapshot correlation and schedule history

### `backup repo`

- [ ] Combine status, keys, locks, snapshot count, latest snapshot, integrity state, and cached storage information into one labeled human summary
- [ ] Replace default raw JSON with formatted human output
- [ ] Keep JSON only behind explicit `--json`
- [ ] Never invoke full restore-size statistics implicitly
- [ ] Add explicit `backup repo --refresh-storage`
- [ ] Show a loading indicator for expensive repository operations
- [ ] Cache full storage statistics with generated time and command metadata
- [ ] Add `backup repo check` with readable progress/result output
- [ ] Format key metadata and lock state as labeled tables
- [ ] Add tests proving default repo view never calls slow statistics

### `backup create`

- [ ] Add a themed creation wizard
- [ ] Walk through backup name
- [ ] Walk through one or more source paths
- [ ] Walk through exclusions
- [ ] Walk through local or remote repository target
- [ ] Walk through credential method and password-file handling
- [ ] Walk through schedule selection
- [ ] Walk through retention selection
- [ ] Show a complete final preview
- [ ] Require explicit save/apply confirmation
- [ ] Create configuration, input files, repository initialization plan, and scheduler plan safely
- [ ] Avoid production mutation in automated tests
- [ ] Add wizard-model tests without launching curses

### Shared terminal UI and presentation

- [x] Select `termdash.interactive_list.InteractiveList` as the shared list/detail component
- [x] Confirm shared component supports arrows, Page Up/Page Down, filtering, horizontal scrolling, multi-select, and detail expansion
- [ ] Add one shared RRBackup palette and status-style policy
- [ ] Green = healthy/success/enabled
- [ ] Yellow = warning/due/manual/preview
- [ ] Red = failure/critical/missed/disabled
- [ ] Cyan = headings/identifiers/selected values
- [ ] Dim = secondary metadata
- [ ] Magenta = active interactive/automatic mode
- [ ] Use the same table, confirmation, footer, and keyboard conventions across view/run/schedule/create
- [ ] Ensure plain text, JSON, Markdown, logs, and redirected output contain no ANSI escapes
- [ ] Add graceful non-TTY fallback to formatted plain text
- [ ] Add TUI formatter, detail block, sorting, filtering, pagination, and callback tests without opening curses

### Compatibility merger

- [ ] Convert canonical TOML backup sets into shared-engine profiles
- [ ] Preserve required historical `backup_module` behavior through `backup`
- [ ] Replace `modules/backup_module` internals with a thin compatibility shim
- [ ] Remove duplicate engine only after compatibility tests pass
- [ ] Add optional legacy shell-history evidence adapter
- [ ] Add detailed scheduler event, service, startup, systemd, and cron discovery
- [ ] Add structured restore history and hash verification
- [ ] Verify known production snapshots through canonical CLI
- [ ] Run explicit production read-only validation

## Stage 3 — Scheduler Management

Scheduler work is being folded into the task-oriented Stage 2 UX where it is required for `run`, `schedule`, and `create`. Cross-platform backend completion remains tracked here.

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
- [ ] Task-oriented full-screen TUI complete
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
