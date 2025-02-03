#!/usr/bin/env python3

import argparse
import os
import subprocess
import datetime
import sys
import json

LOG_DIR = os.path.expanduser("~/logs/scripts")
LOG_FILENAME_PREFIX = "git_sync"
DEBUG_ENABLED = False
_current_log_filepath = None

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
    print(log_message, file=sys.stderr)
    if _current_log_filepath:
        with open(_current_log_filepath, "a") as log_file:
            log_file.write(log_message + "\n")

def run_command(command_list, cwd=".", verbose=False, capture_output=False, text=True, color=False):
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
        process = subprocess.run(command_list, cwd=cwd, capture_output=capture_output, text=text, check=False, encoding='utf-8')
        stdout = process.stdout
        stderr = process.stderr
        returncode = process.returncode

        if verbose and stdout:
            verbose_log("Command output:\n" + stdout)
        elif stdout and DEBUG_ENABLED:
            debug_log("Command output:\n" + stdout)
        if verbose and stderr:
            verbose_log("Command stderr:\n" + stderr)
        elif stderr and DEBUG_ENABLED:
            debug_log("Command stderr:\n" + stderr)

        if returncode != 0:
            error_message = f"Command failed with return code {returncode}: {command_str} in {cwd}"
            error_log(error_message)
            if stderr:
                error_log("Stderr:\n" + stderr)
            return stdout, stderr, returncode

        return stdout, stderr, returncode

    except FileNotFoundError as e:
        error_log(f"FileNotFoundError: {e} - Command: {command_str} in {cwd}")
        return None, str(e), 127
    except Exception as e:
        error_log(f"Exception running command: {e} - Command: {command_str} in {cwd}")
        return None, str(e), 1


def get_submodule_names(repo_path):
    """Returns a list of submodule names in the given repository path, filtering out invalid names."""
    command = ["git", "submodule", "status"]
    debug_log(f"get_submodule_names: repo_path={repo_path}")
    stdout, stderr, returncode = run_command(command, cwd=repo_path, capture_output=True, text=True, verbose=DEBUG_ENABLED)
    debug_log(f"get_submodule_names: git submodule status output:\n{stdout}")
    if returncode != 0:
        error_log(f"Error getting submodule status: {stderr}")
        return []
    submodules = []
    for line in stdout.strip().splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            submodule_name = parts[1]
            # Filter out '.' and names starting with '../' to avoid recursion issues
            if submodule_name != '.' and not submodule_name.startswith('../'):
                submodules.append(submodule_name)
            else:
                debug_log(f"get_submodule_names: Filtering out potential invalid submodule name: {submodule_name}") # Debug log for filtering
    return submodules

def summarize_git_status_porcelain(status_output):
    """Creates a concise summary of git status --porcelain output."""
    lines = status_output.strip().splitlines()
    if not lines:
        return "No changes."

    summary_lines = []
    modified_files = []
    untracked_files = []
    submodule_changes = []

    for line in lines:
        if line.startswith("M ") or line.startswith("A ") or line.startswith("D ") or line.startswith("R ") or line.startswith("C "):
            change_type = line[0].strip()
            file_path = line[3:].strip()
            modified_files.append(f"{change_type} {file_path}")
        elif line.startswith("?? "):
            file_path = line[3:].strip()
            untracked_files.append(f"? {file_path}")
        elif line.startswith(" M") and " " in line[2:]:
            parts = line.split()
            if len(parts) >= 2:
                submodule_name = parts[1]
                submodule_changes.append(f"Submodule modified: {submodule_name}")
        elif line.startswith("? pscripts"): # Example for submodule untracked content - adjust as needed
            submodule_name = line[2:].strip()
            submodule_changes.append(f"Submodule untracked content: {submodule_name}")


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
    debug_log(f"Submodule list in handle_submodules: {submodule_list}")

    if not submodule_list:
        debug_log("No submodules found, handle_submodules returning.")
        return

    for submodule_name in submodule_list:
        if submodules_to_process is not None and submodules_to_process != 'all' and submodule_name not in submodules_to_process:
            debug_log(f"Skipping submodule: {submodule_name} as it's not in submodules_to_process: {submodules_to_process}")
            continue

        submodule_path = os.path.join(repo_path, submodule_name)
        debug_log(f"Processing submodule: {submodule_name} at path: {submodule_path}")

        init_command_submodule = ["git", "submodule", "init", submodule_name]
        run_command(init_command_submodule, cwd=repo_path, verbose=verbose)
        update_command_submodule = ["git", "submodule", "update", "--", submodule_name]
        run_command(update_command_submodule, cwd=repo_path, verbose=verbose)

        submodule_add_pattern = submodule_add_patterns.get(submodule_name, ".") if submodule_add_patterns else "."
        add_command_submodule = ["git", "add", submodule_add_pattern]
        stdout, stderr, returncode = run_command(add_command_submodule, cwd=submodule_path, verbose=verbose, capture_output=True, text=True)
        if returncode != 0:
            error_log(f"Error adding changes in submodule {submodule_name}: {stderr}")
            continue

        submodule_branch = submodule_branches.get(submodule_name, branch) if submodule_branches else branch
        if submodule_branch:
            pull_command_submodule = ["git", "pull", "origin", submodule_branch]
        else:
            pull_command_submodule = ["git", "pull", "origin"]

        branch_check_command = ["git", "rev-parse", "--abbrev-ref", "HEAD"]
        stdout_branch_check, _, _ = run_command(branch_check_command, cwd=submodule_path, capture_output=True, text=True, verbose=False)
        current_branch_submodule = stdout_branch_check.strip()

        if current_branch_submodule == "HEAD":
            main_repo_branch = branch if branch else "main"
            checkout_command_submodule = ["git", "checkout", main_repo_branch]
            stdout_checkout, stderr_checkout, returncode_checkout = run_command(checkout_command_submodule, cwd=submodule_path, verbose=verbose, capture_output=True, text=True)
            if returncode_checkout != 0:
                error_log(f"Error checking out branch '{main_repo_branch}' in submodule {submodule_name}: {stderr_checkout}")
                error_log(f"Submodule {submodule_name} might be in detached HEAD, pull might fail.")
            else:
                verbose_log(f"Checked out branch '{main_repo_branch}' in submodule {submodule_name} as it was in detached HEAD.")


        stdout, stderr, returncode = run_command(pull_command_submodule, cwd=submodule_path, verbose=verbose, capture_output=True, text=True)
        if returncode != 0:
            error_log(f"Error pulling changes in submodule {submodule_name}: {stderr}")

        update_command_submodule_recursive = ["git", "submodule", "update", "--recursive", "--", submodule_name]
        stdout, stderr, returncode = run_command(update_command_submodule_recursive, cwd=repo_path, verbose=verbose, capture_output=True, text=True)
        if returncode != 0:
            error_log(f"Error updating submodule {submodule_name}: {stderr}")


def process_git_workflow(add_pattern, force, cwd, branch, submodules_to_process, submodule_add_patterns, submodule_branches, verbose):
    """Main function to process the git workflow."""
    repo_path = cwd
    debug_log(f"process_git_workflow: repo_path={repo_path}")

    print(f"Entering process_git_workflow at: {repo_path}")

    submodule_list = get_submodule_names(repo_path)
    print(f"Submodule list at {repo_path}: {submodule_list}")
    if submodule_list:
        for submodule_name in submodule_list:
            submodule_path = os.path.join(repo_path, submodule_name)
            status_command_submodule = ["git", "status", "--porcelain"]
            stdout_status_submodule, _, _ = run_command(status_command_submodule, cwd=submodule_path, capture_output=True, text=True, verbose=False)
            print(f"Submodule status output for {submodule_name} at {submodule_path}: {stdout_status_submodule}")
            if stdout_status_submodule.strip():
                print(f"--- Processing submodule: {submodule_name} ---")
                process_git_workflow(add_pattern, force, cwd=submodule_path, branch=branch, submodules_to_process='all',
                                       submodule_add_patterns=submodule_add_patterns, submodule_branches=submodule_branches, verbose=verbose)
                print(f"--- Back to main repo from submodule: {submodule_name} ---")
    else:
        print(f"No submodules found at {repo_path}")


    status_command_color = ["git", "status", "--color=always"]
    stdout_status_color, stderr_status_color, returncode_status_color = run_command(status_command_color, cwd=repo_path, capture_output=True, text=True, verbose=verbose)
    if returncode_status_color != 0:
        error_log(f"Error getting git status (color): {stderr_status_color}")
        print("Error getting git status, aborting.")
        return

    print("Current git status:")
    print(stdout_status_color)
    print(f"Using add pattern: '{add_pattern}'")


    status_command_porcelain = ["git", "status", "--porcelain", "-uall"]
    stdout_status_porcelain, stderr_status_porcelain, returncode_status_porcelain = run_command(status_command_porcelain, cwd=repo_path, capture_output=True, text=True, verbose=verbose)
    if returncode_status_porcelain != 0:
        error_log(f"Error getting git status (porcelain): {stderr_status_porcelain}")
        print("Error getting git status summary, summary might be unavailable.")


    if verbose:
        verbose_log("Git status (porcelain output for verbose log):")
        verbose_log(stdout_status_porcelain)
    else:
        print("Git status summary:")
        print(summarize_git_status_porcelain(stdout_status_porcelain))

    if not stdout_status_porcelain.strip():
        print("No changes to commit.")
        return

    add_command_dry_run = ["git", "add", "--dry-run", add_pattern]
    stdout_add_dry_run, _, _ = run_command(add_command_dry_run, cwd=repo_path, capture_output=True, text=True, verbose=verbose)
    if stdout_add_dry_run.strip():
        print("\nChanges to be staged if you continue:")
        print(stdout_add_dry_run)
    else:
        print("\nNo changes to stage with current add pattern.")


    continue_prompt = "Continue to add, commit, pull, and push? (y/n/s) (s = Skip commit, pull, and push): "
    user_input = input(continue_prompt).lower()

    if user_input == 'n':
        print("Aborted by user.")
        return
    elif user_input == 's':
        skip_commit = True
    else:
        skip_commit = False

    if not skip_commit:
        add_command = ["git", "add", add_pattern]
        stdout_add, stderr_add, returncode_add = run_command(add_command, cwd=repo_path, verbose=verbose, capture_output=True, text=text)
        if returncode_add != 0:
            error_log(f"Error during git add: {stderr_add}")
            print("Error during git add, aborting commit, pull, and push.")
            skip_commit = True

        if not verbose:
            stdout_status_after_add_porcelain, stderr_status_after_add_porcelain, returncode_status_after_add_porcelain = run_command(status_command_porcelain, cwd=repo_path, capture_output=True, text=text, verbose=verbose)
            if returncode_status_after_add_porcelain == 0:
                print("Git status after add:")
                print(summarize_git_status_porcelain(stdout_status_after_add_porcelain))
            else:
                error_log(f"Error getting git status after add (porcelain): {stderr_status_after_add_porcelain}")
                print("Warning: Could not get git status after add summary.")


        if not skip_commit:
            commit_message = input("Commit Message (leave empty for default message): ")
            commit_command = ["git", "commit", "-m", commit_message] if commit_message else ["git", "commit"]
            stdout_commit, stderr_commit, returncode_commit = run_command(commit_command, cwd=repo_path, verbose=verbose, capture_output=True, text=text)
            if returncode_commit != 0:
                error_log(f"Error during git commit: {stderr_commit}")
                print("Error during git commit, proceeding with pull and push.")

    pull_command = ["git", "pull"]
    stdout_pull, stderr_pull, returncode_pull = run_command(pull_command, cwd=repo_path, verbose=verbose, capture_output=True, text=text)
    if returncode_pull != 0:
        error_log(f"Error during git pull: {stderr_pull}")
        print("Error during git pull.")

    push_command = ["git", "push"]
    stdout_push, stderr_push, returncode_push = run_command(push_command, cwd=repo_path, verbose=verbose, capture_output=True, text=text)
    if returncode_push != 0:
        error_log(f"Error during git push: {stderr_push}")
        print("Error during git push.")


    submodule_list = get_submodule_names(repo_path)
    if submodule_list:
        handle_submodules(repo_path, add_pattern, force, branch, submodules_to_process, submodule_add_patterns, submodule_branches, verbose=verbose)


if __name__ == "__main__":
    import sys

    parser = argparse.ArgumentParser(description="Synchronize git repository and submodules with add, commit, pull, and push.")
    parser.add_argument("add", nargs="?", default=".", help="Pattern to use for git add (default: '.').")
    parser.add_argument("-f", "--force", action="store_true", help="Force operations if needed (not currently implemented).")
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
    submodule_add_patterns_dict = {}
    submodule_branches_dict = {}

    if args.submodule_add_patterns:
        try:
            submodule_add_patterns_dict = json.loads(args.submodule_add_patterns)
            if not isinstance(submodule_add_patterns_dict, dict):
                error_log("--submodule-add-patterns should be a JSON dictionary, but it's not. Ignoring.")
                submodule_add_patterns_dict = {}
        except json.JSONDecodeError as e:
            error_log(f"Error parsing --submodule-add-patterns JSON: {e}. Ignoring submodule add patterns.")
            submodule_add_patterns_dict = {}

    if args.submodule_branches:
        try:
            submodule_branches_dict = json.loads(args.submodule_branches)
            if not isinstance(submodule_branches_dict, dict):
                error_log("--submodule-branches should be a JSON dictionary, but it's not. Ignoring.")
                submodule_branches_dict = {}
        except json.JSONDecodeError as e:
            error_log(f"Error parsing --submodule-branches JSON: {e}. Ignoring submodule branches.")
            submodule_branches_dict = {}


    process_git_workflow(args.add, args.force, cwd=".", branch=None, submodules_to_process=submodules_to_process_list,
                           submodule_add_patterns=submodule_add_patterns_dict, submodule_branches=submodule_branches_dict, verbose=args.verbose)

    print("Git sync operations completed.")