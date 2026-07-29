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
