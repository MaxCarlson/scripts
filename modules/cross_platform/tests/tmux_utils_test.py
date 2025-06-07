import pytest
import sys
from unittest.mock import patch, MagicMock, call

from cross_platform.tmux_utils import TmuxManager, main as tmux_main

@pytest.fixture
def manager_with_mocks(monkeypatch):
    """Fixture to get a TmuxManager instance with its dependencies mocked."""
    mock_run_tmux = MagicMock()
    mock_is_installed = MagicMock(return_value=True)
    
    monkeypatch.setattr(TmuxManager, '_run_tmux_command', mock_run_tmux)
    monkeypatch.setattr(TmuxManager, '_is_tmux_installed', mock_is_installed)
    
    manager = TmuxManager()
    return manager, mock_run_tmux

def test_list_sessions_raw(manager_with_mocks):
    manager, mock_run_tmux = manager_with_mocks
    mock_run_tmux.return_value = (0, "session1\nsession2", "")
    
    sessions = manager.list_sessions_raw()
    
    assert sessions == ["session1", "session2"]
    mock_run_tmux.assert_called_once_with(['list-sessions', '-F', "'#{session_name}'"])

def test_session_exists_true(manager_with_mocks):
    manager, mock_run_tmux = manager_with_mocks
    mock_run_tmux.return_value = (0, "", "") # RC 0 means it exists
    
    assert manager.session_exists("my_session") is True
    mock_run_tmux.assert_called_once_with(['has-session', '-t', "my_session"])

def test_session_exists_false(manager_with_mocks):
    manager, mock_run_tmux = manager_with_mocks
    mock_run_tmux.return_value = (1, "", "not found") # RC non-zero means it doesn't exist
    
    assert manager.session_exists("my_session") is False

@patch('os.environ.get', return_value=None) # Simulate being outside tmux
@patch('subprocess.call')
def test_attach_or_create_session_attaches_if_exists(mock_sub_call, mock_env_get, manager_with_mocks):
    manager, mock_run_tmux = manager_with_mocks
    # First call for session_exists, second for switch-client (which won't happen)
    mock_run_tmux.return_value = (0, "", "") # Session exists
    
    manager.attach_or_create_session("existing_session")
    
    mock_sub_call.assert_called_once_with(['tmux', 'attach-session', '-t', 'existing_session'])

@patch('os.environ.get', return_value=None) # Simulate being outside tmux
@patch('subprocess.call')
def test_attach_or_create_session_creates_if_not_exists(mock_sub_call, mock_env_get, manager_with_mocks):
    manager, mock_run_tmux = manager_with_mocks
    mock_run_tmux.return_value = (1, "", "not found") # Session does not exist
    
    manager.attach_or_create_session("new_session", default_command="nvim")
    
    expected_call_args = ['tmux', 'new-session', '-s', 'new_session', '-n', 'shell', 'nvim']
    mock_sub_call.assert_called_once_with(expected_call_args)

@patch('os.environ.get', return_value="some_value") # Simulate being inside tmux
def test_attach_or_create_switches_client_if_inside_tmux(mock_env_get, manager_with_mocks):
    manager, mock_run_tmux = manager_with_mocks
    # First call for session_exists, second for switch-client
    mock_run_tmux.side_effect = [(0, "", ""), (0, "", "")]
    
    manager.attach_or_create_session("another_session")

    assert mock_run_tmux.call_count == 2
    mock_run_tmux.assert_has_calls([
        call(['has-session', '-t', 'another_session']),
        call(['switch-client', '-t', 'another_session'])
    ])

def test_capture_pane_success(manager_with_mocks):
    manager, mock_run_tmux = manager_with_mocks
    expected_buffer = "line 1\nline 2\n"
    mock_run_tmux.return_value = (0, expected_buffer, "")
    
    buffer = manager.capture_pane(start_line='-100', end_line='-')
    
    assert buffer == expected_buffer
    mock_run_tmux.assert_called_once_with(['capture-pane', '-pS', '-100', '-E', '-', '-J'])

def test_capture_pane_failure(manager_with_mocks):
    manager, mock_run_tmux = manager_with_mocks
    mock_run_tmux.return_value = (1, "", "some error")
    
    buffer = manager.capture_pane()
    
    assert buffer is None
    mock_run_tmux.assert_called_once()

@patch('argparse.ArgumentParser.parse_args')
@patch('cross_platform.tmux_utils.TmuxManager')
def test_main_dispatch(MockTmuxManager, mock_parse_args):
    """Test that main correctly dispatches to the right manager method."""
    mock_manager_instance = MockTmuxManager.return_value
    
    # Test 'ls' command
    mock_args = MagicMock()
    mock_args.command = 'ls'
    mock_parse_args.return_value = mock_args
    tmux_main()
    mock_manager_instance.list_sessions_pretty.assert_called_once()
    
    # Test 'ts' command
    mock_manager_instance.reset_mock()
    mock_args.command = 'ts'
    mock_args.session_name = 'test_session'
    mock_parse_args.return_value = mock_args
    tmux_main()
    mock_manager_instance.attach_or_create_session.assert_called_once_with('test_session')
