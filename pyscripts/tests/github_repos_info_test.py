import pytest
from unittest.mock import patch, MagicMock, call
import subprocess
import json
import base64
import argparse
from datetime import datetime, timezone
import builtins
import time
import os

# Add script path to allow importing from the root directory
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import functions from the script
from github_repos_info import (
    run_gh_command,
    get_github_repos,
    get_commit_count,
    get_submodule_dependencies,
    main,
    get_repo_details,
    fetch_all_repo_data,
)

# --- Fixtures ---

@pytest.fixture(autouse=True)
def mock_exit():
    """Mocks sys.exit to prevent tests from stopping"""
    with patch('sys.exit') as mock_sys_exit:
        yield mock_sys_exit

# --- Sample Data Fixtures ---

@pytest.fixture
def sample_raw_repo_data():
    """Raw data as returned by 'gh repo list'"""
    return [
        {"owner": {"login": "user"}, "name": "repo-c", "diskUsage": 100, "pushedAt": "2023-01-01T12:00:00Z"},
        {"owner": {"login": "user"}, "name": "repo-a", "diskUsage": 300, "pushedAt": "2024-01-01T12:00:00Z"},
        {"owner": {"login": "user"}, "name": "repo-b", "diskUsage": 200, "pushedAt": "2022-01-01T12:00:00Z"},
        {"owner": {"login": "user"}, "name": "repo-d-no-date", "diskUsage": 50, "pushedAt": None},
    ]

@pytest.fixture
def sample_processed_repo_data():
    """Processed data as returned by fetch_all_repo_data"""
    return [
        {'full_name': 'user/repo-c', 'short_name': 'repo-c', 'size_kb': 100, 'last_commit_date_obj': datetime(2023, 1, 1, 12, 0, tzinfo=timezone.utc), 'last_commit_date_str': '2023-01-01 12:00', 'commits': 10, 'dependencies': []},
        {'full_name': 'user/repo-a', 'short_name': 'repo-a', 'size_kb': 300, 'last_commit_date_obj': datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc), 'last_commit_date_str': '2024-01-01 12:00', 'commits': 50, 'dependencies': []},
        {'full_name': 'user/repo-b', 'short_name': 'repo-b', 'size_kb': 200, 'last_commit_date_obj': datetime(2022, 1, 1, 12, 0, tzinfo=timezone.utc), 'last_commit_date_str': '2022-01-01 12:00', 'commits': 5, 'dependencies': []},
        {'full_name': 'user/repo-d-no-date', 'short_name': 'repo-d-no-date', 'size_kb': 50, 'last_commit_date_obj': None, 'last_commit_date_str': 'N/A', 'commits': 1, 'dependencies': []},
    ]

@pytest.fixture
def full_args_namespace():
    """A complete argparse.Namespace object with all default values."""
    return argparse.Namespace(
        interactive=False, user=None, commits=False, size=False, dependencies=False,
        no_cache=False, cache_ttl=3600,
        sort_date_asc=False, sort_date_desc=False, verbose=False
    )

# --- Tests for run_gh_command ---
@patch('subprocess.run')
def test_run_gh_command_success_json(mock_run):
    mock_run.return_value = MagicMock(stdout='{"data": "value"}', stderr="", returncode=0)
    result = run_gh_command(["repo", "list", "--json"], "Error", json_output=True)
    mock_run.assert_called_once_with(["gh", "repo", "list", "--json"], capture_output=True, text=True, check=True, encoding='utf-8')
    assert result == {"data": "value"}

@patch('subprocess.run')
def test_run_gh_command_called_process_error(mock_run, mock_exit, capsys):
    mock_run.side_effect = subprocess.CalledProcessError(1, "gh", stderr="critical error")
    run_gh_command(["some", "cmd"], "Test Error")
    mock_exit.assert_called_once_with(1)
    captured = capsys.readouterr()
    assert "Error executing 'gh some cmd': Test Error" in captured.err
    assert "Stderr: critical error" in captured.err

# --- Tests for Data Fetching and Processing ---

@patch('github_repos_info.run_gh_command')
def test_get_github_repos(mock_run_gh):
    mock_data = [{"name": "repo1"}, {"name": "repo2"}]
    mock_run_gh.return_value = mock_data
    get_github_repos(user="testuser")
    mock_run_gh.assert_called_with(["repo", "list", "testuser", "--json", "owner,name,diskUsage,pushedAt", "--limit", "1000"], "Failed to list repositories.", json_output=True)

@pytest.mark.parametrize("gh_output, expected_count", [
    ('Link: <...page=155>; rel="last"\n\n[]', 155), ('HTTP/1.1 200 OK\n\n[{"sha":"abc"}]', 1),
    ("EMPTY_REPO", 0), (None, -1)
])
@patch('github_repos_info.run_gh_command')
def test_get_commit_count(mock_run_gh, gh_output, expected_count):
    mock_run_gh.return_value = gh_output
    assert get_commit_count("owner", "repo") == expected_count

@patch('github_repos_info.run_gh_command')
def test_get_submodule_dependencies(mock_run_gh):
    gitmodules_content = '[submodule "dep1"]\n    url = https://github.com/owner/dep1.git'
    b64_content = base64.b64encode(gitmodules_content.encode('utf-8')).decode('utf-8')
    mock_run_gh.return_value = {"content": b64_content}
    deps = get_submodule_dependencies("owner", "repoA", {"owner/repoA", "owner/dep1"})
    assert deps == ["owner/dep1"]

@patch('github_repos_info.run_gh_command')
def test_get_repo_details_log(mock_run_gh):
    mock_run_gh.return_value = [{'sha': 'abcdef123', 'commit': {'message': 'feat: new thing\n\nmore details'}}]
    result = get_repo_details('owner/repo', 'log')
    assert result == ['abcdef1 - feat: new thing']

# --- Tests for main() Static Output Logic ---

@patch('github_repos_info.fetch_all_repo_data')
def test_main_default_sort_by_commit(mock_fetch_data, sample_processed_repo_data, capsys):
    mock_fetch_data.return_value = (sample_processed_repo_data, "user", {"name": 25, "commits": 5, "date": 16, "size": 10})
    with patch('sys.argv', ['github_repos_info.py', '-c']):
        main()
    out = capsys.readouterr().out
    assert "Commits" in out
    assert out.find("repo-a") < out.find("repo-c") < out.find("repo-b")

@patch('github_repos_info.fetch_all_repo_data')
def test_main_sort_date_asc(mock_fetch_data, sample_processed_repo_data, capsys):
    mock_fetch_data.return_value = (sample_processed_repo_data, "user", {"name": 25, "commits": 5, "date": 16, "size": 10})
    with patch('sys.argv', ['github_repos_info.py', '-A']):
        main()
    out = capsys.readouterr().out
    assert out.find("repo-b") < out.find("repo-c") < out.find("repo-a")

@patch('github_repos_info.fetch_all_repo_data')
def test_main_sort_date_desc(mock_fetch_data, sample_processed_repo_data, capsys):
    mock_fetch_data.return_value = (sample_processed_repo_data, "user", {"name": 25, "commits": 5, "date": 16, "size": 10})
    with patch('sys.argv', ['github_repos_info.py', '-D']):
        main()
    out = capsys.readouterr().out
    assert out.find("repo-a") < out.find("repo-c") < out.find("repo-b")

@patch('github_repos_info.fetch_all_repo_data')
def test_main_size_and_deps_flags(mock_fetch_data, sample_processed_repo_data, capsys):
    sample_processed_repo_data[0]['dependencies'] = ['user/dep1']
    mock_fetch_data.return_value = (sample_processed_repo_data, "user", {"name": 25, "commits": 5, "date": 16, "size": 10})
    with patch('sys.argv', ['github_repos_info.py', '-s', '-d']):
        main()
    out = capsys.readouterr().out
    assert "Size (KB)" in out and "Dependencies" in out
    assert "-> user/dep1" in out

@patch('github_repos_info.fetch_all_repo_data')
def test_main_no_repos(mock_fetch_data, capsys):
    mock_fetch_data.return_value = ([], "user", {})
    with patch('sys.argv', ['github_repos_info.py']):
        main()
    err = capsys.readouterr().err
    assert "No repositories found for 'user'" in err

# --- Tests for fetch_all_repo_data and Integrations ---

@patch('subprocess.run')
@patch('github_repos_info.get_commit_count', return_value=10)
@patch('github_repos_info.get_submodule_dependencies', return_value=[])
def test_fetch_all_data_verbose_mode(mock_get_deps, mock_get_commits, mock_subprocess_run, sample_raw_repo_data, capsys, full_args_namespace):
    def sub_side_effect(*args, **kwargs):
        cmd = args[0]
        if "api" in cmd and "/user" in cmd: return MagicMock(stdout='"testuser"', returncode=0)
        if "repo" in cmd and "list" in cmd: return MagicMock(stdout=json.dumps(sample_raw_repo_data), returncode=0)
        return MagicMock(stdout="", returncode=0)
    mock_subprocess_run.side_effect = sub_side_effect

    full_args_namespace.no_cache = True
    with patch('github_repos_info.VERBOSE', True):
        fetch_all_repo_data(full_args_namespace)
    err = capsys.readouterr().err
    assert "VERBOSE: Running command: gh api /user --jq .login" in err
    assert "VERBOSE: Fetching repository list for 'testuser'..." in err
    assert "VERBOSE: Processing user/repo-c..." in err

@patch('sys.stdout.isatty', return_value=True)
@patch('github_repos_info.run_gh_command')
@patch('github_repos_info.get_commit_count', return_value=10)
@patch('github_repos_info.get_submodule_dependencies', return_value=[])
def test_fetch_all_data_uses_tqdm(mock_get_deps, mock_get_commits, mock_run_gh, mock_isatty, sample_raw_repo_data, full_args_namespace):
    mock_run_gh.side_effect = ['"user"', sample_raw_repo_data]
    with patch('tqdm.tqdm') as mock_tqdm_class:
        mock_tqdm_instance = MagicMock()
        mock_tqdm_instance.__iter__.return_value = enumerate(sample_raw_repo_data)
        mock_tqdm_class.return_value = mock_tqdm_instance
        full_args_namespace.no_cache = True
        fetch_all_repo_data(full_args_namespace)
        mock_tqdm_class.assert_called_once()

@patch('sys.stdout.isatty', return_value=True)
def test_main_tqdm_import_error_fallback(mock_isatty, sample_raw_repo_data, capsys, full_args_namespace):
    _real_import = builtins.__import__
    def import_side_effect(name, *args, **kwargs):
        if name == 'tqdm': raise ImportError("No module named 'tqdm'")
        return _real_import(name, *args, **kwargs)

    with patch('builtins.__import__', side_effect=import_side_effect), \
         patch('github_repos_info.get_github_repos', return_value=sample_raw_repo_data), \
         patch('github_repos_info.run_gh_command', return_value='"user"'), \
         patch('github_repos_info.get_commit_count', return_value=10), \
         patch('github_repos_info.get_submodule_dependencies', return_value=[]):
        full_args_namespace.no_cache = True
        fetch_all_repo_data(full_args_namespace)
        err = capsys.readouterr().err
        assert "Warning: `tqdm` is not installed." in err

# --- Tests for Caching Logic ---
@patch('time.time')
@patch('os.path.getmtime')
@patch('builtins.open', new_callable=MagicMock)
@patch('os.path.exists')
@patch('github_repos_info.run_gh_command')
def test_cache_is_used_when_fresh(mock_run_gh, mock_exists, mock_open, mock_getmtime, mock_time, full_args_namespace):
    mock_exists.return_value = True
    mock_time.return_value = 10000
    mock_getmtime.return_value = 9000
    
    mock_file_content = json.dumps({
        "data": [{"full_name": "user/cached-repo", "short_name": "cached-repo", "last_commit_date_str": "N/A"}],
        "column_widths": {"name": 12, "commits": 5, "date": 16, "size": 10}
    })
    mock_open.return_value.__enter__.return_value.read.return_value = mock_file_content

    full_args_namespace.user = "user"
    repo_data, _, _ = fetch_all_repo_data(full_args_namespace)
    
    mock_run_gh.assert_not_called()
    assert len(repo_data) == 1
    assert repo_data[0]['short_name'] == 'cached-repo'
