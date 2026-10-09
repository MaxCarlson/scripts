# Scheduler Module

A robust Python scheduling and task execution module providing:
- Command-line interface (`scheduler` and `sched`) matching `file-util` conventions.
- Interactive menu-driven Terminal User Interface (TUI) with arrow-key navigation.
- Persistent single-file JSON storage within the module directory.
- Shell execution across `pwsh`, `powershell`, and standard terminal with admin toggles.
- Windows Task Scheduler setup from both CLI and TUI, using a limited-privilege daemon and a separate highest-privilege worker for Admin tasks.
- Sequential execution of attached tasks in schedule assignment order.
- First-time setup gate in the CLI and TUI; Windows operations remain unavailable until the runner is registered correctly.
- TUI delayed runner tests that dispatch an Admin task through the active elevated daemon and open a visible console without blocking the TUI.
- $EDITOR integration for task scripts.
- Strict centralized system logging and pruned task output logging.
- Durable SQLite run history, schedule/task statistics, and a schedule-aware TUI log browser powered by the reusable `script_logging` module.
- Catch-up execution for missed schedules.
