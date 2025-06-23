import subprocess
import json
import re
import sys
import argparse
import textwrap
from datetime import datetime, timezone
import os
import tempfile
import time
import shutil

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
    """Retrieves a list of GitHub repositories for the authenticated user or a specified user."""
    print_verbose(f"Fetching repository list for '{user or 'authenticated user'}'...")
    cmd = ["repo", "list", "--json", "owner,name,diskUsage,pushedAt", "--limit", "1000"]
    if user:
        cmd.insert(2, user)
    return run_gh_command(cmd, "Failed to list repositories.", json_output=True)

def get_commit_count(owner, repo_name):
    """Retrieves the total commit count for a given repository."""
    api_path = f"/repos/{owner}/{repo_name}/commits"
    cmd_args = ["api", "-i", f"{api_path}?per_page=1"]
    output = run_gh_command(cmd_args, f"Failed to get commit count for {owner}/{repo_name}.", check_error_string="409")

    if output == "EMPTY_REPO": return 0
    if output is None: return -1

    link_header_match = re.search(r'Link:.*<.*?page=(\d+)>; rel="last"', output, re.IGNORECASE)
    if link_header_match: return int(link_header_match.group(1))

    body_start = output.find('\n\n')
    if body_start != -1:
        json_body = output[body_start:].strip()
        if json_body:
            try:
                commits_data = json.loads(json_body)
                if isinstance(commits_data, list): return len(commits_data)
            except json.JSONDecodeError:
                print_verbose(f"Could not parse commit body for {owner}/{repo_name}")
    return 0

def get_submodule_dependencies(owner, repo_name, all_repos_full_names):
    """Identifies submodules within a repository that are also owned by the user."""
    api_path = f"/repos/{owner}/{repo_name}/contents/.gitmodules"
    file_info = run_gh_command(["api", api_path], f"Failed to get .gitmodules for {owner}/{repo_name}.", json_output=True, check_error_string="404")

    if file_info is None: return []
    if not isinstance(file_info, dict) or "content" not in file_info: return []

    submodules = []
    try:
        import base64
        content_decoded = base64.b64decode(file_info["content"]).decode('utf-8')
        submodule_url_pattern = re.compile(r'^\s*url\s*=\s*https://github\.com/([^/]+/[^/]+?)(?:\.git)?$', re.MULTILINE)
        for match in submodule_url_pattern.finditer(content_decoded):
            sub_full_name = match.group(1)
            if sub_full_name in all_repos_full_names:
                submodules.append(sub_full_name)
    except Exception as e:
        print_verbose(f"An unexpected error occurred while parsing submodules for {owner}/{repo_name}: {e}")
    return submodules

def fetch_all_repo_data(args):
    """Fetches and processes data for all repositories, using a cache if available."""
    owner_name = args.user or run_gh_command(["api", "/user", "--jq", ".login"], "Failed to get authenticated user.").strip()

    # --- Caching Logic ---
    cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "github-repos-info")
    cache_file = os.path.join(cache_dir, f"{owner_name}.json")

    if not args.no_cache:
        if os.path.exists(cache_file):
            try:
                mtime = os.path.getmtime(cache_file)
                if (time.time() - mtime) < args.cache_ttl:
                    print_verbose(f"Loading data from cache file: {cache_file}")
                    with open(cache_file, 'r') as f:
                        cached_data = json.load(f)
                        # Re-parse date objects from strings
                        for repo in cached_data['data']:
                            if repo['last_commit_date_str'] != "N/A":
                                repo['last_commit_date_obj'] = datetime.strptime(repo['last_commit_date_str'], '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)
                            else:
                                repo['last_commit_date_obj'] = None
                        return cached_data['data'], owner_name, cached_data['column_widths']
            except (json.JSONDecodeError, KeyError) as e:
                print_verbose(f"Cache file is corrupted, re-fetching. Error: {e}")

    # --- Fetching Logic ---
    repos = get_github_repos(args.user)
    if not repos:
        print(f"No repositories found for '{owner_name}'.", file=sys.stderr)
        return [], owner_name, {}

    repo_data = []
    all_repos_full_names = {f"{r['owner']['login']}/{r['name']}" for r in repos}
    repo_iterator = enumerate(repos)

    if not VERBOSE and sys.stdout.isatty():
        try:
            from tqdm import tqdm
            repo_iterator = tqdm(enumerate(repos), desc=f"Processing {owner_name}'s repositories", unit=" repo", total=len(repos), dynamic_ncols=True, ascii=True, leave=False, file=sys.stdout)
        except ImportError:
            print("Warning: `tqdm` is not installed. No progress bar will be shown.", file=sys.stderr)

    is_sort_flag_set = args.sort_date_asc or args.sort_date_desc
    for i, repo in repo_iterator:
        owner, name = repo["owner"]["login"], repo["name"]
        print_verbose(f"[{i+1}/{len(repos)}] Processing {owner}/{name}...")

        date_str = repo.get("pushedAt")
        date_obj, date_display = None, "N/A"
        if date_str:
            try:
                date_obj = datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
                date_display = date_obj.strftime('%Y-%m-%d %H:%M')
            except (ValueError, TypeError):
                print_verbose(f"Could not parse date '{date_str}' for {owner}/{name}")

        current_repo_info = {"full_name": f"{owner}/{name}", "short_name": name, "size_kb": repo.get("diskUsage", 0), "last_commit_date_obj": date_obj, "last_commit_date_str": date_display, "commits": "N/A", "dependencies": []}
        if args.commits or is_sort_flag_set or args.interactive:
            current_repo_info["commits"] = get_commit_count(owner, name)
        if args.dependencies:
            current_repo_info["dependencies"] = get_submodule_dependencies(owner, name, all_repos_full_names)
        repo_data.append(current_repo_info)

    column_widths = {"name": max(len(r["short_name"]) for r in repo_data) if repo_data else 20, "commits": max(len(str(r.get("commits", "N/A"))) for r in repo_data) if repo_data else 0, "date": 16, "size": max(len(str(r.get("size_kb", "N/A"))) for r in repo_data) if repo_data else 0}
    
    # Save to cache
    if not args.no_cache:
        os.makedirs(cache_dir, exist_ok=True)
        data_to_cache = [r.copy() for r in repo_data]
        for r in data_to_cache:
            del r['last_commit_date_obj']
        with open(cache_file, 'w') as f:
            json.dump({"data": data_to_cache, "column_widths": column_widths}, f)
        print_verbose(f"Saved data to cache file: {cache_file}")

    return repo_data, owner_name, column_widths

# --- TUI and Details View Functions ---

def run_external_command_and_resume_tui(stdscr, command_list):
    """Suspends curses, runs a command, and properly resumes by redrawing the screen."""
    curses.def_prog_mode()
    curses.endwin()
    subprocess.run(command_list)
    curses.reset_prog_mode()
    stdscr.touchwin()
    stdscr.refresh()


def get_repo_details(full_name, detail_type, path="", ref=None):
    """Fetches specific details like logs, branches, or file tree for a repo."""
    api_path = f"/repos/{full_name}/contents/{path}"
    query_params = f"?ref={ref}" if ref else ""
    
    if detail_type == "log":
        api_path = f"/repos/{full_name}/commits"
    elif detail_type == "branches":
        api_path = f"/repos/{full_name}/branches"
    elif detail_type == "file":
        api_path = f"/repos/{full_name}/contents/{path}{query_params}"
    elif detail_type == "tree":
        api_path = f"/repos/{full_name}/contents/{path}{query_params}"
    elif detail_type == "default_branch":
        api_path = f"/repos/{full_name}"
        data = run_gh_command(["api", api_path, "--jq", ".default_branch"], "Failed to get default branch.")
        return data.strip() if data else "main"

    data = run_gh_command(["api", api_path], f"Failed to get {detail_type}", json_output=True, check_error_string="404")

    if detail_type == "log":
        return [f"{c['sha'][:7]} - {c['commit']['message'].splitlines()[0]}" for c in data] if data else ["No commits found."]
    if detail_type == "branches":
        return [b['name'] for b in data] if data else ["No branches found."]
    
    return data if data else []

def view_file(stdscr, repo, item, ref):
    """Downloads a file to a temp location and opens it in nvim."""
    file_content_data = get_repo_details(repo['full_name'], 'file', item['path'], ref=ref)
    if file_content_data and 'content' in file_content_data:
        import base64
        decoded_content = base64.b64decode(file_content_data['content'])
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix=f"_{item['name']}") as tmpfile:
            tmp_path = tmpfile.name
            tmpfile.write(decoded_content)
        run_external_command_and_resume_tui(stdscr, ["nvim", tmp_path])
        os.unlink(tmp_path)
        return True
    return False

def draw_details_ui(stdscr, repo, clone_dir):
    """Draws the detailed view for a single repository."""
    panes, active_pane_idx = ["tree", "log", "branches"], 0
    cursors, tops, current_path = {"log": 0, "branches": 0, "tree": 0}, {"log": 0, "branches": 0, "tree": 0}, ""
    
    current_ref = get_repo_details(repo['full_name'], 'default_branch')
    repo_log = get_repo_details(repo['full_name'], 'log')
    repo_branches = get_repo_details(repo['full_name'], 'branches')
    repo_tree = sorted(get_repo_details(repo['full_name'], 'tree', current_path, ref=current_ref), key=lambda x: x['type'], reverse=True)
    data = {"log": repo_log, "branches": repo_branches, "tree": repo_tree}

    while True:
        h, w = stdscr.getmaxyx()
        stdscr.clear()
        stdscr.refresh()
        
        stdscr.addstr(0, 1, f"Details for {repo['full_name']}", curses.A_BOLD)
        
        top_pane_h = h // 2
        bottom_pane_h = h - top_pane_h - 1 

        log_win = curses.newwin(top_pane_h - 1, w // 2 - 2, 1, 1)
        branch_win = curses.newwin(top_pane_h - 1, w - (w // 2), 1, w // 2)
        tree_win = curses.newwin(bottom_pane_h, w - 2, top_pane_h, 1)
        
        pane_map = {"log": log_win, "branches": branch_win, "tree": tree_win}
        
        for pane_name, win in pane_map.items():
            win.erase()
            is_active = panes[active_pane_idx] == pane_name
            win.box()
            win.addstr(0, 2, f" {pane_name.capitalize()} ", curses.A_BOLD if is_active else 0)
            
            content_h, content_w = win.getmaxyx()
            content_h -= 2
            
            if cursors[pane_name] < tops[pane_name]: tops[pane_name] = cursors[pane_name]
            if cursors[pane_name] >= tops[pane_name] + content_h: tops[pane_name] = cursors[pane_name] - content_h + 1

            for i in range(content_h):
                item_idx = tops[pane_name] + i
                if item_idx >= len(data[pane_name]): break
                item = data[pane_name][item_idx]
                
                display_str = item
                if pane_name == 'tree':
                    display_str = f"📁 {item['name']}" if item['type'] == 'dir' else f"📄 {item['name']}"
                elif pane_name == 'branches':
                    display_str = f"* {item}" if item == current_ref else f"  {item}"

                attr = curses.color_pair(1) if is_active and item_idx == cursors[pane_name] else 0
                win.addstr(i + 1, 1, display_str[:content_w-2], attr)
            
            win.noutrefresh()
        
        footer_path = f"/{current_path}" if current_path else "/"
        footer_ref = f"@{current_ref}" if current_ref else ""
        footer = f"[q]back [tab]pane | [c]lone [e]xplore [v]iew [bksp]up | Path: {footer_path}{footer_ref}"
        stdscr.addstr(h - 1, 0, footer[:w-1], curses.A_REVERSE)
        
        curses.doupdate()

        key = stdscr.getch()
        active_pane = panes[active_pane_idx]
        
        action_taken = False
        if key == ord('q'): break
        elif key == 9: active_pane_idx = (active_pane_idx + 1) % len(panes)
        elif key == curses.KEY_UP: cursors[active_pane] = max(0, cursors[active_pane] - 1)
        elif key == curses.KEY_DOWN: cursors[active_pane] = min(len(data[active_pane]) - 1, cursors[active_pane] + 1)
        elif key == curses.KEY_BACKSPACE and active_pane == 'tree' and current_path:
            leaving_dir_name = os.path.basename(current_path)
            current_path = os.path.dirname(current_path) if os.path.dirname(current_path) != current_path else ""
            data['tree'] = sorted(get_repo_details(repo['full_name'], 'tree', current_path, ref=current_ref), key=lambda x: x['type'], reverse=True)
            
            try:
                new_cursor_pos = [item['name'] for item in data['tree']].index(leaving_dir_name)
                cursors['tree'] = new_cursor_pos
            except ValueError:
                cursors['tree'] = 0
            tops['tree'] = 0
            action_taken = True
        elif key in [curses.KEY_ENTER, 10, 13]:
            if active_pane == 'tree' and data['tree']:
                selected_item = data['tree'][cursors['tree']]
                if selected_item['type'] == 'dir':
                    current_path = selected_item['path']
                    data['tree'] = sorted(get_repo_details(repo['full_name'], 'tree', current_path, ref=current_ref), key=lambda x: x['type'], reverse=True)
                    cursors['tree'] = tops['tree'] = 0
                    action_taken = True
                elif selected_item['type'] == 'file':
                    action_taken = view_file(stdscr, repo, selected_item, current_ref)
            elif active_pane == 'branches' and data['branches']:
                new_ref = data['branches'][cursors['branches']]
                if new_ref != current_ref:
                    current_ref = new_ref
                    current_path = ""
                    cursors['tree'] = tops['tree'] = 0
                    data['tree'] = sorted(get_repo_details(repo['full_name'], 'tree', current_path, ref=current_ref), key=lambda x: x['type'], reverse=True)
                    action_taken = True
        elif key == ord('c'):
            run_external_command_and_resume_tui(stdscr, ["gh", "repo", "clone", repo['full_name']])
            action_taken = True
        elif key == ord('e'):
            repo_clone_path = os.path.join(clone_dir, repo['short_name'])
            if os.path.exists(repo_clone_path):
                print_verbose(f"Repository already cloned. Pulling latest changes for {repo['full_name']}")
                run_external_command_and_resume_tui(stdscr, ["git", "-C", repo_clone_path, "pull"])
            else:
                print_verbose(f"Cloning {repo['full_name']} for exploration.")
                run_external_command_and_resume_tui(stdscr, ["gh", "repo", "clone", repo['full_name'], repo_clone_path])
            run_external_command_and_resume_tui(stdscr, ["nvim", repo_clone_path])
            action_taken = True
        elif key == ord('v') and active_pane == 'tree' and data['tree']:
            selected_item = data['tree'][cursors['tree']]
            if selected_item['type'] == 'file':
                action_taken = view_file(stdscr, repo, selected_item, current_ref)
        
        if action_taken:
            continue

def draw_main_list_ui(stdscr, repo_data, owner_name, column_widths, clone_dir):
    """The main list view TUI."""
    cursor_y, top_of_view, sort_key, sort_reverse = 0, 0, 'commits', True
    sorted_repos = repo_data

    def sort_data():
        nonlocal sorted_repos
        if sort_key == 'name': sorted_repos = sorted(repo_data, key=lambda r: r['short_name'].lower(), reverse=sort_reverse)
        elif sort_key == 'size': sorted_repos = sorted(repo_data, key=lambda r: r.get('size_kb', 0) if isinstance(r.get('size_kb'), int) else -1, reverse=sort_reverse)
        elif sort_key == 'date':
            default_date = datetime.min.replace(tzinfo=timezone.utc) if sort_reverse else datetime.max.replace(tzinfo=timezone.utc)
            sorted_repos = sorted(repo_data, key=lambda r: r['last_commit_date_obj'] or default_date, reverse=sort_reverse)
        else: sorted_repos = sorted(repo_data, key=lambda r: r.get("commits", 0) if isinstance(r.get("commits"), int) else -1, reverse=sort_reverse)
    sort_data()
    
    curses.curs_set(0)
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_WHITE)

    while True:
        stdscr.clear(); h, w = stdscr.getmaxyx()
        stdscr.addstr(0, 0, f"Repositories for {owner_name}"[:w-1], curses.A_BOLD)
        header_parts = [f'{"Repository":<{column_widths["name"]}}', f'{"Commits":>{column_widths["commits"]}}', f'{"Last Commit":<{column_widths["date"]}}', f'{"Size (KB)":>{column_widths["size"]}}']
        stdscr.addstr(1, 0, " | ".join(header_parts), curses.A_BOLD)
        
        list_h = h - 3
        if cursor_y < top_of_view: top_of_view = cursor_y
        if cursor_y >= top_of_view + list_h: top_of_view = cursor_y - list_h + 1

        for i in range(list_h):
            repo_idx = top_of_view + i
            if repo_idx >= len(sorted_repos): break
            repo = sorted_repos[repo_idx]
            line_parts = [f'{repo["short_name"]:<{column_widths["name"]}}', f'{str(repo.get("commits", "N/A")):>{column_widths["commits"]}}', f'{repo["last_commit_date_str"]:<{column_widths["date"]}}', f'{str(repo.get("size_kb", "N/A")):>{column_widths["size"]}}']
            attr = curses.color_pair(1) if repo_idx == cursor_y else 0
            stdscr.addstr(i + 2, 0, " | ".join(line_parts)[:w-1], attr)

        sort_indicator = 'DESC' if sort_reverse else 'ASC'
        status_str = f"Sort: {sort_key.upper()} ({sort_indicator}) | [q]uit | [c]ommits [d]ate [n]ame [s]ize | [r]everse | [Enter]details"
        stdscr.addstr(h - 1, 0, status_str[:w-1], curses.A_REVERSE)
        stdscr.refresh()
        key = stdscr.getch()

        if key == ord('q'): break
        elif key == curses.KEY_UP: cursor_y = max(0, cursor_y - 1)
        elif key == curses.KEY_DOWN: cursor_y = min(len(sorted_repos) - 1, cursor_y + 1)
        elif key == curses.KEY_PPAGE: cursor_y = max(0, cursor_y - list_h)
        elif key == curses.KEY_NPAGE: cursor_y = min(len(sorted_repos) - 1, cursor_y + list_h)
        elif key in [ord('c'), ord('s'), ord('d'), ord('n'), ord('r')]:
            if key == ord('r'): sort_reverse = not sort_reverse
            else:
                key_map = {'c': 'commits', 'd': 'date', 'n': 'name', 's': 'size'}
                new_sort_key = key_map[chr(key)]
                if new_sort_key == sort_key: sort_reverse = not sort_reverse
                else: sort_key, sort_reverse = new_sort_key, True
            cursor_y, top_of_view = 0, 0
            sort_data()
        elif key in [curses.KEY_ENTER, 10, 13]:
            draw_details_ui(stdscr, sorted_repos[cursor_y], clone_dir)


def main():
    parser = argparse.ArgumentParser(description="List GitHub repositories with various statistics.", formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("-i", "--interactive", action="store_true", help="Run the script in an interactive TUI mode.")
    parser.add_argument("-u", "--user", help="Specify a GitHub username or organization (defaults to the authenticated user).")
    parser.add_argument("-c", "--commits", action="store_true", help="Include commit counts and last commit date. (Default for static mode if no other flags)")
    parser.add_argument("-s", "--size", action="store_true", help="Include repository size (in KB).")
    parser.add_argument("-d", "--dependencies", action="store_true", help=textwrap.dedent("Identify submodules that are also owned by the target user.\nNOTE: This is slower as it makes additional API calls per repo."))
    
    cache_group = parser.add_argument_group('caching arguments')
    cache_group.add_argument("--no-cache", action="store_true", help="Force a refresh and ignore any cached data.")
    cache_group.add_argument("--cache-ttl", type=int, default=3600, help="Time-to-live for cache in seconds. Default: 3600 (1 hour).")

    sort_group = parser.add_mutually_exclusive_group()
    sort_group.add_argument("-A", "--sort-date-asc", action="store_true", help="Sort repositories by last commit date in ascending order (oldest first).")
    sort_group.add_argument("-D", "--sort-date-desc", action="store_true", help="Sort repositories by last commit date in descending order (newest first).")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output for debugging and progress.")
    args = parser.parse_args()
    
    print_verbose("Starting script.")
    clone_dir = None

    try:
        if args.interactive:
            if curses is None: sys.exit(1)
            args.commits, args.size = True, True
            clone_dir = os.path.join(os.path.expanduser("~"), ".cache", "github-repos-info", "clones")
            os.makedirs(clone_dir, exist_ok=True)
        
        global VERBOSE
        VERBOSE = args.verbose

        if not (args.commits or args.size or args.dependencies or args.sort_date_asc or args.sort_date_desc or args.interactive):
            args.commits = True

        repo_data, owner_name, column_widths = fetch_all_repo_data(args)
        if not repo_data: return

        if args.interactive:
            curses.wrapper(draw_main_list_ui, repo_data, owner_name, column_widths, clone_dir)
            return

        # Standard Static Display Logic
        if args.sort_date_asc: sorted_repos = sorted(repo_data, key=lambda r: r['last_commit_date_obj'] or datetime.max.replace(tzinfo=timezone.utc))
        elif args.sort_date_desc: sorted_repos = sorted(repo_data, key=lambda r: r['last_commit_date_obj'] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        elif args.commits: sorted_repos = sorted(repo_data, key=lambda r: r.get("commits", 0) if isinstance(r.get("commits"), int) else -1, reverse=True)
        else: sorted_repos = sorted(repo_data, key=lambda r: r["short_name"])

        print(f"\n--- GitHub Repositories for {owner_name} ---")
        if not sorted_repos:
            print("No data to display.")
            return

        header_parts = [f'{"Repository":<{column_widths["name"]}}']
        if args.commits or args.sort_date_asc or args.sort_date_desc:
            header_parts.append(f'{"Commits":>{column_widths["commits"]}}')
            header_parts.append(f'{"Last Commit":<{column_widths["date"]}}')
        if args.size: header_parts.append(f'{"Size (KB)":>{column_widths["size"]}}')
        if args.dependencies: header_parts.append("Dependencies")
        header = " | ".join(header_parts)
        print(header); print("-" * len(header))

        for repo in sorted_repos:
            line_parts = [f'{repo["short_name"]:<{column_widths["name"]}}']
            if args.commits or args.sort_date_asc or args.sort_date_desc:
                line_parts.append(f'{str(repo.get("commits", "N/A")):>{column_widths["commits"]}}')
                line_parts.append(f'{repo["last_commit_date_str"]:<{column_widths["date"]}}')
            if args.size: line_parts.append(f'{str(repo.get("size_kb", "N/A")):>{column_widths["size"]}}')
            line = " | ".join(line_parts)
            if args.dependencies and repo.get("dependencies"): line += f" -> {', '.join(repo['dependencies'])}"
            print(line)
    finally:
        if clone_dir and os.path.exists(clone_dir):
            shutil.rmtree(clone_dir)
            print_verbose(f"Cleaned up clone directory: {clone_dir}")

if __name__ == "__main__":
    main()
