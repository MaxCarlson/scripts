import json
import os
import shlex
import sys
import time
from pathlib import Path

import libtmux

# This ensures the daemon can find its own configuration if run directly
sys.path.append(str(Path(__file__).parent.parent))

# --- Configuration ---
APP_NAME = "tmux-control"
RUNTIME_DIR = Path(os.environ.get("TMPDIR", "/tmp")) / APP_NAME
JOBS_DIR = RUNTIME_DIR / "jobs"
DONE_DIR = RUNTIME_DIR / "done"


def set_global_banner(server: libtmux.Server, message: str, color: str = "cyan"):
    """Sets a banner on all panes on the server."""
    banner_format = f"#[align=centre]#[fg={color},bold]{message}#[default]"
    for pane in server.panes:
        pane.set_option("pane-border-status", "top")
        pane.set_option("pane-border-format", banner_format)


def handle_run_command_job(server: libtmux.Server, job_data: dict):
    """Handles the logic for running a command and setting up monitoring."""
    job_id = job_data["job_id"]
    user_command = " ".join(shlex.quote(arg) for arg in job_data["command"])
    done_file_path = DONE_DIR / f"{job_id}.json"

    # This is the wrapper script that tmux will execute.
    # It runs the user's command, captures the exit code, and reports back.
    wrapper_command = f"""
    clear
    echo "--- Running Job: {job_id} ---"
    echo "--- Command: {user_command} ---"
    echo ""

    # Execute the user's command
    {user_command}

    # Capture the exit code
    exit_code=$?

    # Create the 'done' file with the result
    echo '{{"job_id": "{job_id}", "exit_code": '"$exit_code"'}}' > "{done_file_path}"

    echo ""
    echo "--- Job finished with exit code: $exit_code ---"
    echo "--- This pane will close in 30 seconds. ---"
    sleep 30
    """

    # Create a new window to run the job, ensuring it doesn't attach to our session
    window_name = f"job-{job_id[:8]}"
    window = server.new_window(
        attach=False,
        window_name=window_name,
        window_shell=wrapper_command,
    )
    print(f"[{job_id}] Created window '{window.name}' to run command.")


def check_for_new_jobs(server: libtmux.Server):
    """Scans the jobs directory and processes any new jobs."""
    for job_file in JOBS_DIR.glob("*.json"):
        try:
            with open(job_file, "r") as f:
                job_data = json.load(f)
            
            print(f"[{job_data['job_id']}] Picked up new job.")
            if job_data.get("job_type") == "run_command":
                handle_run_command_job(server, job_data)
            
            # Job has been processed, remove the file
            job_file.unlink()

        except (json.JSONDecodeError, KeyError) as e:
            print(f"Error processing job file {job_file.name}: {e}. Deleting.")
            job_file.unlink()


def check_for_done_jobs(server: libtmux.Server):
    """Scans the done directory and processes any completed jobs."""
    for done_file in DONE_DIR.glob("*.json"):
        try:
            with open(done_file, "r") as f:
                done_data = json.load(f)
            
            job_id = done_data["job_id"]
            exit_code = done_data["exit_code"]
            print(f"[{job_id}] Job completed with exit code {exit_code}.")

            if exit_code == 0:
                message = f"✅ Job '{job_id[:8]}' Completed Successfully"
                set_global_banner(server, message, color="green")
            else:
                message = f"❌ Job '{job_id[:8]}' Failed (Code: {exit_code})"
                set_global_banner(server, message, color="red")
            
            # Cleanup the done file
            done_file.unlink()

        except (json.JSONDecodeError, KeyError) as e:
            print(f"Error processing done file {done_file.name}: {e}. Deleting.")
            done_file.unlink()


def main():
    """The main loop for the daemon process."""
    print("Daemon started. Monitoring for tasks...")
    server = libtmux.Server()
    
    try:
        while True:
            check_for_new_jobs(server)
            check_for_done_jobs(server)
            time.sleep(1) # Poll every second
    except KeyboardInterrupt:
        print("Daemon shutting down.")
    except Exception as e:
        # Basic error logging for the daemon itself
        with open(RUNTIME_DIR / "daemon.log", "a") as f:
            f.write(f"{time.ctime()}: Daemon crashed with error: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
