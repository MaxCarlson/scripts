# Status

## Overall

Stage 1 is verified. The Windows safety-foundation checkpoint passed package compilation, focused correctness lint, 199 tests, and both PowerShell checks; 8 environment-dependent tests skipped intentionally. The repository-root validation evidence workflow also works as intended.

Checkpoint **2A — Single-CLI UX Foundation** is automated-test complete. Checkpoint **2A.1a — Completed Versus Attempted Run Visibility** is also accepted: the latest Windows validation passed 289 tests with 7 intentional skips, and manual testing confirmed that the April completed snapshot and July interrupted attempt are displayed separately.

The current validation-ready patch is **2A.1b — Interactive Viewer Carousel**. It is implemented but has not yet been locally validated. Do not begin the live run monitor, Stop action, or pause/resume work until its automated and manual evidence is reviewed.

Detailed scope is tracked in:

```text
03_viewer-carousel-and-run-monitor__in-progress.md
```

## Latest Accepted Evidence

The pushed Windows run at commit `7639d2a5ea82c2e81acc5039ee32f930b13e354b` recorded:

- dependency cleanup, uninstall, and editable installation: passed,
- package/test compilation: passed,
- focused correctness lint: passed,
- root `backup` help contract: passed,
- condensed `backup view` help contract: passed,
- pytest: 289 passed, 7 skipped, 0 failed,
- PowerShell installed-entry-point/environment smoke test: passed,
- production read-only test: safely skipped,
- package branch coverage: 60%,
- pytest ANSI color sequences: preserved through the root dispatcher.

The validation command may have been run twice. This was harmless: `LATEST.txt` contains the newest clean run, while the progress artifact simply re-established its comparison baseline.

## Accepted Manual Findings

### Completed versus attempted runs

- `backup view` shows:
  - Last complete: April snapshot
  - Last attempt: recent interrupted run
  - Attempt state: `INTERRUPTED`
- `backup view --section history` showed both:
  - attempted interrupted run
  - completed snapshot `022aad5b`
- `backup run auto` displayed the same separation.
- The plain post-selector table was readable and correctly separated completion from attempt state.

### Remaining presentation findings

- Interactive rows repeated labels such as `complete`, `attempt`, `next`, and `missed` even though headers already identified those fields.
- One real backup made the viewer visually sparse.
- History, Repository, Schedules, and Diagnostics needed to become pages in one interactive viewer.
- Diagnostics and Audit default human output was too large and JSON/Markdown-heavy.

### Run selector and execution findings

- `backup run auto` opens the expected selector.
- Pressing `R` still immediately starts a real backup in the currently accepted build.
- Restic JSON progress messages are printed raw.
- The future monitor must show aggregate progress, elapsed time, ETA, file/byte counts, current files, active state, and a confirmed Stop action.
- Active-run information must also be visible from `backup view` and both details pages.
- Pause/resume and delayed resume remain a separate safety-sensitive checkpoint.
- Exact per-drive progress cannot be claimed from Restic's aggregate JSON without additional verified instrumentation.

## Current Patch — Checkpoint 2A.1b

Implemented on the branch:

- One interactive six-page `backup view` carousel:
  1. Overview
  2. Backups
  3. History
  4. Repository
  5. Schedules
  6. Diagnostics
- Persistent page label:

```text
View: OVERVIEW — pg. 1/6
```

- Page controls:
  - `[` previous
  - `]` next
  - Tab next
  - `1` through `6` direct jump
- `--section` selects the starting interactive page.
- Explicit `--plain`, `--json`, and `--markdown` remain noninteractive.
- Repository and diagnostics pages load only when first visited.
- Default repository page remains read-only and never runs full restore-size statistics.
- Diagnostics default human output is a compact category/status/summary index with details on Enter.
- Audit default human output is a compact index; complete evidence remains explicit through `--json` or `--markdown`.
- Safe visual test mode:

```text
backup view --demo
```

- Demo mode supplies varied healthy, warning, failed, interrupted, running, disabled-schedule, multi-repository, and multi-source records.
- Demo mode does not load real configuration, inspect the host, invoke Restic, or write state.
- Interactive viewer and run-selector rows no longer repeat inline `complete`, `attempt`, `next`, or `missed` labels.
- Focused tests cover all six page builders, demo-state diversity, compact diagnostics/audit output, page labels, direct switching, lazy page loading, and concise run-selector formatting.
- Root validation now compiles and lints the new viewer/runtime modules and runs their tests.

Not implemented in this patch:

- confirmation before pressing `R`,
- live progress monitor,
- active-run refresh,
- explicit Stop action,
- pause/resume,
- scheduled resume,
- global switching between root command areas.

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
- Manual acceptance of completed-versus-attempted run visibility

### Current bugs and uncertainty

- Checkpoint 2A.1b has not yet been locally compiled, linted, or tested.
- Carousel page hotkeys, visual hierarchy, terminal resize behavior, and detail usefulness require manual Windows verification.
- Lazy repository collection may pause briefly when the Repository page is first opened; it remains read-only.
- `R` in `backup run auto` still begins execution immediately. Do not press it during 2A.1b acceptance.
- The installed build still prints raw Restic JSON during execution until Checkpoint 2A.2.
- Pause/resume feasibility and repository-lock safety require a dedicated design and controlled acceptance.
- The module root `README.md` still documents the historical `rrb` interface and remains deferred until the new UX passes acceptance.

### Stall/loop assessment

Measurable progress continues. The project moved from the single-CLI foundation to accepted interrupted-run visibility and is now addressing a distinct interactive presentation layer. The work is not repeating the same failure or stuck; each new patch is bounded and driven by manual UX findings that automated tests cannot assess.

## Next Validation

From the repository root:

```powershell
./Invoke-Tests.ps1
```

After automated validation, manually exercise:

```text
backup view --demo
backup view
backup run auto
```

Do not press `R` in the run selector during this checkpoint.

## Last Known Production State

- Repository: `B:\ResticRepos\PC-Local`
- Known completed snapshots: `a1609113`, `022aad5b`
- Latest completed snapshot: 2026-04-14
- Latest attempted run: interrupted during manual Checkpoint 2A acceptance on 2026-07-29
- Current module-owned backup schedule: absent
- Automated production mutation: prohibited
