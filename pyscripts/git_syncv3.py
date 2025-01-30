"""
Automates the git commit workflow with configurable options and submodule support.

Description:
    - Runs `git status` and colorizes output (M=yellow, A=green, ??=red)  *(Now using debug channels for status info)*
    - Adds all changes (or a pattern if `-a <pattern>` or `--add <pattern>` is provided)
    - Displays added files *(Now using debug channels for staged files info)*
    - Allows skipping the commit (`s` option during confirmation)
    - Prompts for a commit message only if files are staged
    - Runs `git pull` and `git push`
    - Recursively handles submodules, applying the same workflow to each submodule.

Parameters:
    - `-a <pattern>`, `--add <pattern>`:
        A file pattern to add instead of adding everything. Defaults to adding all changes (`.`).
        Example patterns: "*.py", "src/", "README.md"
    - `-f`, `--force`:
        Skips the confirmation prompt before committing. Use with caution.
    - `-v`, `--verbose`:
        Enables verbose debug output for all git commands and operations.
    - `--submodules-to-process <list>`:
        Comma-separated list of submodule names to process. 'all' to process all.
    - `--submodule-add-patterns <list>`:
        Comma-separated list of add patterns for submodules (applied in order).
    - `--commit-template <template_name>`:
        Specify commit message template (e.g., 'simple', 'conventional', 'concise').
    - `--create-branch <branch_name>`:
        Create a new branch if it doesn't exist in the main repository.
    - `--submodule-branches <list>`:
        Comma-separated list of branches for submodules (applied in order).

Examples:
    # Run the script with default options (add all, with confirmation)
    python git_sync.py

    # Run the script, adding only Python files
    python git_sync.py -a "*.py"

    # Run the script, adding files in the 'docs' directory with verbose output
    python git_sync.py --add "docs/" -v

    # Run the script and force commit without confirmation
    python git_sync.py -f

    # Run the script, processing only 'submodule1' and 'submodule2'
    python git_sync.py --submodules-to-process "submodule1,submodule2"

    # Run with a specific commit template
    python git_sync.py --commit-template "conventional"

    # Run and create a new branch 'feature-x' if it doesn't exist
    python git_sync.py --create-branch "feature-x"

    # Run with specific branches for submodules
    python git_sync.py --submodule-branches "develop,main"
"""
#!/usr/bin/env python3

import os
import subprocess
import sys
import argparse
import logging
from datetime import datetime
import textwrap
import getpass
import configparser
from debug_utils import write_debug_v2  # Import the debug_v2 function


def run_git_command(command, cwd=None, capture_output=True, check=True, verbose=False):
    """
    Runs a git command using subprocess, with improved error handling and debug output.

    Args:
        command (list): List of command arguments (e.g., ["git", "status"]).
        cwd (str, optional): Current working directory. Defaults to None.
        capture_output (bool, optional): Whether to capture output. Defaults to True.
        check (bool, optional): Whether to raise an exception on non-zero exit code. Defaults to True.
        verbose (bool, optional): Enable verbose output for this command.

    Returns:
        subprocess.CompletedProcess: Result of the command execution.
    """
    try:
        cmd_str = ' '.join(command)
        write_debug_v2(f"Executing command: {cmd_str}", channel="Info", condition=verbose)
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=capture_output,
            text=True,
            check=check
        )
        if capture_output and result.stdout:
            write_debug_v2(f"Command output:\n{result.stdout.strip()}", channel="Verbose", condition=verbose)
        if capture_output and result.stderr:
            write_debug_v2(f"Command stderr:\n{result.stderr.strip()}", channel="Verbose", condition=verbose)
        return result
    except subprocess.CalledProcessError as e:
        error_msg = f"Git command failed: {e}\nCommand: {' '.join(command)}\nReturn Code: {e.returncode}"
        if e.stderr:
            error_msg += f"\nError details:\n{e.stderr.strip()}"
        write_debug_v2(error_msg, channel="Error", output_stream="stderr")
        sys.exit(1)
    except FileNotFoundError:
        write_debug_v2("Error: Git command not found. Please ensure Git is installed and in your PATH.", channel="Error", output_stream="stderr")
        sys.exit(1)

def get_default_commit_message():
    """Generates a default commit message with timestamp and username."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user = getpass.getuser()
    return f"{timestamp} - {user}"

def show_git_status(repo_path=".", verbose=False):
    """Displays Git status using debug output."""
    status_lines = get_git_status(repo_path, verbose=verbose)
    if not status_lines:
        return False # Indicate no changes

    write_debug_v2("Git Status:", channel="Info", condition=True) # Always show status header
    for line in status_lines:
        if line.startswith("M"):
            write_debug_v2(line, channel="Warning")  # Modified (Yellow in original)
        elif line.startswith("A"):
            write_debug_v2(line, channel="Success")   # Added (Green in original)
        elif line.startswith("??"):
            write_debug_v2(line, channel="Error")     # Untracked (Red in original)
        else:
            write_debug_v2(line, channel="Verbose", condition=verbose) # Less important status lines in verbose mode
    return True # Indicate changes were found and displayed

def get_git_status(repo_path=".", verbose=False):
    """Runs git status --short and returns the output lines."""
    result = run_git_command(["git", "status", "--short"], cwd=repo_path, capture_output=True, verbose=verbose)
    return result.stdout.strip().splitlines()

def git_add_changes(add_pattern=".", repo_path=".", verbose=False):
    """Runs git add with the specified pattern."""
    write_debug_v2(f"Adding files: {add_pattern}", channel="Info", condition=True) # Always show add info
    run_git_command(["git", "add", add_pattern], cwd=repo_path, verbose=verbose)

def get_staged_files(repo_path=".", verbose=False):
    """Gets the list of staged files using git diff --cached --name-status."""
    result = run_git_command(["git", "diff", "--cached", "--name-status"], cwd=repo_path, capture_output=True, verbose=verbose)
    return result.stdout.strip().splitlines()

def show_staged_files(repo_path=".", verbose=False):
    """Displays staged files using debug output."""
    staged_files = get_staged_files(repo_path, verbose=verbose)
    if not staged_files:
        return False # Indicate no staged files

    write_debug_v2("Staged Files:", channel="Info", condition=True) # Always show staged files header
    for line in staged_files:
        if line.startswith("M"):
            write_debug_v2(line, channel="Warning")  # Modified (Yellow in original)
        elif line.startswith("A"):
            write_debug_v2(line, channel="Success")   # Added (Green in original)
        elif line.startswith("D"):
            write_debug_v2(line, channel="Error")     # Deleted (Red in original)
        elif line.startswith("R"):
            write_debug_v2(line, channel="Info")    # Renamed (Cyan in original - Info level is fine)
        elif line.startswith("C"):
            write_debug_v2(line, channel="Info")    # Copied (Cyan in original - Info level is fine)
        elif line.startswith("U"):
            write_debug_v2(line, channel="Warning")  # Unmerged (Yellow - needs resolving)
        else:
            write_debug_v2(line, channel="Verbose", condition=verbose) # Less important staged file info in verbose mode
    return True # Indicate staged files were found and displayed


def git_commit_changes(commit_message, repo_path=".", verbose=False):
    """Runs git commit with the given message."""
    write_debug_v2("Committing changes", channel="Info", condition=True) # Always show commit info
    run_git_command(["git", "commit", "-m", commit_message], cwd=repo_path, verbose=verbose)

def git_pull_changes(repo_path=".", branch=None, verbose=False):
    """Runs git pull."""
    pull_command = ["git", "pull"]
    if branch:
        pull_command.extend(["origin", branch]) # Explicitly specify origin and branch
    write_debug_v2("Pulling latest changes", channel="Info", condition=True) # Always show pull info
    run_git_command(pull_command, cwd=repo_path, verbose=verbose)

def git_push_changes(repo_path=".", branch=None, verbose=False):
    """Runs git push."""
    push_command = ["git", "push"]
    if branch:
        push_command.extend(["origin", branch]) # Explicitly specify origin and branch
    write_debug_v2("Pushing changes", channel="Info", condition=True) # Always show push info
    run_git_command(push_command, cwd=repo_path, verbose=verbose)

def create_local_branch_if_not_exists(repo_path, branch_name, verbose=False):
    """Creates a local branch if it doesn't exist."""
    try:
        run_git_command(["git", "rev-parse", "--quiet", "--verify", branch_name], cwd=repo_path, capture_output=True, check=False, verbose=verbose)
        branch_exists = True # No exception, branch exists
    except subprocess.CalledProcessError:
        branch_exists = False # Exception, branch doesn't exist

    if not branch_exists:
        write_debug_v2(f"Branch '{branch_name}' does not exist locally. Creating...", channel="Info", condition=True) # Always show branch creation info
        run_git_command(["git", "checkout", "-b", branch_name], cwd=repo_path, verbose=verbose)
    else:
        write_debug_v2(f"Branch '{branch_name}' already exists locally.", channel="Info", condition=True) # Always show branch exists info
    return True # Indicate success or branch now exists

def apply_commit_template(template_name, repo_path, verbose=False):
    """Applies a predefined commit message template."""
    templates = {
        "simple": "feat: <Short description>\n\n<Long description if needed>",
        "conventional": "feat(<scope>): <Short description>\n\n<Long description if needed>\n\n<footer>",
        "concise": "<Short description>"
        # Add more templates as needed
    }

    if template_name not in templates:
        write_debug_v2(f"Commit template '{template_name}' not found. Using default.", channel="Warning")
        return None

    template = templates[template_name]
    write_debug_v2(f"Using commit template: {template_name}", channel="Info", condition=True) # Always show template info
    write_debug_v2("\nCommit Message Template:\n", channel="BoldMagenta") # Assuming 'BoldMagenta' channel is handled by debug_utils
    write_debug_v2(textwrap.dedent(template), channel="Magenta")      # Assuming 'Magenta' channel is handled by debug_utils
    write_debug_v2("\n---", channel="BoldMagenta")                   # Assuming 'BoldMagenta' channel is handled by debug_utils

    placeholders = {} # Dictionary to store placeholder values

    # Basic placeholders - extend as needed
    placeholders["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    placeholders["user"] = getpass.getuser()
    placeholders["repo_path"] = repo_path
    placeholders["repo_name"] = os.path.basename(repo_path)

    # Prompt user to fill in template placeholders
    message_lines = []
    for line in template.splitlines():
        templated_line = line
        if "<" in line and ">" in line: # Check if line contains placeholders
            while True: # Loop for each placeholder in the line
                start_index = templated_line.find("<")
                if start_index == -1:
                    break # No more placeholders in this line
                end_index = templated_line.find(">", start_index)
                if end_index == -1:
                    break # Malformed placeholder, but just proceed
                placeholder_name = templated_line[start_index+1:end_index]
                if placeholder_name not in placeholders: # Only prompt for unknown placeholders
                    prompt_text = f"Enter value for '<{placeholder_name}>': "
                    placeholders[placeholder_name] = input(prompt_text).strip()
                # Replace placeholder with value (or leave placeholder if no value)
                value = placeholders.get(placeholder_name, f"<{placeholder_name}>") # Fallback to placeholder if no value
                templated_line = templated_line.replace(f"<{placeholder_name}>", value) # Replace just the first instance
        message_lines.append(templated_line) # Append line after placeholder replacement

    commit_message = "\n".join(message_lines)

    write_debug_v2("\n--- Commit Message Preview ---", channel="BoldCyan") # Assuming 'BoldCyan' channel is handled by debug_utils
    write_debug_v2(commit_message, channel="Cyan")                     # Assuming 'Cyan' channel is handled by debug_utils
    write_debug_v2("\n---", channel="BoldCyan")                      # Assuming 'BoldCyan' channel is handled by debug_utils

    return commit_message

def handle_submodules(repo_path, add_pattern, force, branch, submodules_to_process, submodule_add_patterns, submodule_branches, verbose):
    """Handles Git submodules recursively."""
    write_debug_v2("Checking for submodules...", channel="Info", condition=True) # Always show submodule check info
    result = run_git_command(["git", "submodule", "status"], cwd=repo_path, capture_output=True, verbose=verbose)
    submodules_output = result.stdout.strip().splitlines()

    for line in submodules_output:
        if not line:
            continue # Skip empty lines
        parts = line.split()
        if len(parts) > 1:
            submodule_path = parts[1]
            submodule_name = os.path.basename(submodule_path) # Extract submodule name

            if submodules_to_process != 'all' and submodule_name not in submodules_to_process:
                write_debug_v2(f"Skipping submodule: {submodule_path} as it's not in the process list.", channel="Info")
                continue # Skip if submodule is not in the list to process

            full_submodule_path = os.path.join(repo_path, submodule_path)
            write_debug_v2(f"Entering submodule: {full_submodule_path}", channel="Info", condition=True) # Always show submodule entry

            current_submodule_add_pattern = add_pattern # Default to main repo pattern
            if submodule_add_patterns: # If submodule-specific patterns are provided
                if len(submodule_add_patterns) == 1: # Single pattern for all submodules
                    current_submodule_add_pattern = submodule_add_patterns[0]
                elif len(submodule_add_patterns) >= submodules_output.index(line): # Pattern for each submodule in order
                     current_submodule_add_pattern = submodule_add_patterns[submodules_output.index(line)]
                else:
                    current_submodule_add_pattern = "." # Fallback if not enough patterns provided

            current_submodule_branch = None # Default to no specific branch for submodule
            if submodule_branches:
                if len(submodule_branches) == 1: # Single branch for all submodules
                    current_submodule_branch = submodule_branches[0]
                elif len(submodule_branches) >= submodules_output.index(line): # Branch for each submodule in order
                    current_submodule_branch = submodule_branches[submodules_output.index(line)]
                else:
                    current_submodule_branch = None # Fallback to default branch behavior

            process_git_workflow(current_submodule_add_pattern, force, cwd=full_submodule_path, branch=current_submodule_branch,
                                 submodules_to_process=submodules_to_process, submodule_add_patterns=submodule_add_patterns, submodule_branches=submodule_branches, verbose=verbose)

def process_git_workflow(add_pattern, force, cwd=".", branch=None, submodules_to_process=None, submodule_add_patterns=None, commit_template=None, submodule_branches=None, create_branch=None, verbose=False):
    """Main function to process the git workflow."""
    repo_path = cwd # More descriptive variable name

    # Handle branch creation if requested and before any operations that might depend on branch
    if create_branch and repo_path == os.getcwd(): # Only for main repo
        create_local_branch_if_not_exists(repo_path, create_branch, verbose=verbose)

    write_debug_v2(f"Processing repository: {repo_path}", channel="Info", condition=True) # Always show repo processing info

    # Check git status
    write_debug_v2("Checking Git Status...", channel="Info", condition=True) # Always show status check info
    if not show_git_status(repo_path, verbose=verbose):
        write_debug_v2("No changes detected. Running git pull...", channel="Success")
        git_pull_changes(repo_path, branch=branch, verbose=verbose)
        return

    # Run git add
    git_add_changes(add_pattern, repo_path, verbose=verbose)

    # Show staged files
    write_debug_v2("Checking Staged Files...", channel="Info", condition=True) # Always show staged files check info
    if not show_staged_files(repo_path, verbose=verbose):
        write_debug_v2("No files were staged. Skipping commit.", channel="Warning")
        write_debug_v2("Proceeding to git pull.", channel="Info")
        git_pull_changes(repo_path, branch=branch, verbose=verbose)
        return

    # Handle confirmation step unless --force is used
    if not force:
        confirmation = input("Continue? (y/n/s) (s = Skip commit, but continue with git pull): ").strip().lower()
        if confirmation == "n":
            write_debug_v2("Aborting Git Process", channel="Error")
            return
        elif confirmation == "s":
            write_debug_v2("Skipping commit, proceeding to git pull.", channel="Info")
            git_pull_changes(repo_path, branch=branch, verbose=verbose)
            return

    # Prompt for commit message
    write_debug_v2("Prompting for Commit Message", channel="Info", condition=True) # Always show commit message prompt info
    if commit_template:
        commit_message = apply_commit_template(commit_template, repo_path, verbose=verbose)
        if not commit_message: # apply_commit_template can return None if template not found
            commit_message = input("Commit Message (or leave empty for default message): ").strip()
    else: # No commit template
        commit_message = input("Commit Message (leave empty for default message): ").strip()
        if not commit_message:
            commit_message = get_default_commit_message() # Generate default if still empty

    git_commit_changes(commit_message, repo_path, verbose=verbose)

    git_pull_changes(repo_path, branch=branch, verbose=verbose)

    new_commits_result = run_git_command(["git", "log", "--branches", "--not", "--remotes", "--oneline"], cwd=repo_path, capture_output=True, verbose=verbose)
    new_commits = new_commits_result.stdout.strip()
    if not new_commits:
        write_debug_v2("No new commits to push. Process complete.", channel="Success")
    else:
        git_push_changes(repo_path, branch=branch, verbose=verbose)

    handle_submodules(repo_path, add_pattern, force, branch, submodules_to_process, submodule_add_patterns, submodule_branches, verbose=verbose) # Process submodules after main module


def print_repo_processing_order(args, submodules_output):
    """Prints the order in which repositories will be processed based on arguments and submodule status."""
    repo_order = ["main repository"] # Main repo is always first
    if submodules_output:
        if args.submodules_to_process and args.submodules_to_process != 'all':
            repo_order.extend([f"submodule '{name}'" for name in args.submodules_to_process.split(',') if name in [os.path.basename(path.split()[1]) for path in submodules_output if len(path.split()) > 1]])
        elif args.submodules_to_process == 'all' or not args.submodules_to_process:
            repo_order.extend([f"submodule '{path.split()[1]}'" for path in submodules_output if len(path.split()) > 1])

    write_debug_v2("\nRepository processing order:", channel="Info", condition=True) # Always show processing order
    for i, repo_desc in enumerate(repo_order):
        write_debug_v2(f"{i+1}. {repo_desc}", channel="Info")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Automates the git commit workflow with submodule handling.")
    parser.add_argument("-a", "--add", type=str, default=".", help="File pattern to add instead of adding everything.")
    parser.add_argument("-f", "--force", action="store_true", help="Skips the confirmation prompt.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug output.")
    parser.add_argument("--submodules-to-process", type=str, help="Specify submodules to process (comma-separated names, or 'all').")
    parser.add_argument("--submodule-add-patterns", type=str, help="Specify add patterns for submodules (comma-separated, applied to submodules in order).")
    parser.add_argument("--commit-template", type=str, help="Specify commit message template (e.g., 'simple', 'conventional').")
    parser.add_argument("--create-branch", type=str, help="Create a new branch if it doesn't exist (for main repo).")
    parser.add_argument("--submodule-branches", type=str, help="Specify branches for submodules (comma-separated, applied to submodules in order).")


    args = parser.parse_args()

    submodules_list_output = subprocess.run(["git", "submodule", "status"], capture_output=True, text=True).stdout.strip().splitlines()
    print_repo_processing_order(args, submodules_list_output) # Print processing order upfront

    submodule_add_patterns_list = args.submodule_add_patterns.split(',') if args.submodule_add_patterns else None
    submodule_branches_list = args.submodule_branches.split(',') if args.submodule_branches else None
    submodules_to_process_list = args.submodules_to_process.split(',') if args.submodules_to_process else 'all' if args.submodules_to_process == 'all' else None


    process_git_workflow(args.add, args.force, cwd=".", branch=None, submodules_to_process=submodules_to_process_list,
                         submodule_add_patterns=submodule_add_patterns_list, commit_template=args.commit_template, create_branch=args.create_branch,
                         submodule_branches=submodule_branches_list, verbose=args.verbose)

    write_debug_v2("\nGit sync completed.", channel="Success")
