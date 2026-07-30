# Status

## Overall

Stage 1 is verified. Checkpoint **2A — Single-CLI UX Foundation**, Checkpoint **2A.1a — Completed Versus Attempted Run Visibility**, and Checkpoint **2A.1b — Interactive Viewer Carousel** are accepted.

Checkpoint **2A.2a — Expandable Live Viewer and Confirmed Aggregate Monitor** is accepted. Restic JSON parsing, aggregate progress persistence, confirmation, and graceful Stop were verified manually.

Checkpoint **2A.2b — Persistent Backup Operations Dashboard** passed automated Windows validation with 314 tests passing and 7 intentional skips. Manual review confirmed the persistent dashboard loads, but exposed two semantic/information-architecture defects:

1. an interrupted terminal run retained its final progress sample and displayed a purple `ACTIVE` drive marker even though no backup was running;
2. bare `backup view` still opened the six-page reference carousel instead of making current operations the primary surface.

The current validation-ready patch is **2A.2c — Operations-First View and Current-versus-Historical State Semantics**. Bare `backup view` and interactive `backup run` now share a two-tab Operations/History hub. Current state, latest result, and historical partial progress are explicitly separated. Pause/resume and delayed resume remain deferred to Checkpoint 2A.3.

Detailed scope is tracked in:

```text
03_viewer-carousel-and-run-monitor__in-progress.md
```

## Latest Automated Evidence

The pushed Windows run at commit `16f96f8a2b1d72cddc7175ed657ec39aa1d2ed64` recorded:

- dependency cleanup, uninstall, and editable installation: passed,
- package/test compilation: passed,
- focused correctness lint for Checkpoint 2A.2b: passed,
- root `backup` help contract: passed,
- condensed `backup view` help contract: passed,
- pytest: 314 passed, 7 skipped, 0 failed,
- PowerShell installed-entry-point/environment smoke test: passed,
- production read-only test: safely skipped,
- pytest ANSI color sequences: preserved through the root dispatcher.

The progress artifact showed an increase from 310 to 314 passing tests. This is measurable forward progress, not a repeated failure cycle.

## Accepted Manual Findings

### Execution plumbing

Manual Windows review confirmed:

- confirmation prevents immediate execution,
- Restic JSON is consumed without raw terminal output,
- WAITING transitions to RUNNING,
- aggregate percentage, files, bytes, speed, elapsed time, ETA, and current files update,
- graceful Stop is available,
- an interrupted attempt is preserved independently from the last completed snapshot.

### Persistent operations dashboard

Manual review confirmed:

- `backup run auto` opens the persistent operations dashboard,
- inline backup details and source groups render,
- confirmation and execution remain inside the terminal UI,
- latest interrupted progress remains persisted for historical diagnosis.

### Defects discovered after 2A.2b

The latest manual evidence established:

- the parent row showed `INTERRUPTED` as though it were the current operational state,
- the row retained stale percentage, speed, and ETA from the interrupted attempt,
- `C:` appeared as purple `ACTIVE` even though the run was no longer active,
- bare `backup view` did not put current operations first,
- `backup view --section history` was correctly read-only, but the command organization made Start/Stop controls difficult to discover,
- the six reference pages should not have equal prominence with live operational status.

`ACTIVE` must mean current-file activity during a genuinely active run only. It must never describe a terminal attempt.

## Current Patch — Checkpoint 2A.2c

### Operations-first command routing

- Bare interactive `backup view` opens the shared Operations/History hub.
- Interactive `backup run` opens the same hub.
- Operations is the default tab and supports Start/Stop.
- History is the secondary read-only tab.
- `1` or `O` opens Operations.
- `2` or `H` opens History.
- Pressing `R` or `S` from History returns to Operations with an explanatory message.
- Explicit `backup view --section ...` commands remain read-only reference pages.
- `backup view --demo` remains safe and uses the existing synthetic reference carousel.
- Noninteractive `--plain`, `--json`, and `--markdown` behavior remains unchanged.

### Current versus historical semantics

Operations rows now separate:

- `NOW`: `IDLE`, `QUEUED`, `WAITING`, `RUNNING`, or `STOPPING`;
- `LAST RESULT`: `SUCCESS`, `INTERRUPTED`, `FAILURE`, `SKIPPED`, `DRY-RUN`, or `NONE`;
- `LAST ATTEMPT` time;
- `LAST COMPLETE` time.

Terminal attempts always render `NOW: IDLE`. Their saved progress is removed from live percentage, speed, ETA, and source activity columns.

Historical partial progress remains available only in expanded details and is labeled:

- `Last attempt partial files`,
- `Last attempt partial bytes`,
- `Last observed files`.

No historical ETA or live speed is displayed for a terminal attempt.

### Source activity semantics

- `ACTIVE`, `SEEN`, and `PENDING` appear only while `NOW` is an active state.
- An idle expanded backup shows sources as `CONFIGURED`.
- Source rows continue to state that Restic completion totals are aggregate.
- No per-drive percentage or ETA is fabricated.

### Operations status hierarchy

The shared hub displays a visible status strip:

```text
RUNNING NOW: n | WAITING/STOPPING: n | IDLE: n | ATTENTION: n
```

A second line explicitly states either the active backup names/states or:

```text
No backups are currently running. Latest attempt: <backup> <result> (<age>).
```

### Integrated History

- History is available without leaving the hub.
- It lists attempted runs and completed snapshots.
- Enter or `i` opens event details.
- History refreshes from the same run records as Operations.
- History remains read-only; Start/Stop belongs to Operations.

### Safety and compatibility boundaries

- Existing engine, lock, progress-persistence, and Stop behavior is reused.
- Automated tests do not start a production backup.
- Scheduled and noninteractive named runs retain their existing behavior.
- `--print-command-only` remains a hard no-side-effect barrier.
- Pause/resume, scheduler writes, retention execution, restore changes, and production mutation are not included.

### Focused tests added or updated

- Interrupted progress renders `NOW: IDLE` and `LAST RESULT: INTERRUPTED`.
- Terminal source groups render `CONFIGURED`, never `ACTIVE`.
- Terminal progress is labeled historical and has no live ETA.
- A genuine running attempt still renders live progress and `ACTIVE` source activity.
- Bare `backup view` routes to the Operations/History hub.
- Explicit `--section overview` still routes to the read-only reference carousel.
- Plain bare view still renders aggregate Overview output.
- View-style arguments receive safe default run options.
- History contains both attempted runs and completed snapshots.

## Current Bugs and Uncertainty

- Checkpoint 2A.2c has not yet been locally compiled, linted, or tested.
- Windows curses rendering, resizing, filtering, tab switching, confirmation scrolling, and History details require manual review.
- External active runs are visible but cannot be stopped by a hub that does not own their process control object.
- ETA remains aggregate and may fluctuate while Restic discovers files and total bytes.
- The old six-page carousel remains available through explicit `--section` commands; consolidation into a smaller System/Reference page is deferred until the Operations/History hierarchy is accepted.
- Pause/resume still requires a dedicated Windows process-suspension design.
- The module root `README.md` still documents the historical `rrb` interface.

## Progress Assessment

### Accomplished

- Stage 1 safety foundation
- Canonical `backup` executable and seven task-oriented command areas
- Unified canonical/legacy inventory
- Completed-versus-attempted run visibility
- Six-page reference viewer and compact Diagnostics/Audit
- Structured Restic progress parsing and persistence
- Confirmed execution and graceful Stop plumbing
- Persistent multi-backup operations dashboard
- Clean validation milestones:
  - 288 passed, 7 skipped
  - 289 passed, 7 skipped
  - 295 passed, 7 skipped
  - 297 passed, 7 skipped
  - 310 passed, 7 skipped
  - 314 passed, 7 skipped

### Stall/loop assessment

The project is not stuck. The executor, progress stream, confirmation, persistence, and Stop behavior are working. Manual review identified a distinct semantic defect: historical progress was presented as current activity, and live operations were not the default information hierarchy. Checkpoint 2A.2c corrects that interpretation and command organization without changing the verified execution engine.

## Next Validation

From the repository root:

```powershell
./Invoke-Tests.ps1
```

After automated validation, manually exercise:

```text
backup view
backup run auto
backup view --section history
```

Required manual acceptance:

1. Bare `backup view` opens `View: OPERATIONS — 1/2`.
2. The status strip clearly says `RUNNING NOW: 0` when no backup is active.
3. `local-main` shows `NOW: IDLE` and `LAST RESULT: INTERRUPTED`.
4. Percentage, speed, and ETA are blank for the interrupted attempt.
5. Expanded source rows show `CONFIGURED`, not `ACTIVE` or `PENDING`.
6. Expanded historical statistics say `Last attempt partial` and `Last observed files`.
7. `R` opens confirmation from Operations.
8. `2` or `H` opens History; `1` or `O` returns to Operations.
9. History shows the interrupted attempt and April completed snapshot.
10. During a controlled run, `NOW` changes to WAITING/RUNNING and source rows may show ACTIVE/SEEN/PENDING.
11. After Stop, `NOW` returns to IDLE and `LAST RESULT` becomes INTERRUPTED.

Do not test pause/resume yet; it is not implemented.

## Last Known Production State

- Repository: `B:\ResticRepos\PC-Local`
- Known completed snapshots: `a1609113`, `022aad5b`
- Latest completed snapshot: 2026-04-14
- Latest attempted run: interrupted on 2026-07-29
- Current module-owned backup schedule: absent
- Automated production mutation: prohibited
