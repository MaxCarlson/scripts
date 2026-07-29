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
