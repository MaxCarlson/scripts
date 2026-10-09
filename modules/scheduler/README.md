<!-- version: 0.6.0 -->
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
- **Run History**: SQLite run metadata persists across text-log rotation. The TUI groups logs by schedule, standalone task, and unmatched legacy file, with per-run output, statistics, timing, and a one-year activity grid. Full output expires after 365 days by default while run metadata remains.
- **Notification Hooks**: Cross-platform desktop notifications on schedule triggers, task completions, and failures.
- **Windows Background Runner**: One-time setup installs a limited-privilege schedule daemon and a separate highest-privilege worker for tasks marked Admin.
- **Sequential Schedule Tasks**: Tasks attached to a schedule run sequentially in attachment order.
- **Delayed Runner Test**: From the TUI, queue an Admin task through the elevated worker for about ten seconds later; the TUI returns immediately and the task opens in a visible console window.

## First-Time Windows Setup

The Windows logon runners must be installed once before normal scheduler commands can manage or run tasks. Until both are ready, the CLI prints a red setup warning and the TUI only offers setup. Installation asks for administrator approval once and registers a limited-privilege daemon plus an elevated worker for the current user. Scheduled tasks only run elevated when their Admin option is enabled; other scheduled tasks run in the limited daemon.

Run this from a terminal and approve the one-time UAC prompt:

```bash
scheduler setup windows
```

The task begins at the next user logon. Check it with `scheduler setup windows status`; start it immediately with `scheduler setup windows start -y` after considering any due catch-up tasks. The older `scheduler setup windows-runner` spelling remains supported. Linux setup is not implemented yet.

## Logs and history in the TUI

Choose **View Logs** to browse system events, schedules, standalone tasks, and unmatched legacy files. A schedule page shows its current recurrence, task summaries, run counts for the last 7/30/365 days, runtime bounds, and timing compared with scheduled occurrences. Choose a task for its own statistics and run list. Enter on a run opens only that run's output. Escape returns one screen; `H` returns to the main menu. Shift+Escape also works in terminals that report it distinctly.

The activity grid covers the last 365 days. Scheduled days with no recorded occurrence appear red; unscheduled days remain blank. Timing uses a configurable five-minute tolerance (`on_time_tolerance_seconds`). Expected days are estimates from the **current** recurrence and the date structured history began. Changing a schedule's timing or enabled state does not reconstruct its earlier recurrence. Old retained text logs are imported only when their filename identifies exactly one task. Colliding or orphaned filenames remain under **Unmatched legacy logs**.

The shared `script_logging` package stores compact run facts in `scheduler_history.sqlite3` beside `scheduler_data.json`. `output_retention_days` defaults to 365 and removes stdout/stderr after that age while retaining run facts. Clearing all logs in the TUI also removes this history and resets its coverage date. The existing text logs remain readable; their per-task retention is controlled separately by `log_retention_runs`.

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

# Install the Windows logon runner (requests UAC approval during setup)
scheduler setup windows
# Inspect it, or start it now (may trigger missed schedules)
scheduler setup windows status
scheduler setup windows start -y

# View central system logs
scheduler logs system -n 50
```

The Windows runners start at the next sign-in for the current user. The scheduler
daemon runs with limited privileges; its separate Admin worker runs with the account's
highest privileges and accepts only tasks marked Admin. Both use the same scheduler data file.
Starting them manually can immediately execute due or catch-up
tasks; the CLI requires `-y/--yes`, and the TUI asks for confirmation. The runner
uses an interactive user logon so user-scoped tools such as `winget` have the user's
profile and session. It will stop when that user signs out. Remove it with
`scheduler setup windows remove`.

The TUI exposes the same status, install/update, start, and remove actions under
**Configuration & Shell Paths → Windows background runner setup / status**.

From **Run Tasks / Schedules → Run Single Task**, choose **Schedule elevated runner test** to queue an Admin task for about ten seconds later. Both Windows runners must already be running; the task output opens in a separate visible console window while the TUI stays responsive. This tests the runner's elevated execution path. **Run immediately** remains a manual run and can request UAC when launched from a non-elevated TUI.
