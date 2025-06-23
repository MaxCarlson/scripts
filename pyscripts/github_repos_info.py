import subprocess
import json
import re
import sys
import argparse
import textwrap
from datetime import datetime, timezone

# Conditionally import curses
try:
    import curses
except ImportError:
    if sys.platform == "win32":
        print("Error: The 'curses' module is required for interactive mode on Windows.", file=sys.stderr)
        print("Please install it with: pip install windows-curses", file=sys.stderr)
    curses = None


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
    print_verbose(f"Fetching repository list for '{user or 'authenticated user'}'...")
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

def draw_interactive_ui(stdscr, repo_data, owner_name, column_widths):
    """The main drawing and event loop for the interactive UI."""
    # State variables
    cursor_y = 0
    top_of_view = 0
    sort_key = 'commits'
    sort_reverse = True
    sorted_repos = repo_data

    # Helper function to re-sort data
    def sort_data():
        nonlocal sorted_repos
        if sort_key == 'name':
            sorted_repos = sorted(repo_data, key=lambda r: r['short_name'].lower(), reverse=sort_reverse)
        elif sort_key == 'size':
            sorted_repos = sorted(repo_data, key=lambda r: r.get('size_kb', 0) if isinstance(r.get('size_kb'), int) else -1, reverse=sort_reverse)
        elif sort_key == 'date':
            # Handle None dates correctly during sorting
            if sort_reverse: # Descending (newest first), None is oldest
                default_date = datetime.min.replace(tzinfo=timezone.utc)
            else: # Ascending (oldest first), None is newest
                default_date = datetime.max.replace(tzinfo=timezone.utc)
            sorted_repos = sorted(repo_data, key=lambda r: r['last_commit_date_obj'] or default_date, reverse=sort_reverse)
        else: # Default to commits
            sorted_repos = sorted(repo_data, key=lambda r: r.get("commits", 0) if isinstance(r.get("commits"), int) else -1, reverse=sort_reverse)

    sort_data() # Initial sort

    # Setup curses
    curses.curs_set(0) # Hide the cursor
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_WHITE) # Highlighted pair

    while True:
        stdscr.clear()
        h, w = stdscr.getmaxyx()
        
        # --- Draw Header ---
        title = f"Repositories for {owner_name}"
        header_parts = [
            f'{"Repository":<{column_widths["name"]}}',
            f'{"Commits":>{column_widths["commits"]}}',
            f'{"Last Commit":<{column_widths["date"]}}',
            f'{"Size (KB)":>{column_widths["size"]}}'
        ]
        header_str = " | ".join(header_parts)
        stdscr.addstr(0, 0, title[:w-1], curses.A_BOLD)
        stdscr.addstr(1, 0, header_str, curses.A_BOLD)
        
        # --- Scrolling Logic ---
        list_h = h - 3 # Height available for the list
        if cursor_y < top_of_view:
            top_of_view = cursor_y
        if cursor_y >= top_of_view + list_h:
            top_of_view = cursor_y - list_h + 1

        # --- Draw Repository List ---
        for i in range(list_h):
            repo_idx = top_of_view + i
            if repo_idx >= len(sorted_repos):
                break
            
            repo = sorted_repos[repo_idx]
            line_parts = [
                f'{repo["short_name"]:<{column_widths["name"]}}',
                f'{str(repo.get("commits", "N/A")):>{column_widths["commits"]}}',
                f'{repo["last_commit_date_str"]:<{column_widths["date"]}}',
                f'{str(repo.get("size_kb", "N/A")):>{column_widths["size"]}}'
            ]
            line_str = " | ".join(line_parts)

            # Highlight the current line
            if repo_idx == cursor_y:
                stdscr.addstr(i + 2, 0, line_str[:w-1], curses.color_pair(1))
            else:
                stdscr.addstr(i + 2, 0, line_str[:w-1])

        # --- Draw Footer/Status Bar ---
        sort_indicator = 'DESC' if sort_reverse else 'ASC'
        status_str = f"Sort: {sort_key.upper()} ({sort_indicator}) | [q]uit | [c]ommits [d]ate [n]ame [s]ize | [r]everse | [Enter]details"
        stdscr.addstr(h - 1, 0, status_str[:w-1], curses.A_REVERSE)

        stdscr.refresh()

        # --- Handle Input ---
        key = stdscr.getch()

        if key == ord('q'):
            break
        elif key == curses.KEY_UP:
            cursor_y = max(0, cursor_y - 1)
        elif key == curses.KEY_DOWN:
            cursor_y = min(len(sorted_repos) - 1, cursor_y + 1)
        elif key == curses.KEY_PPAGE:
            cursor_y = max(0, cursor_y - list_h)
        elif key == curses.KEY_NPAGE:
            cursor_y = min(len(sorted_repos) - 1, cursor_y + list_h)
        elif key in [ord('c'), ord('s'), ord('d'), ord('n'), ord('r')]:
            if key == ord('r'):
                sort_reverse = not sort_reverse
            else:
                key_map = {'c': 'commits', 'd': 'date', 'n': 'name', 's': 'size'}
                new_sort_key = key_map[chr(key)]
                if new_sort_key == sort_key:
                    sort_reverse = not sort_reverse # Toggle reverse if pressing same key
                else:
                    sort_key = new_sort_key
                    sort_reverse = True # Default to descending for new keys
            cursor_y = 0 # Reset cursor on sort change
            top_of_view = 0
            sort_data()
        elif key in [curses.KEY_ENTER, 10, 13]:
            # Placeholder for future feature
            selected_repo = sorted_repos[cursor_y]['full_name']
            stdscr.addstr(h // 2, w // 2 - 20, f" Details for {selected_repo} (not implemented) ", curses.A_REVERSE)
            stdscr.getch() # Wait for another keypress


def main():
    parser = argparse.ArgumentParser(
        description="List GitHub repositories with various statistics.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    # --- Add interactive mode flag ---
    parser.add_argument(
        "-i", "--interactive", action="store_true",
        help="Run the script in an interactive TUI mode."
    )
    parser.add_argument(
        "-u", "--user",
        help="Specify a GitHub username or organization (defaults to the authenticated user)."
    )
    parser.add_argument(
        "-c", "--commits", action="store_true",
        help="Include commit counts and last commit date. (Default for static mode if no other flags)"
    )
    parser.add_argument(
        "-s", "--size", action="store_true",
        help="Include repository size (in KB)."
    )
    parser.add_argument(
        "-d", "--dependencies", action="store_true",
        help=textwrap.dedent("""\
            Identify submodules that are also owned by the target user.
            NOTE: This is slower as it makes additional API calls per repo.""")
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

    # In interactive mode, we need all data, so we override flags
    if args.interactive:
        if curses is None:
            sys.exit(1) # Error message printed during import
        args.commits = True
        args.size = True

    global VERBOSE
    VERBOSE = args.verbose

    # If no data flags are specified in non-interactive mode, default to showing commits.
    is_data_flag_set = args.commits or args.size or args.dependencies
    is_sort_flag_set = args.sort_date_asc or args.sort_date_desc
    if not is_data_flag_set and not is_sort_flag_set and not args.interactive:
        args.commits = True

    # Determine the target owner
    owner_name = args.user
    if not owner_name:
        # Get the authenticated user's login name if no user is specified
        owner_name = run_gh_command(["api", "/user", "--jq", ".login"], "Failed to get authenticated user.").strip()

    print_verbose("Starting script.")
    repos = get_github_repos(args.user)

    if not repos:
        print(f"No repositories found for '{owner_name}'.", file=sys.stderr)
        return

    repo_data = []
    all_my_repos_full_names = {f"{r['owner']['login']}/{r['name']}" for r in repos}
    total_repos = len(repos)
    repo_iterator = enumerate(repos)  # Default iterator

    # Conditionally wrap with a progress bar if not verbose and in a TTY
    if not VERBOSE and sys.stdout.isatty():
        try:
            from tqdm import tqdm
            repo_iterator = tqdm(enumerate(repos),
                                 desc=f"Processing {owner_name}'s repositories",
                                 unit=" repo",
                                 total=total_repos,
                                 dynamic_ncols=True,
                                 ascii=True,
                                 leave=False,
                                 file=sys.stdout)
        except ImportError:
            print("Warning: `tqdm` is not installed. No progress bar will be shown. "
                  "Run `pip install tqdm` to enable it.", file=sys.stderr)

    for i, repo in repo_iterator:
        owner = repo["owner"]["login"]
        name = repo["name"]
        
        print_verbose(f"[{i+1}/{total_repos}] Processing {owner}/{name}...")

        date_str = repo.get("pushedAt")
        date_obj, date_display = None, "N/A"
        if date_str:
            try:
                date_obj = datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
                date_display = date_obj.strftime('%Y-%m-%d %H:%M')
            except (ValueError, TypeError):
                print_verbose(f"Could not parse date '{date_str}' for {owner}/{name}")

        current_repo_info = {
            "full_name": f"{owner}/{name}",
            "short_name": name,
            "size_kb": repo.get("diskUsage", 0),
            "last_commit_date_obj": date_obj,
            "last_commit_date_str": date_display,
            "commits": "N/A",
            "dependencies": []
        }

        if args.commits or is_sort_flag_set or args.interactive:
            commits = get_commit_count(owner, name)
            current_repo_info["commits"] = commits if commits != -1 else "N/A"

        if args.dependencies:
            dependencies = get_submodule_dependencies(owner, name, all_my_repos_full_names)
            current_repo_info["dependencies"] = dependencies

        repo_data.append(current_repo_info)

    # --- Calculate column widths for both modes ---
    max_name_len = max(len(r["short_name"]) for r in repo_data) if repo_data else 20
    max_commits_len = max(len(str(r.get("commits", "N/A"))) for r in repo_data) if (args.commits or args.interactive) else 0
    max_size_len = max(len(str(r.get("size_kb", "N/A"))) for r in repo_data) if (args.size or args.interactive) else 0
    DATE_COL_WIDTH = 16

    column_widths = {
        "name": max_name_len,
        "commits": max_commits_len,
        "date": DATE_COL_WIDTH,
        "size": max_size_len
    }

    if args.interactive:
        curses.wrapper(draw_interactive_ui, repo_data, owner_name, column_widths)
        return

    # --- Standard Static Display Logic ---
    if args.sort_date_asc:
        sorted_repos = sorted(repo_data, key=lambda r: r['last_commit_date_obj'] or datetime.max.replace(tzinfo=timezone.utc))
    elif args.sort_date_desc:
        sorted_repos = sorted(repo_data, key=lambda r: r['last_commit_date_obj'] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    elif args.commits:
        sorted_repos = sorted(repo_data, key=lambda r: r.get("commits", 0) if isinstance(r.get("commits"), int) else -1, reverse=True)
    else:
        sorted_repos = sorted(repo_data, key=lambda r: r["short_name"])

    print(f"\n--- GitHub Repositories for {owner_name} ---")
    if not sorted_repos:
        print("No data to display.")
        return

    show_commits_date = args.commits or is_sort_flag_set
    show_size = args.size
    show_deps = args.dependencies
    
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
        line_parts = [f'{repo["short_name"]:<{max_name_len}}']
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
