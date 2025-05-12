#!/usr/bin/env python3
import argparse
import datetime
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

# External dependencies: rich, psutil, filelock, readchar
try:
    from rich.console import Console
    from rich.table import Table
    from rich.live import Live
    from rich.panel import Panel
    from rich import box
    import psutil
    import filelock
    # Only import readchar if not on Windows for status input, or handle differently
    if sys.platform != "win32":
        import readchar
    else:
        # On Windows, readchar might have issues or require msvcrt
        # For simplicity in status, we might rely only on Ctrl+C
        # Or you could add `import msvcrt` here and use it in handle_status
        pass

except ImportError as e:
    print(f"Error: Missing required package(s): {e.name}", file=sys.stderr)
    # Provide more specific instructions based on the missing package
    install_cmd = f"pip install {e.name}"
    if e.name == "readchar" and sys.platform == "win32":
         install_cmd = "pip install readchar  # (Note: may have limited functionality on Windows cmd/powershell)"
    print(f"Please install it using: {install_cmd}", file=sys.stderr)
    sys.exit(1)

console = Console()

# --- Configuration ---
STATE_FILENAME = ".batch_runner_state.json"
STATE_LOCK_FILENAME = ".batch_runner_state.lock"
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

# --- State Management ---

def get_state_paths(batch_file_path: Path) -> (Path, Path):
    """Gets the paths for the state file and lock file based on the batch file location."""
    # Ensure the input path is absolute for consistency
    abs_batch_path = batch_file_path.resolve()
    state_dir = abs_batch_path.parent
    state_path = state_dir / STATE_FILENAME
    lock_path = state_dir / STATE_LOCK_FILENAME
    return state_path, lock_path

def load_state(state_path: Path, lock: filelock.FileLock) -> Dict[str, Any]:
    """Loads the state from the JSON file, handling errors."""
    acquired = lock.acquire(timeout=0.1) # Short non-blocking attempt first
    if not acquired:
        # If couldn't get lock quickly, wait a bit longer
        try:
            lock.acquire(timeout=2) # Wait up to 2 seconds
            acquired = True
        except filelock.Timeout:
            console.print(f"[yellow]Warning:[/yellow] Could not acquire lock on '{lock.lock_file}' quickly. Reading state might be slightly delayed or stale.", file=sys.stderr)
            # Proceed without lock for read-only access, but it's risky if another process writes
            # A better approach might be to raise an error or return a specific signal

    try: # Ensure lock is released even if reading fails
        if not state_path.exists():
            return {"batches": {}}
        try:
            with open(state_path, 'r', encoding='utf-8') as f:
                state_data = json.load(f)
                # Basic validation
                if not isinstance(state_data, dict) or "batches" not in state_data or not isinstance(state_data["batches"], dict):
                    console.print(f"[yellow]Warning:[/yellow] State file '{state_path}' has invalid format. Initializing new state.", file=sys.stderr)
                    return {"batches": {}}
                # Further validation: Ensure batch keys and process lists are reasonable
                # (This could be expanded based on expected structure)
                for k, v in state_data.get("batches", {}).items():
                    if not isinstance(v, dict) or "processes" not in v or not isinstance(v["processes"], list):
                         console.print(f"[yellow]Warning:[/yellow] Invalid structure for batch '{k}' in state file. Problems may occur.", file=sys.stderr)

                return state_data
        except json.JSONDecodeError:
            console.print(f"[yellow]Warning:[/yellow] State file '{state_path}' is corrupted (invalid JSON). Initializing new state.", file=sys.stderr)
            return {"batches": {}}
        except IOError as e:
             console.print(f"[red]Error reading state file '{state_path}': {e}[/red]", file=sys.stderr)
             return {"batches": {}} # Return default on read error
        except Exception as e:
            console.print(f"[red]Error loading state file '{state_path}': {e}[/red]", file=sys.stderr)
            return {"batches": {}} # Return default empty state on other errors
    finally:
        if acquired:
            lock.release()


def save_state(state_path: Path, lock: filelock.FileLock, state_data: Dict[str, Any]):
    """Saves the state to the JSON file atomically."""
    try:
        with lock: # Acquire exclusive lock for writing
            # Ensure directory exists
            state_path.parent.mkdir(parents=True, exist_ok=True)
            temp_state_path = state_path.with_suffix(state_path.suffix + '.tmp')
            with open(temp_state_path, 'w', encoding='utf-8') as f:
                json.dump(state_data, f, indent=2, ensure_ascii=False)
            # Atomic rename (or replace)
            os.replace(temp_state_path, state_path)
    except filelock.Timeout:
         console.print(f"[red]Error:[/red] Could not acquire lock on state file '{lock.lock_file}' to save state. State may not be updated.", file=sys.stderr)
    except Exception as e:
        console.print(f"[red]Error saving state file '{state_path}': {e}[/red]", file=sys.stderr)
        # Attempt to remove temporary file if rename failed
        if 'temp_state_path' in locals() and temp_state_path.exists():
            try:
                temp_state_path.unlink()
            except OSError:
                 pass # Ignore error during cleanup attempt

def sanitize_filename(name: str) -> str:
    """Removes or replaces potentially problematic characters for filenames."""
    # Allow alphanumeric, underscore, hyphen, period. Replace others with underscore.
    sanitized = "".join(c if c.isalnum() or c in ('-', '_', '.') else '_' for c in name)
    # Replace multiple consecutive underscores with a single one
    sanitized = '_'.join(filter(None, sanitized.split('_')))
    # Remove leading/trailing underscores/periods
    sanitized = sanitized.strip('_.')
    # Handle empty result after sanitizing
    if not sanitized:
        return "sanitized_empty_name"
    # Limit length
    return sanitized[:100]

def format_duration(seconds: Optional[float]) -> str:
    """Formats a duration in seconds into a human-readable string (d H:MM:SS)."""
    if seconds is None or seconds < 0: return "N/A"
    try:
        delta = datetime.timedelta(seconds=int(seconds))
        return str(delta)
    except OverflowError:
        return " ખૂબ જ લાંબું " # Very Long Time in Gujarati

def format_bytes(byte_count: Optional[int]) -> str:
    """Formats bytes into KB, MB, GB, handling None."""
    if byte_count is None: return "N/A"
    try:
        if byte_count < 1024: return f"{byte_count} B"
        if byte_count < 1024**2: return f"{byte_count/1024:.1f} KB"
        if byte_count < 1024**3: return f"{byte_count/1024**2:.1f} MB"
        return f"{byte_count/1024**3:.1f} GB"
    except TypeError:
        return "Error" # If byte_count is not a number

# --- Command Handlers ---

def handle_add(args: argparse.Namespace):
    """Adds commands to the specified batch file."""
    batch_file = Path(args.batch_file).resolve()
    added_count = 0

    try:
        batch_file.parent.mkdir(parents=True, exist_ok=True)

        # Use exclusive lock to prevent concurrent adds corrupting the file
        add_lock_path = batch_file.with_suffix(batch_file.suffix + '.add_lock')
        add_lock = filelock.FileLock(add_lock_path, timeout=5)

        with add_lock:
            with open(batch_file, 'a+', encoding='utf-8') as f: # Open in append mode, create if doesn't exist
                if args.command:
                    cmd_to_write = args.command.strip()
                    if cmd_to_write: # Avoid adding empty lines
                        f.write(cmd_to_write + "\n") # Ensure newline
                        added_count = 1
                        console.print(f"Added command to '[cyan]{batch_file.name}[/cyan]'.")
                    else:
                        console.print("[yellow]Warning:[/yellow] Provided command was empty, nothing added.")

                elif args.from_file:
                    source_file = Path(args.from_file).resolve()
                    if not source_file.is_file():
                        console.print(f"[red]Error:[/red] Source file '{source_file}' not found.")
                        return # Exit the function on error
                    with open(source_file, 'r', encoding='utf-8') as sf:
                        for line in sf:
                            command = line.strip()
                            if command and not command.startswith('#'):
                                f.write(command + "\n")
                                added_count += 1
                    if added_count > 0:
                        console.print(f"Added {added_count} command(s) from '[yellow]{source_file.name}[/yellow]' to '[cyan]{batch_file.name}[/cyan]'.")
                    else:
                        console.print(f"Source file '[yellow]{source_file.name}[/yellow]' contained no valid commands to add.")

                else:
                    # This case should not be reachable due to argparse mutual exclusion
                    console.print("[red]Error:[/red] No command or source file specified for adding.", file=sys.stderr)
                    return

            # Read the file back to count total commands accurately
            with open(batch_file, 'r', encoding='utf-8') as f:
                total_commands = sum(1 for line in f if line.strip() and not line.strip().startswith('#'))

            console.print(f"Batch file '[cyan]{batch_file.name}[/cyan]' in directory '[cyan]{batch_file.parent}[/cyan]' now contains [bold]{total_commands}[/bold] command(s).")

    except filelock.Timeout:
        console.print(f"[red]Error:[/red] Could not acquire lock '{add_lock_path}' to add commands. Is another 'add' process running?", file=sys.stderr)
    except IOError as e:
        console.print(f"[red]Error accessing file '{batch_file}': {e}[/red]", file=sys.stderr)
    except Exception as e:
        console.print(f"[red]An unexpected error occurred during add: {e}[/red]", file=sys.stderr)
        import traceback
        traceback.print_exc()


def handle_run(args: argparse.Namespace):
    """Runs commands from the specified batch file, each in a new process."""
    batch_file = Path(args.batch_file).resolve()
    state_path, lock_path = get_state_paths(batch_file)
    # Use a longer timeout for run as it needs to write the initial state
    state_lock = filelock.FileLock(lock_path, timeout=10)

    if not batch_file.is_file():
        console.print(f"[red]Error:[/red] Batch file '{batch_file}' not found.")
        return

    log_dir = batch_file.parent / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        console.print(f"[red]Error creating log directory '{log_dir}': {e}[/red]", file=sys.stderr)
        return

    try:
        with open(batch_file, 'r', encoding='utf-8') as f:
            commands = [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]
    except IOError as e:
        console.print(f"[red]Error reading batch file '{batch_file}': {e}[/red]", file=sys.stderr)
        return

    if not commands:
        console.print(f"Batch file '[cyan]{batch_file.name}[/cyan]' is empty or contains only comments. Nothing to run.")
        return

    console.print(f"Starting batch run from '[cyan]{batch_file.name}[/cyan]'...")
    run_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    batch_key = str(batch_file) # Use resolved absolute path as key
    batch_processes = []
    current_run_start_time = time.time()

    try:
        # --- Check Existing State ---
        state_data = load_state(state_path, state_lock) # Load uses its own lock timing

        if batch_key in state_data.get("batches", {}) and state_data["batches"][batch_key].get("status") == "Running":
            active_pids_in_state = []
            stale_pids_found = False
            potentially_active_script_pids = []
            existing_processes = state_data["batches"][batch_key].get("processes", [])
            current_pid = os.getpid()

            for proc_info in existing_processes:
                pid = proc_info.get('pid')
                if not pid: continue
                active_pids_in_state.append(pid)
                try:
                    p = psutil.Process(pid)
                    if p.is_running() and pid != current_pid:
                         # Basic check: Is the parent one of the other PIDs in the batch?
                         # This helps identify children of the original run commands.
                         # A more robust check might involve storing the runner script's PID.
                         try:
                             parent_pid = p.ppid()
                         except psutil.Error:
                             parent_pid = None

                         # Consider it potentially active if it's running and wasn't marked exited
                         if proc_info.get("status") == "Running":
                             potentially_active_script_pids.append(pid)

                except psutil.NoSuchProcess:
                    stale_pids_found = True
                except (psutil.AccessDenied, psutil.ZombieProcess):
                     if proc_info.get("status") == "Running":
                         potentially_active_script_pids.append(pid) # Assume active if can't check fully
                except Exception:
                    stale_pids_found = True # Treat other errors as potentially stale

            if potentially_active_script_pids:
                console.print(f"[yellow]Warning:[/yellow] Batch '{batch_file.name}' seems to have running processes from a previous run (PIDs: {potentially_active_script_pids}).")
                console.print("Use the 'status' command to check details.")
                # Add a prompt or flag later to force run or stop existing
                # For now, prevent concurrent runs on the same file more strictly:
                console.print("[red]Error:[/red] Cannot start a new run while another appears active. Please 'stop' the existing run or clear the state if it's incorrect.")
                return # Exit if potential active run detected
            elif stale_pids_found:
                console.print("[yellow]Info:[/yellow] Found stale process entries for a previous run in the state file. Proceeding with new run.")
                # Overwrite the old entry by proceeding below

        # --- Start Processes ---
        for i, command in enumerate(commands):
            # Sanitize based on the first part of the command for a meaningful name
            cmd_parts = shlex.split(command, posix=(sys.platform != "win32"))
            safe_cmd_name = sanitize_filename(Path(cmd_parts[0]).name if cmd_parts else f"cmd_{i+1}")
            log_filename = f"cmd_{i+1}_{safe_cmd_name}_{run_timestamp}.log"
            log_path = log_dir / log_filename
            log_file = None

            try:
                # Open log file first, using utf-8 encoding
                log_file = open(log_path, 'w', encoding='utf-8')

                # Process creation flags/functions
                creationflags = 0
                preexec_fn = None
                if sys.platform == "win32":
                    # CREATE_NEW_PROCESS_GROUP allows sending Ctrl+Break to the group later
                    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
                else:
                    # os.setsid creates a new session and process group (Unix-like)
                    preexec_fn = os.setsid

                process = subprocess.Popen(
                    command,
                    shell=True, # Necessary for complex commands, but be security aware
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    preexec_fn=preexec_fn,
                    creationflags=creationflags,
                    cwd=batch_file.parent, # Run command CWD relative to batch file
                    env=os.environ.copy() # Pass environment
                )

                start_time = time.time()
                proc_info = {
                    "pid": process.pid,
                    "command": command,
                    "log_path": str(log_path),
                    "start_time": start_time,
                    "status": "Running", # Initial status
                    "exit_code": None,
                    "end_time": None,
                }
                batch_processes.append(proc_info)
                console.print(f"  [green]Started:[/green] PID {process.pid} - '{command[:60]}{'...' if len(command)>60 else ''}' -> Log: '[dim]{log_path.name}[/dim]'")

            except Exception as e:
                console.print(f"  [red]Failed:[/red] Could not start '{command}': {e}", file=sys.stderr)
                # Create a placeholder entry in the state for failed starts?
                proc_info = {
                    "pid": None, # No PID if failed to start
                    "command": command,
                    "log_path": str(log_path), # Log path might exist or not
                    "start_time": time.time(),
                    "status": "Start Failed", # Specific status
                    "exit_code": None,
                    "end_time": time.time(),
                    "error": str(e) # Store error message
                }
                batch_processes.append(proc_info) # Add placeholder to list
                if log_file: # Write failure to log if file was opened
                    try:
                        log_file.write(f"BATCHRUNNER: Failed to start process.\n")
                        log_file.write(f"BATCHRUNNER: Command: {command}\n")
                        log_file.write(f"BATCHRUNNER: Error: {e}\n")
                        import traceback
                        traceback.print_exc(file=log_file)
                    except Exception as log_err:
                         console.print(f"  [red]Error writing failure to log '{log_path.name}': {log_err}[/red]", file=sys.stderr)
            finally:
                if log_file:
                    try:
                        log_file.close()
                    except Exception as close_err:
                        console.print(f"  [yellow]Warning:[/yellow] Error closing log file '{log_path.name}': {close_err}", file=sys.stderr)

        # --- Update State File ---
        if not batch_processes:
             console.print("[yellow]Warning:[/yellow] No processes were started (all failed or none provided?).", file=sys.stderr)
             return

        state_data.setdefault("batches", {})
        state_data["batches"][batch_key] = {
            "file_path": str(batch_file),
            "run_start_time": current_run_start_time,
            "status": "Running", # Overall batch status
            "processes": batch_processes # Include failed starts placeholders
        }
        # Save state requires the lock
        save_state(state_path, state_lock, state_data)

        success_count = sum(1 for p in batch_processes if p.get("status") == "Running")
        fail_count = len(batch_processes) - success_count

        if success_count > 0:
             console.print(f"[bold green]Batch run initiated:[/bold] {success_count} process(es) started.", end="")
             if fail_count > 0:
                 console.print(f" [bold red]{fail_count} failed to start.[/bold]")
             else:
                 console.print() # Just newline
             console.print(f"Use 'status --batch-file \"{batch_file}\"' to monitor.")
        else:
             console.print(f"[bold red]Batch run failed:[/bold] All {fail_count} process(es) failed to start.")


    except filelock.Timeout:
        console.print(f"[red]Error:[/red] Could not acquire lock on state file '{lock_path}'. Another process might be holding it.", file=sys.stderr)
    except Exception as e:
        console.print(f"[red]An unexpected error occurred during run: {e}[/red]", file=sys.stderr)
        import traceback
        traceback.print_exc()


def generate_status_table(batch_key: str, state_data: Dict[str, Any], state_path: Path, lock: filelock.FileLock) -> Optional[Table]:
    """Generates the Rich table for the status display. Updates state if discrepancies found."""
    batch_info = None
    resolved_batch_key = None

    # Try direct key match first
    if batch_key in state_data.get("batches", {}):
        batch_info = state_data["batches"][batch_key]
        resolved_batch_key = batch_key
    else:
        # If direct match fails, try matching by filename (useful if CWD changed)
        target_filename = Path(batch_key).name
        for key, b_info in state_data.get("batches", {}).items():
             stored_path = b_info.get("file_path")
             if stored_path and Path(stored_path).name == target_filename:
                  batch_info = b_info
                  resolved_batch_key = key # Use the full path key found in state
                  console.print(f"[dim]Info: Matched batch by filename. Full path in state: {key}[/dim]", file=sys.stderr)
                  break # Found first match

    if not batch_info or not resolved_batch_key:
        console.print(f"No running or previous batch found matching key '{batch_key}' or filename '{Path(batch_key).name}'.")
        console.print(f"Checked state file: '{state_path}'")
        return None

    processes_info = batch_info.get("processes", [])
    batch_file_path = Path(batch_info.get("file_path", resolved_batch_key)) # Fallback to key if path missing
    run_start_time_ts = batch_info.get("run_start_time")
    run_start_str = datetime.datetime.fromtimestamp(run_start_time_ts).strftime(TIMESTAMP_FORMAT) if run_start_time_ts else "Unknown"
    current_batch_status = batch_info.get("status", "Unknown")

    table = Table(
        title=f"Status for Batch: [cyan]{batch_file_path.name}[/cyan] (Path: [dim]{batch_file_path.parent}[/dim])",
        caption=f"Batch Status: [bold {('green' if current_batch_status=='Running' else 'yellow' if current_batch_status=='Completed' else 'red')}]{current_batch_status}[/bold] | Started: {run_start_str}. Press 'q' to quit.",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta"
    )
    table.add_column("PID", style="dim", width=7, justify="right")
    table.add_column("Command", max_width=50)
    table.add_column("Status", justify="center", width=15)
    table.add_column("Runtime", justify="right", width=15)
    table.add_column("CPU %", justify="right", width=7)
    table.add_column("Memory", justify="right", width=10)
    table.add_column("Log File", style="dim", max_width=35)

    state_changed = False
    active_process_count = 0
    now = time.time()

    for i, p_info in enumerate(processes_info):
        pid = p_info.get("pid")
        command = p_info.get("command", "N/A")
        log_path_str = p_info.get("log_path", "N/A")
        log_path = Path(log_path_str) if log_path_str != "N/A" else None
        start_time = p_info.get("start_time")
        current_recorded_status = p_info.get("status", "Unknown")
        end_time = p_info.get("end_time")
        exit_code = p_info.get("exit_code")

        # Default values
        display_status = current_recorded_status
        cpu_usage = "N/A"
        mem_usage = "N/A"
        runtime_seconds = None
        status_style = "yellow" # Default for unknown/transitioning

        process_active_this_cycle = False # Flag if process is running/sleeping now

        if current_recorded_status == "Start Failed":
            display_status = "[red]Start Failed[/red]"
            runtime_seconds = (end_time or start_time) - start_time if start_time else None
            status_style = "red"

        elif pid is None: # Should be covered by Start Failed, but defensive
             display_status = "[red]No PID[/red]"
             status_style = "red"
             if current_recorded_status != "Start Failed":
                 p_info["status"] = "Start Failed" # Correct state if inconsistent
                 state_changed = True

        # Only check psutil if we think it should be running
        elif current_recorded_status == "Running":
            try:
                p = psutil.Process(pid)
                if p.is_running():
                    process_active_this_cycle = True
                    with p.oneshot(): # Efficiently get multiple stats
                        try: cpu_usage = f"{p.cpu_percent(interval=0.01):.1f}" # Very short interval
                        except Exception: cpu_usage = "N/A" # Handle errors getting CPU%

                        try:
                            mem_info = p.memory_info()
                            mem_usage = format_bytes(mem_info.rss)
                        except psutil.Error: mem_usage = "N/A" # Handle errors getting memory

                        ps_status = p.status()
                        if ps_status == psutil.STATUS_RUNNING:
                             display_status = "Running"
                             status_style = "green"
                        elif ps_status == psutil.STATUS_SLEEPING:
                             display_status = "Sleeping"
                             status_style = "blue"
                        elif ps_status == psutil.STATUS_DISK_SLEEP:
                             display_status = "Disk Sleep"
                             status_style = "cyan"
                        elif ps_status == psutil.STATUS_STOPPED:
                             display_status = "Stopped"
                             status_style = "magenta"
                             process_active_this_cycle = False # Stopped isn't actively running
                        elif ps_status == psutil.STATUS_ZOMBIE:
                             display_status = "Zombie"
                             status_style = "red"
                             process_active_this_cycle = False # Zombie is finished
                             # Mark as Exited in state
                             if p_info["status"] == "Running":
                                 p_info["status"] = "Exited"
                                 p_info["end_time"] = p_info.get("end_time") or now # Use existing end time if set, else now
                                 try: p_info["exit_code"] = p_info.get("exit_code") or p.wait(timeout=0)
                                 except Exception: p_info["exit_code"] = p_info.get("exit_code", "?")
                                 state_changed = True
                        else:
                             display_status = ps_status.capitalize()
                             status_style = "yellow" # Other states

                    runtime_seconds = now - start_time if start_time else None

                else: # Process object exists but p.is_running() is false
                    process_active_this_cycle = False
                    display_status = "Exited"
                    status_style = "yellow" # Indicate it just finished
                    if p_info["status"] == "Running": # Update state only if it was thought running
                        p_info["status"] = "Exited"
                        p_info["end_time"] = now
                        try: p_info["exit_code"] = p.wait(timeout=0)
                        except Exception: p_info["exit_code"] = "?"
                        state_changed = True
                    # Use recorded end_time if available (might be from previous check)
                    runtime_seconds = (p_info.get("end_time") or start_time) - start_time if start_time else None


            except psutil.NoSuchProcess:
                process_active_this_cycle = False
                display_status = "Exited"
                status_style = "red" # Assume abnormal exit if gone unexpectedly
                if p_info["status"] == "Running":
                    p_info["status"] = "Exited"
                    p_info["end_time"] = now
                    p_info["exit_code"] = "?" # Can't get exit code if process is gone
                    state_changed = True
                runtime_seconds = (p_info.get("end_time") or start_time) - start_time if start_time else None

            except psutil.AccessDenied:
                # If access denied, assume it *might* be running, keep status and count active
                process_active_this_cycle = True # Keep checking it
                display_status = "AccessDenied"
                status_style = "red"
                runtime_seconds = now - start_time if start_time else None # Keep runtime ticking

            except Exception as e:
                # Other psutil errors
                process_active_this_cycle = False # Treat as uncertain, stop counting active
                display_status = "[red]Error[/red]"
                status_style = "red"
                console.print(f"\n[red]Error checking PID {pid}: {e}[/red]", file=sys.stderr)
                runtime_seconds = now - start_time if start_time else None # Show runtime until error
                # Decide if state should change on error, e.g., p_info["status"] = "Error"
                # Let's just display error for now, keep state as "Running" to retry check
                # If error persists, it might need manual state cleanup.

        # Handle states that are already terminal (Exited, Completed, Failed)
        elif current_recorded_status != "Running":
             display_status = current_recorded_status # Use recorded status
             process_active_this_cycle = False
             if current_recorded_status == "Exited":
                 exit_info = f" (Code: {exit_code})" if exit_code is not None else ""
                 display_status = f"Exited{exit_info}"
                 status_style = "dim" if exit_code == 0 else "red" if exit_code != "?" else "yellow"
             elif current_recorded_status == "Start Failed":
                  display_status = "[red]Start Failed[/red]"
                  status_style = "red"
             else: # Other terminal states?
                  status_style = "magenta" # Default style for other terminal states

             runtime_seconds = (end_time or start_time) - start_time if start_time else None

        # Increment active count if process was running/sleeping this cycle
        if process_active_this_cycle:
            active_process_count += 1

        # Format runtime
        runtime_str = format_duration(runtime_seconds)

        # Truncate command and log file for display
        display_command = (command[:47] + '...') if len(command) > 50 else command
        display_log = log_path.name if log_path else "N/A"
        display_log = (display_log[:32] + '...') if len(display_log) > 35 else display_log

        table.add_row(
            str(pid) if pid else "[dim]N/A[/dim]",
            display_command,
            f"[{status_style}]{display_status}[/{status_style}]",
            runtime_str,
            cpu_usage,
            mem_usage,
            f"[dim]{display_log}[/dim]"
        )

    # --- Update Overall Batch Status ---
    # Only change status if it was previously "Running"
    if current_batch_status == "Running":
        # Check if *all* processes are in a terminal state
        all_terminal = True
        if not processes_info: # If no processes were ever listed (e.g., failed run)
             all_terminal = False # Treat as not completed cleanly
        for p_info in processes_info:
            if p_info.get("status") == "Running": # If any are still marked running, not terminal
                all_terminal = False
                break
            # Consider "Start Failed" as terminal for batch completion purposes
            if p_info.get("status") not in ("Exited", "Start Failed"):
                 # If we add other terminal states like "Stopped", include them here
                 # For now, only Exited/Start Failed count
                 pass # Let's assume only Exited/Start Failed are truly terminal for now


        if all_terminal and active_process_count == 0:
             # Check if any failed
             any_failed = any(p.get("exit_code") != 0 or p.get("status") == "Start Failed" for p in processes_info)
             if any_failed:
                  batch_info["status"] = "CompletedWithErrors"
             else:
                  batch_info["status"] = "Completed"
             # Add a batch end time?
             batch_info["run_end_time"] = now
             state_changed = True


    if state_changed:
        # Save the updated state (e.g., process status changes, batch status)
        # This requires acquiring the write lock
        save_state(state_path, lock, state_data)

    return table


def handle_status(args: argparse.Namespace):
    """Displays the status of the running batch processes."""
    batch_file = Path(args.batch_file).resolve()
    state_path, lock_path = get_state_paths(batch_file)
    # Use shared lock for status as it might need to write updates
    # Shorten timeout for status acquisition as it's less critical than run/add
    state_lock = filelock.FileLock(lock_path, timeout=2)

    batch_key = str(batch_file)

    console.print("Starting status monitor...")
    last_table_content = None
    no_batch_message_shown = False

    try:
        # Use transient=True to clean up the table on exit
        with Live(console=console, refresh_per_second=1.5, transient=True, vertical_overflow="visible") as live:
            while True:
                current_content = None
                # Load the latest state within the loop
                state_data = load_state(state_path, state_lock) # Handles lock internally

                # Generate the table (this function also updates state if needed)
                table = generate_status_table(batch_key, state_data, state_path, state_lock) # Handles lock internally

                if table is None:
                    if not no_batch_message_shown:
                        current_content = Panel(f"No active or completed batch found for [cyan]{Path(batch_key).name}[/cyan].\nState file checked: [dim]{state_path}[/dim]\nPress 'q' or Ctrl+C to exit.", title="Info", border_style="yellow", padding=(1,2))
                        live.update(current_content)
                        no_batch_message_shown = True
                else:
                    current_content = table
                    no_batch_message_shown = False # Reset if batch found again

                # Update live display only if content changed (or first run)
                # Comparing rich renderables directly might be complex, compare structure/text?
                # For simplicity, update every time if table generated.
                if current_content is not None:
                    live.update(current_content)
                    last_table_content = current_content # Store for potential future comparison

                # --- Check for 'q' input ---
                # This remains tricky cross-platform without blocking
                input_char = None
                if sys.platform != "win32":
                    # Try using select/poll for non-blocking read if possible,
                    # but readchar itself might block. This is a simplified check.
                    # A more robust solution might involve threading for input.
                    try:
                        # Check if data is available on stdin
                        import select
                        if select.select([sys.stdin], [], [], 0.05)[0]: # 50ms timeout
                           input_char = readchar.readkey()
                    except (ImportError, Exception):
                        # Fallback or ignore if select not available or fails
                        pass
                else:
                    # Windows: msvcrt.kbhit() can check without blocking
                    try:
                        import msvcrt
                        if msvcrt.kbhit():
                            input_char = msvcrt.getwch() # Read wide character
                    except ImportError:
                         pass # msvcrt not available (e.g., Git Bash?)
                    except Exception:
                         pass # Other console errors

                if input_char and input_char.lower() == 'q':
                    break # Exit loop on 'q'

                # If no 'q', sleep for the remainder of the refresh interval
                # The input check above might have taken some time
                time.sleep(max(0, (1.0 / 1.5) - 0.1)) # Sleep interval minus approx input check time

    except KeyboardInterrupt:
        console.print("\nExiting status monitor.")
    except Exception as e:
        console.print(f"[red]An unexpected error occurred during status monitoring: {e}[/red]", file=sys.stderr)
        import traceback
        traceback.print_exc()
    finally:
        # Live(transient=True) should handle cleanup, but ensure console is okay
        console.print() # Print a newline for cleaner exit


# --- Signal Handling ---
def signal_handler(sig, frame):
    """Gracefully handle Ctrl+C or termination signals."""
    console.print("\n[yellow]Signal received, exiting...[/yellow]")
    # Add potential cleanup here if necessary (e.g., attempt to terminate child process groups)
    # Finding and killing specific child groups reliably can be complex and platform-dependent.
    # A simple exit is often sufficient as child processes might terminate on their own.
    sys.exit(0)

# Register signal handlers for graceful termination
try:
    signal.signal(signal.SIGINT, signal_handler) # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler) # Termination request
    # On Windows, SIGBREAK can also be used
    if sys.platform == "win32":
        signal.signal(signal.SIGBREAK, signal_handler)
except (ValueError, AttributeError):
     # ValueError: signal only works in main thread
     # AttributeError: SIGBREAK not available on non-Windows
     console.print("[dim]Info: Could not set all signal handlers (e.g., running in non-main thread or non-Windows).[/dim]", file=sys.stderr)

# --- Main Execution ---
def main():
    parser = argparse.ArgumentParser(
        prog="batch_runner", # Explicitly set program name for help
        description="""BatchRunner: Manage and Execute Command Batches.

This tool allows you to define batches of shell commands in simple text files
and manage their execution. You can add commands, run entire batches in
parallel (each command in its own process), and monitor their status.""",
        formatter_class=argparse.RawDescriptionHelpFormatter, # Preserves formatting
        epilog="""Workflow:
  1. Create a batch file (e.g., my_jobs.cmds) or use 'add' to create it.
  2. Use 'add' to populate the batch file with commands.
  3. Use 'run' to start all commands in the batch file concurrently.
  4. Use 'status' to monitor the progress of the running batch.

Examples:

  # Add a single long-running command to a new/existing batch file
  %(prog)s add --batch-file my_analysis.cmds --command "python run_simulation.py --input data.h5 --duration 3600"

  # Add multiple commands from a text file (one command per line)
  %(prog)s add --batch-file my_analysis.cmds -f ./setup_commands.txt

  # Run all commands defined in the batch file concurrently
  # Logs will be placed in ./logs/ relative to my_analysis.cmds
  # State will be tracked in ./ .batch_runner_state.json
  %(prog)s run --batch-file my_analysis.cmds

  # Monitor the status of the running batch (live update)
  # Press 'q' or Ctrl+C to exit the monitor.
  %(prog)s status --batch-file my_analysis.cmds

Notes:
  - Batch files are simple text files; lines starting with '#' are ignored as comments.
  - State (.batch_runner_state.json) and logs (logs/ directory) are stored in the
    same directory as the specified batch file.
  - Use quotes within the --command argument for commands containing spaces or
    special shell characters (e.g., pipes, redirection).
  - Ensure commands added to the batch file are executable in the shell environment
    and context where you run the '%(prog)s run' command. The working directory
    for each executed command defaults to the directory containing the batch file.
"""
    )
    subparsers = parser.add_subparsers(dest='action', required=True,
                                       title='Available Actions',
                                       description='Choose one of the following actions:',
                                       help='Action to perform (e.g., add, run, status).')

    # --- Add Command ---
    parser_add = subparsers.add_parser('add',
        help='Add one or more commands to a specified batch file.',
        description='Appends commands to the batch file. Creates the file and parent directories if they do not exist. Reports the total command count after adding.')
    parser_add.add_argument('--batch-file', required=True, metavar='FILE_PATH',
        help='Path to the target batch file (e.g., path/to/my_batch.cmds). This file defines the group of commands.')
    add_group = parser_add.add_mutually_exclusive_group(required=True)
    add_group.add_argument('--command', '-c', metavar='COMMAND_STRING',
        help='A single command string to add to the batch file (use quotes if needed).')
    add_group.add_argument('--from-file', '-f', metavar='SOURCE_FILE',
        help='Path to a text file containing commands to add (one command per line; comments starting with # and empty lines are ignored).')
    parser_add.set_defaults(func=handle_add)

    # --- Run Command ---
    parser_run = subparsers.add_parser('run',
        help='Execute all commands in a batch file concurrently.',
        description='Starts each valid command from the batch file in a separate background process. Creates a "logs" subdirectory relative to the batch file for stdout/stderr logs and tracks process state in ".batch_runner_state.json" in the same directory. Warns if a previous run seems active.')
    parser_run.add_argument('--batch-file', required=True, metavar='FILE_PATH',
        help='Path to the batch file containing commands to execute.')
    # Future flag idea: parser_run.add_argument('--force', action='store_true', help='Force start even if another run seems active.')
    parser_run.set_defaults(func=handle_run)

    # --- Status Command ---
    parser_status = subparsers.add_parser('status',
        help='Monitor the status of processes initiated by a batch run.',
        description='Displays a live-updating table showing the status (PID, command, runtime, CPU/Memory usage, log file) of processes associated with the specified batch file. Reads state from ".batch_runner_state.json". Updates process status (e.g., to Exited) based on current system state. Press "q" or Ctrl+C to exit.')
    parser_status.add_argument('--batch-file', required=True, metavar='FILE_PATH',
        help='Path to the batch file whose run status you want to monitor.')
    parser_status.set_defaults(func=handle_status)

    # --- (Keep placeholder comments for future commands like 'stop', 'list', 'clean') ---

    # Handle case where no arguments are given (besides script name)
    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    try:
        args = parser.parse_args()
        # Execute the function associated with the chosen subparser
        args.func(args)
    except Exception as e:
         # Catch potential argument parsing errors or other top-level exceptions
         console.print(f"[bold red]An unexpected error occurred:[/bold] {e}", file=sys.stderr)
         import traceback
         traceback.print_exc()
         sys.exit(2) # Exit with a non-zero code on error


if __name__ == "__main__":
    main()
