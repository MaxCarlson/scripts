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
