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
import traceback
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
        try:
            import msvcrt
        except ImportError:
            msvcrt = None # Indicate msvcrt is not available
        pass

except ImportError as e:
    print(f"Error: Missing required package(s): {e.name}", file=sys.stderr)
    # Provide more specific instructions based on the missing package
    install_cmd = f"pip install {e.name}"
    if e.name == "readchar" and sys.platform == "win32":
         install_cmd = "pip install readchar  # (Note: may have limited functionality on Windows cmd/powershell)"
    print(f"Please install it using: {install_cmd}", file=sys.stderr)
    sys.exit(1)

# Main console for standard output
console = Console()
# Separate console for error messages directed to stderr
console_stderr = Console(stderr=True, style="bold red")


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
    acquired = False
    try:
        acquired = lock.acquire(timeout=0.1) # Short non-blocking attempt first
        if not acquired:
            # If couldn't get lock quickly, wait a bit longer
            lock.acquire(timeout=2) # Wait up to 2 seconds
            acquired = True
    except filelock.Timeout:
        # Print warning using stderr console if lock times out during acquire attempt
        console_stderr.print(f"Warning: Could not acquire lock on '{lock.lock_file}' quickly. Reading state might be slightly delayed or stale.")
        # Proceed without lock for read-only access might be okay for status, but risky if another process writes

    try: # Ensure lock is released even if reading fails
        if not state_path.exists():
            return {"batches": {}}
        try:
            with open(state_path, 'r', encoding='utf-8') as f:
                state_data = json.load(f)
                # Basic validation
                if not isinstance(state_data, dict) or "batches" not in state_data or not isinstance(state_data["batches"], dict):
                    console_stderr.print(f"Warning: State file '{state_path}' has invalid format. Initializing new state.")
                    return {"batches": {}}
                # Further validation: Ensure batch keys and process lists are reasonable
                for k, v in state_data.get("batches", {}).items():
                    if not isinstance(v, dict) or "processes" not in v or not isinstance(v["processes"], list):
                         console_stderr.print(f"Warning: Invalid structure for batch '{k}' in state file. Problems may occur.")

                return state_data
        except json.JSONDecodeError:
            console_stderr.print(f"Warning: State file '{state_path}' is corrupted (invalid JSON). Initializing new state.")
            return {"batches": {}}
        except IOError as e:
             console_stderr.print(f"Error reading state file '{state_path}': {e}")
             return {"batches": {}} # Return default on read error
        except Exception as e:
            console_stderr.print(f"Error loading state file '{state_path}': {e}")
            return {"batches": {}} # Return default empty state on other errors
    finally:
        if acquired:
            try:
                lock.release()
            except Exception as release_err:
                 # Use console_stderr for warnings about lock release failure
                 console_stderr.print(f"Warning: Error releasing state lock '{lock.lock_file}': {release_err}")


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
         console_stderr.print(f"Error: Could not acquire lock on state file '{lock.lock_file}' to save state. State may not be updated.")
    except Exception as e:
        console_stderr.print(f"Error saving state file '{state_path}': {e}")
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
        return " Very Long " # Handle extremely large values if necessary

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
    commands_to_add = []
    source_desc = ""

    try:
        # --- Step 1: Collect valid commands first ---
        if args.command:
            cmd_to_write = args.command.strip()
            if cmd_to_write: # Avoid adding empty lines
                commands_to_add.append(cmd_to_write)
                source_desc = "command argument"
            else:
                console.print("[yellow]Warning:[/yellow] Provided command was empty, nothing added.")
                # Do not proceed to file creation if command is empty
                return

        elif args.from_file:
            source_file = Path(args.from_file).resolve()
            source_desc = f"file '[yellow]{source_file.name}[/yellow]'"
            if not source_file.is_file():
                # Use regular console for info/error message here
                console.print(f"[red]Error:[/red] Source file '{source_file}' not found.")
                return # Exit the function on error
            try:
                with open(source_file, 'r', encoding='utf-8') as sf:
                    for line in sf:
                        command = line.strip()
                        if command and not command.startswith('#'):
                            commands_to_add.append(command)
            except Exception as read_err:
                console_stderr.print(f"Error reading from source file '{source_file}': {read_err}")
                return

            if not commands_to_add:
                console.print(f"Source {source_desc} contained no valid commands to add.")
                # Do not proceed to file creation if source is empty/invalid
                return

        else:
            # This case should not be reachable due to argparse mutual exclusion
            console_stderr.print("Error: No command or source file specified for adding.")
            return

        # --- Step 2: Only create/open file if there are commands ---
        if commands_to_add:
            batch_file.parent.mkdir(parents=True, exist_ok=True)
            add_lock_path = batch_file.with_suffix(batch_file.suffix + '.add_lock')
            add_lock = filelock.FileLock(add_lock_path, timeout=5)

            with add_lock:
                with open(batch_file, 'a+', encoding='utf-8') as f: # Open in append mode, create if needed
                    # Move to end of file in case 'a+' didn't on some systems
                    f.seek(0, os.SEEK_END)
                    for command in commands_to_add:
                        f.write(command + "\n") # Ensure newline

                added_count = len(commands_to_add)
                console.print(f"Added {added_count} command(s) from {source_desc} to '[cyan]{batch_file.name}[/cyan]'.")

                # Read the file back to count total commands accurately
                # Re-open in read mode to ensure accurate count after append
                with open(batch_file, 'r', encoding='utf-8') as f_read:
                    total_commands = sum(1 for line in f_read if line.strip() and not line.strip().startswith('#'))

                console.print(f"Batch file '[cyan]{batch_file.name}[/cyan]' in directory '[cyan]{batch_file.parent}[/cyan]' now contains [bold]{total_commands}[/bold] command(s).")

    except filelock.Timeout:
        console_stderr.print(f"Error: Could not acquire lock '{add_lock_path}' to add commands. Is another 'add' process running?")
    except IOError as e:
        console_stderr.print(f"Error accessing file '{batch_file}': {e}")
    except Exception as e:
        console_stderr.print(f"An unexpected error occurred during add: {e}")
        # Use traceback.print_exc which prints to stderr by default
        traceback.print_exc()


def handle_run(args: argparse.Namespace):
    """Runs commands from the specified batch file, each in a new process."""
    batch_file = Path(args.batch_file).resolve()
    state_path, lock_path = get_state_paths(batch_file)
    # Use a longer timeout for run as it needs to write the initial state
    state_lock = filelock.FileLock(lock_path, timeout=10)

    if not batch_file.is_file():
        # Use regular console for this info message
        console.print(f"[red]Error:[/red] Batch file '{batch_file}' not found.")
        return

    log_dir = batch_file.parent / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        console_stderr.print(f"Error creating log directory '{log_dir}': {e}")
        return

    commands = []
    try:
        with open(batch_file, 'r', encoding='utf-8') as f:
            commands = [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]
    except IOError as e:
        console_stderr.print(f"Error reading batch file '{batch_file}': {e}")
        return

    if not commands:
        console.print(f"Batch file '[cyan]{batch_file.name}[/cyan]' is empty or contains only comments. Nothing to run.")
        return

    console.print(f"Starting batch run from '[cyan]{batch_file.name}[/cyan]'...")
    run_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    batch_key = str(batch_file.resolve()) # Use resolved absolute path as key
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
                         try:
                             parent_pid = p.ppid()
                         except psutil.Error:
                             parent_pid = None
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
                # Use stderr console for this error sequence
                console_stderr.print(f"Warning: Batch '{batch_file.name}' seems to have running processes from a previous run (PIDs: {potentially_active_script_pids}).")
                console_stderr.print("Use the 'status' command to check details.")
                console_stderr.print("Error: Cannot start a new run while another appears active. Please 'stop' the existing run or clear the state if it's incorrect.")
                return # Exit if potential active run detected
            elif stale_pids_found:
                 # Use regular console for info
                console.print("[yellow]Info:[/yellow] Found stale process entries for a previous run in the state file. Proceeding with new run.")

        # --- Start Processes ---
        for i, command in enumerate(commands):
            # Sanitize based on the first part of the command for a meaningful name
            try:
                # Use shlex to handle quotes better, but fall back if it fails
                cmd_parts = shlex.split(command, posix=(sys.platform != "win32"))
                safe_cmd_name = sanitize_filename(Path(cmd_parts[0]).name if cmd_parts else f"cmd_{i+1}")
            except ValueError: # Handle complex commands shlex might fail on
                 safe_cmd_name = sanitize_filename(command.split()[0] if command else f"cmd_{i+1}")

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
                    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
                else:
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
                # Use regular console for start messages
                console.print(f"  [green]Started:[/green] PID {process.pid} - '{command[:60]}{'...' if len(command)>60 else ''}' -> Log: '[dim]{log_path.name}[/dim]'")

            except Exception as e:
                # Use stderr console for the failure message during startup
                console_stderr.print(f"  Failed: Could not start '{command}': {e}")
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
                        traceback.print_exc(file=log_file)
                    except Exception as log_err:
                         console_stderr.print(f"  Warning: Error writing failure to log '{log_path.name}': {log_err}")
            finally:
                if log_file:
                    try:
                        log_file.close()
                    except Exception as close_err:
                        console_stderr.print(f"  Warning: Error closing log file '{log_path.name}': {close_err}")

        # --- Update State File ---
        if not batch_processes:
             console.print("[yellow]Warning:[/yellow] No processes were started (all failed or none provided?).")
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

        # --- FINAL PRINT STATEMENTS (Simplified Further) ---
        if success_count > 0:
            msg = f"[green]Batch run initiated:[/green] {success_count} process(es) started."
            if fail_count > 0:
                msg += f" [red]({fail_count} failed to start)[/red]"
            console.print(msg) # Single print statement for the summary
            console.print(f"Use 'status --batch-file \"{batch_file}\"' to monitor.")
        else:
             # Use stderr console for complete failure message
             console_stderr.print(f"Batch run failed: All {fail_count} process(es) failed to start.")
             sys.exit(1) # Exit with non-zero code if ALL fail to start

    except filelock.Timeout:
        console_stderr.print(f"Error: Could not acquire lock on state file '{lock_path}'. Another process might be holding it.")
        sys.exit(1)
    except Exception as e:
        console_stderr.print(f"An unexpected error occurred during run: {e}")
        # Use traceback.print_exc which prints to stderr by default
        traceback.print_exc()
        sys.exit(1)


def generate_status_table(batch_key: str, state_data: Dict[str, Any], state_path: Path, lock: filelock.FileLock) -> Optional[Table]:
    """Generates the Rich table for the status display. Updates state if discrepancies found."""
    batch_info = None
    resolved_batch_key = None

    # Try direct key match first (absolute path)
    abs_batch_key = str(Path(batch_key).resolve())
    if abs_batch_key in state_data.get("batches", {}):
        batch_info = state_data["batches"][abs_batch_key]
        resolved_batch_key = abs_batch_key
    else:
        # If direct match fails, try matching by filename (useful if CWD changed)
        target_filename = Path(batch_key).name
        for key, b_info in state_data.get("batches", {}).items():
             stored_path = b_info.get("file_path")
             if stored_path and Path(stored_path).name == target_filename:
                  batch_info = b_info
                  resolved_batch_key = key # Use the full path key found in state
                  # Print info message to regular console
                  console.print(f"[dim]Info: Matched batch by filename. Full path in state: {key}[/dim]")
                  break # Found first match

    if not batch_info or not resolved_batch_key:
        # Use regular console for this info message
        console.print(f"No running or previous batch found matching key '{abs_batch_key}' or filename '{Path(batch_key).name}'.")
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
                # Print error to stderr console
                console_stderr.print(f"\nError checking PID {pid}: {e}")
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
                 # Style based on exit code: 0=dim, non-zero=red, ?=yellow
                 status_style = "dim" if exit_code == 0 else "red" if (isinstance(exit_code, int) and exit_code != 0) else "yellow"
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
        if not processes_info: # If no processes were ever listed
             all_terminal = False # Treat as not completed cleanly (shouldn't happen if run started)
        for p_info in processes_info:
            if p_info.get("status") == "Running": # If any are still marked running, not terminal
                all_terminal = False
                break
            # Consider "Start Failed" as terminal for batch completion purposes
            if p_info.get("status") not in ("Exited", "Start Failed"):
                 # If we add other terminal states like "Stopped", include them here
                 pass

        # Ensure active_process_count from psutil also reflects zero running
        if all_terminal and active_process_count == 0:
             # Check if any failed to start or exited with non-zero code
             any_failed = any(
                 p.get("status") == "Start Failed" or
                 (p.get("status") == "Exited" and p.get("exit_code") != 0)
                 for p in processes_info
             )
             if any_failed:
                  batch_info["status"] = "CompletedWithErrors"
             else:
                  batch_info["status"] = "Completed"
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

    batch_key = str(batch_file.resolve()) # Use absolute path

    # Add a check here: if state file doesn't exist, print message and exit early
    if not state_path.exists():
        # Use regular console for this info message
        console.print(f"No state file found at '{state_path}'. Has a batch been run for '{batch_file.name}'?")
        return

    console.print("Starting status monitor...")
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
                        # Modify panel message for clarity
                        current_content = Panel(f"No batch data found for key '{batch_key}' in state file.\nState file checked: [dim]{state_path}[/dim]\nPress 'q' or Ctrl+C to exit.", title="Info", border_style="yellow", padding=(1,2))
                        live.update(current_content)
                        no_batch_message_shown = True
                else:
                    current_content = table
                    no_batch_message_shown = False # Reset if batch found again

                # Update live display
                if current_content is not None:
                    live.update(current_content)

                # --- Check for 'q' input ---
                input_char = None
                wait_time = 1.0 / 1.5 # Time between refreshes
                check_interval = 0.05 # How often to check for input within wait_time
                start_wait = time.time()

                while time.time() - start_wait < wait_time:
                    if sys.platform != "win32":
                        try:
                            import select
                            if select.select([sys.stdin], [], [], 0)[0]: # Check immediately if data available
                               input_char = readchar.readkey()
                               break # Exit inner loop once key is read
                        except (ImportError, Exception):
                            # Fallback or ignore if select not available or fails
                            pass
                    else:
                        # Windows: msvcrt.kbhit() can check without blocking
                        try:
                            # Check if msvcrt was imported successfully
                            if msvcrt and msvcrt.kbhit():
                                input_char = msvcrt.getwch()
                                break # Exit inner loop once key is read
                        except NameError: # msvcrt might not be defined
                            pass
                        except Exception:
                            pass # Other console errors

                    # Sleep briefly before checking again
                    # Ensure sleep duration is non-negative
                    remaining_wait = wait_time - (time.time() - start_wait)
                    time.sleep(min(check_interval, max(0, remaining_wait)))


                if input_char and input_char.lower() == 'q':
                    break # Exit outer loop on 'q'

    except KeyboardInterrupt:
        console.print("\nExiting status monitor.")
    except Exception as e:
        console_stderr.print(f"An unexpected error occurred during status monitoring: {e}")
        traceback.print_exc(file=sys.stderr)
    finally:
        # Live(transient=True) should handle cleanup, but ensure console is okay
        console.print() # Print a newline for cleaner exit


# --- Signal Handling ---
def signal_handler(sig, frame):
    """Gracefully handle Ctrl+C or termination signals."""
    # Use regular console for this message
    console.print("\n[yellow]Signal received, exiting...[/yellow]")
    sys.exit(0)

# Register signal handlers for graceful termination
try:
    signal.signal(signal.SIGINT, signal_handler) # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler) # Termination request
    if sys.platform == "win32":
        signal.signal(signal.SIGBREAK, signal_handler) # Ctrl+Break
except (ValueError, AttributeError, OSError) as sig_err:
     # Use stderr console for warnings about signal handlers
     console_stderr.print(f"Warning: Could not set all signal handlers: {sig_err}")

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
        description='Appends commands to the batch file. Creates the file and parent directories if they do not exist (only if valid commands are provided). Reports the total command count after adding.')
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
        description='Starts each valid command from the batch file in a separate background process. Creates a "logs" subdirectory relative to the batch file for stdout/stderr logs and tracks process state in ".batch_runner_state.json" in the same directory. Prevents starting if another run of the same batch file appears active.')
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
         # Use the dedicated stderr console
         console_stderr.print(f"An unexpected error occurred: {e}")
         # Use traceback.print_exc which prints to stderr by default
         traceback.print_exc()
         sys.exit(2) # Exit with a non-zero code on error

if __name__ == "__main__":
    main()
