# Runmux Multi-Attach, Input Lock, Status UI, and History

This is the parent implementation roadmap for four ordered runmux cycles.

## Goals

- Fix the supervisor-port race during immediate run/view/interact attachment.
- Support concurrent view and interact clients.
- Serialize program input through a supervisor-managed FIFO ownership lock.
- Track current and lifetime attachment counts.
- Reserve configurable top and bottom status rows for runmux.
- Replace the current history store with retained, searchable JSONL history.

## Input Ownership

- The first interact client receives the initial lock.
- Other clients request the lock with lowercase `l` while runmux owns input.
- Requests are FIFO and idempotent.
- A holder receives a configurable minimum tenure, default 10 seconds.
- With a queued request, transfer occurs after the minimum tenure, 250 ms of
  holder input inactivity, and completion of previously accepted PTY writes.
- Holder disconnect transfers immediately to the next live requester.
- Unlocked input is rejected rather than buffered or replayed.
- Ctrl-X commands remain local and available in every attached client.

## Attachment UI

- Reserve row 1 for connection/runtime status.
- Reserve the final row for warnings, controls, and input ownership.
- The managed PTY receives the remaining rows.
- Top status degrades from full labels and runtime to compact colored `I/V/T`
  counts when the terminal is narrow.
- Bottom status shows program/runmux/view input ownership and FIFO position.
- New connection warnings display for three seconds.
- `Ctrl-X M` toggles persistent runmux-input mode.
- `Ctrl-X T` and `Ctrl-X B` toggle the status rows for one attachment.
- View mode accepts runmux hotkeys directly.

## Settings

Add equivalent `runmux config` and `runmux settings` commands. Persist validated
settings in `modules/runmux/.runmux/config.json`, including:

- History retention, default 10,000.
- Startup, heartbeat, lease, refresh, and warning timing.
- Default top/bottom status visibility.
- Input-lock minimum tenure and idle-transfer interval.

## History

- Store one managed run per line in `history.jsonl`.
- Store saved commands separately in `saved_commands.json`.
- Migrate the existing `commands.json` idempotently and preserve a backup.
- Record command, argv, cwd, timing, status, exit code, relationships, and
  lifetime attachment statistics.
- Support prefix and contains filtering, recent and frequency ordering,
  incremental interactive search, structured JSON, and aggregate summaries.

## Execution Discipline

For every numbered cycle:

1. Mark its plan in progress.
2. Implement only that cycle.
3. Run the previously passing suite.
4. Add focused tests and run old and new tests together.
5. Run Ruff, Black check, compileall, and coverage.
6. Review the diff and update plan status.
7. Stage and commit the verified cycle.
8. Refine and begin the next cycle plan.
