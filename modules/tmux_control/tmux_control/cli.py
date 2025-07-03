import os
import subprocess
import sys
import time
from pathlib import Path
from typing import List

import psutil
import typer

# --- Configuration ---
APP_NAME = "tmux-control"
# Use a runtime directory for pid files and command sockets
RUNTIME_DIR = Path(os.environ.get("TMPDIR", "/tmp")) / APP_NAME
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
        # Check if a process with the PID exists and has the same name
        proc = psutil.Process(pid)
        # Check if the process is running the daemon script
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
    
    # Use Popen to launch the daemon in the background
    process = subprocess.Popen(
        [sys.executable, str(DAEMON_SCRIPT_PATH)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True, # Detach from the current terminal
    )
    
    PID_FILE.write_text(str(process.pid))
    typer.echo(f"Daemon started with PID: {process.pid}")
    time.sleep(0.5) # Give it a moment to start up
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
        proc.terminate() # Send SIGTERM
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
    
    # This is where we would communicate with the daemon.
    # For now, we'll just print a message.
    # In the future, this will write a command file or use a socket.
    typer.echo(f"Requesting daemon to run and monitor command: {' '.join(command)}")
    # TODO: Implement communication with the daemon
    

if __name__ == "__main__":
    app()
