import datetime
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import List

import psutil
import typer

# --- Configuration ---
APP_NAME = "tmux-control"
RUNTIME_DIR = Path(os.environ.get("TMPDIR", "/tmp")) / APP_NAME
JOBS_DIR = RUNTIME_DIR / "jobs"
DONE_DIR = RUNTIME_DIR / "done"
PID_FILE = RUNTIME_DIR / "daemon.pid"
DAEMON_SCRIPT_PATH = Path(__file__).parent / "daemon.py"

app = typer.Typer(help="A utility to control and automate tmux sessions.")
daemon_app = typer.Typer(name="daemon", help="Manage the tmux-control background daemon.")
app.add_typer(daemon_app)


# --- Daemon Management Commands ---

def is_daemon_running() -> bool:
    """Check if the daemon process is currently running."""
    if not PID_FILE.exists():
        return False
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
        typer.echo("Daemon is already running.")
        raise typer.Exit()

    RUNTIME_DIR.mkdir(exist_ok=True)
    JOBS_DIR.mkdir(exist_ok=True)
    DONE_DIR.mkdir(exist_ok=True)

    # THE FIX IS HERE: We pass `env=os.environ` to ensure the daemon
    # inherits the necessary TMUX environment variables.
    process = subprocess.Popen(
        [sys.executable, str(DAEMON_SCRIPT_PATH)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=os.environ,  # <-- THIS IS THE FIX
    )

    PID_FILE.write_text(str(process.pid))
    typer.echo(f"Daemon started with PID: {process.pid}")
    time.sleep(0.5)
    if not is_daemon_running():
        typer.secho("Daemon failed to start.", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@daemon_app.command("stop")
def daemon_stop():
    """Stop the background daemon."""
    if not is_daemon_running():
        typer.echo("Daemon is not running.")
        raise typer.Exit()

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


# --- Main Application Commands ---

@app.command("run")
def run_command(
    command: List[str] = typer.Argument(..., help="The command to run and monitor."),
):
    """
    Run a command in a new tmux pane and set a server-wide banner on completion.
    """
    if not is_daemon_running():
        typer.secho("Daemon is not running. Please start it with 'tmux-control daemon start'", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    job_id = str(uuid.uuid4())
    job_file_path = JOBS_DIR / f"{job_id}.json"

    job_data = {
        "job_id": job_id,
        "job_type": "run_command",
        "command": command,
        "metadata": {
            "request_time": datetime.datetime.utcnow().isoformat(),
        },
    }

    with open(job_file_path, "w") as f:
        json.dump(job_data, f)

    typer.echo(f"✅ Job '{job_id}' submitted to daemon.")
    typer.echo(f"Command: {' '.join(command)}")


if __name__ == "__main__":
    app()
