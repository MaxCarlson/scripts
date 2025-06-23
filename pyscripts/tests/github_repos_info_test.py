import pytest
from unittest.mock import patch, MagicMock, call
import subprocess
import json
import base64
import argparse
from datetime import datetime, timezone

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
    main
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
    mock_run.return_value = MagicMock(
        stdout='{"data": "value"}', stderr="", returncode=0, check_returncode=lambda: None
    )
    result = run_gh_command(["repo", "list", "--json"], "Error", json_output=True)
    mock_run.assert_called_once_with(
        ["gh", "repo", "list", "--json"], capture_output=True, text=True, check=True, encoding='utf-8'
    )
    assert result == {"data": "value"}

def test_run_gh_command_success_with_headers(mock_run):
    mock_run.return_value = MagicMock(
        stdout='HTTP/2 200\n\n{"data": "value"}', stderr="", returncode=0
    )
    result = run_gh_command(["api", "-i", "/endpoint"], "Error", json_output=True)
    assert result == {"data": "value"}

def test_run_gh_command_called_process_error(mock_run, mock_exit, capsys):
    mock_run.side_effect = subprocess.CalledProcessError(1, "gh", stderr="critical error")
    run_gh_command(["some", "cmd"], "Test Error")
    mock_exit.assert_called_once_with(1)
    captured = capsys.readouterr()
    assert "Error executing 'gh some cmd': Test Error" in captured.err
    assert "Stderr: critical error" in captured.err

def test_run_gh_command_handled_error_string(mock_run, mock_exit):
    mock_run.side_effect = subprocess.CalledProcessError(1, "gh", stderr="some error with 404")
    result = run_gh_command(["some", "cmd"], "Error", check_error_string="404")
    assert result is None
    mock_exit.assert_not_called()

def test_run_gh_command_handled_empty_repo(mock_run, mock_exit):
    mock_run.side_effect = subprocess.CalledProcessError(1, "gh", stderr="Git repo is empty (409)")
    result = run_gh_command(["api", "commits"], "Error", check_error_string="409")
    assert result == "EMPTY_REPO"
    mock_exit.assert_not_called()

def test_run_gh_command_json_decode_error(mock_run, mock_exit, capsys):
    mock_run.return_value = MagicMock(stdout='not json', stderr="", returncode=0)
    run_gh_command(["some", "cmd"], "Error", json_output=True)
    mock_exit.assert_called_once_with(1)
    captured = capsys.readouterr()
    assert "Error parsing JSON output" in captured.err

# --- Tests for Data Fetching Functions ---

@patch('github_repos_info.run_gh_command')
def test_get_github_repos(mock_run_gh):
    mock_data = [{"name": "repo1"}, {"name": "repo2"}]
    mock_run_gh.return_value = mock_data
    # Test with no user
    repos = get_github_repos()
    mock_run_gh.assert_called_with(
        ["repo", "list", "--json", "owner,name,diskUsage,pushedAt", "--limit", "1000"],
        "Failed to list repositories.", json_output=True
    )
    assert repos == mock_data
    # Test with a user
    get_github_repos(user="testuser")
    mock_run_gh.assert_called_with(
        ["repo", "list", "testuser", "--json", "owner,name,diskUsage,pushedAt", "--limit", "1000"],
        "Failed to list repositories.", json_output=True
    )


@pytest.mark.parametrize("gh_output, expected_count", [
    ('Link: <...page=155>; rel="last"\n\n[]', 155),
    ('HTTP/1.1 200 OK\n\n[{"sha":"abc"}]', 1),
    ('HTTP/1.1 200 OK\n\n[]', 0),
    ("EMPTY_REPO", 0),
    (None, -1)
])
@patch('github_repos_info.run_gh_command')
def test_get_commit_count(mock_run_gh, gh_output, expected_count):
    mock_run_gh.return_value = gh_output
    count = get_commit_count("owner", "repo")
    assert count == expected_count
    mock_run_gh.assert_called_once_with(
        ["api", "-i", "/repos/owner/repo/commits?per_page=1"],
        "Failed to get commit count for owner/repo.",
        check_error_string="409"
    )

@patch('github_repos_info.run_gh_command')
def test_get_submodule_dependencies(mock_run_gh):
    # Case 1: .gitmodules not found
    mock_run_gh.return_value = None
    deps = get_submodule_dependencies("owner", "repo", {"owner/dep"})
    assert deps == []
    mock_run_gh.assert_called_once_with(
        ['api', '/repos/owner/repo/contents/.gitmodules'],
        'Failed to get .gitmodules for owner/repo.',
        json_output=True, check_error_string='404'
    )

    # Case 2: .gitmodules found and parsed
    mock_run_gh.reset_mock()
    gitmodules_content = """
        [submodule "dep1"]
            path = dep1
            url = https://github.com/owner/dep1.git
        [submodule "external"]
            path = external
            url = https://github.com/other/external.git
    """
    b64_content = base64.b64encode(gitmodules_content.encode('utf-8')).decode('utf-8')
    mock_run_gh.return_value = {"content": b64_content}
    all_repos = {"owner/repo", "owner/dep1"}
    deps = get_submodule_dependencies("owner", "repo", all_repos)
    assert deps == ["owner/dep1"]

# --- Tests for main() logic ---

@pytest.fixture
def mock_data_funcs():
    """Mocks all data fetching functions used by main()"""
    with patch('github_repos_info.get_github_repos') as mock_get_repos, \
         patch('github_repos_info.get_commit_count') as mock_get_commits, \
         patch('github_repos_info.get_submodule_dependencies') as mock_get_deps:
        yield mock_get_repos, mock_get_commits, mock_get_deps

@pytest.fixture
def sample_repo_data():
    return [
        {"owner": {"login": "user"}, "name": "repo-c", "diskUsage": 100, "pushedAt": "2023-01-01T12:00:00Z"},
        {"owner": {"login": "user"}, "name": "repo-a", "diskUsage": 300, "pushedAt": "2024-01-01T12:00:00Z"},
        {"owner": {"login": "user"}, "name": "repo-b", "diskUsage": 200, "pushedAt": "2022-01-01T12:00:00Z"},
        {"owner": {"login": "user"}, "name": "repo-d-no-date", "diskUsage": 50, "pushedAt": None},
    ]

def run_main_with_args(arg_list, mock_data_funcs, sample_repo_data):
    """Helper to run main with mocked args and data"""
    mock_get_repos, mock_get_commits, mock_get_deps = mock_data_funcs
    mock_get_repos.return_value = sample_repo_data
    # Assign commits to specific repos by name
    commit_counts = {'repo-c': 10, 'repo-a': 50, 'repo-b': 5, 'repo-d-no-date': 1}
    mock_get_commits.side_effect = lambda owner, name: commit_counts.get(name, 0)
    mock_get_deps.return_value = []

    with patch('sys.argv', ['github_repos_info.py'] + arg_list):
        main()

def test_main_default_sort_by_commit(mock_data_funcs, sample_repo_data, capsys):
    run_main_with_args([], mock_data_funcs, sample_repo_data)
    out = capsys.readouterr().out
    assert "Commits" in out and "Last Commit" in out
    assert "Size (KB)" not in out
    # Expected order by commits desc: repo-a (50), repo-c (10), repo-b (5), repo-d (1)
    assert out.find("repo-a") < out.find("repo-c") < out.find("repo-b") < out.find("repo-d-no-date")

def test_main_sort_date_asc(mock_data_funcs, sample_repo_data, capsys):
    run_main_with_args(['-A'], mock_data_funcs, sample_repo_data)
    out = capsys.readouterr().out
    assert "Commits" in out and "Last Commit" in out
    # Expected order by date asc: repo-b (2022), repo-c (2023), repo-a (2024), repo-d (None, last)
    assert out.find("repo-b") < out.find("repo-c") < out.find("repo-a") < out.find("repo-d-no-date")

def test_main_sort_date_desc(mock_data_funcs, sample_repo_data, capsys):
    run_main_with_args(['-D'], mock_data_funcs, sample_repo_data)
    out = capsys.readouterr().out
    assert "Commits" in out and "Last Commit" in out
    # Expected order by date desc: repo-a (2024), repo-c (2023), repo-b (2022), repo-d (None, last)
    assert out.find("repo-a") < out.find("repo-c") < out.find("repo-b") < out.find("repo-d-no-date")

def test_main_size_and_deps_flags(mock_data_funcs, sample_repo_data, capsys):
    mock_get_repos, mock_get_commits, mock_get_deps = mock_data_funcs
    # Let's say repo-c has a dependency
    mock_get_deps.side_effect = lambda o, n, a: ["user/dep1"] if n == "repo-c" else []
    
    run_main_with_args(['-s', '-d'], mock_data_funcs, sample_repo_data)
    out = capsys.readouterr().out
    assert "Commits" not in out and "Last Commit" not in out
    assert "Size (KB)" in out and "Dependencies" in out
    # Should be sorted alphabetically as no commit/date sort is specified
    assert out.find("repo-a") < out.find("repo-b") < out.find("repo-c") < out.find("repo-d-no-date")
    assert "-> user/dep1" in out

def test_main_no_repos(mock_data_funcs, capsys):
    mock_get_repos, _, _ = mock_data_funcs
    mock_get_repos.return_value = []
    with patch('sys.argv', ['github_repos_info.py']):
        main()
    err = capsys.readouterr().err
    assert "No repositories found" in err

@patch('github_repos_info.get_submodule_dependencies')
@patch('github_repos_info.get_commit_count')
@patch('subprocess.run')
def test_main_verbose_flag_deep_mock(mock_subprocess_run, mock_get_commits, mock_get_deps, sample_repo_data, capsys):
    """
    This test mocks a lower level function (subprocess.run) to ensure that the
    verbose logging inside higher-level functions like get_github_repos is
    actually executed and captured.
    """
    # Setup the mock for the 'gh repo list' call made by get_github_repos -> run_gh_command -> subprocess.run
    mock_subprocess_run.return_value = MagicMock(
        stdout=json.dumps(sample_repo_data), stderr="", returncode=0
    )

    # Setup mocks for functions called in the main loop (these are higher level and don't need to be run)
    commit_counts = {'repo-c': 10, 'repo-a': 50, 'repo-b': 5, 'repo-d-no-date': 1}
    mock_get_commits.side_effect = lambda owner, name: commit_counts.get(name, 0)
    mock_get_deps.return_value = []

    with patch('sys.argv', ['github_repos_info.py', '-v']):
        main()

    err = capsys.readouterr().err
    assert "VERBOSE: Starting script." in err
    assert "VERBOSE: Fetching initial list of GitHub repositories..." in err
    # This assertion now passes because the real run_gh_command is executed
    assert "VERBOSE: Running command: gh repo list" in err
    assert "VERBOSE: [1/4] Processing user/repo-c..." in err
    assert "VERBOSE:   Getting commit count for user/repo-c..." in err
