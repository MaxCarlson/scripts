import os
import threading

def execute_command(command, dry_run=False, force=False):
    """Executes a command with error handling."""
    print(f"Executing: {command}")
    if not dry_run:
        result = os.system(command)
        if result != 0:
            if force:
                print(f"Warning: Command failed but continuing (--force enabled).")
            else:
                print(f"Error: Command failed.")
                exit(1)

def execute_commands(commands, parallel=False, dry_run=False, force=False):
    """Executes multiple commands sequentially or in parallel."""
    if parallel:
        threads = [threading.Thread(target=execute_command, args=(cmd, dry_run, force)) for cmd in commands]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    else:
        for cmd in commands:
            execute_command(cmd, dry_run, force)
