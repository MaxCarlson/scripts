# Validation Context: rrbackup

Generated: 2026-07-29T14:07:04.3628924-07:00
Branch: agent/merge-restic-backup-modules
Commit: 2b52dfd4f6bc8d04f37c012fff299da3d123c16a
Validation report: docs\test-results\rrbackup\LATEST.txt

## Validation Highlights

- RESULT: PASS - Clean stale RRBackup and TermDash editable metadata
- RESULT: PASS - Uninstall prior RRBackup entry points
- RESULT: PASS - Install shared TermDash dependency
- RESULT: PASS - Install RRBackup editable development dependencies
- RESULT: PASS - Compile RRBackup package and tests
- RESULT: PASS - Lint RRBackup checkpoint 2A.2
- RESULT: PASS - Canonical backup CLI help contract
- RESULT: PASS - Condensed backup view help contract
- [32m======================= [32m[1m310 passed[0m, [33m7 skipped[0m[32m in 15.17s[0m[32m =======================[0m
- RESULT: PASS - RRBackup pytest and coverage suite
- RESULT: PASS - PowerShell test: tests\powershell\environment_smoke_test.ps1
- RESULT: PASS - PowerShell test: tests\powershell\production_read_only_test.ps1
- TARGET RESULT: PASS

## Working Tree

```text
 M docs/test-results/rrbackup/LATEST.txt
 D docs/test-results/rrbackup/LATEST_CONTEXT.md
 D docs/test-results/rrbackup/LATEST_PROGRESS.diff
 D docs/test-results/rrbackup/history/20260729-105729_rrbackup.txt
 D docs/test-results/rrbackup/history/20260729-105729_rrbackup_context.md
 D docs/test-results/rrbackup/history/20260729-105729_rrbackup_progress.diff
?? docs/test-results/rrbackup/history/20260729-133648_rrbackup.txt
?? docs/test-results/rrbackup/history/20260729-133648_rrbackup_context.md
?? docs/test-results/rrbackup/history/20260729-133648_rrbackup_progress.diff
```

## Project Status Sources

### `docs/plans/20260729-0700_rrbackup-consolidation-viewer-alerting/STATUS.md`

# Status

## Overall

Stage 1 is verified. The Windows safety-foundation checkpoint passed package compilation, focused correctness lint, 199 tests, and both PowerShell checks; 8 environment-dependent tests skipped intentionally. The repository-root validation evidence workflow also works as intended.

Checkpoint **2A — Single-CLI UX Foundation**, Checkpoint **2A.1a — Completed Versus Attempted Run Visibility**, and Checkpoint **2A.1b — Interactive Viewer Carousel** are accepted.

The current validation-ready patch is **2A.2 — Expandable Live Viewer and Confirmed In-TUI Run Monitor**. It adds inline expansion, reliable alternate page keys, confirmation before execution, aggregate Restic progress, live viewer refresh, and graceful Stop. Pause/resume and delayed resume remain deferred to Checkpoint 2A.3.

Detailed scope is tracked in:

```text
03_viewer-carousel-and-run-monitor__in-progress.md
```

## Latest Automated Evidence

The pushed Windows run at commit `a8b2b5fb14f5b015315ae6d03b953921138ae976` recorded:

- dependency cleanup, uninstall, and editable installation: passed,
- package/test compilation: passed,
- focused correctness lint: passed,
- root `backup` help contract: passed,
- condensed `backup view` help contract: passed,
- pytest: 297 passed, 7 skipped, 0 failed,
- PowerShell installed-entry-point/environment smoke test: passed,
- production read-only test: safely skipped,
- pytest ANSI color sequences: preserved through the root dispatcher.

`LATEST_PROGRESS.diff` had no prior context snapshot and therefore established a new comparison baseline. This does not reduce the authority of the clean `LATEST.txt` result.

## Accepted Manual Findings

### Completed versus attempted runs

- `backup view` distinguishes the April completed snapshot from the July interrupted attempt.
- `backup view --section history` shows both the interrupted attempt and completed snapshot `022aad5b`.
- `backup run auto` shows Last complete, Last attempt, and Attempt state separately.

### Viewer carousel

Manual Windows review confirmed:

- bare `backup view` opens `View: OVERVIEW — pg. 1/6`,
- Overview is an aggregate dashboard rather than a duplicate backup list,
- page 2 shows configured backups,
- page 3 shows History,
- page 4 shows Repository,
- page 5 shows Schedules,
- page 6 shows compact Diagnostics,
- `backup view --demo` supplies six varied synthetic backups,
- `backup view --plain` uses aggregate Overview semantics,
- `backup view --section history` starts directly on page 3,
- default Audit output is concise,
- explicit Audit `--json` remains the complete large machine-readable export,
- the run selector uses the cleaner unlabeled row layout.

### Manual interaction gaps found after 2A.1b

- Overview details required Enter and left much of the screen unused.
- Inline expand/collapse, expand-all, and collapse-all controls were requested.
- The displayed `[`/`]` page controls were unreliable in the active Windows terminal.
- Additional previous/next keys were requested.
- Pressing `R` in `backup run auto` still exited the selector and immediately started Restic.
- Raw Restic JSON status objects still printed once per line.
- Real execution needed to remain inside a progress UI with speed, elapsed time, ETA, file/byte counts, current files, and Stop.
- `backup view` needed to show persisted progress while a backup is running.

## Current Patch — Checkpoint 2A.2

Implemented on the branch:

### Expandable viewer

- `e`: toggle inline details for the selected row.
- `c`: collapse the selected row.
- `E`: expand all rows on the current page.
- `C`: collapse all rows on the current page.
- Expanded detail rows remain adjacent to their parent and retain the parent's sort values.
- Enter still opens the complete detail screen.
- Additional page controls:
  - `p` or `-`: previous page,
  - `n`, `+`, or `=`: next page,
  - existing Tab and `1` through `6` controls remain.
- Page 2 now includes live State, Progress, Speed, and ETA columns while preserving sources and repository information.
- Overview Activity details include active progress.

### Live viewer refresh

- Interactive real-data viewers wake once per second without requiring a key press.
- Only run-state JSON is refreshed; Restic repository listing and diagnostics are not repeatedly executed.
- Overview, Backups, and History pages are invalidated only when the persisted run record changes.
- Demo mode remains deterministic and does not start the refresh thread.

### Confirmed execution

- Pressing `R` in the selector now means review/confirm, not immediate execution.
- A second curses screen lists selected backups, sources, and repositories.
- `Y` begins execution.
- `N`, Esc, `q`, or Ctrl+Q cancels before any backup input is materialized or Restic is started.
- Interactive named runs use the same confirmation monitor.
- Noninteractive JSON/plain/Markdown, scheduled named runs, and `--print-command-only` retain their existing behavior.

### In-TUI run monitor

- Restic output is consumed without raw terminal echo.
- JSON status lines are parsed into:
  - aggregate percentage,
  - processed/total files,
  - processed/total bytes,
  - average bytes per second,
  - elapsed time,
  - estimated remaining time,
  - current files.
- Progress is shown for each selected backup in one monitor.
- Multiple selected backups execute sequentially.
- Progress is persisted into the active run record at a throttled interval for `backup view`.
- Final progress is preserved in terminal run metadata.
- `S` opens a Stop confirmation.
- Confirmed Stop terminates the active Restic process gracefully and cancels remaining selections.
- Ctrl+C remains an emergency graceful-stop path.
- The monitor does not allow a normal quit while execution is active.

### Safety and scope boundaries

- Restic still creates one snapshot with the existing source-file semantics.
- The monitor reports only aggregate Restic progress.
- Per-drive percentages and ETAs are not fabricated because the Restic status stream does not provide trustworthy source-level totals.
- No production backup is started by automated tests.
- Pause/resume, delayed resume, and Windows process suspension are not implemented here.

### Focused tests added

- Restic progress parsing, speed, and ETA.
- Malformed/non-status line rejection.
- Streaming output callbacks without terminal echo.
- Stop requested before process creation.
- Stop requested after process attachment.
- Monitor worker progress and terminal state handling.
- Pending-run cancellation.
- Interactive run routing through confirmation rather than immediate execution.
- Throttled progress persistence into a running record.
- Live Overview and Backups progress rendering.
- Inline expansion materialization.
- Expand/collapse-all and reliable previous/next navigation.

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
- Clean aggregate-Overview correction validation: 297 passed, 7 skipped
- Manual acceptance of all six viewer pages, demo mode, plain Overview, compact Diagnostics/Audit, and concise run-selector rows

### Current bugs and uncertainty

- Checkpoint 2A.2 has not yet been locally compiled, linted, or tested.
- The selector-to-confirmation transition may produce a brief terminal redraw, but must never expose raw Restic JSON.
- Windows curses behavior for the one-second wake key requires manual validation.
- Inline expansion density, scrolling, filtering, and resize behavior require visual review.
- ETA is based on average processed bytes per second and may fluctuate while Restic is still discovering files and total bytes.
- Stop during a CPU-policy wait is recorded immediately in the monitor but the worker cannot exit until the CPU waiter returns or Restic starts and honors the already-requested stop.
- The shared state root still assumes one latest active run per profile directory; broader simultaneous multi-profile execution remains outside this checkpoint.
- Pause/resume feasibility and repository-lock safety require Checkpoint 2A.3.
- The module root `README.md` still documents the historical `rrb` interface and remains deferred until the new UX passes acceptance.

### Stall/loop assessment

Measurable progress continues. The 2A.1b correction passed 297 tests and manual review confirmed the new information architecture. The current work addresses two distinct user-observed interaction defects: unused viewer space and unsafe/unusable execution presentation. The project is not repeating the same failure or stuck.

## Next Validation

From the repository root:

```powershell
./Invoke-Tests.ps1
```

After automated validation, manually verify the expandable viewer first. Only then perform a short controlled backup-monitor test and stop it deliberately.

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

