# Scheduler Module Handoff

## Overview

The scheduler module (`scripts/modules/scheduler/`) provides scheduled task automation and script execution across PowerShell and standard terminal environments, with both a feature-complete CLI and an interactive arrow-key driven TUI.

## Active Work

The latest generic monitored-process rules and conditional task controls are tracked in:

```text
docs/plans/20261013-conditional-monitored-tasks/
```

The monitor engine, CLI/TUI controls, GPU counter example, per-rule event logs, and lifecycle statistics are implemented. The local Pearl miner rule is enabled. The probe was verified with 1,318 GPU Engine counter instances under the host user's non-admin interactive token; the earlier zero-counter result came from the low-integrity Codex sandbox. The registered daemon remains stopped (`Ready`), so the rule is saved but not currently polling. Earlier startup, run queue, and unattended Winget changes are tracked in `docs/plans/20261012-2002_startup-runner-console-and-import-fix/`.

The underlying per-user Windows runner setup, privilege separation, setup gate, and visible delayed-run test are documented in `docs/plans/20261008-2132_windows-runner-and-elevation/`. Registration is an explicit CLI/TUI action and automated tests do not modify the live PC. Newly registered runners use `pythonw.exe` when available; rerun `scheduler setup windows` to update existing Task Scheduler actions. The queue implementation now lives in `scheduler/request_queue.py` because the module's `run_requests` data directory can shadow a same-named Python import when the repository's `modules/` directory is on `PYTHONPATH`.

## Documentation Index

- `README.md` — User and developer guide
- `plans/` — Planning artifacts

## Approved Log Explorer Work

The schedule-aware log explorer, durable run statistics, reusable shared logging module, and consistent Esc/Home navigation are planned in the repository-level proposal:

```text
docs/plans/20261009-0941_scheduler-log-explorer-and-shared-logging/
```

The user approved implementation. The shared `script_logging` package, durable scheduler history, statistics, schedule-aware log browser, and TUI Back/Home behavior are implemented in the current uncommitted worktree. See the repository-level plan status for validation and limits.
