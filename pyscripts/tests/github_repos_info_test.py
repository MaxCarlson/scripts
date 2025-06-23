import pytest
from unittest.mock import patch, MagicMock, call
import subprocess
import json
import base64
import argparse
from datetime import datetime, timezone
import builtins

# Add script path to allow importing from the root directory
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import functions from the script
from github_repos_info import (
    run_gh_command,
    get_github_repos,
    get_commit_count,
    get_submodule_dependencies,
    main,
    get_repo_details,
)

# --- Fixtures ---

@pytest.fixture
def mock_run():
    """Mocks subprocess.run"""
    with patch('subprocess.run') as mock_subprocess_run:
        yield mock_subprocess_run

@pytest.fixture(autouse=True)
def mock_exit():
    """Mocks sys.exit to prevent tests from stopping"""
    with patch('sys.exit') as mock_sys_exit:
        yield mock_sys_exit

# --- Tests for run_gh_command ---

def test_run_gh_command_success_json(mock_run):
    mock_run.return_value = MagicMock(stdout='{"data": "value"}', stderr="", returncode=0)
    result = run_gh_command(["repo", "list", "--json"], "Error", json_output=True)
    mock_run.assert_called_once_with(["gh", "repo", "list", "--json"], capture_output=True, text=True, check=True, encoding='utf-8')
    assert result == {"data": "value"}

# --- Tests for Data Fetching Functions ---

@patch('github_repos_info.run_gh_command')
def test_get_repo_details_log(mock_run_gh):
    mock_run_gh.return_value = [{'sha': 'abcdef123', 'commit': {'message': 'feat: new thing\n\nmore details'}}]
    result = get_repo_details('owner/repo', 'log')
    mock_run_gh.assert_called_with(['api', '/repos/owner/repo/commits?per_page=30'], "Failed to get commit log.", json_output=True)
    assert result == ['abcdef1 - feat: new thing']

@patch('github_repos_info.run_gh_command')
def test_get_repo_details_branches(mock_run_gh):
    mock_run_gh.return_value = [{'name': 'main'}, {'name': 'develop'}]
    result = get_repo_details('owner/repo', 'branches')
    mock_run_gh.assert_called_with(['api', '/repos/owner/repo/branches'], "Failed to get branches.", json_output=True)
    assert result == ['main', 'develop']

@patch('github_repos_info.run_gh_command')
def test_get_repo_details_tree(mock_run_gh):
    mock_run_gh.return_value = [{'name': 'src', 'type': 'dir'}]
    result = get_repo_details('owner/repo', 'tree', 'some/path')
    mock_run_gh.assert_called_with(['api', '/repos/owner/repo/contents/some/path'], f"Failed to get contents of some/path", json_output=True, check_error_string="404")
    assert result == [{'name': 'src', 'type': 'dir'}]


# --- Tests for main() logic ---

@pytest.fixture
def mock_data_funcs():
    """Mocks all data fetching functions used by main()"""
    with patch('github_repos_info.fetch_all_repo_data') as mock_fetch_data:
        yield mock_fetch_data

@pytest.fixture
def sample_repo_data():
    return [
        {"owner": {"login": "user"}, "full_name": "user/repo-c", "short_name": "repo-c", "diskUsage": 100, "pushedAt": "2023-01-01T12:00:00Z"},
        {"owner": {"login": "user"}, "full_name": "user/repo-a", "short_name": "repo-a", "diskUsage": 300, "pushedAt": "2024-01-01T12:00:00Z"},
        {"owner": {"login": "user"}, "full_name": "user/repo-b", "short_name": "repo-b", "diskUsage": 200, "pushedAt": "2022-01-01T12:00:00Z"},
    ]

def run_main_with_args(arg_list, mock_data_funcs, sample_repo_data):
    """Helper to run main with mocked args and data"""
    # mock_fetch_all_repo_data now returns a tuple
    mock_data_funcs.return_value = (sample_repo_data, "user", {"name": 20, "commits": 5, "date": 16, "size": 10})

    with patch('sys.argv', ['github_repos_info.py'] + arg_list):
        main()

def test_main_default_sort_by_commit(mock_data_funcs, sample_repo_data, capsys):
    # This test is for static mode, so we need to mock fetch_all_repo_data
    # and also assign some "commits" data for sorting.
    for repo in sample_repo_data:
        if repo['short_name'] == 'repo-a': repo['commits'] = 50
        if repo['short_name'] == 'repo-b': repo['commits'] = 5
        if repo['short_name'] == 'repo-c': repo['commits'] = 10
    
    run_main_with_args([], mock_data_funcs, sample_repo_data)
    out = capsys.readouterr().out
    assert "Commits" in out and "Last Commit" in out
    assert "repo-a" in out and "repo-b" in out and "repo-c" in out
    assert out.find("repo-a") < out.find("repo-c") < out.find("repo-b")


# --- New and Fixed Tests ---

@patch('github_repos_info.get_submodule_dependencies')
@patch('github_repos_info.get_commit_count')
@patch('subprocess.run')
def test_main_verbose_flag_deep_mock(mock_subprocess_run, mock_get_commits, mock_get_deps, sample_repo_data, capsys):
    """
    This test mocks subprocess.run to ensure verbose logging is captured correctly.
    It now handles multiple different calls to the gh cli.
    """
    def sub_side_effect(*args, **kwargs):
        cmd = args[0]
        if "api" in cmd and "/user" in cmd:
            return MagicMock(stdout='"testuser"', stderr="", returncode=0)
        elif "repo" in cmd and "list" in cmd:
            return MagicMock(stdout=json.dumps(sample_repo_data), stderr="", returncode=0)
        return MagicMock(stdout="", stderr="", returncode=0)

    mock_subprocess_run.side_effect = sub_side_effect
    mock_get_commits.return_value = 10 # Just return a dummy value

    with patch('sys.argv', ['github_repos_info.py', '-v']):
        main()

    err = capsys.readouterr().err
    assert "VERBOSE: Starting script." in err
    assert "VERBOSE: Running command: gh api /user --jq .login" in err
    assert "VERBOSE: Fetching repository list for 'testuser'..." in err
    assert "VERBOSE: Running command: gh repo list" in err
    assert "Processing user/repo-c" in err

@patch('sys.stdout.isatty', return_value=True)
def test_main_tqdm_import_error_fallback(mock_isatty, mock_data_funcs, sample_repo_data, capsys):
    _real_import = builtins.__import__
    def import_side_effect(name, *args, **kwargs):
        if name == 'tqdm':
            raise ImportError("No module named 'tqdm'")
        return _real_import(name, *args, **kwargs)

    with patch('builtins.__import__', side_effect=import_side_effect):
        run_main_with_args([], mock_data_funcs, sample_repo_data)

    err = capsys.readouterr().err
    assert "Warning: `tqdm` is not installed." in err
