# tests/history_utils_test.py
# VERSION: Cleaned up diagnostics, fixed assertions for the 2 failing tests.

import pytest
import os
import platform
import subprocess
import sys
import pathlib # Keep for spec=pathlib.Path in mocks
from unittest.mock import patch, mock_open, MagicMock, call

from cross_platform.history_utils import HistoryUtils, main as history_main

# --- Fixtures ---

@pytest.fixture
def mock_os_path_exists(monkeypatch):
    mock = MagicMock(return_value=False)
    monkeypatch.setattr(os.path, 'exists', mock)
    return mock

@pytest.fixture
def mock_os_expanduser(monkeypatch):
    def _mock_expanduser(p):
        if p.startswith("~"):
            return p.replace("~", "/home/testuser", 1)
        return p
    mock = MagicMock(side_effect=_mock_expanduser)
    monkeypatch.setattr(os.path, 'expanduser', mock)
    return mock

# --- Helper function using side_effect for mock methods ---
def create_path_constructor_side_effect(exists_check_func_from_test, test_name="UnknownTest"):
    # This outer function is called once per test that uses it, when MockPatchedPath.side_effect is set.
    # It returns path_constructor_side_effect.
    
    def path_constructor_side_effect(path_str_arg_to_constructor_param):
        # This inner function is called every time Path(...) is called in the SUT.
        # It creates and returns one mock_path_instance.
        mock_path_instance = MagicMock(spec=pathlib.Path)
        actual_path_str = str(path_str_arg_to_constructor_param)
        
        mock_path_instance.name = os.path.basename(actual_path_str)
        
        # --- .exists() via side_effect ---
        def exists_side_effect_func():
            # Uses 'actual_path_str' (specific to this mock_path_instance's creation)
            # and 'exists_check_func_from_test' (specific to the test case) from closures.
            result = bool(exists_check_func_from_test(actual_path_str))
            # Minimal print for verbosity if needed, but usually kept off for clean test runs
            # print(f"[{test_name}_SIDE_EFFECT_EXISTS] Path '{actual_path_str}', TestLambdaResult: {result}")
            return result
        mock_path_instance.exists.side_effect = exists_side_effect_func

        # --- .resolve() via side_effect ---
        def resolve_side_effect_func(strict=False):
            # Uses 'actual_path_str' (from this instance) and 
            # 'path_constructor_side_effect' (the factory, for recursion) from closures.
            # print(f"[{test_name}_SIDE_EFFECT_RESOLVE] Path '{actual_path_str}', Strict: {strict}")
            return path_constructor_side_effect(actual_path_str) # Return a new, fully configured mock
        mock_path_instance.resolve.side_effect = resolve_side_effect_func

        # --- __str__() via side_effect ---
        def str_side_effect_func():
            # Uses 'actual_path_str' from this instance's closure.
            # print(f"[{test_name}_SIDE_EFFECT_STR] Path '{actual_path_str}'")
            return actual_path_str
        mock_path_instance.__str__.side_effect = str_side_effect_func
        
        return mock_path_instance
    return path_constructor_side_effect


# --- Tests for _get_shell_type ---
@patch('cross_platform.history_utils.Path')
def test_get_shell_type_zsh_env(MockPatchedPath, monkeypatch):
    MockPatchedPath.side_effect = create_path_constructor_side_effect(lambda _: True, "ShellDetectZsh")
    monkeypatch.setattr(platform, 'system', lambda: 'Linux')
    monkeypatch.setenv("SHELL", "/usr/bin/zsh")
    hu = HistoryUtils()
    assert hu.shell_type == "zsh"

@patch('cross_platform.history_utils.Path') 
def test_get_shell_type_bash_env(MockPatchedPath, monkeypatch):
    MockPatchedPath.side_effect = create_path_constructor_side_effect(lambda _: True, "ShellDetectBash")
    monkeypatch.setattr(platform, 'system', lambda: 'Linux')
    monkeypatch.setenv("SHELL", "/bin/bash")
    hu = HistoryUtils()
    assert hu.shell_type == "bash"

@patch('cross_platform.history_utils.Path')
def test_get_shell_type_macos_fallback_zsh(MockPatchedPath, monkeypatch, mock_os_path_exists):
    MockPatchedPath.side_effect = create_path_constructor_side_effect(lambda _: True, "ShellDetectMacZsh")
    monkeypatch.setattr(platform, 'system', lambda: 'Darwin')
    monkeypatch.delenv("SHELL", raising=False) 
    mock_os_path_exists.side_effect = lambda p: p == "/bin/zsh"
    hu = HistoryUtils() 
    assert hu.shell_type == "zsh"

@patch('cross_platform.history_utils.Path')
def test_get_shell_type_linux_fallback_bash(MockPatchedPath, monkeypatch, mock_os_path_exists):
    MockPatchedPath.side_effect = create_path_constructor_side_effect(lambda _: True, "ShellDetectLinBash")
    monkeypatch.setattr(platform, 'system', lambda: 'Linux')
    monkeypatch.delenv("SHELL", raising=False)
    mock_os_path_exists.side_effect = lambda p: p == "/bin/bash"
    hu = HistoryUtils() 
    assert hu.shell_type == "bash"

@patch('cross_platform.history_utils.Path')
def test_get_shell_type_unknown(MockPatchedPath, monkeypatch, mock_os_path_exists):
    MockPatchedPath.side_effect = create_path_constructor_side_effect(lambda _: False, "ShellDetectUnknown")
    monkeypatch.setattr(platform, 'system', lambda: 'Linux') 
    monkeypatch.setenv("SHELL", "/bin/unknown_shell")
    mock_os_path_exists.return_value = False 
    hu = HistoryUtils()
    assert hu.shell_type == "unknown"

def test_get_shell_type_windows(monkeypatch):
    monkeypatch.setattr(platform, 'system', lambda: 'Windows')
    with patch('cross_platform.history_utils.Path', MagicMock()) as mock_path_constructor_if_called:
        hu = HistoryUtils()
        assert hu.shell_type == "powershell"
        mock_path_constructor_if_called.assert_not_called()


# --- Tests for _get_history_file_path ---
@patch('cross_platform.history_utils.Path') 
def test_get_history_file_path_zsh_histfile_env(MockPatchedPath, monkeypatch, mock_os_path_exists, mock_os_expanduser):
    MockPatchedPath.side_effect = create_path_constructor_side_effect(lambda _: True, "GetHistZshEnvSetup")
    monkeypatch.setattr(platform, 'system', lambda: 'Linux')
    monkeypatch.setenv("SHELL", "/usr/bin/zsh") 
    hu = HistoryUtils() 
    hu.shell_type = 'zsh' 
    
    monkeypatch.setenv("HISTFILE", "~/.custom_zsh_hist")
    mock_os_path_exists.side_effect = lambda p: p == "/home/testuser/.custom_zsh_hist"
    
    path = hu._get_history_file_path()
    assert path == "/home/testuser/.custom_zsh_hist"
    mock_os_expanduser.assert_any_call("~/.custom_zsh_hist")

@patch('cross_platform.history_utils.Path')
def test_get_history_file_path_zsh_default(MockPatchedPath, monkeypatch, mock_os_path_exists, mock_os_expanduser):
    MockPatchedPath.side_effect = create_path_constructor_side_effect(lambda _: True, "GetHistZshDefSetup")
    monkeypatch.setattr(platform, 'system', lambda: 'Linux')
    monkeypatch.setenv("SHELL", "/bin/zsh")
    hu = HistoryUtils()
    hu.shell_type = 'zsh'
    monkeypatch.delenv("HISTFILE", raising=False)
    mock_os_path_exists.side_effect = lambda p: p == "/home/testuser/.zsh_history"
    path = hu._get_history_file_path()
    assert path == "/home/testuser/.zsh_history"
    mock_os_expanduser.assert_any_call("~/.zsh_history")

@patch('cross_platform.history_utils.Path')
def test_get_history_file_path_zsh_alt_histfile(MockPatchedPath, monkeypatch, mock_os_path_exists, mock_os_expanduser):
    MockPatchedPath.side_effect = create_path_constructor_side_effect(lambda _: True, "GetHistZshAltSetup")
    monkeypatch.setattr(platform, 'system', lambda: 'Linux')
    monkeypatch.setenv("SHELL", "/bin/zsh")
    hu = HistoryUtils()
    hu.shell_type = 'zsh'
    monkeypatch.delenv("HISTFILE", raising=False)

    def os_path_exists_side_effect(p_str):
        if p_str == "/home/testuser/.zsh_history": return False
        if p_str == "/home/testuser/.histfile": return True
        return False
    mock_os_path_exists.side_effect = os_path_exists_side_effect
    
    path = hu._get_history_file_path()
    assert path == "/home/testuser/.histfile"
    mock_os_expanduser.assert_any_call("~/.zsh_history")
    mock_os_expanduser.assert_any_call("~/.histfile")


@patch('cross_platform.history_utils.Path')
def test_get_history_file_path_bash_default(MockPatchedPath, monkeypatch, mock_os_path_exists, mock_os_expanduser):
    MockPatchedPath.side_effect = create_path_constructor_side_effect(lambda _: True, "GetHistBashDefSetup")
    monkeypatch.setattr(platform, 'system', lambda: 'Linux')
    monkeypatch.setenv("SHELL", "/bin/bash")
    hu = HistoryUtils()
    hu.shell_type = 'bash'
    monkeypatch.delenv("HISTFILE", raising=False)
    mock_os_path_exists.side_effect = lambda p: p == "/home/testuser/.bash_history"
    path = hu._get_history_file_path()
    assert path == "/home/testuser/.bash_history"
    mock_os_expanduser.assert_any_call("~/.bash_history")

# --- Tests for _extract_paths_from_history_lines ---

@patch('cross_platform.history_utils.Path') 
def test_extract_paths_simple(MockPatchedPath, monkeypatch, mock_os_expanduser):
    expected_paths_to_exist = ["/foo/bar", "/another/path"]
    MockPatchedPath.side_effect = create_path_constructor_side_effect(
        lambda path_str: path_str in expected_paths_to_exist, "ExtractSimple"
    )
    monkeypatch.setattr(platform, 'system', lambda: 'Linux')
    monkeypatch.setenv("SHELL", "/bin/bash")

    hu = HistoryUtils() 
    history_lines = ["cd /foo/bar", "ls /another/path", "git status"]
    paths = hu._extract_paths_from_history_lines(history_lines)
    assert paths == ["/another/path", "/foo/bar"] 

@patch('cross_platform.history_utils.Path')
def test_extract_paths_zsh_extended_format(MockPatchedPath, monkeypatch, mock_os_expanduser):
    expected_path_to_exist = "/valid/zsh_path"
    MockPatchedPath.side_effect = create_path_constructor_side_effect(
        lambda path_str: path_str == expected_path_to_exist, "ExtractZshExt"
    )
    monkeypatch.setattr(platform, 'system', lambda: 'Linux')
    monkeypatch.setenv("SHELL", "/bin/zsh")
    
    hu = HistoryUtils()
    hu.shell_type = 'zsh' 
    history_lines = [": 1234567890:0;cd /valid/zsh_path"]
    paths = hu._extract_paths_from_history_lines(history_lines)
    assert paths == [expected_path_to_exist]

@patch('cross_platform.history_utils.Path')
def test_extract_paths_uniqueness_and_order(MockPatchedPath, monkeypatch, mock_os_expanduser):
    existing_paths_for_mock = ["/path1", "/path2", "/path3.txt"]
    MockPatchedPath.side_effect = create_path_constructor_side_effect(
        lambda path_str: path_str in existing_paths_for_mock, "ExtractUniqOrder"
    )
    monkeypatch.setattr(platform, 'system', lambda: 'Linux')
    monkeypatch.setenv("SHELL", "/bin/bash")

    hu = HistoryUtils()
    history_lines = ["cd /path1", "ls /path2", "cd /path1", "cat /path3.txt"]
    paths = hu._extract_paths_from_history_lines(history_lines)
    # Corrected expected order based on SUT logic (reversed lines, append unique)
    assert paths == ["/path3.txt", "/path1", "/path2"]

@patch('cross_platform.history_utils.Path')
def test_extract_paths_with_spaces_and_quotes(MockPatchedPath, monkeypatch, mock_os_expanduser):
    path_as_arg_to_exist = "/mnt/c/My Docs/file.txt" 
    MockPatchedPath.side_effect = create_path_constructor_side_effect(
        lambda path_str: path_str == path_as_arg_to_exist, "ExtractSpacesQuotes"
    )
    monkeypatch.setattr(platform, 'system', lambda: 'Linux') 
    monkeypatch.setenv("SHELL", "/bin/bash")

    hu = HistoryUtils()
    history_lines = ['open "/mnt/c/My Docs/file.txt"']
    paths = hu._extract_paths_from_history_lines(history_lines)
    assert paths == [path_as_arg_to_exist]

@patch('cross_platform.history_utils.Path')
def test_extract_paths_filters_options_and_urls(MockPatchedPath, monkeypatch, mock_os_expanduser):
    # Only /actual/path should "exist" according to the mock for this test's purpose
    # /another/path is part of --config= which will be filtered by startswith("-")
    paths_that_should_exist_in_mock = ["/actual/path"] 
    MockPatchedPath.side_effect = create_path_constructor_side_effect(
        lambda path_str: path_str in paths_that_should_exist_in_mock, "ExtractFilters"
    )
    monkeypatch.setattr(platform, 'system', lambda: 'Linux')
    monkeypatch.setenv("SHELL", "/bin/bash")
    
    hu = HistoryUtils()
    history_lines = ["ls -l /actual/path", "curl http://example.com", "some_tool --config=/another/path"]
    paths = hu._extract_paths_from_history_lines(history_lines)
    
    # Current SUT logic will filter out "--config=/another/path" because it starts with "-"
    # Therefore, only "/actual/path" should be found.
    assert paths == ["/actual/path"]
    assert "/actual/path" in paths
    assert "/another/path" not in paths # Explicitly check it's not there
    assert len(paths) == 1


# --- Tests for get_nth_recent_path ---

@patch('builtins.open', new_callable=mock_open, read_data="cd /path3\nls /path2\ncat /path1")
@patch.object(HistoryUtils, '_get_history_file_path') 
@patch('cross_platform.history_utils.Path') 
def test_get_nth_recent_path_success(MockPatchedPath, mock_get_hist_path, mock_open_file, monkeypatch, mock_os_expanduser):
    existing_paths_for_mock = ["/path1", "/path2", "/path3"]
    MockPatchedPath.side_effect = create_path_constructor_side_effect(
        lambda path_str: path_str in existing_paths_for_mock, "GetNthSuccess"
    )
    monkeypatch.setattr(platform, 'system', lambda: 'Linux') 
    monkeypatch.setenv("SHELL", "/bin/bash") 
    
    hu = HistoryUtils() 
    mock_get_hist_path.return_value = "/fake/history.txt" 
    
    # Based on "cd /path3", "ls /path2", "cat /path1" and processing reversed:
    # 1. /path1
    # 2. /path2
    # 3. /path3
    assert hu.get_nth_recent_path(1) == "/path1" 
    assert hu.get_nth_recent_path(2) == "/path2"
    assert hu.get_nth_recent_path(3) == "/path3"


@patch('builtins.open', new_callable=mock_open, read_data="cd /path1")
@patch.object(HistoryUtils, '_get_history_file_path')
@patch('cross_platform.history_utils.Path') 
def test_get_nth_recent_path_n_too_large(MockPatchedPath, mock_get_hist_path, mock_open_file, monkeypatch, mock_os_expanduser):
    MockPatchedPath.side_effect = create_path_constructor_side_effect(
        lambda path_str: path_str == "/path1", "GetNthTooLarge"
    )
    monkeypatch.setattr(platform, 'system', lambda: 'Linux')
    monkeypatch.setenv("SHELL", "/bin/bash")
        
    hu = HistoryUtils()
    mock_get_hist_path.return_value = "/fake/history.txt"
    assert hu.get_nth_recent_path(2) is None

@patch.object(HistoryUtils, '_get_history_file_path') 
@patch('cross_platform.history_utils.Path') 
def test_get_nth_recent_path_no_history_file(MockPatchedPath, mock_get_hist_path, monkeypatch):
    MockPatchedPath.side_effect = create_path_constructor_side_effect(lambda _: False) 
    monkeypatch.setattr(platform, 'system', lambda: 'Linux')
    hu = HistoryUtils()
    mock_get_hist_path.return_value = None 
    assert hu.get_nth_recent_path(1) is None

@patch('cross_platform.history_utils.Path') 
def test_get_nth_recent_path_n_invalid(MockPatchedPath, monkeypatch):
    MockPatchedPath.side_effect = create_path_constructor_side_effect(lambda _: False)
    monkeypatch.setattr(platform, 'system', lambda: 'Linux')
    hu = HistoryUtils()
    assert hu.get_nth_recent_path(0) is None
    assert hu.get_nth_recent_path(-1) is None

@patch('builtins.open', new_callable=mock_open, read_data="") 
@patch.object(HistoryUtils, '_get_history_file_path')
@patch('cross_platform.history_utils.Path')
def test_get_nth_recent_path_empty_history_file(MockPatchedPath, mock_get_hist_path, mock_open_file, monkeypatch):
    MockPatchedPath.side_effect = create_path_constructor_side_effect(lambda _: False) 
    monkeypatch.setattr(platform, 'system', lambda: 'Linux')
    monkeypatch.setenv("SHELL", "/bin/bash")
    hu = HistoryUtils()
    mock_get_hist_path.return_value = "/fake/empty_history.txt"
    assert hu.get_nth_recent_path(1) is None

# --- Tests for main ---

@patch('argparse.ArgumentParser.parse_args')
@patch('cross_platform.history_utils.HistoryUtils') 
@patch('cross_platform.history_utils.console') 
def test_main_success(mock_console, MockHistoryUtils, mock_parse_args, monkeypatch):
    mock_args = MagicMock()
    mock_args.number = 1
    mock_parse_args.return_value = mock_args
    
    mock_hu_instance = MockHistoryUtils.return_value
    mock_hu_instance.get_nth_recent_path.return_value = "/expected/path"
    
    history_main() 
    
    MockHistoryUtils.assert_called_once() 
    mock_hu_instance.get_nth_recent_path.assert_called_once_with(1)
    mock_console.print.assert_called_once_with("/expected/path")

@patch('argparse.ArgumentParser.parse_args')
@patch('cross_platform.history_utils.HistoryUtils')
@patch('sys.exit') 
@patch('cross_platform.history_utils.console') 
def test_main_failure_path_not_found(mock_console, mock_sys_exit, MockHistoryUtils, mock_parse_args, monkeypatch):
    mock_args = MagicMock()
    mock_args.number = 5
    mock_parse_args.return_value = mock_args
    
    mock_hu_instance = MockHistoryUtils.return_value
    mock_hu_instance.get_nth_recent_path.return_value = None
    
    history_main()
    
    MockHistoryUtils.assert_called_once()
    mock_hu_instance.get_nth_recent_path.assert_called_once_with(5)
    
    assert "Error: Could not retrieve the 5th" in mock_console.print.call_args[0][0]
    assert mock_console.print.call_args[1]['stderr'] is True 
    
    mock_sys_exit.assert_called_once_with(1)
