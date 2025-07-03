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
from collections import defaultdict

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
# Global flag to ensure the 'tokei not found' warning is only printed once.
_tokei_warning_issued = False

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
    cmd = ["repo", "list", "--json", "owner,name,diskUsage,pushedAt,isPrivate", "--limit", "1000"]
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

def get_gh_token():
    """Retrieves the GitHub token from gh."""
    try:
        return subprocess.check_output(["gh", "auth", "token"], text=True).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

def manage_repo_clone(full_name, clone_dir, keep_clones=False, bare=False):
    """
    Manages repository clones. By default, uses a temporary directory.
    If keep_clones is True, uses a persistent directory.
    Returns the path to the repo and a boolean indicating if it's temporary.
    """
    if keep_clones:
        repo_path = os.path.join(clone_dir, full_name.replace('/', '_'))
        is_temp = False
        temp_dir_obj = None
    else:
        # Use a temporary directory that will be cleaned up automatically
        temp_dir_obj = tempfile.TemporaryDirectory()
        repo_path = temp_dir_obj.name
        is_temp = True

    if os.path.exists(repo_path) and not is_temp:
        print_verbose(f"Fetching updates for {full_name} in {repo_path}...")
        try:
            fetch_cmd = ["git", "fetch", "--all", "--prune"]
            subprocess.run(fetch_cmd, cwd=repo_path, check=True, capture_output=True, text=True)
            return repo_path, None
        except subprocess.CalledProcessError as e:
            print(f"Failed to update {full_name}. Error: {e.stderr.strip()}", file=sys.stderr)
            return None, None # Indicate failure
    else:
        print_verbose(f"Cloning {full_name} into {repo_path}...")
        token = get_gh_token()
        if token:
            repo_url = f"https://{token}@github.com/{full_name}.git"
        else:
            repo_url = f"https://github.com/{full_name}.git"
            print_verbose("No gh token found, cloning via standard HTTPS. May require interactive auth.")

        clone_cmd = ["git", "clone", "--progress", repo_url, repo_path]
        if bare:
            clone_cmd.insert(2, "--bare")
        
        try:
            # Use stderr=subprocess.STDOUT to capture git's progress output in stdout
            result = subprocess.run(clone_cmd, check=True, text=True, capture_output=True)
            print_verbose(result.stdout)
            return repo_path, temp_dir_obj if is_temp else None
        except subprocess.CalledProcessError as e:
            if "repository not found" in str(e.stdout) or "does not appear to be a git repository" in str(e.stdout):
                print_verbose(f"Skipping {full_name} (likely empty or not found).")
            else:
                print(f"Failed to clone {full_name}. Error: {e.stdout.strip()}", file=sys.stderr)
            return None, None

def get_loc_stats(full_name, clone_dir, use_latest_branch=False):
    """Clones/updates a repo and runs 'tokei' to get LOC stats."""
    global _tokei_warning_issued
    if not shutil.which("tokei"):
        if not _tokei_warning_issued:
            print("Warning: 'tokei' command not found, skipping LOC analysis. Install from https://github.com/XAMPPRocky/tokei", file=sys.stderr)
            _tokei_warning_issued = True
        return None

    repo_path = manage_repo_clone(full_name, clone_dir, bare=False)
    if not repo_path:
        return None

    if use_latest_branch:
        print_verbose(f"Finding and checking out the latest branch for {full_name}...")
        try:
            branches_raw = subprocess.check_output(
                ["git", "for-each-ref", "--sort=-committerdate", "refs/remotes", "--format=%(refname:short)"],
                cwd=repo_path, text=True
            ).strip().split('\n')
            
            if branches_raw and branches_raw[0]:
                latest_branch_name = branches_raw[0].split('/', 1)[1]
                print_verbose(f"Latest branch is '{latest_branch_name}'. Checking it out...")
                subprocess.run(["git", "checkout", latest_branch_name], cwd=repo_path, check=True, capture_output=True)
        except Exception as e:
            print(f"An error occurred while finding the latest branch for {full_name}: {e}", file=sys.stderr)

    print_verbose(f"Running 'tokei' on {repo_path}...")
    tokei_cmd = ["tokei", "--output", "json", repo_path]
    try:
        process = subprocess.run(tokei_cmd, capture_output=True, text=True, check=True, encoding='utf-8')
        return json.loads(process.stdout)
    except Exception as e:
        print(f"Error running or parsing 'tokei' on {full_name}: {e}", file=sys.stderr)
        return None

def fetch_all_repo_data(args):
    """Fetches and processes data for all repositories, using a cache if available."""
    owner_name = args.user or run_gh_command(["api", "/user", "--jq", ".login"], "Failed to get authenticated user.").strip()
    clone_dir = args.clone_dir or os.path.join(os.path.expanduser("~"), ".cache", "github-repos-info", "clones")
    os.makedirs(clone_dir, exist_ok=True)

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
                        
                        is_cache_sufficient = True
                        if args.loc:
                            first_repo = cached_data.get("data", [{}])[0]
                            if "loc_stats" not in first_repo:
                                print_verbose("Cache does not contain LOC data, re-fetching.")
                                is_cache_sufficient = False

                        if is_cache_sufficient:
                            for repo in cached_data['data']:
                                if repo.get('last_commit_date_str') != "N/A":
                                    repo['last_commit_date_obj'] = datetime.strptime(repo['last_commit_date_str'], '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)
                                else:
                                    repo['last_commit_date_obj'] = None
                            return cached_data['data'], owner_name, cached_data['column_widths']
            except (json.JSONDecodeError, KeyError, IndexError) as e:
                print_verbose(f"Cache file is corrupted or outdated, re-fetching. Error: {e}")

    # --- Fetching Logic ---
    repos = get_github_repos(args.user)
    if not repos:
        print(f"No repositories found for '{owner_name}'.", file=sys.stderr)
        return [], owner_name, {}
    
    if args.max_repos is not None:
        repos = repos[:args.max_repos]

    repo_data = []
    all_repos_full_names = {f"{r['owner']['login']}/{r['name']}" for r in repos}
    
    repo_iterator = enumerate(repos)
    
    if not VERBOSE and sys.stdout.isatty() and not args.loc:
        try:
            from tqdm import tqdm
            repo_iterator = tqdm(enumerate(repos), desc=f"Processing {owner_name}'s repositories", unit=" repo", total=len(repos), dynamic_ncols=True, ascii=True, leave=False, file=sys.stdout)
        except ImportError:
            print("Warning: `tqdm` is not installed. No progress bar will be shown.", file=sys.stderr)

    for i, repo in repo_iterator:
        owner, name = repo["owner"]["login"], repo["name"]
        full_name = f"{owner}/{name}"
        if 'tqdm' in sys.modules and isinstance(repo_iterator, sys.modules['tqdm'].tqdm):
            repo_iterator.set_description(f"Processing {full_name}", refresh=True)

        if not args.loc:
            print_verbose(f"[{i+1}/{len(repos)}] Processing {full_name}...")

        date_str = repo.get("pushedAt")
        date_obj, date_display = None, "N/A"
        if date_str:
            try:
                date_obj = datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
                date_display = date_obj.strftime('%Y-%m-%d %H:%M')
            except (ValueError, TypeError):
                print_verbose(f"Could not parse date '{date_str}' for {full_name}")

        current_repo_info = {
            "full_name": full_name,
            "short_name": name,
            "isPrivate": repo.get("isPrivate", False),
            "size_kb": repo.get("diskUsage", 0),
            "last_commit_date_obj": date_obj,
            "last_commit_date_str": date_display,
            "commits": "N/A",
            "dependencies": [],
            "loc_stats": None
        }
        
        if args.loc:
            if sys.stdout.isatty() and not VERBOSE:
                sys.stdout.write("\033[H\033[J")
                sys.stdout.flush()
            print(f"--- LOC Analysis for {owner_name} ---")
            print(f"Processing {i + 1}/{len(repos)}: {full_name}")
            current_repo_info["loc_stats"] = get_loc_stats(full_name, clone_dir, args.use_latest_branch)
        
        if args.commits or args.sort_date_asc or args.sort_date_desc or args.interactive:
            current_repo_info["commits"] = get_commit_count(owner, name)
        if args.dependencies:
            current_repo_info["dependencies"] = get_submodule_dependencies(owner, name, all_repos_full_names)
        
        repo_data.append(current_repo_info)

        if args.loc:
            if sys.stdout.isatty() and not VERBOSE:
                sys.stdout.write("\033[H\033[J")
                sys.stdout.flush()
            
            print(f"--- LOC Analysis for {owner_name} ---")
            print(f"Processed {i + 1}/{len(repos)}: {full_name}")
            print_loc_live_summary(repo_data)

    column_widths = {"name": max(len(r["short_name"]) for r in repo_data) if repo_data else 20, "commits": max(len(str(r.get("commits", "N/A"))) for r in repo_data) if repo_data else 0, "date": 16, "size": max(len(str(r.get("size_kb", "N/A"))) for r in repo_data) if repo_data else 0}
    
    if not args.no_cache:
        os.makedirs(cache_dir, exist_ok=True)
        data_to_cache = [r.copy() for r in repo_data]
        for r in data_to_cache:
            if 'last_commit_date_obj' in r:
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
    query_params = f"?ref={ref}" if ref else ""
    
    if detail_type == "log":
        api_path = f"/repos/{full_name}/commits{query_params}"
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

def view_file_in_editor(stdscr, repo, item, ref):
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
    view_mode = 'standard'
    panes, active_pane_idx = [], 0
    cursors = {"log": 0, "branches": 0, "tree": 0, "preview": 0}
    tops = {"log": 0, "branches": 0, "tree": 0, "preview": 0}
    current_path = ""
    
    current_ref = get_repo_details(repo['full_name'], 'default_branch')
    repo_log = get_repo_details(repo['full_name'], 'log', ref=current_ref)
    repo_branches = get_repo_details(repo['full_name'], 'branches')
    if current_ref not in repo_branches:
        repo_branches.insert(0, current_ref)

    repo_tree = sorted(get_repo_details(repo['full_name'], 'tree', current_path, ref=current_ref), key=lambda x: x['type'], reverse=True)
    data = {"log": repo_log, "branches": repo_branches, "tree": repo_tree}

    preview_content = ["Select a file to preview its content."]
    last_previewed_item = None

    while True:
        h, w = stdscr.getmaxyx()
        
        selected_item_in_tree = data['tree'][cursors['tree']] if cursors['tree'] < len(data['tree']) else None
        if view_mode == 'preview' and selected_item_in_tree != last_previewed_item:
            if selected_item_in_tree and selected_item_in_tree['type'] == 'file':
                content_data = get_repo_details(repo['full_name'], 'file', selected_item_in_tree['path'], ref=current_ref)
                if content_data and 'content' in content_data:
                    import base64
                    try:
                        decoded_content = base64.b64decode(content_data['content']).decode('utf-8')
                        preview_content = decoded_content.splitlines()
                    except (UnicodeDecodeError, TypeError):
                        preview_content = ["[Binary file or content not displayable]"]
                else:
                    preview_content = ["[Could not load file content]"]
            else:
                preview_content = ["Select a file to preview its content."]
            last_previewed_item = selected_item_in_tree
            cursors['preview'] = tops['preview'] = 0

        stdscr.clear()
        stdscr.refresh()
        
        stdscr.addstr(0, 1, f"Details for {repo['full_name']}", curses.A_BOLD)
        
        top_pane_h = h // 2
        bottom_pane_h = h - top_pane_h - 1 

        if view_mode == 'standard':
            panes = ['tree', 'log', 'branches']
            if active_pane_idx >= len(panes): active_pane_idx = 0
            log_win = curses.newwin(top_pane_h - 1, w // 2 - 2, 1, 1)
            branch_win = curses.newwin(top_pane_h - 1, w - (w // 2), 1, w // 2)
            tree_win = curses.newwin(bottom_pane_h, w - 2, top_pane_h, 1)
            pane_map = {"log": log_win, "branches": branch_win, "tree": tree_win}
        else: # preview mode
            panes = ['tree', 'preview']
            if active_pane_idx >= len(panes): active_pane_idx = 0
            preview_win = curses.newwin(top_pane_h - 1, w - 2, 1, 1)
            tree_win = curses.newwin(bottom_pane_h, w - 2, top_pane_h, 1)
            pane_map = {"preview": preview_win, "tree": tree_win}

        for pane_name, win in pane_map.items():
            win.erase()
            is_active = panes[active_pane_idx] == pane_name
            win.box()
            title = pane_name.capitalize()
            if pane_name == 'preview' and selected_item_in_tree and selected_item_in_tree['type'] == 'file':
                title = f"Preview: {selected_item_in_tree['name']}"
            win.addstr(0, 2, f" {title} ", curses.A_BOLD if is_active else 0)
            
            content_h, content_w = win.getmaxyx()
            content_h -= 2
            
            current_cursor = cursors[pane_name]
            current_top = tops[pane_name]
            if current_cursor < current_top: tops[pane_name] = current_cursor
            if current_cursor >= current_top + content_h: tops[pane_name] = current_cursor - content_h + 1

            pane_data = data.get(pane_name, preview_content)
            for i in range(content_h):
                item_idx = tops[pane_name] + i
                if item_idx >= len(pane_data): break
                item = pane_data[item_idx]
                
                display_str = item
                if pane_name == 'tree':
                    display_str = f"📁 {item['name']}" if item['type'] == 'dir' else f"📄 {item['name']}"
                elif pane_name == 'branches':
                    display_str = f"* {item}" if item == current_ref else f"  {item}"

                attr = curses.color_pair(1) if is_active and item_idx == cursors[pane_name] else 0
                win.addstr(i + 1, 1, display_str[:content_w-2], attr)
            
            win.noutrefresh()
        
        footer_path = f"/{current_path}" if current_path else "/"
        footer_ref = f"@{current_ref}"
        footer = f"[q]back [tab]pane [v]iew toggle [bksp]up | Path: {footer_path}{footer_ref}"
        stdscr.addstr(h - 1, 0, footer[:w-1], curses.A_REVERSE)
        
        curses.doupdate()

        key = stdscr.getch()
        active_pane = panes[active_pane_idx]
        
        action_taken = False
        if key == ord('q'): break
        elif key == ord('v'):
            view_mode = 'preview' if view_mode == 'standard' else 'standard'
            action_taken = True
        elif key == 9: active_pane_idx = (active_pane_idx + 1) % len(panes)
        elif key == curses.KEY_UP: cursors[active_pane] = max(0, cursors[active_pane] - 1)
        elif key == curses.KEY_DOWN:
            max_val = len(data.get(active_pane, preview_content)) - 1
            cursors[active_pane] = min(max_val, cursors[active_pane] + 1)
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
            if active_pane == 'tree' and selected_item_in_tree:
                if selected_item_in_tree['type'] == 'dir':
                    current_path = selected_item_in_tree['path']
                    data['tree'] = sorted(get_repo_details(repo['full_name'], 'tree', current_path, ref=current_ref), key=lambda x: x['type'], reverse=True)
                    cursors['tree'] = tops['tree'] = 0
                    action_taken = True
                elif selected_item_in_tree['type'] == 'file':
                    action_taken = view_file_in_editor(stdscr, repo, selected_item_in_tree, current_ref)
            elif active_pane == 'branches' and data['branches']:
                new_ref = data['branches'][cursors['branches']]
                if new_ref != current_ref:
                    current_ref = new_ref
                    current_path = ""
                    cursors['tree'] = tops['tree'] = 0
                    data['tree'] = sorted(get_repo_details(repo['full_name'], 'tree', current_path, ref=current_ref), key=lambda x: x['type'], reverse=True)
                    data['log'] = get_repo_details(repo['full_name'], 'log', ref=current_ref)
                    action_taken = True
        
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

def get_terminal_height():
    """Gets the terminal height, returns a default if not available."""
    try:
        return os.get_terminal_size().lines
    except OSError:
        return 24 # Default height

def print_table(title, stats, is_live=False):
    """Prints a formatted table for LOC stats."""
    if not stats:
        if not is_live:
            print(f"\n--- {title} ---")
            print("No data to display.")
        return

    print(f"\n--- {title} ---")
    # Shorter padding to fit more terminals
    header = f'{"Language":<18} {"Files":>8} {"Lines":>10} {"Code":>10} {"Comments":>10} {"Blanks":>10}'
    print(header)
    print("-" * len(header))

    total = defaultdict(int)
    sorted_langs = sorted(stats.items(), key=lambda item: item[1]['lines'], reverse=True)
    
    max_rows_to_print = len(sorted_langs)
    if is_live:
        # Reserve lines for: Title(2), Header(2), Footer(2), Progress(2), Git(4)
        reserved_lines = 12
        available_height = get_terminal_height() - reserved_lines
        max_rows_to_print = max(0, min(len(sorted_langs), available_height))

    for i, (lang, data) in enumerate(sorted_langs):
        if i >= max_rows_to_print:
            print(f"... and {len(sorted_langs) - max_rows_to_print} more ...")
            break
        
        files = data.get("files", 0)
        lines = data.get("lines", 0)
        code = data.get("code", 0)
        comments = data.get("comments", 0)
        blanks = data.get("blanks", 0)

        print(f'{lang:<18} {files:>8,} {lines:>10,} {code:>10,} {comments:>10,} {blanks:>10,}')
        
        total["files"] += files
        total["lines"] += lines
        total["code"] += code
        total["comments"] += comments
        total["blanks"] += blanks
    
    print("-" * len(header))
    print(f'{"Total":<18} {total.get("files", 0):>8,} {total.get("lines", 0):>10,} {total.get("code", 0):>10,} {total.get("comments", 0):>10,} {total.get("blanks", 0):>10,}')

def aggregate_loc_stats(repo_data):
    """Helper to aggregate LOC stats from a list of repo data."""
    stats = defaultdict(lambda: defaultdict(int))
    for repo in repo_data:
        if not repo.get('loc_stats'):
            continue
        for lang, lang_stats in repo['loc_stats'].items():
            if lang == "Total": continue
            
            code = lang_stats.get('code', 0)
            comments = lang_stats.get('comments', 0)
            blanks = lang_stats.get('blanks', 0)

            stats[lang]['code'] += code
            stats[lang]['comments'] += comments
            stats[lang]['blanks'] += blanks
            stats[lang]['lines'] += code + comments + blanks # Manually calculate lines
            stats[lang]['files'] += len(lang_stats.get('reports', []))
    return stats

def print_loc_live_summary(repo_data):
    """Aggregates and prints a simple, combined summary of LOC for live updates."""
    total_stats = aggregate_loc_stats(repo_data)
    print_table("Live LOC Summary (All Repos)", total_stats, is_live=True)

def print_loc_summary(repo_data):
    """Aggregates and prints a final, detailed summary of lines of code."""
    public_data = [r for r in repo_data if not r.get('isPrivate')]
    private_data = [r for r in repo_data if r.get('isPrivate')]

    public_stats = aggregate_loc_stats(public_data)
    private_stats = aggregate_loc_stats(private_data)
    total_stats = aggregate_loc_stats(repo_data)

    print_table("Lines of Code Summary (Public Repos)", public_stats)
    print_table("Lines of Code Summary (Private Repos)", private_stats)
    print_table("Lines of Code Summary (All Repos)", total_stats)


def print_commit_history_summary(all_commits, owner_name):
    """Analyzes and prints the summary of all commits."""
    if not all_commits:
        print("\nNo commits found to analyze.")
        return

    print(f"\n--- Commit History Summary for {owner_name} ---")

    # Sort commits by timestamp
    all_commits.sort(key=lambda x: x['timestamp'])

    total_commits = len(all_commits)
    total_insertions = sum(c['insertions'] for c in all_commits)
    total_deletions = sum(c['deletions'] for c in all_commits)
    
    first_commit_date = datetime.fromtimestamp(all_commits[0]['timestamp'], timezone.utc)
    last_commit_date = datetime.fromtimestamp(all_commits[-1]['timestamp'], timezone.utc)
    
    # Overall Summary
    print("\nOverall Summary:")
    print(f"  - Total Commits: {total_commits:,}")
    print(f"  - Total Insertions: {total_insertions:,}")
    print(f"  - Total Deletions: {total_deletions:,}")
    print(f"  - First Commit: {first_commit_date.strftime('%Y-%m-%d')}")
    print(f"  - Last Commit: {last_commit_date.strftime('%Y-%m-%d')}")

    # Commit activity by day of the week
    day_of_week_commits = defaultdict(int)
    for commit in all_commits:
        day = datetime.fromtimestamp(commit['timestamp'], timezone.utc).strftime('%A')
        day_of_week_commits[day] += 1
    
    if day_of_week_commits:
        most_active_day = max(day_of_week_commits, key=day_of_week_commits.get)
        print(f"  - Most Active Day: {most_active_day} ({day_of_week_commits[most_active_day]:,} commits)")

    # Commit Velocity
    total_days = (last_commit_date - first_commit_date).days
    if total_days > 0:
        print("\nCommit Velocity:")
        print(f"  - Average Commits per Day: {total_commits / total_days:.2f}")
        print(f"  - Average Commits per Month: {total_commits / (total_days / 30.44):.2f}")

    # Yearly Breakdown
    yearly_stats = defaultdict(lambda: {'commits': 0, 'insertions': 0, 'deletions': 0})
    for commit in all_commits:
        year = datetime.fromtimestamp(commit['timestamp'], timezone.utc).year
        yearly_stats[year]['commits'] += 1
        yearly_stats[year]['insertions'] += commit['insertions']
        yearly_stats[year]['deletions'] += commit['deletions']

    if yearly_stats:
        print("\nYearly Breakdown:")
        header = f'{"Year":<6} {"Commits":>10} {"Insertions":>12} {"Deletions":>12}'
        print(header)
        print("-" * len(header))
        for year in sorted(yearly_stats.keys()):
            stats = yearly_stats[year]
            print(f"{year:<6} {stats['commits']:>10,} {stats['insertions']:>12,} {stats['deletions']:>12,}")


def analyze_commit_history(repos, owner_name, clone_dir, keep_clones=False, max_repos=None):
    """
    Clones/updates repositories and analyzes their commit history.
    """
    print(f"--- Starting Full Commit History Analysis for {owner_name} ---")
    if keep_clones:
        print(f"Using persistent clone directory: {clone_dir}")

    if max_repos is not None:
        repos = repos[:max_repos]

    all_commits = []
    total_repos = len(repos)
    total_size_kb = sum(r.get('diskUsage', 0) for r in repos)
    processed_size_kb = 0

    for i, repo in enumerate(repos):
        full_name = f"{repo['owner']['login']}/{repo['name']}"
        repo_disk_usage = repo.get('diskUsage', 0)
        
        if sys.stdout.isatty() and not VERBOSE:
            sys.stdout.write("\033[H\033[J")
            sys.stdout.flush()
        
        size_str = f"({processed_size_kb/1024:.1f} / {total_size_kb/1024:.1f} MB)"
        print(f"--- History Analysis {size_str} ---")
        print(f"Processing {i + 1}/{total_repos}: {full_name}")

        repo_path, temp_dir_obj = manage_repo_clone(full_name, clone_dir, keep_clones)
        if not repo_path:
            processed_size_kb += repo_disk_usage
            continue
        
        try:
            processed_size_kb += repo_disk_usage
            
            log_cmd = [
                "git", "log",
                f"--author={owner_name}",
                "--pretty=format:%H|%at",
                "--shortstat"
            ]
            
            log_output = subprocess.check_output(log_cmd, cwd=repo_path, text=True, stderr=subprocess.PIPE)
            
            commit_hash = None
            for line in log_output.splitlines():
                if '|' in line and len(line.split('|')) == 2:
                    commit_hash, commit_timestamp = line.split('|')
                    all_commits.append({
                        "timestamp": int(commit_timestamp),
                        "insertions": 0,
                        "deletions": 0
                    })
                elif "changed" in line and commit_hash:
                    insertions = re.search(r'(\d+) insertion', line)
                    deletions = re.search(r'(\d+) deletion', line)
                    if all_commits:
                        all_commits[-1]["insertions"] = int(insertions.group(1)) if insertions else 0
                        all_commits[-1]["deletions"] = int(deletions.group(1)) if deletions else 0
                    commit_hash = None

        except subprocess.CalledProcessError as e:
            if "does not have any commits yet" in e.stderr:
                print_verbose(f"Skipping {full_name} as it has no commits.")
            else:
                print(f"Could not analyze log for {full_name}. Error: {e.stderr.strip()}", file=sys.stderr)
        except Exception as e:
            print(f"An unexpected error occurred during log analysis for {full_name}: {e}")
        finally:
            if temp_dir_obj:
                temp_dir_obj.cleanup()
    
    return all_commits


def main():
    parser = argparse.ArgumentParser(description="List GitHub repositories with various statistics.", formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("-i", "--interactive", action="store_true", help="Run the script in an interactive TUI mode.")
    parser.add_argument("-u", "--user", help="Specify a GitHub username or organization (defaults to the authenticated user).")
    parser.add_argument("-c", "--commits", action="store_true", help="Include commit counts and last commit date. (Default for static mode if no other flags)")
    parser.add_argument("-s", "--size", action="store_true", help="Include repository size (in KB).")
    parser.add_argument("-d", "--dependencies", action="store_true", help=textwrap.dedent("""
        Identify submodules that are also owned by the target user.
        NOTE: This is slower as it makes additional API calls per repo."""))
    
    loc_group = parser.add_argument_group('lines-of-code arguments')
    loc_group.add_argument("--loc", action="store_true", help="Include Lines-of-Code analysis for each repository (requires 'tokei' to be installed).")
    loc_group.add_argument("--use-latest-branch", action="store_true", help="For LOC analysis, check out the branch with the most recent commit instead of the default branch.")

    history_group = parser.add_argument_group('historical stats arguments')
    history_group.add_argument("--history", action="store_true", help=textwrap.dedent("""\\
        Analyze the entire commit history to generate stats like commits per year and daily averages.\\
        WARNING: This is a very slow operation that clones every repository."""))

    clone_group = parser.add_argument_group('cloning arguments')
    clone_group.add_argument("--keep-clones", action="store_true", help="Keep repository clones in a persistent directory for faster subsequent runs.")
    clone_group.add_argument("--clone-dir", help="Specify a persistent directory for clones. Requires --keep-clones. Defaults to ~/.cache/github-repos-info/clones.")
    clone_group.add_argument("--clear-clone-cache", action="store_true", help="Delete the cached repositories in the persistent clone directory.")
    clone_group.add_argument("--max-repos", type=int, help="Stop processing after N repositories (for --loc and --history). Useful for testing.")
    
    cache_group = parser.add_argument_group('caching arguments')
    cache_group.add_argument("--no-cache", action="store_true", help="Force a refresh and ignore any cached data.")
    cache_group.add_argument("--cache-ttl", type=int, default=3600, help="Time-to-live for cache in seconds. Default: 3600 (1 hour).")

    sort_group = parser.add_mutually_exclusive_group()
    sort_group.add_argument("-A", "--sort-date-asc", action="store_true", help="Sort repositories by last commit date in ascending order (oldest first).")
    sort_group.add_argument("-D", "--sort-date-desc", action="store_true", help="Sort repositories by last commit date in descending order (newest first).")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output for debugging and progress.")
    args = parser.parse_args()
    
    print_verbose("Starting script.")
    
    clone_dir = args.clone_dir or os.path.join(os.path.expanduser("~"), ".cache", "github-repos-info", "clones")
    if args.keep_clones or args.clone_dir:
        os.makedirs(clone_dir, exist_ok=True)

    if args.clear_clone_cache:
        if os.path.exists(clone_dir):
            print(f"Clearing clone cache at: {clone_dir}")
            shutil.rmtree(clone_dir)
            print("Cache cleared.")
        else:
            print("Clone cache directory does not exist.")
        return

    try:
        if args.interactive:
            if curses is None: sys.exit(1)
            args.commits, args.size = True, True
        
        global VERBOSE
        VERBOSE = args.verbose

        if not (args.commits or args.size or args.dependencies or args.sort_date_asc or args.sort_date_desc or args.interactive or args.loc or args.history):
            args.commits = True

        if args.history:
            repos = get_github_repos(args.user)
            if not repos:
                print(f"No repositories found for '{args.user or 'authenticated user'}'.", file=sys.stderr)
                return
            owner_name = args.user or run_gh_command(["api", "/user", "--jq", ".login"], "Failed to get authenticated user.").strip()
            all_commits = analyze_commit_history(repos, owner_name, clone_dir, args.keep_clones, args.max_repos)
            print_commit_history_summary(all_commits, owner_name)
            return

        repo_data, owner_name, column_widths = fetch_all_repo_data(args)
        if not repo_data: return

        if args.interactive:
            curses.wrapper(draw_main_list_ui, repo_data, owner_name, column_widths, clone_dir)
            return

        if args.loc:
            if sys.stdout.isatty() and not VERBOSE:
                sys.stdout.write("\033[H\033[J")
                sys.stdout.flush()
            print(f"--- Final LOC Analysis for {owner_name} ---")
            print(f"Processed {len(repo_data)}/{len(repo_data)} repositories.")
            print_loc_summary(repo_data)
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
        # No automatic cleanup of a persistent clone_dir
        pass

if __name__ == "__main__":
    main()
