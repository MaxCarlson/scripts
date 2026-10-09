# Scheduler Module Handoff

## Overview

The scheduler module (`scripts/modules/scheduler/`) provides scheduled task automation and script execution across PowerShell and standard terminal environments, with both a feature-complete CLI and an interactive arrow-key driven TUI.

## Active Work

Windows background runner setup, unattended elevation, and the setup gate are tracked in:

```text
docs/plans/20261008-2132_windows-runner-and-elevation/
```

The runner registers a per-user highest-privilege logon task. Registration is an explicit CLI/TUI action and does not modify the live PC during tests.

Stages 1 through 3 implement the Windows runner, setup gate, and setup-output capture fix. Stage 4 adds a delayed TUI runner test with a visible console; see the active plan `STATUS.md` for validation state. Stage 4 uses a file-backed one-shot request and does not change regular task schedules.

## Documentation Index

- `README.md` — User and developer guide
- `plans/` — Planning artifacts

## Approved Log Explorer Work

The schedule-aware log explorer, durable run statistics, reusable shared logging module, and consistent Esc/Home navigation are planned in the repository-level proposal:

```text
docs/plans/20261009-0941_scheduler-log-explorer-and-shared-logging/
```

The user approved implementation. The shared `script_logging` package, durable scheduler history, statistics, schedule-aware log browser, and TUI Back/Home behavior are implemented in the current uncommitted worktree. See the repository-level plan status for validation and limits.
