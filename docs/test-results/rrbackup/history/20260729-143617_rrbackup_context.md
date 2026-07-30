# Validation Context: rrbackup

Generated: 2026-07-29T14:36:45.3959935-07:00
Branch: agent/merge-restic-backup-modules
Commit: 16f96f8a2b1d72cddc7175ed657ec39aa1d2ed64
Validation report: docs\test-results\rrbackup\LATEST.txt

## Validation Highlights

- RESULT: PASS - Clean stale RRBackup and TermDash editable metadata
- RESULT: PASS - Uninstall prior RRBackup entry points
- RESULT: PASS - Install shared TermDash dependency
- RESULT: PASS - Install RRBackup editable development dependencies
- RESULT: PASS - Compile RRBackup package and tests
- RESULT: PASS - Lint RRBackup checkpoint 2A.2b
- RESULT: PASS - Canonical backup CLI help contract
- RESULT: PASS - Condensed backup view help contract
- [32m======================= [32m[1m314 passed[0m, [33m7 skipped[0m[32m in 15.34s[0m[32m =======================[0m
- RESULT: PASS - RRBackup pytest and coverage suite
- RESULT: PASS - PowerShell test: tests\powershell\environment_smoke_test.ps1
- RESULT: PASS - PowerShell test: tests\powershell\production_read_only_test.ps1
- TARGET RESULT: PASS

## Working Tree

```text
 M docs/test-results/rrbackup/LATEST.txt
 D docs/test-results/rrbackup/LATEST_CONTEXT.md
 D docs/test-results/rrbackup/LATEST_PROGRESS.diff
 D docs/test-results/rrbackup/history/20260729-110436_rrbackup.txt
 D docs/test-results/rrbackup/history/20260729-110436_rrbackup_context.md
 D docs/test-results/rrbackup/history/20260729-110436_rrbackup_progress.diff
?? docs/test-results/rrbackup/history/20260729-140638_rrbackup.txt
?? docs/test-results/rrbackup/history/20260729-140638_rrbackup_context.md
?? docs/test-results/rrbackup/history/20260729-140638_rrbackup_progress.diff
```

## Project Status Sources

### `docs/plans/20260729-0700_rrbackup-consolidation-viewer-alerting/STATUS.md`

# Status

## Overall

Stage 1 is verified. Checkpoint **2A — Single-CLI UX Foundation**, Checkpoint **2A.1a — Completed Versus Attempted Run Visibility**, and Checkpoint **2A.1b — Interactive Viewer Carousel** are accepted.

Checkpoint **2A.2a — Expandable Live Viewer and Confirmed Aggregate Monitor** passed automated Windows validation and manual review. The execution plumbing is accepted: Restic JSON is parsed rather than printed, aggregate progress is persisted, `backup view` can observe active progress, and graceful Stop is available.

The current validation-ready patch is **2A.2b — Persistent Backup Operations Dashboard**. It corrects the interaction model discovered during manual testing: starting a backup must not replace the inventory with an exclusive monitor. Confirmation, execution, progress, selection, and Stop now remain on one dashboard. A focused single-backup view is available only when explicitly requested. Pause/resume and delayed resume remain deferred to Checkpoint 2A.3.

Detailed scope is tracked in:

```text
03_viewer-carousel-and-run-monitor__in-progress.md
```

## Latest Accepted Automated Evidence

The pushed Windows run at commit `2b52dfd4f6bc8d04f37c012fff299da3d123c16a` recorded:

- dependency cleanup, uninstall, and editable installation: passed,
- package/test compilation: passed,
- focused correctness lint for Checkpoint 2A.2: passed,
- root `backup` help contract: passed,
- condensed `backup view` help contract: passed,
- pytest: 310 passed, 7 skipped, 0 failed,
- PowerShell installed-entry-point/environment smoke test: passed,
- production read-only test: safely skipped,
- pytest ANSI color sequences: preserved through the root dispatcher.

The progress artifact showed an increase from 297 to 310 passing tests. This is measurable forward progress, not a repeated failure cycle.

## Accepted Manual Findings

### Viewer carousel and expansion

Manual Windows review confirmed:

- bare `backup view` opens `View: OVERVIEW — pg. 1/6`,
- Overview is an aggregate dashboard,
- page 2 shows configured backups,
- page 3 shows History,
- page 4 shows Repository,
- page 5 shows Schedules,
- page 6 shows compact Diagnostics,
- `backup view --demo` supplies six varied synthetic backups,
- `backup view --plain` uses aggregate Overview semantics,
- default Audit output is concise,
- explicit Audit `--json` remains the complete machine-readable export,
- `e`/`c` and `E`/`C` expose useful inline information,
- the alternate `p`/`n` and `-`/`+` page controls are available,
- active source and run information can be displayed without raw Restic output.

### Confirmed aggregate monitor

Manual controlled execution confirmed:

- pressing `R` no longer starts immediately,
- a confirmation surface appears before execution,
- Restic JSON lines are no longer printed to the terminal,
- the monitor displays aggregate percentage, files, bytes, speed, elapsed time, ETA, and current files,
- the run transitions from WAITING to RUNNING,
- progress values update correctly once Restic begins processing.

### Interaction mismatch found after 2A.2a

Manual review also established that the modal monitor is not the desired default UX:

- the confirmation surface did not show enough information about every selected backup,
- the exclusive monitor hid idle and other configured backups,
- the user could not select and start another eligible backup while one was running,
- source/drive activity needed to appear directly below each active backup,
- the exclusive single-backup presentation should be entered only by explicitly focusing one backup,
- operational state needed visible color coding.

The desired default is one persistent operations page containing all configured backups, active progress, inline source-drive activity, confirmation, Start, and Stop.

## Current Patch — Checkpoint 2A.2b

Implemented on the branch:

### Persistent operations dashboard

- `backup run auto` now opens one persistent `RRBackup — Backup Operations` dashboard.
- The dashboard remains open while backups are idle, waiting, running, stopping, or terminal.
- Starting a backup does not replace the inventory with another UI.
- A user may select another eligible backup and press `R` while a locally managed backup is running.
- Multiple approved backups may be launched from the same dashboard; existing process-lock and engine safety semantics remain authoritative.
- Interactive named runs use the same dashboard with only the named backup visible.
- Noninteractive JSON/plain/Markdown, scheduled named runs, and `--print-command-only` retain their prior behavior.

### Inline confirmation

- `R` opens a confirmation region inside the current dashboard.
- No backup starts until `Y` is pressed.
- `N` or Esc cancels without materializing inputs or starting Restic.
- Confirmation includes every selected backup and shows:
  - health,
  - current state,
  - repository,
  - schedule,
  - retention,
  - last completed backup,
  - last attempted run,
  - exclusion count,
  - tags,
  - every configured source path.
- Page Up/Page Down scroll long confirmation content while the inventory remains present.

### Inline execution and management

- Parent rows show:
  - selection,
  - backup name,
  - health,
  - state,
  - aggregate percentage,
  - aggregate speed,
  - aggregate ETA,
  - last complete,
  - last attempt,
  - source summary.
- Running jobs automatically add one activity line per configured drive/source group.
- Source lines show `ACTIVE`, `SEEN`, or `PENDING`.
- Source lines explicitly state that Restic totals are aggregate; no per-drive percentage is fabricated.
- `Space` selects or deselects backups.
- `R` reviews and starts selected or current eligible backups.
- `S` opens a Stop confirmation for selected locally managed active backups.
- Ctrl+C requests graceful Stop for all locally managed active backups.
- `e`/`c` expand or collapse the current backup.
- `E`/`C` expand or collapse all visible backups.
- Enter, `i`, or `m` explicitly enters or exits a focused single-backup presentation.
- `f` filters the dashboard without leaving it.
- Normal quit is blocked while a locally managed backup remains active.

### Color and state hierarchy

- Running rows: magenta.
- Waiting/queued rows: yellow.
- Successful rows: green.
- Failure, interruption, stopping, and critical idle rows: red.
- Informational and dry-run states: cyan.
- Secondary source and detail lines: dim unless active or completed.

### Concurrency and safety boundary

- Each approved backup receives its own worker and `ResticExecutionControl`.
- Progress persistence continues through the existing shared engine and state store.
- Existing process locks decide whether two backup definitions may execute simultaneously.
- A persisted run created by another process remains visible but cannot be stopped by this dashboard unless this dashboard owns its control object.
- Automated tests do not start a production backup.
- No scheduler, retention, configuration-write, restore, pause/resume, or production-mutation work is mixed into this checkpoint.

### Focused tests added or updated

- Confirmation contains complete information for every selected backup.
- Confirmation does not execute before approval.
- Active operation rows include drive activity and explicitly aggregate-only totals.
- Two selected backups can start from one persistent model.
- Stop confirmation targets a locally managed active job.
- Interactive run routing uses the persistent operations dashboard rather than the modal monitor.
- Existing throttled progress-persistence coverage remains.
- Root compile, lint, pytest, help, packaging, and PowerShell gates include the new module and tests.

## Current Bugs and Uncertainty

- Checkpoint 2A.2b has not yet been locally compiled, linted, or tested.
- Windows curses redraw, resizing, filtering, selection, confirmation scrolling, and color rendering require manual review.
- Starting multiple backups concurrently is subject to their configured process-lock files and repository behavior; a conflicting backup may be safely skipped by the engine.
- ETA remains based on aggregate average processed bytes and may fluctuate while Restic discovers additional files and bytes.
- Drive/source rows indicate activity and discovery state only. Restic does not provide trustworthy independent drive totals, so per-drive percentages and ETAs are intentionally absent.
- Stop during a CPU-policy wait records the request in the dashboard, but the worker cannot fully exit until the CPU waiter returns or Restic starts and honors the pre-requested stop.
- External runs are observable through persisted state but are not controllable by a dashboard that did not start them.
- Pause/resume requires a separate Windows process-suspension design that preserves process identity and repository-lock ownership.
- The historical modal monitor remains in the package for compatibility and tests but is no longer the default interactive run surface.
- The module root `README.md` still documents the historical `rrb` interface and remains deferred until the new UX passes acceptance.

## Progress Assessment

### Accomplished

- Stage 1 safety foundation
- Canonical `backup` executable and seven task-oriented command areas
- Unified canonical/legacy inventory
- Completed-versus-attempted run visibility
- Six-page viewer carousel
- Aggregate Overview and compact Diagnostics/Audit
- Safe synthetic visual fixtures
- Inline expansion and reliable page navigation
- Structured Restic progress parsing and persistence
- Confirmed execution and graceful Stop plumbing
- Clean validation milestones:
  - 288 passed, 7 skipped
  - 289 passed, 7 skipped
  - 295 passed, 7 skipped
  - 297 passed, 7 skipped
  - 310 passed, 7 skipped
- Manual verification that the monitor reports real aggregate progress without raw JSON

### Stall/loop assessment

The project is not stuck. Checkpoint 2A.2a validated the execution and progress plumbing; manual testing then exposed a distinct information-architecture problem. Checkpoint 2A.2b reuses the verified engine, parser, persistence, and Stop control while replacing only the default interactive orchestration surface.

## Next Validation

From the repository root:

```powershell
./Invoke-Tests.ps1
```

After automated validation, manually exercise:

```text
backup run auto
```

Required manual acceptance:

1. Confirm the dashboard initially shows all configured backups.
2. Select `local-main`, press `R`, and review the inline confirmation.
3. Cancel with `N` and verify no attempt is created.
4. Repeat, approve with `Y`, and confirm the dashboard remains visible.
5. Verify WAITING and RUNNING colors and aggregate progress.
6. Verify one automatic source-drive line per configured drive group.
7. Verify `e` expansion and Enter/`m` focused mode.
8. While running, select another eligible synthetic or configured backup if available and verify `R` remains usable.
9. Press `S`, confirm Stop, and verify the row reaches INTERRUPTED without raw JSON.
10. Verify `backup view` and History reflect the interrupted attempt.

Do not test pause/resume yet; it is not implemented in this checkpoint.

## Last Known Production State

- Repository: `B:\ResticRepos\PC-Local`
- Known completed snapshots: `a1609113`, `022aad5b`
- Latest completed snapshot: 2026-04-14
- A controlled manual backup attempt was started during 2026-07-29 monitor acceptance; its final terminal state must be confirmed from the next pushed evidence and History view.
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
- [ ] Manually accept the persistent operations dashboard and controlled execution

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
- [x] Carry expansion/navigation refinements into Checkpoint 2A.2a

### Checkpoint 2A.2a — Expandable Live Viewer and Confirmed Aggregate Monitor — Accepted

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
- [x] Pass local automated validation: 310 passed, 7 skipped
- [x] Manually accept expansion density and demo-mode detail presentation

#### Confirmed aggregate monitor plumbing

- [x] Add final confirmation before interactive execution
- [x] Parse Restic JSON status rather than printing it raw
- [x] Show aggregate percentage, files, bytes, speed, elapsed time, ETA, and current files
- [x] Persist throttled progress for live display from `backup view`
- [x] Show active-run state from both `backup run auto` and `backup view`
- [x] Add richer live/persisted details to the Backups page
- [x] Show terminal completion state without raw terminal output
- [x] Add confirmed graceful Stop
- [x] Preserve Ctrl+C as an emergency graceful-stop path
- [x] Cancel remaining selected backups after confirmed Stop
- [x] Preserve noninteractive, scheduled, JSON/plain/Markdown, and print-command-only behavior
- [x] Add progress parser, streaming executor, stop-control, monitor-model, routing, and persistence tests
- [x] Pass local automated validation: 310 passed, 7 skipped
- [x] Manually verify WAITING to RUNNING transitions and aggregate progress
- [x] Manually verify no raw Restic JSON output
- [x] Record that modal monitor is not the accepted default information architecture

### Checkpoint 2A.2b — Persistent Backup Operations Dashboard — Awaiting Local Validation

#### Persistent inventory and confirmation

- [x] Keep all configured backups visible after pressing `R`
- [x] Add inline confirmation rather than switching to a modal monitor
- [x] Show complete confirmation information for every selected backup
- [x] Include repository, schedule, retention, last complete, last attempt, excludes, tags, and all sources
- [x] Require `Y` before materializing inputs or starting Restic
- [x] Preserve `N` and Esc cancellation with no side effects
- [x] Add confirmation scrolling while retaining inventory context
- [x] Add confirmation-content regression tests

#### Inline operations and source activity

- [x] Show selection, name, health, state, aggregate percentage, speed, ETA, last complete, last attempt, and sources
- [x] Add one automatic activity line per configured drive/source group while running
- [x] Show source groups as ACTIVE, SEEN, or PENDING
- [x] Label source lines as aggregate-only rather than fabricating per-drive percentages
- [x] Keep `Space` multi-selection available while other jobs run
- [x] Allow `R` to start another eligible backup without leaving the dashboard
- [x] Use independent worker/control objects for approved backups
- [x] Preserve existing process-lock conflict handling
- [x] Keep external persisted runs visible but not falsely controllable
- [x] Add concurrent-start model tests

#### Inline management and focused details

- [x] Add inline Stop confirmation with `S`
- [x] Limit Stop to locally managed active runs
- [x] Preserve Ctrl+C as graceful Stop-all for locally managed jobs
- [x] Block normal quit while a locally managed job is active
- [x] Keep `e`/`c` and `E`/`C` expansion controls
- [x] Add explicit focused single-backup view through Enter, `i`, or `m`
- [x] Keep filtering through `f`
- [x] Add operational color hierarchy for running, waiting, success, failure, interruption, stopping, and idle health
- [x] Add Stop-target regression tests

#### Routing and compatibility

- [x] Route interactive `backup run auto` through the persistent operations dashboard
- [x] Route interactive named runs through the same dashboard
- [x] Preserve noninteractive JSON/plain/Markdown behavior
- [x] Preserve scheduled named execution
- [x] Preserve `--print-command-only` as a hard no-side-effect barrier
- [x] Add the new module and tests to compile, lint, pytest, help, packaging, and PowerShell validation
- [ ] Pass local automated validation
- [ ] Manually verify colors, resizing, filtering, scrolling, and focused mode
- [ ] Manually verify rich inline confirmation cancellation creates no attempt
- [ ] Manually verify live execution remains on the inventory dashboard
- [ ] Manually verify another eligible backup can be selected while one runs
- [ ] Manually verify source-drive activity lines
- [ ] Manually verify graceful Stop and History persistence
- [ ] Show successful terminal snapshot ID prominently in the operations dashboard

### Checkpoint 2A.3 — Pause, Resume, and Scheduled Resume — Deferred

- [ ] Design a safe Windows process-suspension boundary
- [ ] Preserve process identity and repository lock ownership
- [ ] Persist and display paused state
- [ ] Add Pause and Resume actions to the persistent operations dashboard
- [ ] Add pause-now/resume-after-duration
- [ ] Define UI-exit and reboot behavior for scheduled resume
- [ ] Add crash/stale-process recovery
- [ ] Add stop-while-paused handling
- [ ] Add injected-clock and Windows controlled-acceptance tests

### Checkpoint 2B — Create and Schedule Wizard Preview — Deferred Until Viewer/Operations Work Passes

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

