<!-- version: 0.1.0 -->
# Scheduler Module

A robust Python task scheduling and command execution module featuring both a comprehensive CLI and an interactive Terminal User Interface (TUI).

## Features

- **CLI & TUI Parity**: Every action (create, edit, delete, attach, run, inspect) is available via CLI arguments and an arrow-key-driven curses TUI.
- **Persistent JSON Storage**: Schedules, tasks, and shell executable paths are stored directly in `scheduler_data.json` within the module directory.
- **Flexible Timing**: Daily, hourly/interval, weekly, specific days, 1st of month at midnight, and cron expressions.
- **Missed Run Catch-Up**: Automatically triggers missed runs when the scheduler wakes up or runs a check.
- **Safety**: Warns when deleting a schedule that would orphan attached tasks.
- **Multi-Environment Execution**: Run scripts in PowerShell Core (`pwsh`), Windows PowerShell (`powershell`), or the default terminal (`bash`, `sh`, `cmd`), with optional admin/elevated execution.
- **Script Composing**: Direct terminal entry or shell-out to `$EDITOR` (e.g. Neovim, Nano, Vim).
- **Strict Logging**: Central system log formatted strictly as `[date-time] | [LOGITEM_TYPE]: "message"`.
- **Task Output Retention**: Dedicated task logs folder keeping only the N most recent runs per task to prevent bloat.
- **Notification Hooks**: Cross-platform desktop notifications on schedule triggers, task completions, and failures.

## Quick Start

### Interactive TUI

```bash
scheduler tui
# or simply
sched
```

### CLI Usage

```bash
# Create a schedule
scheduler schedule create -n "NightlyBackup" -t daily -a "02:00" -u

# Create a task linked to that schedule
scheduler task create -n "BackupDb" -s "NightlyBackup" -e pwsh -c "Backup-SqlDatabase -ServerInstance localhost"

# Run a task immediately
scheduler run -t "BackupDb"

# Run a single daemon tick or start the scheduler daemon
scheduler daemon -o
scheduler daemon -i 30

# View central system logs
scheduler logs system -n 50
```
