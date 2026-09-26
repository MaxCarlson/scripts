# Scheduler Module Implementation Plan

## Objective

Create a robust, production-ready Python scheduling module at `scripts/modules/scheduler/` (accessible as `scheduler` and `sched` CLI commands and library) matching the architectural and subcommand patterns of `scripts/modules/file-util/` (`modules/file_utils`).

The module supports:
1. Persistent configuration and schedule data in a JSON file located directly in the scheduler module directory (`scripts/modules/scheduler/scheduler_data.json`).
2. Interactive menu-driven Terminal User Interface (TUI) navigable via arrow keys (Create Schedule, Edit/Delete Schedule, Create Task, Edit Task, View Logs, Configuration, Run Now).
3. Schedule management with versatile timing (daily, hourly/intervals, weekly, specific days, 1st of month at midnight, cron) and missed run catch-up execution.
4. Schedule deletion safety: attached tasks display and prominent warning before leaving tasks orphaned.
5. Task management with shell environment selection (`pwsh`, `powershell`, `terminal`), admin/non-admin elevation toggles, direct code composition or shell-out to `$EDITOR` (e.g. Neovim), and schedule linking.
6. Full CLI parity for every action available in the TUI.
7. Auto-detection and persistent configuration of underlying executables (`pwsh`, `powershell`, default terminal).
8. Strictly formatted central system log (`[date-time] | [LOGITEM_TYPE]: "message"`), dedicated task run logs with N-run bloat-prevention retention, and cross-platform notification hooks.

## Architectural Alignment with `file_utils`

- CLI structure: `argparse.ArgumentParser` with command and sub-command parsers.
- Flag consistency: short and long forms (`-X` and `--full-name`) for every user-facing argument.
- Logging and UI integration: using `standard_ui` and `termdash` conventions with ASCII/headless fallbacks.
- Cross-platform support: Linux, WSL2, Windows, and Termux.

## Acceptance Criteria

- All CLI subcommands operate with valid exit codes and support JSON/table/plain output formats.
- TUI navigation with arrow keys functions properly for all menus and includes $EDITOR integration and orphaned-task warnings.
- Schedule evaluation accurately handles intervals, daily times, specific days, 1st of month midnight, cron expressions, and catch-up triggers.
- Multi-line code execution runs in designated environments (`pwsh`, `powershell`, `terminal`) with admin toggles.
- Central system log strictly formats entries as `[date-time] | [LOGITEM_TYPE]: "message"`.
- Dedicated task logs folder maintains only the N most recent run outputs per task.
- Automated tests achieve high coverage across models, storage, timing, execution, logging, CLI, and TUI.
