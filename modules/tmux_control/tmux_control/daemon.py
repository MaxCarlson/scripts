import json
import os
import shlex
import sys
import time
import traceback
from pathlib import Path
from itertools import cycle

sys.path.append(str(Path(__file__).parent.parent))

APP_NAME = "tmux-control"
RUNTIME_DIR = Path(os.environ.get("TMPDIR", "/tmp")) / APP_NAME
JOBS_DIR = RUNTIME_DIR / "jobs"
SCHEDULED_DIR = RUNTIME_DIR / "scheduled"
LOG_FILE = RUNTIME_DIR / "daemon.log"

import libtmux

# --- Global State for the Daemon ---
# This list holds all currently active banners.
active_banners = []
banner_cycler = None
last_banner_update_time = 0

def log(message: str):
    with open(LOG_FILE, "a") as f:
        f.write(f"{time.ctime()}: {message}\n")

# --- Banner Management ---

def trigger_banner(message: str, color: str, duration: int):
    """Adds a new banner to the active list and resets the cycler."""
    global banner_cycler, active_banners
    expiry_time = (time.time() + duration) if duration > 0 else float('inf')
    banner = {"message": message, "color": color, "expiry_time": expiry_time}
    active_banners.append(banner)
    # FIX: Reset the cycler with the new, updated list of banners
    banner_cycler = cycle(active_banners)
    log(f"Triggered banner: '{message}' for {duration}s. Total active: {len(active_banners)}")

def update_banner_display(server: libtmux.Server):
    """The core function to manage and cycle through active banners."""
    global active_banners, banner_cycler, last_banner_update_time

    # 1. Filter out expired banners
    now = time.time()
    initial_banner_count = len(active_banners)
    active_banners = [b for b in active_banners if now < b["expiry_time"]]

    # 2. If the list of banners has changed (e.g., one expired), reset the cycler
    if len(active_banners) != initial_banner_count:
        banner_cycler = cycle(active_banners) if active_banners else None
        log(f"Banners expired. Remaining active: {len(active_banners)}")

    # 3. If no banners are active, clear the display and reset
    if not active_banners:
        if banner_cycler is not None:
            clear_global_banner(server)
            banner_cycler = None # Mark as cleared
        return

    # 4. If banners are active, update the display every 5 seconds
    if now - last_banner_update_time > 5:
        if not banner_cycler: # Should not happen if active_banners is not empty, but safe
             banner_cycler = cycle(active_banners)

        current_banner = next(banner_cycler)
        banner_format = f"#[align=centre]#[fg={current_banner['color']},bold]{current_banner['message']}#[default]"
        for pane in server.panes:
            try:
                server.cmd('set-option', '-t', pane.pane_id, 'pane-border-status', 'top')
                server.cmd('set-option', '-t', pane.pane_id, 'pane-border-format', banner_format)
            except Exception as e:
                log(f"Error setting banner for pane {pane.pane_id}: {e}")
        last_banner_update_time = now

def clear_global_banner(server: libtmux.Server):
    for pane in server.panes:
        try:
            server.cmd('set-option', '-t', pane.pane_id, 'pane-border-status', 'off')
        except Exception as e:
            log(f"Error clearing banner for pane {pane.pane_id}: {e}")

# --- Job Handlers ---

def handle_watch_command_job(server: libtmux.Server, job_data: dict):
    """Handles a job created by the 'watch' command's PROMPT_COMMAND hook."""
    exit_code = job_data.get("exit_code", -1)
    if exit_code == 0:
        trigger_banner(job_data['on_success'], "green", job_data['duration'])
    else:
        trigger_banner(job_data['on_fail'], "red", job_data['duration'])

def handle_mark_done_job(server: libtmux.Server, job_data: dict):
    global active_banners, banner_cycler
    prefix = job_data["target_job_id_prefix"]
    log(f"[{job_data['job_id']}] Marking reminders starting with '{prefix}' as done.")
    
    active_banners = []
    banner_cycler = None
    clear_global_banner(server)
    
    for job_file in SCHEDULED_DIR.glob(f"{prefix}*.json"):
        job_file.unlink()
        log(f"Deleted scheduled job file: {job_file.name}")

def check_for_new_jobs(server: libtmux.Server):
    for job_file in JOBS_DIR.glob("*.json"):
        try:
            with open(job_file, "r") as f:
                job_data = json.load(f)
            log(f"[{job_data['job_id']}] Picked up new job: {job_data.get('job_type')}")
            
            if job_data.get("job_type") == "watch_command":
                handle_watch_command_job(server, job_data)
            elif job_data.get("job_type") == "mark_done":
                handle_mark_done_job(server, job_data)

            job_file.unlink()
        except Exception as e:
            log(f"Error processing job file {job_file.name}: {e}. Deleting.")
            job_file.unlink()

def check_for_scheduled_jobs(server: libtmux.Server):
    current_time = time.time()
    for job_file in SCHEDULED_DIR.glob("*.json"):
        try:
            with open(job_file, "r") as f:
                data = json.load(f)
            
            if current_time >= data.get("remind_at", float('inf')):
                log(f"[{data['job_id']}] Triggering reminder: {data['message']}")
                trigger_banner(f"⏰ {data['message']}", "yellow", data['duration'])
                
                if data.get("interval", 0) > 0 and data.get("repeat", 0) > 0:
                    data["repeat"] -= 1
                    data["remind_at"] = current_time + data["interval"]
                    with open(job_file, "w") as f:
                        json.dump(data, f, indent=2)
                    log(f"[{data['job_id']}] Rescheduled. {data['repeat']} repeats left.")
                else:
                    job_file.unlink()
                    log(f"[{data['job_id']}] Reminder finished.")
        except Exception as e:
            log(f"Error processing scheduled file {job_file.name}: {e}. Deleting.")
            job_file.unlink()

def main():
    try:
        log("Daemon process started.")
        server = libtmux.Server()
        log(f"Successfully connected to tmux server. Panes found: {len(server.panes)}")
        while True:
            check_for_new_jobs(server)
            check_for_scheduled_jobs(server)
            update_banner_display(server)
            time.sleep(1)
    except Exception:
        log("--- DAEMON CRASHED ---")
        log(traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    main()
