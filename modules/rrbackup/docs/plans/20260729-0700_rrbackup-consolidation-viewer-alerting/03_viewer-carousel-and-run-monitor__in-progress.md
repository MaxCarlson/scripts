# Checkpoint 2A.1–2A.3 — Viewer Carousel and Run Monitoring

## Status

In progress, split into bounded sub-checkpoints. Checkpoint 2A passed automated Windows validation with 288 tests passing and 7 intentional skips. Checkpoint 2A.1a then passed with 289 tests and manual confirmation that completed and interrupted attempts are displayed separately.

The current validation-ready patch is **Checkpoint 2A.1b — Interactive Viewer Carousel**. Do not begin the live run monitor or pause/resume implementation until this patch passes automated and manual validation.

## Manual Findings That Define This Work

1. `backup view` opened a useful TermDash inventory, but one real backup left the screen visually sparse.
2. Overview and Backups were interactive, while History, Repository, Schedules, Diagnostics, and Audit fell back to disconnected static output.
3. Diagnostics and Audit default human output was oversized Markdown/JSON and was not useful as an interactive human-facing display.
4. The interface did not clearly identify the active view or current page number.
5. Interactive rows repeated labels such as `complete`, `attempt`, `next`, and `missed` even though column headers already described the fields.
6. `backup run auto` treated `R` as immediate execution, closed the selector, and dumped raw Restic JSON status lines to the terminal.
7. Starting a real backup from the selector did not require a final confirmation.
8. An interrupted attempt was persisted, but the initial inventory showed only the previous successful snapshot.
9. Active-run progress was not visible from `backup view`.
10. More varied synthetic backup records were needed for visual testing without creating or mutating production definitions.

## Checkpoint 2A.1a — Completed Versus Attempted Run Visibility — Accepted

### Implemented

- Show **Last complete** separately from **Last attempt** in:
  - `backup view`
  - `backup run auto`
  - plain backup tables
  - schedule tables where run history is relevant
- Last complete uses:
  - the newest successful structured run when available, or
  - the newest snapshot as authoritative fallback for pre-merge history.
- Last attempt uses the latest structured run regardless of state:
  - queued
  - waiting
  - running
  - success
  - failure
  - interrupted
  - skipped
  - dry-run
- Attempt state uses the shared status semantics.
- Details show:
  - run ID
  - state
  - created/started/finished timestamps
  - exit code
  - reason
  - snapshot ID when present
- History distinguishes completed snapshot events from attempted run events.

### Evidence

- Automated: 289 passed, 7 skipped, 0 failed.
- Manual:
  - April snapshot remained under Last complete.
  - July interrupted run appeared under Last attempt.
  - Attempt state displayed `INTERRUPTED`.
  - History showed both the attempted interrupted run and completed snapshot.

## Checkpoint 2A.1b — Interactive Viewer Carousel — Awaiting Local Validation

### Implemented in this patch

- Convert `backup view` into one interactive six-page dashboard:
  1. Overview
  2. Backups
  3. History
  4. Repository
  5. Schedules
  6. Diagnostics
- Display a persistent colored page label through the shared TermDash header:

```text
View: OVERVIEW — pg. 1/6
```

- Page controls:
  - `[` previous page
  - `]` next page
  - `Tab` next page
  - `1` through `6` direct page selection
- Preserve:
  - Up/Down and `j`/`k`
  - Page Up/Page Down
  - filtering
  - Enter/details
  - horizontal scrolling
  - terminal resizing
- `--section` now selects the starting interactive page.
- `--plain`, `--json`, and `--markdown` retain noninteractive output.
- Repository and diagnostics pages are loaded lazily when first visited.
- Repository status collection remains read-only and does not run full storage statistics.
- Diagnostics default human output is now a compact category/status/summary index with expandable details.
- Audit default human output is now a compact audit index; complete evidence remains behind explicit `--json` or `--markdown`.
- Add safe visual fixtures through:

```text
backup view --demo
```

- Demo mode includes varied records:
  - healthy successful backup
  - warning/skipped backup
  - failed attempt
  - interrupted attempt
  - running attempt
  - disabled schedule
  - multiple repositories
  - different source counts and retention policies
- Demo mode does not:
  - load user configuration
  - inspect environment or host paths
  - invoke Restic
  - mutate state
- Remove redundant inline labels from interactive viewer and run-selector rows.
- Route `backup run auto` through the concise selector while preserving current execution behavior for this checkpoint.
- Add non-curses unit tests for:
  - all six page builders
  - page labels and direct switching
  - lazy repository/diagnostic loading
  - compact diagnostics and audit summaries
  - demo-state diversity
  - clean selector row formatting

### Out of scope

- confirmation before `R`
- live run progress
- explicit Stop action
- pause/resume
- scheduled resume
- switching directly between root command areas inside a global application shell

### Manual acceptance

Run:

```text
backup view --demo
```

Verify:

- visible `View: ... — pg. n/6` label,
- `[`/`]`, Tab, and `1`–`6` page switching,
- all six pages contain useful varied data,
- Enter/details works on each page,
- filtering works after changing pages,
- resizing does not corrupt the display,
- no production paths or real Restic activity occur,
- Overview rows do not repeat `complete`, `attempt`, `next`, or `missed` labels.

Then run:

```text
backup view
```

Verify the real interrupted attempt remains visible and page switching works against the real repository.

Finally run:

```text
backup run auto
```

Verify the selector row is aligned and no longer repeats the inline labels. Exit with Ctrl+Q; do not press `R` until Checkpoint 2A.2 adds confirmation.

## Checkpoint 2A.2 — Confirmed In-TUI Run Monitor — Deferred

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
- Refresh without losing keyboard control.
- Show active-run status from both:
  - `backup run auto`
  - `backup view`
- Enrich both details pages with all available live and persisted run fields.
- On completion, show terminal state and snapshot ID without raw terminal output.
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

## Checkpoint 2A.3 — Pause, Resume, and Scheduled Resume — Deferred

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
  - repository lock ownership
  - process identity validation
  - state persistence across UI exits
  - clear paused status
  - crash/reboot recovery behavior
  - an upper bound or warning for long pauses
  - safe cancellation while paused
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

- visual hierarchy and color use
- narrow and wide terminals
- terminal resize
- keyboard discoverability
- cancellation and confirmation
- details-page usefulness
- multiple synthetic records
- active, failed, interrupted, and completed states
- no raw JSON in default human mode
- no production mutation unless explicitly approved
