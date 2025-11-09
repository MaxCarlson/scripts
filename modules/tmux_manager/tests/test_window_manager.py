"""
Comprehensive tests for TmuxWindowManager class.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from tmux_manager.window_manager import TmuxWindowManager


@pytest.fixture
def manager():
    """Create a TmuxWindowManager instance for testing."""
    return TmuxWindowManager()


class TestWindowSpecParsing:
    """Tests for _parse_window_spec method."""

    def test_single_index(self, manager):
        """Test parsing a single window index."""
        indices, needs_resolution = manager._parse_window_spec("5")
        assert indices == [5]
        assert needs_resolution is False

    def test_range_with_dots(self, manager):
        """Test parsing range with .. separator."""
        indices, needs_resolution = manager._parse_window_spec("4..10")
        assert indices == [4, 5, 6, 7, 8, 9, 10]
        assert needs_resolution is False

    def test_range_with_colon(self, manager):
        """Test parsing range with : separator."""
        indices, needs_resolution = manager._parse_window_spec("4:10")
        assert indices == [4, 5, 6, 7, 8, 9, 10]
        assert needs_resolution is False

    def test_comma_separated(self, manager):
        """Test parsing comma-separated indices."""
        indices, needs_resolution = manager._parse_window_spec("1,7,8,11")
        assert indices == [1, 7, 8, 11]
        assert needs_resolution is False

    def test_single_negative_index(self, manager):
        """Test parsing single negative index."""
        indices, needs_resolution = manager._parse_window_spec("-1")
        assert indices == [-1]
        assert needs_resolution is True

    def test_range_with_negative_end(self, manager):
        """Test parsing range with negative end index."""
        indices, needs_resolution = manager._parse_window_spec("4..-1")
        assert indices == (4, -1)
        assert needs_resolution is True

    def test_range_with_negative_start(self, manager):
        """Test parsing range with negative start index."""
        indices, needs_resolution = manager._parse_window_spec("-3..10")
        assert indices == (-3, 10)
        assert needs_resolution is True

    def test_comma_with_negative(self, manager):
        """Test parsing comma-separated with negative indices."""
        indices, needs_resolution = manager._parse_window_spec("1,7,-2,11")
        assert indices == [1, 7, -2, 11]
        assert needs_resolution is True

    def test_empty_spec(self, manager):
        """Test parsing empty specification."""
        indices, needs_resolution = manager._parse_window_spec("")
        assert indices == []
        assert needs_resolution is False

    def test_none_spec(self, manager):
        """Test parsing None specification."""
        indices, needs_resolution = manager._parse_window_spec(None)
        assert indices == []
        assert needs_resolution is False


class TestNegativeIndexResolution:
    """Tests for _resolve_negative_indices method."""

    def test_resolve_single_negative(self, manager):
        """Test resolving single negative index."""
        with patch.object(manager, 'get_window_indices', return_value=[0, 1, 2, 5, 7]):
            resolved = manager._resolve_negative_indices([-1], 'test_session')
            assert resolved == [7]

    def test_resolve_second_to_last(self, manager):
        """Test resolving -2 (second to last)."""
        with patch.object(manager, 'get_window_indices', return_value=[0, 1, 2, 5, 7]):
            resolved = manager._resolve_negative_indices([-2], 'test_session')
            assert resolved == [5]

    def test_resolve_range_with_negative(self, manager):
        """Test resolving range with negative end."""
        with patch.object(manager, 'get_window_indices', return_value=[0, 1, 2, 5, 7]):
            resolved = manager._resolve_negative_indices([(2, -1)], 'test_session')
            assert resolved == [2, 3, 4, 5, 6, 7]

    def test_resolve_mixed_indices(self, manager):
        """Test resolving mix of positive and negative indices."""
        with patch.object(manager, 'get_window_indices', return_value=[0, 1, 2, 5, 7]):
            resolved = manager._resolve_negative_indices([1, -2, 5], 'test_session')
            assert resolved == [1, 5, 5]  # Note: 5 appears twice

    def test_resolve_with_empty_windows(self, manager):
        """Test resolving when no windows exist."""
        with patch.object(manager, 'get_window_indices', return_value=[]):
            resolved = manager._resolve_negative_indices([-1], 'test_session')
            assert resolved == []

    def test_resolve_out_of_range_negative(self, manager):
        """Test resolving negative index that's too large."""
        with patch.object(manager, 'get_window_indices', return_value=[0, 1, 2]):
            resolved = manager._resolve_negative_indices([-10], 'test_session')
            assert resolved == []  # Out of range, so nothing resolved


class TestWindowOperations:
    """Tests for window operation methods."""

    @patch.object(TmuxWindowManager, '_run_tmux_command')
    @patch.object(TmuxWindowManager, '_get_current_session', return_value='test_session')
    @patch.object(TmuxWindowManager, 'get_window_indices', return_value=[0, 1, 2, 5, 7])
    def test_close_single_window(self, mock_indices, mock_session, mock_run, manager):
        """Test closing a single window."""
        mock_run.return_value = (0, "", "")

        result = manager.close_windows("5")

        assert result is True
        mock_run.assert_called_once_with(['kill-window', '-t', 'test_session:5'])

    @patch.object(TmuxWindowManager, '_run_tmux_command')
    @patch.object(TmuxWindowManager, '_get_current_session', return_value='test_session')
    @patch.object(TmuxWindowManager, 'get_window_indices', return_value=[0, 1, 2, 5, 7])
    def test_close_window_range(self, mock_indices, mock_session, mock_run, manager):
        """Test closing a range of windows."""
        mock_run.return_value = (0, "", "")

        result = manager.close_windows("1..2")

        assert result is True
        assert mock_run.call_count == 2  # Called for each window

    @patch.object(TmuxWindowManager, '_run_tmux_command')
    @patch.object(TmuxWindowManager, '_get_current_session', return_value='test_session')
    @patch.object(TmuxWindowManager, 'get_window_indices', return_value=[0, 1, 2])
    def test_close_invalid_window(self, mock_indices, mock_session, mock_run, manager):
        """Test closing window that doesn't exist."""
        result = manager.close_windows("99")

        assert result is False
        mock_run.assert_not_called()

    @patch.object(TmuxWindowManager, '_run_tmux_command')
    @patch.object(TmuxWindowManager, '_get_current_session', return_value='test_session')
    @patch.object(TmuxWindowManager, '_get_current_window_index', return_value=1)
    @patch.object(TmuxWindowManager, 'window_exists', return_value=True)
    @patch.object(TmuxWindowManager, 'get_window_indices', return_value=[0, 1, 2, 5])
    def test_move_window_same_session(self, mock_indices, mock_exists, mock_current_win,
                                     mock_session, mock_run, manager):
        """Test moving window within same session."""
        mock_run.return_value = (0, "", "")

        result = manager.move_window_same_session(target_index=5)

        assert result is True
        mock_run.assert_called_once_with(
            ['move-window', '-s', 'test_session:1', '-t', 'test_session:5']
        )

    @patch.object(TmuxWindowManager, '_run_tmux_command')
    @patch.object(TmuxWindowManager, '_get_current_session', return_value='test_session')
    @patch.object(TmuxWindowManager, '_get_current_window_index', return_value=1)
    @patch.object(TmuxWindowManager, 'window_exists', return_value=True)
    @patch.object(TmuxWindowManager, 'get_window_indices', return_value=[0, 1, 2, 5])
    def test_swap_window_same_session(self, mock_indices, mock_exists, mock_current_win,
                                      mock_session, mock_run, manager):
        """Test swapping windows within same session."""
        mock_run.return_value = (0, "", "")

        result = manager.swap_window_same_session(target_index=5)

        assert result is True
        mock_run.assert_called_once_with(
            ['swap-window', '-s', 'test_session:1', '-t', 'test_session:5']
        )

    @patch.object(TmuxWindowManager, '_run_tmux_command')
    @patch.object(TmuxWindowManager, '_get_current_session', return_value='source_session')
    @patch.object(TmuxWindowManager, '_get_current_window_index', return_value=1)
    @patch.object(TmuxWindowManager, 'window_exists', return_value=True)
    @patch.object(TmuxWindowManager, 'session_exists', return_value=True)
    def test_move_window_to_session(self, mock_sess_exists, mock_win_exists,
                                    mock_current_win, mock_session, mock_run, manager):
        """Test moving window to different session."""
        mock_run.return_value = (0, "", "")

        result = manager.move_window_to_session(target_session='target_session')

        assert result is True
        mock_run.assert_called_once_with(
            ['move-window', '-s', 'source_session:1', '-t', 'target_session']
        )

    @patch.object(TmuxWindowManager, '_run_tmux_command')
    @patch.object(TmuxWindowManager, '_get_current_session', return_value='source_session')
    @patch.object(TmuxWindowManager, '_get_current_window_index', return_value=1)
    @patch.object(TmuxWindowManager, 'window_exists', return_value=True)
    @patch.object(TmuxWindowManager, 'session_exists', return_value=True)
    @patch.object(TmuxWindowManager, 'get_window_indices', return_value=[0, 1, 2])
    def test_swap_window_between_sessions(self, mock_indices, mock_sess_exists, mock_win_exists,
                                         mock_current_win, mock_session, mock_run, manager):
        """Test swapping windows between sessions."""
        mock_run.return_value = (0, "", "")

        result = manager.swap_window_between_sessions(
            target_session='target_session', target_index=2
        )

        assert result is True
        mock_run.assert_called_once_with(
            ['swap-window', '-s', 'source_session:1', '-t', 'target_session:2']
        )


class TestSessionAndWindowQueries:
    """Tests for session and window query methods."""

    @patch.object(TmuxWindowManager, '_run_tmux_command')
    def test_session_exists_true(self, mock_run, manager):
        """Test checking if session exists (positive case)."""
        mock_run.return_value = (0, "", "")

        result = manager.session_exists('test_session')

        assert result is True
        mock_run.assert_called_once_with(['has-session', '-t', 'test_session'])

    @patch.object(TmuxWindowManager, '_run_tmux_command')
    def test_session_exists_false(self, mock_run, manager):
        """Test checking if session exists (negative case)."""
        mock_run.return_value = (1, "", "")

        result = manager.session_exists('nonexistent')

        assert result is False

    @patch.object(TmuxWindowManager, '_run_tmux_command')
    def test_list_sessions(self, mock_run, manager):
        """Test listing sessions."""
        mock_run.return_value = (0, "session1\nsession2\nsession3", "")

        result = manager.list_sessions()

        assert result == ['session1', 'session2', 'session3']

    @patch.object(TmuxWindowManager, '_run_tmux_command')
    @patch.object(TmuxWindowManager, '_get_current_session', return_value='test_session')
    def test_list_windows(self, mock_session, mock_run, manager):
        """Test listing windows."""
        mock_run.return_value = (0, "0 zsh\n1 vim\n2 htop", "")

        result = manager.list_windows()

        assert result == ['0 zsh', '1 vim', '2 htop']

    @patch.object(TmuxWindowManager, 'list_windows')
    def test_get_window_indices(self, mock_list, manager):
        """Test getting window indices."""
        mock_list.return_value = ['0', '1', '2', '5', '7']

        result = manager.get_window_indices('test_session')

        assert result == [0, 1, 2, 5, 7]

    @patch.object(TmuxWindowManager, 'get_window_indices')
    def test_window_exists(self, mock_indices, manager):
        """Test checking if window exists."""
        mock_indices.return_value = [0, 1, 2, 5, 7]

        assert manager.window_exists(1, 'test_session') is True
        assert manager.window_exists(3, 'test_session') is False
        assert manager.window_exists(7, 'test_session') is True


class TestErrorHandling:
    """Tests for error handling."""

    @patch.object(TmuxWindowManager, '_get_current_session', return_value=None)
    def test_close_windows_not_in_tmux(self, mock_session, manager):
        """Test error when not in tmux and no session specified."""
        result = manager.close_windows("5")
        assert result is False

    @patch.object(TmuxWindowManager, '_run_tmux_command')
    @patch.object(TmuxWindowManager, '_get_current_session', return_value='test_session')
    @patch.object(TmuxWindowManager, 'get_window_indices', return_value=[0, 1, 2])
    def test_close_windows_tmux_error(self, mock_indices, mock_session, mock_run, manager):
        """Test error when tmux command fails."""
        mock_run.return_value = (1, "", "error closing window")

        result = manager.close_windows("1")

        assert result is False

    @patch.object(TmuxWindowManager, '_get_current_session', return_value='test_session')
    @patch.object(TmuxWindowManager, '_get_current_window_index', return_value=None)
    def test_move_window_cannot_determine_current(self, mock_current_win, mock_session, manager):
        """Test error when cannot determine current window."""
        result = manager.move_window_same_session(target_index=5)
        assert result is False


class TestFuzzySelection:
    """Tests for fzf integration."""

    @patch('subprocess.run')
    @patch.object(TmuxWindowManager, '_is_fzf_installed', return_value=True)
    @patch.object(TmuxWindowManager, 'list_windows', return_value=['0 zsh', '1 vim', '2 htop'])
    def test_fuzzy_select_window(self, mock_list, mock_fzf_check, mock_subprocess, manager):
        """Test fzf window selection."""
        mock_subprocess.return_value = Mock(stdout='1 vim\n', returncode=0)

        result = manager._fuzzy_select_window('test_session')

        assert result == 1

    @patch('subprocess.run')
    @patch.object(TmuxWindowManager, '_is_fzf_installed', return_value=True)
    @patch.object(TmuxWindowManager, 'list_sessions', return_value=['session1', 'session2'])
    def test_fuzzy_select_session(self, mock_list, mock_fzf_check, mock_subprocess, manager):
        """Test fzf session selection."""
        mock_subprocess.return_value = Mock(stdout='session2', returncode=0)

        result = manager._fuzzy_select_session()

        assert result == 'session2'

    @patch.object(TmuxWindowManager, '_is_fzf_installed', return_value=False)
    def test_fuzzy_select_no_fzf(self, mock_fzf_check, manager):
        """Test fuzzy selection when fzf is not installed."""
        result = manager._fuzzy_select_window('test_session')
        assert result is None
