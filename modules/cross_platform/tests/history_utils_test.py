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
    """Mocks os.path.exists globally."""
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

# --- Helper function to create path_constructor_side_effect ---
def create_path_constructor_side_effect(exists_check_func_from_test, test_name="UnknownTest"):
    def path_constructor_side_effect(path_str_arg_to_constructor):
        mock_instance = MagicMock(spec=pathlib.Path) 
        mock_instance._constructor_arg_str = str(path_str_arg_to_constructor)
        mock_instance.name = os.path.basename(mock_instance._constructor_arg_str)

        # This function is assigned as a method to mock_instance (mock_instance.exists)
        # Therefore, it MUST accept 'self' as its first argument.
        def verbose_exists_logic(slf_instance_param): # Ensure this param is present
            path_to_check_in_exists = slf_instance_param._constructor_arg_str 
            original_result = exists_check_func_from_test(path_to_check_in_exists)
            final_bool_result = bool(original_result) 
            print(
                f"[{test_name}_VERBOSE_EXISTS_LOGIC]\n"
                f"  Path() constructor received: '{slf_instance_param._constructor_arg_str}' (type: {type(slf_instance_param._constructor_arg_str).__name__})\n"
                f"  Path checked by .exists():   '{path_to_check_in_exists}' (type: {type(path_to_check_in_exists).__name__})\n"
                f"  exists_check_func_from_test (original): {original_result} (type: {type(original_result).__name__})\n"
                f"  exists_check_func_from_test (coerced to bool for return): {final_bool_result}"
            )
            return final_bool_result 
        
        mock_instance.exists = verbose_exists_logic 
        
        # resolve_logic is a side_effect for a *new* MagicMock, so it's called like a normal function.
        # The arguments it receives are those passed to path_obj.resolve(...).
        def resolve_logic(strict=False): # 'strict' is from the call to path_obj.resolve(strict=...)
            # 'mock_instance' (the parent Path mock) is available from the closure.
            resolved_path_str = mock_instance._constructor_arg_str 
            
            resolved_path_mock_obj = MagicMock(spec=pathlib.Path)
            resolved_path_mock_obj._constructor_arg_str = resolved_path_str 
            resolved_path_mock_obj.name = os.path.basename(resolved_path_str)
            # This lambda is assigned as a method, so it needs 'self'.
            resolved_path_mock_obj.exists = lambda s_resolved_exists: True 
            # This lambda is assigned as a method, so it needs 'self'.
            # It uses 'resolved_path_str' from its closure.
            resolved_path_mock_obj.__str__ = lambda s_resolved_str: resolved_path_str
            # This lambda is assigned as a method, so it needs 'self'.
            resolved_path_mock_obj.resolve = lambda s_resolved_resolve, strict_level_param=False: resolved_path_mock_obj
            
            print(f"[{test_name}_VERBOSE_RESOLVE_LOGIC] Resolving '{mock_instance._constructor_arg_str}', returning mock for '{resolved_path_str}'")
            return resolved_path_mock_obj

        # mock_instance.resolve is a MagicMock. When mock_instance.resolve() is called,
        # the resolve_logic function is executed as its side_effect.
        mock_instance.resolve = MagicMock(side_effect=resolve_logic)
        
        # This lambda is assigned as a method (mock_instance.__str__), so it needs 'self'.
        mock_instance.__str__ = lambda s_main_str_param: s_main_str_param._constructor_arg_str 
        return mock_instance
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
