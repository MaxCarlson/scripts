#!/usr/bin/env python3

import argparse
import os
import subprocess
import datetime
import sys # Import sys for stderr

LOG_DIR = os.path.expanduser("~/logs/scripts")
LOG_FILENAME_PREFIX = "git_sync"
DEBUG_ENABLED = False  # Global debug flag
_current_log_filepath = None # Initialize _current_log_filepath to None at global scope

def enable_file_logging():
    """Enables file logging to a timestamped log file."""
    global _current_log_filepath
    log_filepath = _initialize_log_file()
    _current_log_filepath = log_filepath
    debug_log(f"_current_log_filepath after enable_file_logging: {_current_log_filepath}")
    print("[Debug] Enabling file logging...")

def _initialize_log_file():
    """Initializes and returns the log file path."""
    debug_log("_initialize_log_file started")
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d")
    log_filename = f"{LOG_FILENAME_PREFIX}_{timestamp}.log"
    log_filepath = os.path.join(LOG_DIR, log_filename)
    debug_log(f"log_filepath after os.path.join: {log_filepath}")
    debug_log("_initialize_log_file returning: " + log_filepath)
    return log_filepath

def debug_log(message):
    """Prints debug messages to stdout and log file if debugging is enabled."""
    if DEBUG_ENABLED:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_message = f"[Debug] {timestamp} - {message}"
        print(log_message)
        if _current_log_filepath:
            with open(_current_log_filepath, "a") as log_file:
                log_file.write(log_message + "\n")

def verbose_log(message):
    """Prints verbose messages to stdout and log file if verbose logging is enabled."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_message = f"[Verbose] {timestamp} - {message}"
    print(log_message)
    if _current_log_filepath:
        with open(_current_log_filepath, "a") as log_file:
            log_file.write(log_message + "\n")

def error_log(message):
    """Prints error messages to stderr and log file."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_message = f"[Error] {timestamp} - {message}"
    print(log_message, file=sys.stderr) # Print to stderr for errors
    if _current_log_filepath:
        with open(_current_log_filepath, "a") as log_file:
            log_file.write(log_message + "\n")

def run_command(command_list, cwd=".", verbose=False, capture_output=False, text=True):
    """
    Runs a shell command and returns output, error, and return code.
    Handles verbose logging and error reporting.
    """
    command_str = " ".join(command_list)
    if verbose:
        verbose_log(f"Running command: {command_str} in {cwd}")
    else:
        debug_log(f"Running command: {command_str} in {cwd}")

    try:
        process = subprocess.run(command_list, cwd=cwd, capture_output=capture_output, text=text, check=False) # check=False to handle non-zero exit codes ourselves
        stdout = process.stdout
        stderr = process.stderr
        returncode = process.returncode

        if verbose and stdout:
            verbose_log("Command output:\n" + stdout)
        elif stdout and DEBUG_ENABLED: # Only log output in debug mode if not verbose
            debug_log("Command output:\n" + stdout)
        if verbose and stderr:
            verbose_log("Command stderr:\n" + stderr)
        elif stderr and DEBUG_ENABLED: # Only log stderr in debug mode if not verbose
            debug_log("Command stderr:\n" + stderr)

        if returncode != 0:
            error_message = f"Command failed with return code {returncode}: {command_str} in {cwd}"
            error_log(error_message)
            if stderr:
                error_log("Stderr:\n" + stderr) # Always log stderr when there's an error
            return stdout, stderr, returncode # Still return output and stderr even on error

        return stdout, stderr, returncode

    except FileNotFoundError as e:
        error_log(f"FileNotFoundError: {e} - Command: {command_str} in {cwd}")
        return None, str(e), 127 # Return 127 for command not found (like shell)
    except Exception as e:
        error_log(f"Exception running command: {e} - Command: {command_str} in {cwd}")
        return None, str(e), 1 # Generic error code


def get_submodule_names(repo_path):
    """Returns a list of submodule names in the given repository path."""
    command = ["git", "submodule", "status"]
    stdout, stderr, returncode = run_command(command, cwd=repo_path, capture_output=True, text=True, verbose=DEBUG_ENABLED)
    if returncode != 0:
        error_log(f"Error getting submodule status: {stderr}")
        return [] # Return empty list on error, handle upstream if needed
    submodules = []
    for line in stdout.strip().splitlines():
        parts = line.strip().split()
        if len(parts) >= 2: # Handle cases where submodule might not be initialized properly
            submodule_name = parts[1]
            submodules.append(submodule_name)
    return submodules

def summarize_git_status_porcelain(status_output): # Renamed to clarify it's for --porcelain output
    """Creates a concise summary of git status --porcelain output."""
    lines = status_output.strip().splitlines()
    if not lines:
        return "No changes."

    summary_lines = []
    modified_files = []
    untracked_files = []
    submodule_changes = []

    for line in lines:
        if line.startswith("M ") or line.startswith("A ") or line.startswith("D ") or line.startswith("R ") or line.startswith("C "): # Modified, Added, Deleted, Renamed, Copied (staged in index)
            change_type = line[0].strip()
            file_path = line[3:].strip() # Skip status codes and space
            modified_files.append(f"{change_type} {file_path}")
        elif line.startswith("?? "): # Untracked files
            file_path = line[3:].strip()
            untracked_files.append(f"? {file_path}")
        elif line.startswith(" M") and " " in line[2:]: # Modified submodule (commit changed in index)
            parts = line.split()
            if len(parts) >= 2:
                submodule_name = parts[1]
                submodule_changes.append(f"Submodule modified: {submodule_name}")
        elif line.startswith("? pscripts"): # Example for submodule untracked content - adjust as needed
            submodule_name = line[2:].strip() # This might be too specific, improve if needed for other submodule untracked scenarios
            submodule_changes.append(f"Submodule untracked content: {submodule_name}") # More generic handling might be needed if '?' appears in other submodule contexts


    if modified_files:
        summary_lines.append("Modified files:")
        summary_lines.extend([f"  {f}" for f in modified_files])
    if untracked_files:
        summary_lines.append("Untracked files:")
        summary_lines.extend([f"  {f}" for f in untracked_files])
    if submodule_changes:
        summary_lines.append("Submodule changes:")
        summary_lines.extend([f"  {s}" for s in submodule_changes])

    if not summary_lines:
        return "No significant changes to summarize."

    return "\n".join(summary_lines)


def handle_submodules(repo_path, add_pattern, force, branch, submodules_to_process, submodule_add_patterns, submodule_branches, verbose):
    """Handles git submodule operations."""
    debug_log("handle_submodules started")
    submodule_list = get_submodule_names(repo_path)
    debug_log(f"Submodule list: {submodule_list}")

    if not submodule_list:
        debug_log("No submodules found, handle_submodules returning.")
        return

    for submodule_name in submodule_list:
        if submodules_to_process is not None and submodules_to_process != 'all' and submodule_name not in submodules_to_process:
            debug_log(f"Skipping submodule: {submodule_name} as it's not in submodules_to_process: {submodules_to_process}")
            continue # Skip if specific submodules are requested and this one is not in the list

        submodule_path = os.path.join(repo_path, submodule_name)
        debug_log(f"Processing submodule: {submodule_name} at path: {submodule_path}")

        # --- Git Add in Submodule ---
        submodule_add_pattern = submodule_add_patterns.get(submodule_name, ".") if submodule_add_patterns else "." # Default to '.' if no specific pattern
        add_command_submodule = ["git", "add", submodule_add_pattern]
        stdout, stderr, returncode = run_command(add_command_submodule, cwd=submodule_path, verbose=verbose, capture_output=True, text=True)
        if returncode != 0:
            error_log(f"Error adding changes in submodule {submodule_name}: {stderr}")
            continue # Continue to next submodule, but log the error

        # --- Git Commit in Submodule (if needed - logic might be added here later) ---
        # For now, assuming commit is handled in the main repo to include submodule changes

        # --- Git Pull in Submodule ---
        submodule_branch = submodule_branches.get(submodule_name, branch) if submodule_branches else branch # Use submodule-specific branch if defined, else main branch
        if submodule_branch:
            pull_command_submodule = ["git", "pull", "origin", submodule_branch]
        else:
            pull_command_submodule = ["git", "pull", "origin"] # If no branch specified, just pull default
        stdout, stderr, returncode = run_command(pull_command_submodule, cwd=submodule_path, verbose=verbose, capture_output=True, text=True)
        if returncode != 0:
            error_log(f"Error pulling changes in submodule {submodule_name}: {stderr}")
            # Non-critical error, might want to continue to next submodule or handle differently

        # --- Git Submodule Update --recursive (after changes in submodules are pulled) ---
        # This might be redundant if pull already updated the submodule to latest commit, but can be kept for robustness
        update_command_submodule = ["git", "submodule", "update", "--recursive", "--", submodule_name] # Target specific submodule
        stdout, stderr, returncode = run_command(update_command_submodule, cwd=repo_path, verbose=verbose, capture_output=True, text=True) # Run from main repo root
        if returncode != 0:
            error_log(f"Error updating submodule {submodule_name}: {stderr}")
            # Non-critical, can continue


def process_git_workflow(add_pattern, force, cwd, branch, submodules_to_process, submodule_add_patterns, submodule_branches, verbose):
    """Main function to process the git workflow."""
    repo_path = cwd

    # --- Git Status before any changes (Full color output) ---
    status_command_color = ["git", "status"] # No --porcelain for color
    stdout_status_color, stderr_status_color, returncode_status_color = run_command(status_command_color, cwd=repo_path, capture_output=True, text=True, verbose=verbose)
    if returncode_status_color != 0:
        error_log(f"Error getting git status (color): {stderr_status_color}")
        print("Error getting git status, aborting.")
        return

    print("Current git status:") # Header for git status
    print(stdout_status_color) # Print full color git status


    # --- Git Status before any changes (Porcelain for summary) ---
    status_command_porcelain = ["git", "status", "--porcelain", "-uall"] # -uall to show untracked files in submodules
    stdout_status_porcelain, stderr_status_porcelain, returncode_status_porcelain = run_command(status_command_porcelain, cwd=repo_path, capture_output=True, text=True, verbose=verbose)
    if returncode_status_porcelain != 0:
        error_log(f"Error getting git status (porcelain): {stderr_status_porcelain}")
        print("Error getting git status, summary might be unavailable.") # Non-critical for summary

    if verbose:
        verbose_log("Git status (porcelain output for verbose log):")
        verbose_log(stdout_status_porcelain) # Log porcelain output in verbose mode
    else:
        print("Git status summary:")
        print(summarize_git_status_porcelain(stdout_status_porcelain)) # Use porcelain output for summary

    if not stdout_status_porcelain.strip(): # Check porcelain output for changes
        print("No changes to commit.")
        return

    # --- Prompt to continue ---
    continue_prompt = "Continue? (y/n/s) (s = Skip commit, but continue with git pull and push): " # Updated prompt to include push
    user_input = input(continue_prompt).lower()

    if user_input == 'n':
        print("Aborted by user.")
        return
    elif user_input == 's':
        skip_commit = True
    else: # 'y' or anything else
        skip_commit = False

    # --- Git Add ---
    if not skip_commit:
        add_command = ["git", "add", add_pattern]
        stdout_add, stderr_add, returncode_add = run_command(add_command, cwd=repo_path, verbose=verbose, capture_output=True, text=True)
        if returncode_add != 0:
            error_log(f"Error during git add: {stderr_add}")
            print("Error during git add, aborting commit.")
            skip_commit = True # Prevent commit if add failed

        if not verbose: # Show git status after add in non-verbose as well (using porcelain for summary)
            stdout_status_after_add_porcelain, stderr_status_after_add_porcelain, returncode_status_after_add_porcelain = run_command(status_command_porcelain, cwd=repo_path, capture_output=True, text=True, verbose=verbose)
            if returncode_status_after_add_porcelain == 0:
                print("Git status after add:")
                print(summarize_git_status_porcelain(stdout_status_after_add_porcelain))
            else:
                error_log(f"Error getting git status after add (porcelain): {stderr_status_after_add_porcelain}")
                print("Warning: Could not get git status after add summary.")


        # --- Git Commit ---
        if not skip_commit:
            commit_message = input("Commit Message (leave empty for default message): ")
            commit_command = ["git", "commit", "-m", commit_message] if commit_message else ["git", "commit"]
            stdout_commit, stderr_commit, returncode_commit = run_command(commit_command, cwd=repo_path, verbose=verbose, capture_output=True, text=True)
            if returncode_commit != 0:
                error_log(f"Error during git commit: {stderr_commit}")
                print("Error during git commit, proceeding with pull and push.") # Non-critical, try to pull and push anyway

    # --- Git Pull ---
    pull_command = ["git", "pull"]
    stdout_pull, stderr_pull, returncode_pull = run_command(pull_command, cwd=repo_path, verbose=verbose, capture_output=True, text=True)
    if returncode_pull != 0:
        error_log(f"Error during git pull: {stderr_pull}")
        print("Error during git pull.")

    # --- Git Push ---
    push_command = ["git", "push"]
    stdout_push, stderr_push, returncode_push = run_command(push_command, cwd=repo_path, verbose=verbose, capture_output=True, text=True)
    if returncode_push != 0:
        error_log(f"Error during git push: {stderr_push}")
        print("Error during git push.")


    # --- Handle Submodules ---
    submodule_list = get_submodule_names(repo_path)
    if submodule_list:
        handle_submodules(repo_path, add_pattern, force, branch, submodules_to_process, submodule_add_patterns, submodule_branches, verbose=verbose)


if __name__ == "__main__":
    import sys

    parser = argparse.ArgumentParser(description="Synchronize git repository and submodules with add, commit, pull, and push.") # Updated description
    parser.add_argument("add", nargs="?", default=".", help="Pattern to use for git add (default: '.').")
    parser.add_argument("-f", "--force", action="store_true", help="Force operations if needed (not currently implemented).") # Placeholder for future use
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output and logging.")
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug output and logging.")
    parser.add_argument("--submodules", nargs='*', default=None, metavar='SUBMODULE', help="Specific submodules to process (or 'all'). If not specified, all submodules are processed.")
    parser.add_argument("--submodule-add-patterns", type=str, help="JSON string or dict for submodule specific add patterns.")
    parser.add_argument("--submodule-branches", type=str, help="JSON string or dict for submodule specific branches to pull.")


    args = parser.parse_args()

    DEBUG_ENABLED = args.debug

    if args.debug or args.verbose:
        enable_file_logging()

    if args.verbose:
        verbose_log("Verbose mode enabled.")
    if args.debug:
        debug_log("Debug mode enabled.")

    submodules_to_process_list = args.submodules
    if submodules_to_process_list == ['all']:
        submodules_to_process_list = 'all'
    elif isinstance(submodules_to_process_list, list) and not submodules_to_process_list:
        submodules_to_process_list = None

    submodule_add_patterns_dict = {} # Placeholder
    submodule_branches_dict = {} # Placeholder


    process_git_workflow(args.add, args.force, cwd=".", branch=None, submodules_to_process=submodules_to_process_list,
                           submodule_add_patterns=submodule_add_patterns_dict, submodule_branches=submodule_branches_dict, verbose=args.verbose)

    print("Git sync operations completed.")