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
    import readchar
except ImportError as e:
    print(f"Error: Missing required package(s): {e.name}", file=sys.stderr)
    print("Please install them using: pip install rich psutil filelock readchar", file=sys.stderr)
    sys.exit(1)

console = Console()

# --- Configuration ---
STATE_FILENAME = ".batch_runner_state.json"
STATE_LOCK_FILENAME = ".batch_runner_state.lock"
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

# --- State Management ---

def get_state_paths(batch_file_path: Path) -> (Path, Path):
    """Gets the paths for the state file and lock file based on the batch file location."""
    state_dir = batch_file_path.parent
    state_path = state_dir / STATE_FILENAME
    lock_path = state_dir / STATE_LOCK_FILENAME
    return state_path, lock_path

def load_state(state_path: Path, lock: filelock.FileLock) -> Dict[str, Any]:
    """Loads the state from the JSON file."""
    with lock:
        if not state_path.exists():
            return {"batches": {}}
        try:
            with open(state_path, 'r') as f:
                state_data = json.load(f)
                # Basic validation
                if "batches" not in state_data or not isinstance(state_data["batches"], dict):
                    console.print(f"[yellow]Warning:[/yellow] State file '{state_path}' has invalid format. Initializing new state.", file=sys.stderr)
                    return {"batches": {}}
                return state_data
        except json.JSONDecodeError:
            console.print(f"[yellow]Warning:[/yellow] State file '{state_path}' is corrupted. Initializing new state.", file=sys.stderr)
            return {"batches": {}}
        except Exception as e:
            console.print(f"[red]Error loading state file '{state_path}': {e}[/red]", file=sys.stderr)
            return {"batches": {}} # Return default empty state on error

def save_state(state_path: Path, lock: filelock.FileLock, state_data: Dict[str, Any]):
    """Saves the state to the JSON file."""
    try:
        with lock:
            # Ensure directory exists (should normally exist by now, but defensive)
            state_path.parent.mkdir(parents=True, exist_ok=True)
            # Write atomically if possible (write to temp then rename)
            temp_state_path = state_path.with_suffix(state_path.suffix + '.tmp')
            with open(temp_state_path, 'w') as f:
                json.dump(state_data, f, indent=2)
            os.replace(temp_state_path, state_path) # Atomic rename
    except Exception as e:
        console.print(f"[red]Error saving state file '{state_path}': {e}[/red]", file=sys.stderr)
        # Attempt to remove temporary file if rename failed
        if 'temp_state_path' in locals() and temp_state_path.exists():
            try:
                temp_state_path.unlink()
            except OSError:
                pass # Ignore error during cleanup


def sanitize_filename(name: str) -> str:
    """Removes potentially problematic characters for filenames."""
    sanitized = "".join(c if c.isalnum() or c in ('-', '_', '.') else '_' for c in name)
    return sanitized[:100] # Limit length

def format_duration(seconds: float) -> str:
    """Formats a duration in seconds into a human-readable string."""
    if seconds < 0: return "N/A"
    delta = datetime.timedelta(seconds=int(seconds))
    return str(delta)

def format_bytes(byte_count: Optional[int]) -> str:
    """Formats bytes into KB, MB, GB."""
    if byte_count is None: return "N/A"
    if byte_count < 1024: return f"{byte_count} B"
    if byte_count < 1024**2: return f"{byte_count/1024:.1f} KB"
    if byte_count < 1024**3: return f"{byte_count/1024**2:.1f} MB"
    return f"{byte_count/1024**3:.1f} GB"

# --- Command Handlers ---

def handle_add(args: argparse.Namespace):
    """Adds commands to the specified batch file."""
    batch_file = Path(args.batch_file).resolve()
    added_count = 0

    try:
        batch_file.parent.mkdir(parents=True, exist_ok=True)

        with open(batch_file, 'a+') as f:
            if args.command:
                f.write(args.command.strip() + "\n") # Ensure newline
                added_count = 1
                console.print(f"Added command to '{batch_file}'.")
            elif args.from_file:
                source_file = Path(args.from_file)
                if not source_file.is_file():
                    # Use console.print for rich formatting, print to stdout by default
                    console.print(f"[red]Error:[/red] Source file '{source_file}' not found.")
                    return # Exit the function on error
                with open(source_file, 'r') as sf:
                    for line in sf:
                        command = line.strip()
                        if command and not command.startswith('#'):
                            f.write(command + "\n")
                            added_count += 1
                console.print(f"Added {added_count} command(s) from '{source_file}' to '{batch_file}'.")
            else:
                console.print("[red]Error:[/red] No command or source file specified for adding.")
                return

        # Read the file back to count total commands accurately
        with open(batch_file, 'r') as f:
            total_commands = sum(1 for line in f if line.strip() and not line.strip().startswith('#'))

        console.print(f"Batch file '[cyan]{batch_file.name}[/cyan]' in directory '[cyan]{batch_file.parent}[/cyan]' now contains [bold]{total_commands}[/bold] command(s).")

    except IOError as e:
        console.print(f"[red]Error accessing file '{batch_file}': {e}[/red]")
    except Exception as e:
        console.print(f"[red]An unexpected error occurred during add: {e}[/red]")


def handle_run(args: argparse.Namespace):
    """Runs commands from the specified batch file, each in a new process."""
    batch_file = Path(args.batch_file).resolve()
    state_path, lock_path = get_state_paths(batch_file)
    state_lock = filelock.FileLock(lock_path, timeout=5)

    if not batch_file.is_file():
        console.print(f"[red]Error:[/red] Batch file '{batch_file}' not found.")
        return

    log_dir = batch_file.parent / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        console.print(f"[red]Error creating log directory '{log_dir}': {e}[/red]")
        return

    try:
        with open(batch_file, 'r') as f:
            commands = [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]
    except IOError as e:
        console.print(f"[red]Error reading batch file '{batch_file}': {e}[/red]")
        return

    if not commands:
        console.print(f"Batch file '{batch_file.name}' is empty or contains only comments. Nothing to run.")
        return

    console.print(f"Starting batch run from '[cyan]{batch_file.name}[/cyan]'...")
    run_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    batch_key = str(batch_file) # Use resolved path as key
    batch_processes = []

    try:
        state_data = load_state(state_path, state_lock)

        # Improved check for already running batches
        if batch_key in state_data.get("batches", {}) and state_data["batches"][batch_key].get("status") == "Running":
             active_pids_in_state = []
             stale_pids_found = False
             potentially_active_script_pids = []
             current_pid = os.getpid() # Don't count the current process

             for proc_info in state_data["batches"][batch_key].get("processes", []):
                 pid = proc_info.get('pid')
                 if not pid: continue
                 active_pids_in_state.append(pid)
                 try:
                     p = psutil.Process(pid)
                     # Check if it's running and looks like our script or a child
                     # This check is heuristic and might need adjustment
                     cmdline = " ".join(p.cmdline()).lower() if hasattr(p, 'cmdline') else p.name().lower()
                     if p.is_running() and pid != current_pid and ('python' in cmdline and SCRIPT_NAME.lower() in cmdline or p.parent().pid in active_pids_in_state ):
                          potentially_active_script_pids.append(pid)
                 except psutil.NoSuchProcess:
                     stale_pids_found = True # Found a PID that doesn't exist anymore
                 except (psutil.AccessDenied, psutil.ZombieProcess):
                      # If access denied or zombie, can't be sure, assume maybe active
                      potentially_active_script_pids.append(pid)
                 except Exception: # Catch other potential psutil errors
                     stale_pids_found = True # Treat errors as potentially stale

             if potentially_active_script_pids and not stale_pids_found:
                 console.print(f"[yellow]Warning:[/yellow] Batch '{batch_file.name}' seems to be already running (PIDs: {potentially_active_script_pids}).")
                 console.print("Use the 'status' command to check details. Consider stopping the existing run before starting a new one.")
                 # Allow running anyway, but warn strongly. Could add a --force flag later.
             elif stale_pids_found:
                 console.print("[yellow]Warning:[/yellow] Found stale process entries for a previous run in the state file. Proceeding with new run.")
                 # Overwrite the old entry by proceeding below

        # --- Start Processes ---
        for i, command in enumerate(commands):
            safe_cmd_name = sanitize_filename(command.split()[0] if command else f"cmd_{i+1}")
            log_filename = f"cmd_{i+1}_{safe_cmd_name}_{run_timestamp}.log"
            log_path = log_dir / log_filename
            log_file = None # Define log_file here to ensure it's available in finally

            try:
                # Open log file first
                log_file = open(log_path, 'w')

                # Use os.setsid for process group separation (Unix-like only)
                preexec = os.setsid if sys.platform != "win32" else None

                process = subprocess.Popen(
                    command,
                    shell=True, # Be cautious with shell=True
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    preexec_fn=preexec,
                    cwd=batch_file.parent # Run command relative to batch file directory
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
                console.print(f"  [green]Started:[/green] PID {process.pid} - '{command}' -> Log: '{log_path.name}'")

            except Exception as e:
                console.print(f"  [red]Failed:[/red] Could not start '{command}': {e}")
                if log_file: # Write failure to log if file was opened
                     log_file.write(f"Failed to start process: {e}\n")
            finally:
                if log_file: # Ensure log file is closed even on Popen error
                    log_file.close()

        # --- Update State File ---
        if not batch_processes:
             console.print("[yellow]Warning:[/yellow] No processes were successfully started.")
             # Don't update state if nothing started
             return

        state_data.setdefault("batches", {})
        state_data["batches"][batch_key] = {
            "file_path": str(batch_file),
            "run_start_time": time.time(),
            "status": "Running", # Overall batch status
            "processes": batch_processes
        }
        save_state(state_path, state_lock, state_data)

        console.print(f"[bold green]Batch run initiated successfully.[/bold] Use 'status --batch-file \"{batch_file}\"' to monitor.")

    except filelock.Timeout:
        console.print(f"[red]Error:[/red] Could not acquire lock on state file '{lock_path}'. Another process might be holding it.")
    except Exception as e:
        console.print(f"[red]An unexpected error occurred during run: {e}[/red]")
        import traceback
        traceback.print_exc() # Print traceback for debugging


def generate_status_table(batch_key: str, state_data: Dict[str, Any], state_path: Path, lock: filelock.FileLock) -> Optional[Table]:
    """Generates the Rich table for the status display. Updates state if discrepancies found."""
    if batch_key not in state_data.get("batches", {}):
        # Check if batch_key is just the filename vs full path
        found_match = None
        for key, batch_info_check in state_data.get("batches", {}).items():
            if Path(batch_info_check.get("file_path", "")).name == Path(batch_key).name:
                batch_key = key # Use the full path key found in state
                found_match = True
                break
        if not found_match:
            console.print(f"No running or previous batch found matching key pattern '*{Path(batch_key).name}*'.")
            console.print(f"Checked state file: '{state_path}'")
            return None


    batch_info = state_data["batches"][batch_key]
    processes_info = batch_info.get("processes", [])
    batch_file_path = Path(batch_info.get("file_path", "Unknown"))
    run_start_time_ts = batch_info.get("run_start_time")
    run_start_str = datetime.datetime.fromtimestamp(run_start_time_ts).strftime(TIMESTAMP_FORMAT) if run_start_time_ts else "Unknown"

    table = Table(
        title=f"Status for Batch: [cyan]{batch_file_path.name}[/cyan] (Path: {batch_file_path.parent})",
        caption=f"Started: {run_start_str}. Press 'q' to quit.",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta"
    )
    table.add_column("PID", style="dim", width=7, justify="right")
    table.add_column("Command", max_width=50)
    table.add_column("Status", justify="center", width=15) # Wider for exit codes
    table.add_column("Runtime", justify="right", width=15)
    table.add_column("CPU %", justify="right", width=7)
    table.add_column("Memory", justify="right", width=10)
    table.add_column("Log File", style="dim", max_width=35)

    state_changed = False
    active_process_count = 0
    now = time.time() # Get time once for consistency

    for i, p_info in enumerate(processes_info):
        pid = p_info.get("pid")
        command = p_info.get("command", "N/A")
        log_path = Path(p_info.get("log_path", "N/A"))
        start_time = p_info.get("start_time")
        current_recorded_status = p_info.get("status", "Unknown")
        end_time = p_info.get("end_time")
        exit_code = p_info.get("exit_code")

        # Default values
        display_status = current_recorded_status
        cpu_usage = "N/A"
        mem_usage = "N/A"
        runtime_seconds = -1
        status_style = "yellow" # Default if unknown/problem

        if pid is None: # Handle case where process failed to start properly
             display_status = "[red]Start Failed[/red]"
             runtime_seconds = -1
             state_changed = state_changed or (current_recorded_status != "Start Failed")
             p_info["status"] = "Start Failed" # Ensure state reflects this
        elif current_recorded_status == "Running":
            try:
                p = psutil.Process(pid)
                if p.is_running():
                    active_process_count += 1
                    with p.oneshot():
                        cpu_usage = f"{p.cpu_percent(interval=0.05):.1f}" # Shorter interval
                        mem_info = p.memory_info()
                        mem_usage = format_bytes(mem_info.rss)
                        ps_status = p.status()
                        # Map psutil status to simpler display statuses
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
                        elif ps_status == psutil.STATUS_ZOMBIE:
                            display_status = "Zombie"
                            status_style = "red"
                            # Treat Zombie as exited for state update purposes
                            current_recorded_status = "Exited" # Trigger state update below
                            p_info["status"] = "Exited"
                            if p_info["end_time"] is None: p_info["end_time"] = now
                            if p_info["exit_code"] is None:
                                try: p_info["exit_code"] = p.wait(timeout=0)
                                except Exception: p_info["exit_code"] = "?"
                            state_changed = True
                        else:
                             display_status = ps_status.capitalize()
                             status_style = "yellow"

                    runtime_seconds = now - start_time if start_time else -1

                else: # Process object exists but not running (e.g., finished between checks)
                    display_status = "Exited"
                    status_style = "yellow"
                    p_info["status"] = "Exited" # Update state
                    if p_info["end_time"] is None: p_info["end_time"] = now
                    if p_info["exit_code"] is None:
                         try: p_info["exit_code"] = p.wait(timeout=0)
                         except Exception: p_info["exit_code"] = "?" # Mark as unknown if error
                    state_changed = True
                    runtime_seconds = (p_info["end_time"] or start_time) - start_time if start_time else -1

            except psutil.NoSuchProcess:
                display_status = "Exited"
                status_style = "red" # Exited unexpectedly (from script's perspective)
                if current_recorded_status == "Running": # Update state only if it was thought to be running
                    p_info["status"] = "Exited"
                    if p_info["end_time"] is None: p_info["end_time"] = now # Approx end time
                    if p_info["exit_code"] is None: p_info["exit_code"] = "?" # Assume abnormal exit
                    state_changed = True
                runtime_seconds = (p_info.get("end_time", start_time) or start_time) - start_time if start_time else -1


            except psutil.AccessDenied:
                display_status = "AccessDenied"
                status_style = "red"
                runtime_seconds = now - start_time if start_time else -1
                active_process_count += 1 # Assume running if access denied

            except Exception as e:
                display_status = "Error"
                status_style = "red"
                console.print(f"\n[red]Error checking PID {pid}: {e}[/red]", file=sys.stderr)
                # Keep process marked as running in state? Let's mark as error status in display only
                runtime_seconds = now - start_time if start_time else -1
                # Don't mark state_changed here unless we decide Error is a final state

        # Handle already exited states
        if p_info.get("status") != "Running" and p_info.get("status") != "Start Failed":
             display_status = p_info.get("status", "Unknown") # Use recorded status
             exit_code = p_info.get("exit_code")
             exit_info = f" (Code: {exit_code})" if exit_code is not None else ""
             display_status = f"Exited{exit_info}"

             if status_style == "yellow": # Set default style if not set by error/zombie above
                 status_style = "dim" if exit_code == 0 else "red" if exit_code != "?" else "yellow"

             runtime_seconds = (p_info.get("end_time", start_time) or start_time) - start_time if start_time else -1

        # Format runtime
        runtime_str = format_duration(runtime_seconds)

        # Truncate command and log file for display
        display_command = (command[:47] + '...') if len(command) > 50 else command
        display_log = (log_path.name[:32] + '...') if len(log_path.name) > 35 else log_path.name

        table.add_row(
            str(pid) if pid else "[dim]N/A[/dim]",
            display_command,
            f"[{status_style}]{display_status}[/{status_style}]",
            runtime_str,
            cpu_usage,
            mem_usage,
            display_log
        )

    # Update overall batch status if no processes are actively running
    if active_process_count == 0 and batch_info.get("status") == "Running" and len(processes_info)>0 :
        batch_info["status"] = "Completed" # Mark overall batch as completed
        # Can add a batch_end_time here if needed: batch_info["run_end_time"] = now
        state_changed = True

    if state_changed:
        # Save the updated state (e.g., process status changes)
        save_state(state_path, lock, state_data)

    return table


def handle_status(args: argparse.Namespace):
    """Displays the status of the running batch processes."""
    batch_file = Path(args.batch_file).resolve()
    state_path, lock_path = get_state_paths(batch_file)
    # Use shared lock for status as it might need to write updates
    state_lock = filelock.FileLock(lock_path, timeout=1)

    batch_key = str(batch_file)

    console.print("Starting status monitor...")

    try:
        # Use transient=True to clean up the table on exit
        with Live(console=console, refresh_per_second=1.5, transient=True) as live:
            while True:
                # Load the latest state within the loop
                # Use a short timeout for status lock acquisition
                try:
                    state_data = load_state(state_path, state_lock)
                except filelock.Timeout:
                     live.update(Panel("[red]Could not acquire state lock. Status might be stale.[/red]", title="Warning", border_style="red"))
                     time.sleep(1) # Wait before retrying lock
                     continue # Skip this update cycle

                # Generate the table (this function also updates state if needed)
                table = generate_status_table(batch_key, state_data, state_path, state_lock)

                if table is None:
                    # generate_status_table already printed message
                    live.update(Panel(f"No active or completed batch found for [cyan]{Path(batch_key).name}[/cyan].\nState file checked: [dim]{state_path}[/dim]", title="Info", border_style="yellow"))
                    # Wait for q press or timeout before exiting
                    try:
                        char = readchar.readkey()
                        if char.lower() == 'q':
                            break
                    except Exception:
                         pass # Ignore input errors
                    time.sleep(1) # Keep message displayed briefly
                    break # Exit loop if batch not found

                live.update(table)

                # Non-blocking check for 'q' with timeout
                try:
                    # readchar with timeout is tricky cross-platform.
                    # A simpler approach is frequent checks with short sleep.
                    start_wait = time.time()
                    char = None
                    while time.time() - start_wait < (1.0 / 1.5): # Check within refresh interval
                        # This part requires a way to check if key is pressed without blocking
                        # readchar doesn't directly support non-blocking check easily cross-platform
                        # For simplicity in this script, we'll rely on the refresh loop and Ctrl+C
                        # or a potentially slightly blocking readkey if available.
                        # Let's assume readchar might block briefly
                        pass # Replace with actual non-blocking check if library supports it

                    # If non-blocking check isn't feasible, use a blocking read with short timeout
                    # This might make refresh slightly less smooth if key is held down
                    # char = readchar.readkey() # This would block until a key is pressed

                    # Alternative: Rely solely on Ctrl+C and the refresh interval sleep
                    time.sleep(1.0 / 1.5) # Sleep for the refresh interval

                    # Check for 'q' IF a non-blocking mechanism was available and returned a char:
                    # if char and char.lower() == 'q':
                    #    break

                except KeyboardInterrupt: # Allow Ctrl+C to exit cleanly
                    break
                except Exception as e:
                     # Log or display error related to reading input if necessary
                     # console.print(f"[red]Input error: {e}[/red]")
                     time.sleep(1.0 / 1.5) # Still sleep


    except KeyboardInterrupt:
        console.print("\nExiting status monitor.")
    except Exception as e:
        console.print(f"[red]An unexpected error occurred during status monitoring: {e}[/red]")
        import traceback
        traceback.print_exc()
    finally:
        # Live(transient=True) should handle cleanup
        pass


# --- Signal Handling ---
def signal_handler(sig, frame):
    """Gracefully handle Ctrl+C or termination signals."""
    console.print("\n[yellow]Signal received, exiting...[/yellow]")
    # Add cleanup here if necessary (e.g., attempt to terminate child process groups)
    # Finding and killing specific child groups reliably can be complex.
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# --- Main Execution ---
def main():
    parser = argparse.ArgumentParser(
        description="Manage and run batches of commands.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  %(prog)s add --batch-file my_jobs.cmds --command "sleep 30 && echo done"
  %(prog)s add --batch-file my_jobs.cmds -f commands.txt
  %(prog)s run --batch-file my_jobs.cmds
  %(prog)s status --batch-file my_jobs.cmds
"""
    )
    subparsers = parser.add_subparsers(dest='action', required=True, help='Action to perform')

    # --- Add Command ---
    parser_add = subparsers.add_parser('add', help='Add commands to a batch file.')
    parser_add.add_argument('--batch-file', required=True, help='Path to the batch file (will be created if needed).')
    add_group = parser_add.add_mutually_exclusive_group(required=True)
    add_group.add_argument('--command', '-c', help='The command string to add.')
    add_group.add_argument('--from-file', '-f', help='Path to a file containing commands to add (one per line).')
    parser_add.set_defaults(func=handle_add)

    # --- Run Command ---
    parser_run = subparsers.add_parser('run', help='Run all commands in a batch file in the background.')
    parser_run.add_argument('--batch-file', required=True, help='Path to the batch file to execute.')
    parser_run.set_defaults(func=handle_run)

    # --- Status Command ---
    parser_status = subparsers.add_parser('status', help='Monitor the status of a running batch.')
    parser_status.add_argument('--batch-file', required=True, help='Path to the batch file being monitored.')
    parser_status.set_defaults(func=handle_status)

    # --- Future Commands (Examples) ---
    # parser_stop = subparsers.add_parser('stop', help='Stop a running batch.')
    # parser_stop.add_argument('--batch-file', required=True, help='Path to the batch file to stop.')
    # parser_stop.add_argument('--force', '-f', action='store_true', help='Force kill processes (SIGKILL).')
    # parser_stop.set_defaults(func=handle_stop) # Need to implement handle_stop

    # parser_list = subparsers.add_parser('list', help='List known batch files and their status.')
    # parser_list.add_argument('--dir', default='.', help='Directory to search for state files (default: current).')
    # parser_list.set_defaults(func=handle_list) # Need to implement handle_list

    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
