# Checkpoint 2A.1–2A.3 — Viewer Carousel and Run Monitoring

## Status

In progress, split into bounded sub-checkpoints. Checkpoint 2A passed automated Windows validation with 288 tests passing and 7 intentional skips. Manual acceptance identified concrete UX gaps that are now tracked here.

Do not implement all items in one pass. Each sub-checkpoint must stop for local automated and manual validation before the next begins.

## Manual Findings That Define This Work

1. `backup view` opens a useful TermDash inventory, but one real backup leaves the screen visually sparse.
2. The Overview and Backups experiences are interactive, while History, Repository, Schedules, Diagnostics, and Audit fall back to disconnected static output.
3. Diagnostics and Audit default human output is oversized Markdown/JSON and is not useful as an interactive human-facing display.
4. The current interface does not clearly identify the active view or the current page number.
5. `backup run auto` treats `R` as immediate execution, closes the selector, and dumps raw Restic JSON status lines to the terminal.
6. Starting a real backup from the selector does not require a final confirmation.
7. An interrupted attempt was persisted, but the inventory showed only the previous successful snapshot, making the attempted run invisible.
8. Active-run progress is not visible from `backup view`.
9. More varied synthetic backup records are needed for visual testing without creating or mutating production backup definitions.

## Checkpoint 2A.1a — Completed Versus Attempted Run Visibility

This is the current bounded patch.

### Scope

- Show **Last complete** separately from **Last attempt** in both:
  - `backup view`
  - `backup run auto`
  - plain backup tables
  - schedule tables where run history is relevant
- Define Last complete as:
  - the newest successful structured run when available, or
  - the newest snapshot as authoritative fallback for pre-merge history.
- Define Last attempt as the latest structured run regardless of state:
  - queued
  - waiting
  - running
  - success
  - failure
  - interrupted
  - skipped
  - dry-run
- Show the latest attempt state with consistent colors.
- In the details view, show:
  - run ID
  - state
  - created/started/finished timestamps
  - exit code
  - reason
  - snapshot ID when present
- Distinguish completed snapshot events from attempted run events in History.

### Out of scope

- live progress monitoring
- confirmation flow changes
- pausing or resuming processes
- viewer page carousel
- synthetic/demo mode

### Acceptance

After interrupting a backup, reopening `backup view` must show:

- the older successful snapshot under Last complete,
- the recent interrupted run under Last attempt,
- `INTERRUPTED` as the attempt state,
- interruption details on Enter/details.

## Checkpoint 2A.1b — Interactive Viewer Carousel

Begin only after 2A.1a passes.

### Scope

- Convert `backup view` into one interactive multi-page dashboard.
- Pages:
  1. Overview
  2. Backups
  3. History
  4. Repository
  5. Schedules
  6. Diagnostics
- Keep Audit as an explicit export/structured operation unless a compact human summary proves useful.
- Display a highly visible colored page label, for example:

```text
View: OVERVIEW — pg. 1/6
```

- Show current page and total page count at all times.
- Add documented previous/next page hotkeys, likely Left/Right plus bracket alternatives where horizontal scrolling does not conflict.
- Preserve list navigation, filtering, details, paging, and terminal resizing.
- Preserve `--section` for direct noninteractive access.
- Replace default Diagnostics human output with a compact labeled summary.
- Keep full diagnostic/audit data behind explicit `--json`, `--markdown`, or export operations.
- Add an internal synthetic/demo inventory fixture or explicit safe demo mode containing varied records:
  - healthy scheduled backup
  - overdue backup
  - failed attempt
  - interrupted attempt
  - running backup
  - disabled schedule
  - missing schedule
  - multiple repositories and source counts
- Demo data must never execute Restic, mutate configuration, or touch production state.

### Deferred

- switching directly between root command areas such as View and Schedule inside one global application shell
- a global top-level TUI router

Those may be added later after the per-command carousels are accepted.

## Checkpoint 2A.2 — Confirmed In-TUI Run Monitor

Begin only after the viewer carousel checkpoint passes.

### Scope

- `R` selects the intended backup or backups but does not immediately start them.
- Show a confirmation page containing:
  - selected backup names
  - sources
  - repository
  - mode
  - schedule context
  - command preview with secrets redacted
- Require explicit confirmation before real execution.
- Keep the user inside a themed TUI while the backup runs.
- Parse Restic JSON status messages instead of printing them raw.
- Show per active backup:
  - state
  - overall percent complete
  - files completed/total
  - bytes completed/total
  - elapsed time
  - estimated remaining time when enough data exists
  - current files, compacted in the overview and expanded in details
- Refresh the UI without losing keyboard control.
- Show active-run status from both:
  - `backup run auto`
  - `backup view`
- Enrich the details page with all available live and persisted run fields.
- On completion, show the terminal state and snapshot ID without dropping back to raw terminal output.
- Add a visible Stop action with confirmation.
- Stop must request graceful Restic termination, preserve logs, release locks, and persist `INTERRUPTED`.
- Preserve `Ctrl+C` as an emergency graceful-stop path.

### Per-drive/source progress caveat

Restic's normal JSON status stream reports aggregate `percent_done`, `bytes_done`, `total_bytes`, file counts, elapsed time, and current files. It does not directly provide trustworthy per-source or per-drive totals and ETAs.

Before implementing per-drive percentages, investigate and document one safe approach:

1. pre-scan source totals and attribute processed files to roots,
2. add an instrumentation layer that tracks file/root progress without changing snapshot semantics, or
3. deliberately show aggregate progress plus current source/drive activity when exact per-drive totals cannot be proven.

Do not display fabricated per-drive percentages or ETAs. Running each source as a separate Restic backup is not an acceptable silent workaround because it changes snapshot and atomicity semantics.

## Checkpoint 2A.3 — Pause, Resume, and Scheduled Resume

Begin only after the monitor and clean Stop behavior pass.

### Requested behavior

While an active backup is selected, provide actions to:

- pause,
- resume,
- stop,
- pause now and resume after a selected duration.

### Safety and platform constraints

- Restic does not provide a native portable pause/resume command.
- Windows process suspension may be possible through platform APIs or `psutil`, but suspending a repository-writing process while holding locks must be treated as high risk.
- The design must preserve:
  - repository lock ownership,
  - process identity validation,
  - state persistence across UI exits,
  - clear paused status,
  - crash/reboot recovery behavior,
  - an upper bound or warning for long pauses,
  - safe cancellation while paused.
- Scheduled resume must survive the interactive UI remaining open; whether it should survive process exit or reboot requires a separate scheduler-backed design.
- Cross-platform behavior must be explicit. Unsupported platforms must show a clear unavailable state rather than pretending the action succeeded.

### Required tests

- pause/resume state-machine tests
- process identity and stale-process tests
- lock retention and cleanup tests
- stop-while-paused tests
- scheduled-resume timing tests with injected clocks
- Windows-specific controlled acceptance using a temporary repository

## Shared Manual-Test Rules

Each interactive patch must ship with manual tests covering:

- visual hierarchy and color use,
- narrow and wide terminals,
- terminal resize,
- keyboard discoverability,
- cancellation and confirmation,
- details-page usefulness,
- multiple synthetic records,
- active, failed, interrupted, and completed states,
- no raw JSON in default human mode,
- no production mutation unless explicitly approved.
