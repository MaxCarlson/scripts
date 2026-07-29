# Status

## Overall

Stage 1 is verified. The Windows safety-foundation checkpoint passed package compilation, focused correctness lint, 199 tests, and both PowerShell checks; 8 environment-dependent tests skipped intentionally. The repository-root validation evidence workflow also works as intended.

Checkpoint **2A — Single-CLI UX Foundation** and Checkpoint **2A.1a — Completed Versus Attempted Run Visibility** are accepted.

Checkpoint **2A.1b — Interactive Viewer Carousel** passed automated Windows validation with 295 tests passing and 7 intentional skips. Manual testing confirmed the interactive History page, concise run-selector rows, and compact default Audit summary. Manual testing also showed that the original Overview page duplicated the old per-backup list closely enough that bare `backup view` appeared unchanged.

The current validation-ready correction keeps the six-page carousel but replaces page 1 with a true aggregate dashboard. Do not begin the live run monitor, Stop action, or pause/resume work until this correction passes automated and manual review.

Detailed scope is tracked in:

```text
03_viewer-carousel-and-run-monitor__in-progress.md
```

## Latest Automated Evidence

The pushed Windows run at commit `e9b4aea5c3b51be3a9adaf94394ce0cb33c1d172` recorded:

- dependency cleanup, uninstall, and editable installation: passed,
- package/test compilation: passed,
- focused correctness lint: passed,
- root `backup` help contract: passed,
- condensed `backup view` help contract: passed,
- pytest: 295 passed, 7 skipped, 0 failed,
- PowerShell installed-entry-point/environment smoke test: passed,
- production read-only test: safely skipped,
- package branch coverage: 61%,
- pytest ANSI color sequences: preserved through the root dispatcher.

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

### Viewer carousel

- `backup view --section history` entered the interactive carousel on `View: HISTORY — pg. 3/6`.
- The History page displayed the interrupted attempt and completed snapshot correctly.
- `backup view --section audit` produced a concise human summary instead of raw Markdown/JSON.
- `backup view --section audit --json` intentionally produced the complete, large machine-readable audit.
- `backup run auto` used the cleaner unlabeled row layout.
- Bare `backup view` appeared unchanged because the original Overview page was another per-backup inventory table rather than an aggregate dashboard.

### Run selector and execution

- `backup run auto` opens the expected selector.
- Pressing `R` still immediately starts a real backup in the current build.
- Restic JSON progress messages are printed raw.
- The future monitor must show aggregate progress, elapsed time, ETA, file/byte counts, current files, active state, and a confirmed Stop action.
- Active-run information must also be visible from `backup view` and both details pages.
- Pause/resume and delayed resume remain a separate safety-sensitive checkpoint.
- Exact per-drive progress cannot be claimed from Restic's aggregate JSON without additional verified instrumentation.

## Current Correction — Checkpoint 2A.1b

Implemented on the branch:

- Bare `backup view` remains page 1 of the six-page carousel.
- Page 1 is now an aggregate dashboard rather than a duplicate backup list.
- The aggregate Overview contains expandable rows for:
  - backup health,
  - current/recent activity,
  - completion coverage,
  - schedule state and missed runs,
  - repository grouping.
- Page 2 remains the detailed per-backup inventory.
- Plain Overview output uses the same aggregate semantics.
- Runtime regression coverage proves that bare `backup view` routes into the carousel with `start_page="overview"`.
- Focused tests distinguish the aggregate Overview from the detailed Backups page.
- The new controller is included in compile, Ruff, and pytest validation.

Already implemented and awaiting complete manual acceptance:

- pages:
  1. Overview
  2. Backups
  3. History
  4. Repository
  5. Schedules
  6. Diagnostics
- persistent page labels such as `View: OVERVIEW — pg. 1/6`,
- `[`/`]`, Tab, and `1`–`6` page controls,
- lazy Repository and Diagnostics loading,
- safe `backup view --demo` fixtures,
- compact Diagnostics and default Audit summaries,
- concise run-selector formatting.

Not implemented in this checkpoint:

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
- Clean initial Checkpoint 2A.1b validation: 295 passed, 7 skipped
- Manual acceptance of completed-versus-attempted run visibility
- Manual acceptance of History carousel entry, compact Audit summary, and concise run-selector rows

### Current bugs and uncertainty

- The aggregate Overview correction has not yet been locally compiled, linted, or tested.
- `backup view --demo` visual density and all page-switch keys still need manual Windows verification.
- Repository, Schedules, Diagnostics, terminal resize, filter persistence expectations, and detail usefulness need manual review.
- Lazy repository collection may pause briefly when the Repository page is first opened; it remains read-only.
- `R` in `backup run auto` still begins execution immediately. Do not press it during this checkpoint.
- The installed build still prints raw Restic JSON during execution until Checkpoint 2A.2.
- Pause/resume feasibility and repository-lock safety require a dedicated design and controlled acceptance.
- The module root `README.md` still documents the historical `rrb` interface and remains deferred until the new UX passes acceptance.

### Stall/loop assessment

Measurable progress continues. Automated 2A.1b validation passed, and manual review identified a presentation-model issue rather than a broken carousel. The correction separates aggregate Overview information from detailed Backups information and adds direct runtime coverage. The project is not looping or stuck.

## Next Validation

From the repository root:

```powershell
./Invoke-Tests.ps1
```

After automated validation, manually exercise:

```text
backup view
backup view --demo
backup view --section backups
backup view --section repository
backup view --section schedules
backup view --section diagnostics
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
