import datetime
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import List

import libtmux
import psutil
import typer

# --- Configuration ---
APP_NAME = "tmux-control"
RUNTIME_DIR = Path(os.environ.get("TMPDIR", "/tmp")) / APP_NAME
JOBS_DIR = RUNTIME_DIR / "jobs"
SCHEDULED_DIR = RUNTIME_DIR / "scheduled"
PID_FILE = RUNTIME_DIR / "daemon.pid"
DAEMON_SCRIPT_PATH = Path(__file__).parent / "daemon.py"
DAEMON_LOG_FILE = RUNTIME_DIR / "daemon.log"

# --- Main Typer Application ---
app = typer.Typer(help="A utility to control and automate tmux sessions.")


# --- Helper Function for Time Parsing ---
def parse_time_string(time_str: str) -> int:
    if time_str == "infinite":
        return 0
    match = re.match(r"(\d+)([smh])$", time_str.lower())
    if not match:
        raise ValueError(f"Invalid time format: '{time_str}'. Use 's', 'm', 'h', or 'infinite'.")
    value, unit = match.groups()
    value = int(value)
    if unit == 's': return value
    if unit == 'm': return value * 60
    if unit == 'h': return value * 3600
    return 0

# --- Daemon Management Subcommand ---
daemon_app = typer.Typer(name="daemon", help="Manage the tmux-control background daemon.")

def is_daemon_running() -> bool:
    if not PID_FILE.exists(): return False
    try:
        pid = int(PID_FILE.read_text())
        proc = psutil.Process(pid)
        return DAEMON_SCRIPT_PATH.name in " ".join(proc.cmdline())
    except (psutil.NoSuchProcess, ValueError, FileNotFoundError):
        return False

@daemon_app.command("start")
def daemon_start():
    """Start the background daemon."""
    if is_daemon_running():
        typer.echo("Daemon is already running."); raise typer.Exit()
    
    RUNTIME_DIR.mkdir(exist_ok=True)
    JOBS_DIR.mkdir(exist_ok=True)
    SCHEDULED_DIR.mkdir(exist_ok=True)
    
    if DAEMON_LOG_FILE.exists(): DAEMON_LOG_FILE.unlink()
    
    daemon_stdout_log = open(RUNTIME_DIR / "daemon.stdout.log", "w")
    daemon_stderr_log = open(RUNTIME_DIR / "daemon.stderr.log", "w")
    
    process = subprocess.Popen(
        [sys.executable, str(DAEMON_SCRIPT_PATH)],
        stdout=daemon_stdout_log, stderr=daemon_stderr_log,
        start_new_session=True, env=os.environ,
    )
    
    PID_FILE.write_text(str(process.pid))
    typer.echo(f"Daemon started with PID: {process.pid}")
    time.sleep(1)
    if not is_daemon_running():
        typer.secho("Daemon failed to start.", fg=typer.colors.RED)
        typer.secho(f"Please check the error log: {DAEMON_LOG_FILE}", fg=typer.colors.YELLOW)
        raise typer.Exit(code=1)

@daemon_app.command("stop")
def daemon_stop():
    """Stop the background daemon."""
    if not is_daemon_running():
        typer.echo("Daemon is not running."); raise typer.Exit()
    try:
        pid = int(PID_FILE.read_text())
        proc = psutil.Process(pid)
        proc.terminate()
        typer.echo(f"Sent stop signal to daemon (PID: {pid}).")
        PID_FILE.unlink()
    except (psutil.NoSuchProcess, ValueError, FileNotFoundError):
        typer.secho("Could not stop daemon. PID file might be stale.", fg=typer.colors.YELLOW)
        PID_FILE.unlink(missing_ok=True)

@daemon_app.command("status")
def daemon_status():
    """Check the status of the background daemon."""
    if is_daemon_running():
        pid = int(PID_FILE.read_text())
        typer.echo(f"Daemon is running with PID: {pid}")
    else:
        typer.echo("Daemon is not running.")

app.add_typer(daemon_app)


# --- Main Application Commands ---

@app.command()
def watch(
    ctx: typer.Context,
    on_success: str = typer.Option(..., "--on-success", "-s", help="Banner message on success (exit code 0)."),
    on_fail: str = typer.Option(..., "--on-fail", "-f", help="Banner message on failure (non-zero exit code)."),
    duration: str = typer.Option("10m", "--duration", "-d", help="How long the banner lasts (e.g., '30s', '10m', 'infinite')."),
):
    """
    Watch the next command in this pane and display a banner on completion.
    """
    if not is_daemon_running():
        typer.secho("Daemon is not running...", fg=typer.colors.RED); raise typer.Exit(code=1)
    if "TMUX_PANE" not in os.environ:
        typer.secho("Error: This command must be run from within a tmux pane.", fg=typer.colors.RED); raise typer.Exit(code=1)

    try:
        duration_seconds = parse_time_string(duration)
    except ValueError as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED); raise typer.Exit(code=1)

    job_id = uuid.uuid4().hex[:8]
    job_data = {
        "job_id": job_id, "job_type": "watch_command",
        "on_success": on_success, "on_fail": on_fail, "duration": duration_seconds,
    }

    # This command will be run by the shell just before the next prompt is displayed.
    # It captures the exit status ($?) of the last command and sends a job to our daemon.
    # It then unsets itself to ensure it only runs once.
    job_json_str_escaped = json.dumps(job_data).replace("'", "'\\''")
    job_file_path = JOBS_DIR / f"{job_id}.json"
    
    # This hook captures the exit status, injects it into our JSON, writes the job file,
    # and then unsets itself. It's designed to be safe for both bash and zsh.
    hook_command = (
        "local exit_code=$?;"
        f"local job_json='{job_json_str_escaped}';"
        "local final_json=$(echo \"$job_json\" | sed \"s/}}$/, \\\"exit_code\\\": $exit_code}}/\");"
        "echo \"$final_json\" > " f"'{job_file_path.as_posix()}';"
        "unset PROMPT_COMMAND;"
        "precmd_functions=(${precmd_functions#tmux_control_hook});"
        "unset -f tmux_control_hook;"
    )
    
    # We use libtmux here to set the environment variable for the next command
    try:
        server = libtmux.Server()
        pane = server.find_where({"pane_id": os.environ["TMUX_PANE"]})
        if pane:
            # For Zsh, we use the precmd_functions array. For Bash, PROMPT_COMMAND.
            # This combined command works for both.
            full_command_to_send = f"tmux_control_hook() {{ {hook_command} }}; precmd_functions+=(tmux_control_hook); PROMPT_COMMAND=tmux_control_hook"
            pane.send_keys(full_command_to_send, enter=True)
            typer.echo(f"✅ Watching pane {pane.pane_id}. Run your command now.")
        else:
            typer.secho("Error: Could not find current tmux pane.", fg=typer.colors.RED)
    except Exception as e:
        typer.secho(f"An error occurred: {e}", fg=typer.colors.RED)


# --- Reminder Subcommand Group ---
remind_app = typer.Typer(name="remind", help="Manage reminders.")

@remind_app.command("set")
def remind_set(
    message: str = typer.Argument(..., help="The reminder message."),
    in_time: str = typer.Option("5m", "--in", "-i", help="When to send the first reminder (e.g., '10s', '5m', '1h')."),
    interval: str = typer.Option(None, "--interval", help="Interval for recurring reminders (e.g., '5m')."),
    repeat: int = typer.Option(0, "--repeat", "-r", help="Number of times to repeat after the first reminder."),
    duration: str = typer.Option("10m", "--duration", "-d", help="How long the banner lasts (e.g., '30s', '10m', 'infinite')."),
):
    """Set a new reminder."""
    if not is_daemon_running():
        typer.secho("Daemon is not running...", fg=typer.colors.RED); raise typer.Exit(code=1)

    try:
        delay_seconds = parse_time_string(in_time)
        interval_seconds = parse_time_string(interval) if interval else 0
        duration_seconds = parse_time_string(duration)
    except ValueError as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED); raise typer.Exit(code=1)

    job_id = uuid.uuid4().hex[:8]
    job_file_path = SCHEDULED_DIR / f"{job_id}.json"
    remind_at = time.time() + delay_seconds
    
    job_data = {
        "job_id": job_id, "job_type": "reminder", "message": message,
        "remind_at": remind_at, "interval": interval_seconds, "repeat": repeat,
        "duration": duration_seconds,
        "metadata": {"request_time": datetime.datetime.utcnow().isoformat()},
    }
    with open(job_file_path, "w") as f:
        json.dump(job_data, f, indent=2)
    
    typer.echo(f"✅ Reminder '{job_id}' scheduled.")

@remind_app.command("list")
def remind_list():
    """List all pending reminders."""
    if not SCHEDULED_DIR.exists() or not any(SCHEDULED_DIR.iterdir()):
        typer.echo("No pending reminders."); return

    from rich.console import Console
    from rich.table import Table

    table = Table("Job ID", "Next Run", "Interval", "Repeats Left", "Message")
    for job_file in sorted(SCHEDULED_DIR.glob("*.json")):
        with open(job_file, "r") as f:
            data = json.load(f)
        next_run = datetime.datetime.fromtimestamp(data['remind_at']).strftime('%H:%M:%S')
        interval = f"{data['interval']}s" if data['interval'] > 0 else "-"
        repeats = str(data['repeat']) if data['interval'] > 0 else "-"
        table.add_row(data['job_id'], next_run, interval, repeats, data['message'])
    
    Console().print(table)

@remind_app.command("cancel")
def remind_cancel(job_id_prefix: str = typer.Argument(..., help="The ID (or prefix) of the reminder to cancel.")):
    """Cancel (delete) a pending reminder."""
    matches = list(SCHEDULED_DIR.glob(f"{job_id_prefix}*.json"))
    if not matches:
        typer.secho(f"Error: Reminder with ID starting with '{job_id_prefix}' not found.", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    if len(matches) > 1:
        typer.secho(f"Error: Multiple reminders found. Please be more specific.", fg=typer.colors.RED)
        for match in matches: typer.echo(f" - {match.stem}")
        raise typer.Exit(code=1)
    
    job_file = matches[0]
    job_file.unlink()
    typer.echo(f"✅ Reminder '{job_file.stem}' cancelled.")

@remind_app.command("done")
def remind_done(job_id_prefix: str = typer.Argument(..., help="The ID (or prefix) of the reminder to mark as done.")):
    """Mark an active reminder as done, clearing its banner and canceling it."""
    if not is_daemon_running():
        typer.secho("Daemon is not running...", fg=typer.colors.RED); raise typer.Exit(code=1)

    job_id = uuid.uuid4().hex[:8]
    job_file_path = JOBS_DIR / f"{job_id}.json"
    job_data = {"job_id": job_id, "job_type": "mark_done", "target_job_id_prefix": job_id_prefix}
    
    with open(job_file_path, "w") as f:
        json.dump(job_data, f)
    
    typer.echo(f"✅ Requesting daemon to mark reminder starting with '{job_id_prefix}' as done.")

app.add_typer(remind_app)

if __name__ == "__main__":
    app()
