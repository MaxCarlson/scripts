"""
Shared pytest fixtures for tmux_manager tests.
"""

import pytest
from unittest.mock import Mock, patch


@pytest.fixture
def mock_tmux_command():
    """Mock _run_tmux_command to avoid actual tmux calls."""
    with patch('tmux_manager.window_manager.TmuxWindowManager._run_tmux_command') as mock:
        mock.return_value = (0, "", "")
        yield mock


@pytest.fixture
def mock_env_tmux():
    """Mock TMUX environment variable to simulate being inside tmux."""
    with patch.dict('os.environ', {'TMUX': '/tmp/tmux-1000/default,12345,0'}):
        yield


@pytest.fixture
def mock_env_no_tmux():
    """Mock environment without TMUX variable."""
    with patch.dict('os.environ', {}, clear=True):
        yield


@pytest.fixture
def sample_window_indices():
    """Provide sample window indices for testing."""
    return [0, 1, 2, 5, 7, 10]


@pytest.fixture
def sample_sessions():
    """Provide sample session names for testing."""
    return ['session1', 'session2', 'ai', 'dotfiles', 'scripts']


@pytest.fixture
def mock_fzf_selection():
    """Mock fzf selection."""
    def _mock_fzf(return_value, success=True):
        mock_proc = Mock()
        mock_proc.stdout = return_value
        mock_proc.returncode = 0 if success else 1
        with patch('subprocess.run', return_value=mock_proc):
            yield
    return _mock_fzf
