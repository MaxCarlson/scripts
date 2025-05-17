# VERSION CHECK: THIS IS THE FILE FROM AFTER THE "SIMPLIFIED MOCK" ATTEMPT - RUNNING NOW

# tests/history_utils_test.py

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

# --- SIMPLIFIED Helper function to create path_constructor_side_effect ---
def create_path_constructor_side_effect(exists_check_func_from_test, test_name="UnknownTest"):
    def path_constructor_side_effect(path_str_arg_to_constructor_param): # This is the side_effect for Path()
        mock_path_instance = MagicMock(spec=pathlib.Path)
        
        # Store the path string that this mock instance represents.
        # Ensure it's a string, as pathlib.Path() can accept Path-like objects.
        actual_path_str = str(path_str_arg_to_constructor_param)
        mock_path_instance._test_path_str = actual_path_str
        
        # For .name attribute, typically used in _get_shell_type
        mock_path_instance.name = os.path.basename(actual_path_str)

        # --- Mocked .exists() method ---
        # This function is assigned as a method, so it needs a 'self'-like first argument.
        def simplified_exists_method(self_obj): # self_obj will be mock_path_instance
            path_to_check = self_obj._test_path_str
            print(f"[{test_name}_SIMPLIFIED_MOCK_EXISTS] Path is '{path_to_check}'. Calling test lambda.")
            # exists_check_func_from_test is the lambda from the specific test (e.g., lambda p: p == "/foo/bar")
            result = bool(exists_check_func_from_test(path_to_check))
            print(f"[{test_name}_SIMPLIFIED_MOCK_EXISTS] Test lambda returned {result}. Mock .exists() is returning {result}.")
            return result
        mock_path_instance.exists = simplified_exists_method

        # --- Mocked .resolve() method ---
        # This function is assigned as a method, so it needs a 'self'-like first argument.
        def simplified_resolve_method(self_obj, strict=False): # self_obj will be mock_path_instance
            path_to_resolve = self_obj._test_path_str
            print(f"[{test_name}_SIMPLIFIED_MOCK_RESOLVE] Path is '{path_to_resolve}'. Returning a new mock for the same path string.")
            
            # Resolve returns a *new* Path object. For simplicity, this new mock will be basic.
            resolved_obj_mock = MagicMock(spec=pathlib.Path)
            resolved_obj_mock._test_path_str = path_to_resolve # Represents the same path string
            # Ensure the new mock can be stringified
            resolved_obj_mock.__str__ = lambda s: s._test_path_str # s is resolved_obj_mock
            # Basic resolve for the new object returns itself
            resolved_obj_mock.resolve = lambda s, st=False: s 
            return resolved_obj_mock
        mock_path_instance.resolve = simplified_resolve_method

        # --- Mocked __str__() method ---
        # This function is assigned as a method, so it needs a 'self'-like first argument.
        def simplified_str_method(self_obj): # self_obj will be mock_path_instance
            path_for_str = self_obj._test_path_str
            print(f"[{test_name}_SIMPLIFIED_MOCK_STR] Path is '{path_for_str}'.")
            return path_for_str
        mock_path_instance.__str__ = simplified_str_method
        
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
    expected_paths = ["/foo/bar", "/another/path"]
    MockPatchedPath.side_effect = create_path_constructor_side_effect(
        lambda path_str: path_str in expected_paths, "ExtractSimple"
    )
    monkeypatch.setattr(platform, 'system', lambda: 'Linux')
    monkeypatch.setenv("SHELL", "/bin/bash")

    hu = HistoryUtils() 
    history_lines = ["cd /foo/bar", "ls /another/path", "git status"]
    paths = hu._extract_paths_from_history_lines(history_lines)
    assert paths == ["/another/path", "/foo/bar"] 

@patch('cross_platform.history_utils.Path')
def test_extract_paths_zsh_extended_format(MockPatchedPath, monkeypatch, mock_os_expanduser):
    expected_path = "/valid/zsh_path"
    MockPatchedPath.side_effect = create_path_constructor_side_effect(
        lambda path_str: path_str == expected_path, "ExtractZshExt"
    )
    monkeypatch.setattr(platform, 'system', lambda: 'Linux')
    monkeypatch.setenv("SHELL", "/bin/zsh")
    
    hu = HistoryUtils()
    hu.shell_type = 'zsh' 
    history_lines = [": 1234567890:0;cd /valid/zsh_path"]
    paths = hu._extract_paths_from_history_lines(history_lines)
    assert paths == [expected_path]

@patch('cross_platform.history_utils.Path')
def test_extract_paths_uniqueness_and_order(MockPatchedPath, monkeypatch, mock_os_expanduser):
    existing_paths = ["/path1", "/path2", "/path3.txt"]
    MockPatchedPath.side_effect = create_path_constructor_side_effect(
        lambda path_str: path_str in existing_paths, "ExtractUniqOrder"
    )
    monkeypatch.setattr(platform, 'system', lambda: 'Linux')
    monkeypatch.setenv("SHELL", "/bin/bash")

    hu = HistoryUtils()
    history_lines = ["cd /path1", "ls /path2", "cd /path1", "cat /path3.txt"]
    paths = hu._extract_paths_from_history_lines(history_lines)
    assert paths == ["/path3.txt", "/path2", "/path1"]

@patch('cross_platform.history_utils.Path')
def test_extract_paths_with_spaces_and_quotes(MockPatchedPath, monkeypatch, mock_os_expanduser):
    path_as_arg = "/mnt/c/My Docs/file.txt" 
    MockPatchedPath.side_effect = create_path_constructor_side_effect(
        lambda path_str: path_str == path_as_arg, "ExtractSpacesQuotes"
    )
    monkeypatch.setattr(platform, 'system', lambda: 'Linux') 
    monkeypatch.setenv("SHELL", "/bin/bash")

    hu = HistoryUtils()
    history_lines = ['open "/mnt/c/My Docs/file.txt"']
    paths = hu._extract_paths_from_history_lines(history_lines)
    assert paths == [path_as_arg]

@patch('cross_platform.history_utils.Path')
def test_extract_paths_filters_options_and_urls(MockPatchedPath, monkeypatch, mock_os_expanduser):
    existing_paths = ["/actual/path", "/another/path"]
    MockPatchedPath.side_effect = create_path_constructor_side_effect(
        lambda path_str: path_str in existing_paths, "ExtractFilters"
    )
    monkeypatch.setattr(platform, 'system', lambda: 'Linux')
    monkeypatch.setenv("SHELL", "/bin/bash")
    
    hu = HistoryUtils()
    history_lines = ["ls -l /actual/path", "curl http://example.com", "some_tool --config=/another/path"]
    paths = hu._extract_paths_from_history_lines(history_lines)
    
    assert "/actual/path" in paths
    assert "/another/path" in paths
    assert len(paths) == 2 
    if paths and len(paths) == 2: 
        assert paths.index("/another/path") < paths.index("/actual/path")


# --- Tests for get_nth_recent_path ---

@patch('builtins.open', new_callable=mock_open, read_data="cd /path3\nls /path2\ncat /path1")
@patch.object(HistoryUtils, '_get_history_file_path') 
@patch('cross_platform.history_utils.Path') 
def test_get_nth_recent_path_success(MockPatchedPath, mock_get_hist_path, mock_open_file, monkeypatch, mock_os_expanduser):
    existing_paths = ["/path1", "/path2", "/path3"]
    MockPatchedPath.side_effect = create_path_constructor_side_effect(
        lambda path_str: path_str in existing_paths, "GetNthSuccess"
    )
    monkeypatch.setattr(platform, 'system', lambda: 'Linux') 
    monkeypatch.setenv("SHELL", "/bin/bash") 
    
    hu = HistoryUtils() 
    mock_get_hist_path.return_value = "/fake/history.txt" 
    
    assert hu.get_nth_recent_path(1) == "/path1" 
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
