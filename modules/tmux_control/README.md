# tmux-control - Tmux Session Automation and Control

`tmux-control` is a Python utility designed to enhance your tmux workflow by providing a background daemon and a command-line interface (CLI) for automating session interactions. It enables features like displaying visual banners based on command completion status and scheduling reminders that appear directly within your tmux panes.

## Features

*   **Background Daemon**: A persistent daemon process (`daemon.py`) that manages scheduled tasks and banner displays, ensuring continuous operation even when the CLI is not active.
*   **Command-Line Interface (CLI)**: A `typer`-based CLI (`cli.py`) for easy interaction with the daemon, allowing users to set up and manage automation tasks.
*   **Command Watching**: Monitor the exit status of the next command executed in a tmux pane and display a customizable banner (success or failure) accordingly.
*   **Scheduled Reminders**: Set one-time or recurring reminders that pop up as banners in your tmux sessions.
*   **Dynamic Banners**: Banners are displayed directly in tmux pane borders, cycling through multiple active banners if necessary.
*   **Daemon Management**: CLI commands to start, stop, and check the status of the `tmux-control` daemon.
*   **Reminder Management**: List, cancel, and mark reminders as done via the CLI.

## Core Components

*   **`daemon.py`**: The heart of `tmux-control`. This script runs in the background, continuously checking for new jobs (from `watch` commands or `remind` schedules) and managing the display of banners in active tmux sessions using `libtmux`.
*   **`cli.py`**: The user-facing command-line interface built with `typer`. It provides subcommands for `daemon` management, `watch` command setup, and `remind`er scheduling and management.
*   **`libtmux`**: A Python library used by the daemon to programmatically interact with tmux server, sessions, windows, and panes.
*   **`psutil`**: Used for checking the status of the daemon process.

## Installation

(Assuming Python 3 and `pip` are installed)

```bash
# Navigate to the module directory
cd /data/data/com.termux/files/home/scripts/modules/tmux_control

# Install required libraries
pip install typer libtmux psutil
```

## Usage

### Daemon Management

First, start the background daemon:

```bash
python -m tmux_control.cli daemon start
```

Check its status:

```bash
python -m tmux_control.cli daemon status
```

Stop the daemon:

```bash
python -m tmux_control.cli daemon stop
```

### Watching Commands

To watch the next command you run in a tmux pane:

```bash
python -m tmux_control.cli watch --on-success "Command Succeeded!" --on-fail "Command Failed!" --duration 5s
# Now, run any command in the same tmux pane. A banner will appear on completion.
```

### Setting Reminders

Set a reminder to appear in 1 minute for 30 seconds:

```bash
python -m tmux_control.cli remind set "Take a break!" --in 1m --duration 30s
```

Set a recurring reminder every 5 minutes, repeating 3 times:

```bash
python -m tmux_control.cli remind set "Check logs" --in 1m --interval 5m --repeat 3
```

List all pending reminders:

```bash
python -m tmux_control.cli remind list
```

Cancel a reminder (use a prefix of the Job ID):

```bash
python -m tmux_control.cli remind cancel <job_id_prefix>
```

Mark an active reminder as done (clears its banner and cancels it):

```bash
python -m tmux_control.cli remind done <job_id_prefix>
```
