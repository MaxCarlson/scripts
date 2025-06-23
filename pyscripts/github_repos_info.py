import subprocess
import json
import re
import sys
import argparse
import textwrap
from datetime import datetime, timezone

# Global flag for verbose output
VERBOSE = False

def print_verbose(message):
    """Prints a message only if VERBOSE is True."""
    if VERBOSE:
        print(f"VERBOSE: {message}", file=sys.stderr)

def run_gh_command(cmd_args, error_message, json_output=False, check_error_string=None):
    """
    Helper function to run gh CLI commands and handle errors.
    `check_error_string`: if provided, checks if this string is in stderr for specific error handling
                          and returns a special value.
    """
    full_cmd = ["gh"] + cmd_args
    print_verbose(f"Running command: {' '.join(full_cmd)}")
    try:
        process = subprocess.run(full_cmd, capture_output=True, text=True, check=True, encoding='utf-8')
        output_text = process.stdout
        if json_output:
            # gh api -i includes headers, we need to strip them before parsing JSON
            if cmd_args[0] == 'api' and '-i' in cmd_args:
                body_start = output_text.find('\n\n')
                if body_start != -1:
                    output_text = output_text[body_start:].strip()
            return json.loads(output_text)
        return output_text
    except subprocess.CalledProcessError as e:
        if check_error_string and check_error_string in e.stderr:
            print_verbose(f"Handled specific error '{check_error_string}' for '{' '.join(full_cmd)}'")
            if "409" in check_error_string: # For empty repos
                return "EMPTY_REPO"
            return None # General signal for expected non-fatal error (e.g., 404)

        print(f"Error executing '{' '.join(full_cmd)}': {error_message}", file=sys.stderr)
        print(f"Stderr: {e.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON output from '{' '.join(full_cmd)}': {e}", file=sys.stderr)
        # Find the output to print, may be in process if it was defined
        try:
            print(f"Raw output: {process.stdout}", file=sys.stderr)
        except NameError:
             print("Raw output could not be retrieved.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred while running '{' '.join(full_cmd)}': {e}", file=sys.stderr)
        sys.exit(1)

def get_github_repos(user=None):
    """
    Retrieves a list of GitHub repositories for the authenticated user or a specified user.
    """
    print_verbose("Fetching initial list of GitHub repositories...")
    cmd = ["repo", "list", "--json", "owner,name,diskUsage,pushedAt", "--limit", "1000"]
    if user:
        # 'gh repo list' takes the user/org name as a positional argument
        cmd.insert(2, user)

    repos_data = run_gh_command(cmd, "Failed to list repositories.", json_output=True)
    return repos_data

def get_commit_count(owner, repo_name):
    """
    Retrieves the total commit count for a given repository.
    Returns 0 for empty repos (409 Conflict), 1 for single-commit repos without clear count.
    Returns -1 on other errors.
    """
    api_path = f"/repos/{owner}/{repo_name}/commits"
    # Call with per_page=1 to efficiently get the 'Link' header for pagination info
    cmd_args = ["api", "-i", f"{api_path}?per_page=1"]

    output = run_gh_command(cmd_args,
                            f"Failed to get commit count for {owner}/{repo_name}.",
                            check_error_string="409") # Check for empty repo

    if output == "EMPTY_REPO":
        return 0

    if output is None: # An error occurred that wasn't a 409
        return -1

    # Use Link header to find the last page number, which equals the commit count when per_page=1
    link_header_match = re.search(r'Link:.*<.*?page=(\d+)>; rel="last"', output, re.IGNORECASE)
    if link_header_match:
        return int(link_header_match.group(1))

    # Fallback for repos with 0 or 1 commit where no 'last' link is present.
    body_start = output.find('\n\n')
    if body_start != -1:
        json_body = output[body_start:].strip()
        if json_body:
            try:
                commits_data = json.loads(json_body)
                if isinstance(commits_data, list):
                    return len(commits_data) # Could be 0 or 1
            except json.JSONDecodeError:
                print_verbose(f"Could not parse commit body for {owner}/{repo_name}")
                return 0

    return 0 # Default to 0 if no clear count or headers found

def get_submodule_dependencies(owner, repo_name, all_my_repos_full_names):
    """
    Identifies submodules within a repository that are also owned by the user.
    """
    api_path = f"/repos/{owner}/{repo_name}/contents/.gitmodules"

    file_info = run_gh_command(["api", api_path],
                                f"Failed to get .gitmodules for {owner}/{repo_name}.",
                                json_output=True,
                                check_error_string="404") # Check for file not found

    if file_info is None: # 404 Not Found was handled
        print_verbose(f"No .gitmodules file found for {owner}/{repo_name}.")
        return []

    if not isinstance(file_info, dict) or "content" not in file_info:
        print_verbose(f"No .gitmodules content found or unexpected format for {owner}/{repo_name}.")
        return []

    submodules = []
    try:
        import base64
        content_decoded = base64.b64decode(file_info["content"]).decode('utf-8')
        # Regex to find submodule URLs like: url = https://github.com/owner/repo.git
        submodule_url_pattern = re.compile(r'^\s*url\s*=\s*https://github\.com/([^/]+/[^/]+?)(?:\.git)?$', re.MULTILINE)

        for match in submodule_url_pattern.finditer(content_decoded):
            sub_full_name = match.group(1)
            if sub_full_name in all_my_repos_full_names:
                submodules.append(sub_full_name)
    except Exception as e:
        print_verbose(f"An unexpected error occurred while parsing submodules for {owner}/{repo_name}: {e}")

    return submodules

def main():
    parser = argparse.ArgumentParser(
        description="List GitHub repositories with various statistics.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "-u", "--user",
        help="Specify a GitHub username or organization (defaults to the authenticated user)."
    )
    parser.add_argument(
        "-c", "--commits", action="store_true",
        help="Include commit counts and last commit date for each repository. (Default if no other flags)"
    )
    parser.add_argument(
        "-s", "--size", action="store_true",
        help="Include repository size (in KB)."
    )
    parser.add_argument(
        "-d", "--dependencies", action="store_true",
        help=textwrap.dedent("""\
            Identify and list submodules that are also owned by the user.
            NOTE: This is slower as it makes additional API calls per repo.
            Only detects dependencies specified in .gitmodules.""")
    )

    sort_group = parser.add_mutually_exclusive_group()
    sort_group.add_argument(
        "-A", "--sort-date-asc", action="store_true",
        help="Sort repositories by last commit date in ascending order (oldest first)."
    )
    sort_group.add_argument(
        "-D", "--sort-date-desc", action="store_true",
        help="Sort repositories by last commit date in descending order (newest first)."
    )

    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable verbose output for debugging and progress."
    )
    args = parser.parse_args()

    global VERBOSE
    VERBOSE = args.verbose

    # If no data flags are specified, default to showing commits.
    is_data_flag_set = args.commits or args.size or args.dependencies
    is_sort_flag_set = args.sort_date_asc or args.sort_date_desc
    if not is_data_flag_set and not is_sort_flag_set:
        args.commits = True

    print_verbose("Starting script.")
    repos = get_github_repos(args.user)

    if not repos:
        print("No repositories found.", file=sys.stderr)
        return

    repo_data = []
    all_my_repos_full_names = {f"{r['owner']['login']}/{r['name']}" for r in repos}

    total_repos = len(repos)
    for i, repo in enumerate(repos):
        owner = repo["owner"]["login"]
        name = repo["name"]
        full_name = f"{owner}/{name}"
        print_verbose(f"[{i+1}/{total_repos}] Processing {full_name}...")

        date_str = repo.get("pushedAt")
        date_obj, date_display = None, "N/A"
        if date_str:
            try:
                # Handle Z timezone format
                date_obj = datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
                date_display = date_obj.strftime('%Y-%m-%d %H:%M')
            except (ValueError, TypeError):
                print_verbose(f"Could not parse date '{date_str}' for {full_name}")

        current_repo_info = {
            "name": full_name,
            "size_kb": repo.get("diskUsage", 0),
            "last_commit_date_obj": date_obj,
            "last_commit_date_str": date_display,
            "commits": "N/A",
            "dependencies": []
        }

        if args.commits or is_sort_flag_set:
            print_verbose(f"  Getting commit count for {full_name}...")
            commits = get_commit_count(owner, name)
            current_repo_info["commits"] = commits if commits != -1 else "N/A"

        if args.dependencies:
            print_verbose(f"  Checking for submodule dependencies in {full_name}...")
            dependencies = get_submodule_dependencies(owner, name, all_my_repos_full_names)
            current_repo_info["dependencies"] = dependencies

        repo_data.append(current_repo_info)

    # --- Sorting ---
    if args.sort_date_asc:
        # For ascending sort, None dates go to the end by treating them as max datetime
        sorted_repos = sorted(
            repo_data,
            key=lambda r: r['last_commit_date_obj'] or datetime.max.replace(tzinfo=timezone.utc)
        )
    elif args.sort_date_desc:
        # For descending sort, None dates go to the end by treating them as min datetime
        sorted_repos = sorted(
            repo_data,
            key=lambda r: r['last_commit_date_obj'] or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True
        )
    elif args.commits: # Default sort by commits if -c is specified or by default
        sorted_repos = sorted(
            repo_data,
            key=lambda r: r.get("commits", 0) if isinstance(r.get("commits"), int) else -1,
            reverse=True
        )
    else: # Fallback to alphabetical sort
        sorted_repos = sorted(repo_data, key=lambda r: r["name"])

    # --- Display ---
    print("\n--- GitHub Repositories Information ---")
    if not sorted_repos:
        print("No data to display.")
        return

    # Determine which columns to show and their widths
    show_commits_date = args.commits or is_sort_flag_set
    show_size = args.size
    show_deps = args.dependencies

    max_name_len = max(len(r["name"]) for r in sorted_repos) if sorted_repos else 0
    max_commits_len = max(len(str(r.get("commits", "N/A"))) for r in sorted_repos) if show_commits_date else 0
    max_size_len = max(len(str(r.get("size_kb", "N/A"))) for r in sorted_repos) if show_size else 0
    DATE_COL_WIDTH = 16 # Fixed width for 'YYYY-MM-DD HH:MM'

    header_parts = [f'{"Repository":<{max_name_len}}']
    if show_commits_date:
        header_parts.append(f'{"Commits":>{max_commits_len}}')
        header_parts.append(f'{"Last Commit":<{DATE_COL_WIDTH}}')
    if show_size:
        header_parts.append(f'{"Size (KB)":>{max_size_len}}')
    if show_deps:
        header_parts.append("Dependencies")

    header = " | ".join(header_parts)
    print(header)
    print("-" * len(header))

    for repo in sorted_repos:
        line_parts = [f'{repo["name"]:<{max_name_len}}']
        if show_commits_date:
            line_parts.append(f'{str(repo.get("commits", "N/A")):>{max_commits_len}}')
            line_parts.append(f'{repo["last_commit_date_str"]:<{DATE_COL_WIDTH}}')
        if show_size:
            line_parts.append(f'{str(repo.get("size_kb", "N/A")):>{max_size_len}}')

        line = " | ".join(line_parts)
        if show_deps and repo.get("dependencies"):
            line += f" -> {', '.join(repo['dependencies'])}"
        print(line)

if __name__ == "__main__":
    main()
