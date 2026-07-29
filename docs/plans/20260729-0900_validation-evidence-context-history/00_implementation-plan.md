# Validation Evidence, Context, and Progress History

## Objective

Create a low-maintenance repository-wide validation evidence system that pairs test execution results with project progress context while keeping the current state immediately identifiable and historical data bounded.

## Current Foundation

The repository-root dispatcher produces, per target:

```text
docs/test-results/<target>/
├── LATEST.txt
├── LATEST_CONTEXT.md
├── LATEST_PROGRESS.diff
└── history/
```

### `LATEST.txt`

The complete authoritative validation transcript for the latest run.

### `LATEST_CONTEXT.md`

A generated snapshot containing:

- target name,
- generation time,
- branch and commit,
- validation highlights,
- working-tree status,
- copies of the context files configured for the target.

The RRBackup target currently includes its active `STATUS.md` and `checklist.md`.

### `LATEST_PROGRESS.diff`

A generated unified diff between the previous and current context snapshots. It provides a compact account of what changed in project status between validation runs.

### `history/`

A bounded comparison history. Defaults:

- three prior artifacts of each type,
- no artifact older than 14 days.

## Design Principles

1. `LATEST.*` files are always authoritative.
2. Generated context reuses existing plan documents rather than requiring duplicate manual summaries.
3. Progress diffs are automatic and require no user-written release note.
4. Historical artifacts are comparison-only and bounded.
5. Validation evidence remains module-targeted even though the dispatcher is repository-wide.
6. The system must not delay feature work after the foundation is usable.
7. Live console output and tracked evidence may use different renderings when that improves usability without losing diagnostic information.

## Future Expansion

Potential later improvements:

- Pair report, context, and progress artifacts with an explicit run identifier.
- Generate a compact machine-readable metadata file such as `LATEST.json`.
- Extract structured checklist transitions: planned → in progress → implemented → verified.
- Record commits since the previous validation run.
- Record changed-file summaries and diff statistics without embedding full source diffs.
- Link each validation run to the active plan stage and acceptance criteria.
- Detect context files that changed after the validation run and mark evidence stale.
- Summarize test-count and coverage changes between runs.
- Produce a chronological repository development log from retained run pairs.
- Support non-PowerShell dispatchers with the same evidence contract.
- Add automated tests specifically for migration, retention, artifact pairing, and diff generation.

## Future Compact-Report Processing

Do not implement this during the active RRBackup checkpoint. Later, add a post-processing stage that reduces tracked report size while preserving equivalent diagnostic value.

The compact report should:

- omit successful dependency-installation chatter unless it contains warnings that need action,
- preserve each command, working directory, exact exit code, and section result,
- replace individual passing-test lines with aggregate passed/skipped/xfailed counts,
- retain complete failure, error, warning, traceback, and short-summary sections,
- retain failed-test identifiers and enough surrounding output to diagnose them,
- retain coverage totals and meaningful coverage regressions without necessarily retaining every per-file passing detail,
- retain slow-test outliers when they are operationally relevant,
- normalize tracked output to plain UTF-8 text without ANSI escape sequences,
- keep ANSI color in the live console during validation,
- make the compact report schema explicit in `AGENTS.md`, `CLAUDE.md`, and `docs/test-results/README.md` before it becomes authoritative,
- prove through tests that report reduction does not hide failures, skipped requirements, exit codes, commands, or environmental context.

A possible later artifact contract is:

```text
LATEST.txt       # compact authoritative handoff
LATEST_RAW.txt   # optional bounded raw transcript, or ignored local-only evidence
LATEST.json      # machine-readable section/test metadata
```

Whether `LATEST_RAW.txt` is tracked, retained only on failures, or kept locally should be decided after measuring report size and remote diagnostic usefulness. Do not discard the only complete failure evidence.

## Explicit Non-Goals for the Current RRBackup Stage

- Do not build a full project-management database.
- Do not store complete Git diffs alongside every test run.
- Do not preserve unlimited test history.
- Do not require manual progress summaries for every validation.
- Do not implement compact-report processing during RRBackup Checkpoint 2A.
- Do not expand this subsystem while RRBackup work is active unless it blocks validation or loses evidence.

## Acceptance Criteria for the Foundation

1. One root validation command creates all three `LATEST.*` artifacts.
2. The previous context snapshot is archived before the new snapshot is generated.
3. The current progress diff compares the previous and current context snapshots.
4. History retention removes excess and expired artifacts.
5. The latest artifacts are tracked and easy for a remote agent to locate.
6. A target without configured context files still produces a valid context snapshot.
7. Validation remains non-destructive by default.
