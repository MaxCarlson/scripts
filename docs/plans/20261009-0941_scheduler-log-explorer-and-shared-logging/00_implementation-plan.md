# Scheduler Log Explorer and Shared Logging Library

## Objective

Replace the flat scheduler log picker with a schedule-aware history browser, durable usage statistics, and selectable per-run output. Extract reusable logging and run-history primitives into a repository module that other scripts modules can adopt. Make Escape return one screen at a time and provide a separate shortcut to the TUI home menu.

The user approved implementation in the conversation. Work proceeded through the six stages without a per-stage pause; no live Windows tasks were modified.

## Current Evidence

- `scheduler/tui.py::workflow_view_logs` lists the central log and task log files as peers, so schedule membership and standalone tasks are not visible in the hierarchy.
- `TaskLogger` writes text blocks containing timestamp, status/exit code, duration, schedule name, script, stdout, and stderr. It retains only the configured most recent N blocks (default 10); older history is removed.
- `TaskLogger.list_task_runs` parses only the retained text and returns latest-first list indices rather than stable run identifiers.
- `sanitize_filename` maps distinct task names such as `Winget Update` and `Winget_Update` to the same filename. The current UI can list both names even though they can resolve to one file.
- Schedule/task models contain recurrence and last-run fields, but no durable per-run identity, planned-versus-actual timing, or long-term success/runtime history.
- `select_menu` maps Esc, `q`, and `b` to the same `-1` result. Nested workflows interpret that result independently; the root menu treats it as exit.
- There is no reusable first-party logger package under `modules/`. `modules/logs/` is a data directory, while modules use a mixture of Python's standard logging, bespoke text loggers, and JSONL stores.

## Proposed Design

### Shared package

Create a dependency-light `script_logging` module (working name; the final import/distribution name must be checked for collisions before Stage 1). It must not shadow Python's built-in `logging` package. It will provide reusable, scheduler-neutral primitives:

- a structured event/run record model with stable record IDs, source and entity references, timestamps, outcome, duration, and JSON metadata;
- a transactional SQLite-backed history store with indexed querying, date windows, filtering, clear/prune operations, and safe concurrent access;
- a bridge for standard `logging.Logger` records and a readable text formatter/handler for applications that still need line-oriented logs;
- explicit retention for potentially large stdout/stderr payloads, separate from compact metadata retention;
- documented APIs and examples suitable for adoption by another module without scheduler concepts.

The scheduler will own recurrence interpretation, schedule/task aggregates, and heatmap semantics. The shared library stores generic events/runs and serves them by entity, source, and time. This keeps reusable storage and logging separate from scheduler-specific analytics.

### Durable scheduler history

Store generic run/event records in a SQLite database adjacent to `scheduler_data.json`. Add stable IDs to schedules and tasks, migrating existing JSON entries by assigning IDs once and persisting them. New run records will associate IDs while retaining the task/schedule names as display snapshots.

For each schedule trigger, persist the expected occurrence time, actual trigger/start time, completion time, catch-up flag, and aggregate outcome. For each task run, persist a unique run ID, source (manual, scheduled, catch-up, or delayed runner test), scheduled occurrence when applicable, start/finish times, exit status, duration, and output. The scheduler remains responsible for deciding whether a run was on time.

Keep the current text logs readable during migration. The structured store becomes the source for statistics and selectable run history. Import all parseable records still present in old task logs, but mark ambiguous filename collisions and do not attribute uncertain records to either task. Runs older than the existing retention window cannot be reconstructed; statistics before the structured history rollout will show the imported coverage boundary instead of implying complete history.

Use a default one-year retention for full run output, configurable independently from compact run metadata. This lets the year view open individual run output while placing a bound on output storage. If output expires before metadata, keep the run row and show that its output has expired. “Clear All Logs” must explicitly confirm that it will clear both readable logs and structured history/statistics.

### Logs navigation and detail screens

The Logs home screen will contain:

- Central System Log;
- one item per schedule, showing recurrence, enabled state, attached task count, and latest/next occurrence;
- a Standalone Tasks group;
- an Unmatched Legacy Logs group when files cannot safely be mapped to current tasks;
- Clear All Logs.

Selecting a schedule opens a schedule dashboard with recurrence details, 7/30/365-day trigger totals, on-time/late/missed/catch-up counts and rates, per-task success/failure/runtime summaries, a year activity grid, and a scrollable/selectable schedule-run list. Selecting one of its tasks opens the task dashboard.

The task dashboard will show schedule/standalone association, 7/30/365-day and lifetime totals, successful/failed counts, success rate, average/minimum/maximum runtime, and the activity grid. Beneath those summaries, a keyboard-navigable run list will show date/time, source, duration, and result. Selecting a run opens only that run's output, using the stable run ID rather than parsing a moving list index.

The activity grid will use a 365-day window with a compact week/day layout. It will render cells only for dates on which the schedule recurrence expects a run; unscheduled dates remain blank. Green means all expected runs on that date succeeded on time; red means a failure or missed occurrence; a third neutral/warning color may distinguish late or partial days. A legend and terminal-width fallback are required. For schedules with multiple occurrences per day, the cell summarizes all occurrences. Standalone task grids show dates with actual runs.

“On time” will use an explicit shared tolerance, proposed default five minutes, based on `scheduled_for` versus actual start. Reports must show both on-time count and the tolerance used. Missed occurrences are derived from expected recurrence dates with no matching trigger/run record; the UI must distinguish missed from dates outside the recurrence.

### Navigation behavior

Refactor menu results into explicit Select, Back, and Home outcomes, then have nested workflows propagate them. Esc returns one screen; the home shortcut returns to the root menu from any screen. Use Shift+Esc when the terminal/curses backend reports it distinctly. Because many Windows terminals report Shift+Esc as the same byte as Esc, provide and document a reliable fallback shortcut (proposed `H` for Home) rather than interpreting a lone Esc ambiguously. Preserve `q`/`b` only where their meaning is clear and consistent.

## Stages

1. **Shared logging module** — settle package name/API, create the reusable package and documentation, add module setup/dependency wiring, and test structured storage, Python logging integration, retention, and concurrency.
2. **Scheduler history migration and capture** — add stable schedule/task IDs; import retained text records safely; record structured task runs and schedule occurrences from all execution paths; preserve readable legacy logs and clear/prune behavior.
3. **Analytics and recurrence evaluation** — implement tested 7/30/365-day/lifetime aggregates, runtime statistics, expected occurrence generation for every supported timing type, on-time/late/missed classification, and per-day cell aggregation.
4. **Schedule-aware log explorer** — replace the flat picker with schedule/standalone/unmatched group navigation, schedule and task dashboards, compact activity grids, scrolling run lists, and per-run output view.
5. **Consistent Back/Home navigation** — implement one-level Esc and direct-to-home behavior, Shift+Esc where supported, and a documented fallback; cover nested workflows with key-sequence tests.
6. **Compatibility, docs, and validation** — verify old JSON/text log compatibility, retention/clear semantics, TUI behavior on Windows and Unix-like terminals where available, update module/repository handoffs and setup validation targets, and record exact validation results.

## Acceptance Criteria

1. Every task is shown under its current schedule or under Standalone Tasks; legacy logs that cannot be mapped are visible but never silently assigned.
2. Schedule recurrence and task membership are visible before opening logs.
3. Schedule/task dashboards show accurate 7/30/365-day counts, outcomes, and runtime aggregates from structured records, with historical-coverage limits visible.
4. Schedule punctuality distinguishes on-time, late, catch-up, and missed occurrences using the displayed tolerance and expected recurrence dates.
5. The yearly grid omits non-scheduled dates, uses a visible legend, and summarizes multiple daily runs deterministically.
6. Users can scroll the complete retained-metadata run list, select any run, and view that run's output when retained; expired output is clearly identified.
7. The shared logging package has no scheduler-specific data model dependency and is usable by another module through documented generic APIs.
8. Esc moves back exactly one view; Home shortcut returns to the root TUI menu; terminal limitations of Shift+Esc are handled with a reliable fallback.
9. Existing human-readable logs remain readable during the transition, and clear-all behavior explains its effect on structured history.
10. Tests cover migrations, filename collisions, retention, date boundaries, all recurrence types, missing/late/failing runs, heatmap aggregation, run selection, and nested navigation without touching live scheduled tasks.

## Risks and Decisions

- The current worktree contains uncommitted scheduler runner/order changes. Before implementation, reconcile their actual source and test state; do not rely on stale handoff claims or overwrite those edits.
- Existing text retention limits historical backfill. Complete historical statistics start only after structured capture is enabled.
- Legacy sanitized filenames can collide. Migration must report ambiguity and preserve source files rather than guess ownership.
- Runtime output may be large. One-year output retention needs size measurements and pruning tests; metadata should remain compact and queryable.
- Curses and Windows terminal support for Shift+Esc varies. The Home fallback is required even when Shift+Esc is available.
- Adding a shared module affects root setup ordering, module dependency installation, and validation manifests. The package must be installed before scheduler and must avoid a dependency cycle.
- Never register, start, or remove a live Windows scheduled task during default tests.
