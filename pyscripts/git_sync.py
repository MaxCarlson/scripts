"""
Automates the git commit workflow with configurable options and submodule support.

Description:
    - Runs `git status` and colorizes output (M=yellow, A=green, ??=red)
    - Adds all changes (or a pattern if `-a <pattern>` or `--add <pattern>` is provided)
    - Displays added files
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

Examples:
    # Run the script with default options (add all, with confirmation)
    python git_sync.py

    # Run the script, adding only Python files
    python git_sync.py -a "*.py"

    # Run the script, adding files in the 'docs' directory
    python git_sync.py --add "docs/"

    # Run the script and force commit without confirmation
    python git_sync.py -f

    # Run the script, adding specific files and forcing commit
    python git_sync.py -a "file1.txt file2.md" --force
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

# ANSI color codes
COLOR_RESET = "\033[0m"
COLOR_RED = "\033[91m"
COLOR_GREEN = "\033[92m"
COLOR_YELLOW = "\033[93m"
COLOR_MAGENTA = "\033[95m"
COLOR_BOLD_MAGENTA = "\033[1;95m"
COLOR_BOLD_CYAN = "\033[1;96m"
COLOR_CYAN = "\033[96m"

def colorize_output(text, color_code):
    """Colorizes text output with ANSI color codes if color is enabled."""
    if color_enabled:  # Use the global flag
        return f"{color_code}{text}{COLOR_RESET}"
    return text

def log_message(level, message):
    """Logs a message with specified level and colorizes level output if enabled."""
    log_level = level.upper()
    log_colors = {
        "INFO": COLOR_CYAN,
        "WARNING": COLOR_YELLOW,
        "ERROR": COLOR_RED,
        "SUCCESS": COLOR_GREEN
    }
    color_code = log_colors.get(log_level, COLOR_RESET)
    colored_level = colorize_output(f"[{log_level}]", color_code) if color_enabled else f"[{log_level}]"
    logging.log(getattr(logging, log_level), f"{colored_level} {message}")


def run_git_command(command, cwd=None, capture_output=True, check=True):
    """
    Runs a git command using subprocess, with improved error handling.

    Args:
        command (list): List of command arguments (e.g., ["git", "status"]).
        cwd (str, optional): Current working directory. Defaults to None.
        capture_output (bool, optional): Whether to capture output. Defaults to True.
        check (bool, optional): Whether to raise an exception on non-zero exit code. Defaults to True.

    Returns:
        subprocess.CompletedProcess: Result of the command execution.
    """
    try:
        log_message("info", f"Executing command: {' '.join(command)}")
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=capture_output,
            text=True,
            check=check
        )
        if capture_output and result.stdout:
            log_message("debug", f"Command output:\n{result.stdout.strip()}")
        if capture_output and result.stderr:
            log_message("debug", f"Command stderr:\n{result.stderr.strip()}") # Log stderr even if successful
        return result
    except subprocess.CalledProcessError as e:
        error_msg = f"Git command failed: {e}\nCommand: {' '.join(command)}\nReturn Code: {e.returncode}"
        if e.stderr:
            error_msg += f"\nError details:\n{e.stderr.strip()}"
        log_message("error", error_msg)
        sys.exit(1)
    except FileNotFoundError:
        log_message("error", "Error: Git command not found. Please ensure Git is installed and in your PATH.")
        sys.exit(1)

def get_default_commit_message():
    """Generates a default commit message with timestamp and username."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user = getpass.getuser()
    return f"{timestamp} - {user}"

def show_git_status(repo_path="."):
    """Displays Git status with color-coded output."""
    status_lines = get_git_status(repo_path)
    if not status_lines:
        return False # Indicate no changes

    log_message("info", "Git Status:")
    for line in status_lines:
        if line.startswith("M"):
            print(colorize_output(line, COLOR_YELLOW))  # Modified
        elif line.startswith("A"):
            print(colorize_output(line, COLOR_GREEN))   # Added
        elif line.startswith("??"):
            print(colorize_output(line, COLOR_RED))     # Untracked
        else:
            print(line)
    return True # Indicate changes were found and displayed

def get_git_status(repo_path="."):
    """Runs git status --short and returns the output lines."""
    result = run_git_command(["git", "status", "--short"], cwd=repo_path, capture_output=True)
    return result.stdout.strip().splitlines()

def git_add_changes(add_pattern=".", repo_path="."):
    """Runs git add with the specified pattern."""
    log_message("info", f"Adding files: {add_pattern}")
    run_git_command(["git", "add", add_pattern], cwd=repo_path)

def get_staged_files(repo_path="."):
    """Gets the list of staged files using git diff --cached --name-status."""
    result = run_git_command(["git", "diff", "--cached", "--name-status"], cwd=repo_path, capture_output=True)
    return result.stdout.strip().splitlines()

def show_staged_files(repo_path="."):
    """Displays staged files with color-coded output."""
    staged_files = get_staged_files(repo_path)
    if not staged_files:
        return False # Indicate no staged files

    log_message("info", "Staged Files:")
    for line in staged_files:
        if line.startswith("M"):
            print(colorize_output(line, COLOR_YELLOW))  # Modified
        elif line.startswith("A"):
            print(colorize_output(line, COLOR_GREEN))   # Added
        elif line.startswith("D"):
            print(colorize_output(line, COLOR_RED))     # Deleted (Red for attention in staged area)
        elif line.startswith("R"):
            print(colorize_output(line, COLOR_CYAN))    # Renamed (Cyan for different type of change)
        elif line.startswith("C"):
            print(colorize_output(line, COLOR_CYAN))    # Copied (Cyan for different type of change)
        elif line.startswith("U"):
            print(colorize_output(line, COLOR_YELLOW))  # Unmerged (Yellow - needs resolving)
        else:
            print(line)
    return True # Indicate staged files were found and displayed


def git_commit_changes(commit_message, repo_path="."):
    """Runs git commit with the given message."""
    log_message("info", "Committing changes")
    run_git_command(["git", "commit", "-m", commit_message], cwd=repo_path)

def git_pull_changes(repo_path=".", branch=None):
    """Runs git pull."""
    pull_command = ["git", "pull"]
    if branch:
        pull_command.extend(["origin", branch]) # Explicitly specify origin and branch
    log_message("info", "Pulling latest changes")
    run_git_command(pull_command, cwd=repo_path)

def git_push_changes(repo_path=".", branch=None):
    """Runs git push."""
    push_command = ["git", "push"]
    if branch:
        push_command.extend(["origin", branch]) # Explicitly specify origin and branch
    log_message("info", "Pushing changes")
    run_git_command(push_command, cwd=repo_path)

def create_local_branch_if_not_exists(repo_path, branch_name):
    """Creates a local branch if it doesn't exist."""
    try:
        run_git_command(["git", "rev-parse", "--quiet", "--verify", branch_name], cwd=repo_path, capture_output=True, check=False)
        branch_exists = True # No exception, branch exists
    except subprocess.CalledProcessError:
        branch_exists = False # Exception, branch doesn't exist

    if not branch_exists:
        log_message("info", f"Branch '{branch_name}' does not exist locally. Creating...")
        run_git_command(["git", "checkout", "-b", branch_name], cwd=repo_path)
    else:
        log_message("info", f"Branch '{branch_name}' already exists locally.")
    return True # Indicate success or branch now exists

def apply_commit_template(template_name, repo_path):
    """Applies a predefined commit message template."""
    templates = {
        "simple": "feat: <Short description>\n\n<Long description if needed>",
        "conventional": "feat(<scope>): <Short description>\n\n<Long description if needed>\n\n<footer>",
        "concise": "<Short description>"
        # Add more templates as needed
    }

    if template_name not in templates:
        log_message("warning", f"Commit template '{template_name}' not found. Using default.")
        return None

    template = templates[template_name]
    log_message("info", f"Using commit template: {template_name}")
    print(colorize_output("\nCommit Message Template:\n", COLOR_BOLD_MAGENTA))
    print(colorize_output(textwrap.dedent(template), COLOR_MAGENTA)) # dedent to remove leading whitespace
    print(colorize_output("\n---", COLOR_BOLD_MAGENTA))

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
                    prompt_text = colorize_output(f"Enter value for '<{placeholder_name}>': ", COLOR_CYAN)
                    placeholders[placeholder_name] = input(prompt_text).strip()
                # Replace placeholder with value (or leave placeholder if no value)
                value = placeholders.get(placeholder_name, f"<{placeholder_name}>") # Fallback to placeholder if no value
                templated_line = templated_line.replace(f"<{placeholder_name}>", value) # Replace just the first instance
        message_lines.append(templated_line) # Append line after placeholder replacement

    commit_message = "\n".join(message_lines)

    print(colorize_output("\n--- Commit Message Preview ---", COLOR_BOLD_CYAN))
    print(colorize_output(commit_message, COLOR_CYAN))
    print(colorize_output("\n---", COLOR_BOLD_CYAN))

    return commit_message

def handle_submodules(repo_path, add_pattern, force, branch, submodules_to_process, submodule_add_patterns, submodule_branches):
    """Handles Git submodules recursively."""
    log_message("info", "Checking for submodules...")
    result = run_git_command(["git", "submodule", "status"], cwd=repo_path, capture_output=True)
    submodules_output = result.stdout.strip().splitlines()

    for line in submodules_output:
        if not line:
            continue # Skip empty lines
        parts = line.split()
        if len(parts) > 1:
            submodule_path = parts[1]
            submodule_name = os.path.basename(submodule_path) # Extract submodule name

            if submodules_to_process != 'all' and submodule_name not in submodules_to_process:
                log_message("info", f"Skipping submodule: {submodule_path} as it's not in the process list.")
                continue # Skip if submodule is not in the list to process

            full_submodule_path = os.path.join(repo_path, submodule_path)
            log_message("info", f"Entering submodule: {full_submodule_path}")

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
                                 submodules_to_process=submodules_to_process, submodule_add_patterns=submodule_add_patterns, submodule_branches=submodule_branches)

def process_git_workflow(add_pattern, force, cwd=".", branch=None, submodules_to_process=None, submodule_add_patterns=None, commit_template=None, submodule_branches=None, create_branch=None):
    """Main function to process the git workflow."""
    repo_path = cwd # More descriptive variable name

    # Handle branch creation if requested and before any operations that might depend on branch
    if create_branch and repo_path == os.getcwd(): # Only for main repo
        create_local_branch_if_not_exists(repo_path, create_branch)

    log_message("info", f"Processing repository: {repo_path}")

    # Check git status
    log_message("info", "Checking Git Status...")
    if not show_git_status(repo_path):
        log_message("success", "No changes detected. Running git pull...")
        git_pull_changes(repo_path, branch=branch)
        return

    # Run git add
    git_add_changes(add_pattern, repo_path)

    # Show staged files
    log_message("info", "Checking Staged Files...")
    if not show_staged_files(repo_path):
        log_message("warning", "No files were staged. Skipping commit.")
        log_message("info", "Proceeding to git pull.")
        git_pull_changes(repo_path, branch=branch)
        return

    # Handle confirmation step unless --force is used
    if not force:
        confirmation = input(colorize_output("Continue? (y/n/s) (s = Skip commit, but continue with git pull): ", COLOR_CYAN)).strip().lower()
        if confirmation == "n":
            log_message("error", "Aborting Git Process")
            return
        elif confirmation == "s":
            log_message("info", "Skipping commit, proceeding to git pull.")
            git_pull_changes(repo_path, branch=branch)
            return

    # Prompt for commit message
    log_message("info", "Prompting for Commit Message")
    if commit_template:
        commit_message = apply_commit_template(commit_template, repo_path)
        if not commit_message: # apply_commit_template can return None if template not found
            commit_message = input(colorize_output("Commit Message (or leave empty for default message): ", COLOR_CYAN)).strip()
    else: # No commit template
        commit_message = input(colorize_output("Commit Message (leave empty for default message): ", COLOR_CYAN)).strip()
        if not commit_message:
            commit_message = get_default_commit_message() # Generate default if still empty

    git_commit_changes(commit_message, repo_path)

    git_pull_changes(repo_path, branch=branch)

    new_commits_result = run_git_command(["git", "log", "--branches", "--not", "--remotes", "--oneline"], cwd=repo_path, capture_output=True)
    new_commits = new_commits_result.stdout.strip()
    if not new_commits:
        log_message("success", "No new commits to push. Process complete.")
    else:
        git_push_changes(repo_path, branch=branch)

    handle_submodules(repo_path, add_pattern, force, branch, submodules_to_process, submodule_add_patterns, submodule_branches) # Process submodules after main module

def print_repo_processing_order(args, submodules_output):
+def print_repo_processing_order(args, submodules_output):
     """Prints the order in which repositories will be processed based on arguments and submodule status."""
     repo_order = ["main repository"] # Main repo is always first
     if submodules_output:
@@ -582,6 +693,7 @@
     parser.add_argument("--submodule-add-patterns", type=str, help="Specify add patterns for submodules (comma-separated, applied to submodules in order).")
     parser.add_argument("--commit-template", type=str, help="Specify commit message template (e.g., 'simple', 'conventional').")
     parser.add_argument("--create-branch", type=str, help="Create a new branch if it doesn't exist (for main repo).")
+    parser.add_argument("--submodule-branches", type=str, help="Specify branches for submodules (comma-separated, applied to submodules in order).")
     parser.add_argument("--submodule-branches", type=str, help="Specify branches for submodules (comma-separated, applied to submodules in order).")

     args = parser.parse_args()
