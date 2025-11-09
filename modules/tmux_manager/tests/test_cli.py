"""
Tests for CLI interface.
"""

import pytest
import sys
from unittest.mock import patch, Mock
from tmux_manager.cli import main


class TestCLICommands:
    """Tests for CLI command execution."""

    @patch('sys.argv', ['tmwin', 'closew', '5'])
    @patch('tmux_manager.cli.TmuxWindowManager')
    def test_closew_command(self, mock_manager_class):
        """Test closew command execution."""
        mock_manager = Mock()
        mock_manager._is_tmux_installed.return_value = True
        mock_manager.close_windows.return_value = True
        mock_manager_class.return_value = mock_manager

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        mock_manager.close_windows.assert_called_once_with('5', None)

    @patch('sys.argv', ['tmwin', 'closew', '4..10', '-t', 'test_session'])
    @patch('tmux_manager.cli.TmuxWindowManager')
    def test_closew_with_session(self, mock_manager_class):
        """Test closew command with session specified."""
        mock_manager = Mock()
        mock_manager._is_tmux_installed.return_value = True
        mock_manager.close_windows.return_value = True
        mock_manager_class.return_value = mock_manager

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        mock_manager.close_windows.assert_called_once_with('4..10', 'test_session')

    @patch('sys.argv', ['tmwin', 'mvw', '-i', '0'])
    @patch('tmux_manager.cli.TmuxWindowManager')
    def test_mvw_command(self, mock_manager_class):
        """Test mvw command execution."""
        mock_manager = Mock()
        mock_manager._is_tmux_installed.return_value = True
        mock_manager.move_window_same_session.return_value = True
        mock_manager_class.return_value = mock_manager

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        mock_manager.move_window_same_session.assert_called_once_with(
            target_index=0, source_index=None, session_name=None
        )

    @patch('sys.argv', ['tmwin', 'mvw', '-i', '-1', '-w', '3'])
    @patch('tmux_manager.cli.TmuxWindowManager')
    def test_mvw_with_negative_index(self, mock_manager_class):
        """Test mvw command with negative target index."""
        mock_manager = Mock()
        mock_manager._is_tmux_installed.return_value = True
        mock_manager.move_window_same_session.return_value = True
        mock_manager_class.return_value = mock_manager

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        mock_manager.move_window_same_session.assert_called_once_with(
            target_index=-1, source_index=3, session_name=None
        )

    @patch('sys.argv', ['tmwin', 'sww', '-i', '3'])
    @patch('tmux_manager.cli.TmuxWindowManager')
    def test_sww_command(self, mock_manager_class):
        """Test sww command execution."""
        mock_manager = Mock()
        mock_manager._is_tmux_installed.return_value = True
        mock_manager.swap_window_same_session.return_value = True
        mock_manager_class.return_value = mock_manager

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        mock_manager.swap_window_same_session.assert_called_once_with(
            target_index=3, source_index=None, session_name=None
        )

    @patch('sys.argv', ['tmwin', 'mvws', '-s', 'ai', '-i', '0'])
    @patch('tmux_manager.cli.TmuxWindowManager')
    def test_mvws_command(self, mock_manager_class):
        """Test mvws command execution."""
        mock_manager = Mock()
        mock_manager._is_tmux_installed.return_value = True
        mock_manager.move_window_to_session.return_value = True
        mock_manager_class.return_value = mock_manager

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        mock_manager.move_window_to_session.assert_called_once_with(
            target_session='ai', target_index=0, source_index=None, source_session=None
        )

    @patch('sys.argv', ['tmwin', 'mvws', '-s', 'ai'])
    @patch('tmux_manager.cli.TmuxWindowManager')
    def test_mvws_append_to_end(self, mock_manager_class):
        """Test mvws command with no target index (append to end)."""
        mock_manager = Mock()
        mock_manager._is_tmux_installed.return_value = True
        mock_manager.move_window_to_session.return_value = True
        mock_manager_class.return_value = mock_manager

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        mock_manager.move_window_to_session.assert_called_once_with(
            target_session='ai', target_index=None, source_index=None, source_session=None
        )

    @patch('sys.argv', ['tmwin', 'swws', '-s', 'ai', '-i', '3'])
    @patch('tmux_manager.cli.TmuxWindowManager')
    def test_swws_command(self, mock_manager_class):
        """Test swws command execution."""
        mock_manager = Mock()
        mock_manager._is_tmux_installed.return_value = True
        mock_manager.swap_window_between_sessions.return_value = True
        mock_manager_class.return_value = mock_manager

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        mock_manager.swap_window_between_sessions.assert_called_once_with(
            target_session='ai', target_index=3, source_index=None, source_session=None
        )

    @patch('sys.argv', ['tmwin', 'mvws', '--from', 'source_sess', '-s', 'target_sess'])
    @patch('tmux_manager.cli.TmuxWindowManager')
    def test_mvws_with_source_session(self, mock_manager_class):
        """Test mvws command with explicit source session."""
        mock_manager = Mock()
        mock_manager._is_tmux_installed.return_value = True
        mock_manager.move_window_to_session.return_value = True
        mock_manager_class.return_value = mock_manager

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        mock_manager.move_window_to_session.assert_called_once_with(
            target_session='target_sess', target_index=None,
            source_index=None, source_session='source_sess'
        )


class TestCLIErrorHandling:
    """Tests for CLI error handling."""

    @patch('sys.argv', ['tmwin', 'closew', '5'])
    @patch('tmux_manager.cli.TmuxWindowManager')
    def test_command_failure(self, mock_manager_class):
        """Test CLI exit code on command failure."""
        mock_manager = Mock()
        mock_manager._is_tmux_installed.return_value = True
        mock_manager.close_windows.return_value = False
        mock_manager_class.return_value = mock_manager

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1

    @patch('sys.argv', ['tmwin', 'closew', '5'])
    @patch('tmux_manager.cli.TmuxWindowManager')
    def test_tmux_not_installed(self, mock_manager_class):
        """Test CLI behavior when tmux is not installed."""
        mock_manager = Mock()
        mock_manager._is_tmux_installed.return_value = False
        mock_manager_class.return_value = mock_manager

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1

    @patch('sys.argv', ['tmwin'])
    def test_no_command(self):
        """Test CLI behavior when no command is provided."""
        with pytest.raises(SystemExit):
            main()

    @patch('sys.argv', ['tmwin', '--help'])
    def test_help_flag(self):
        """Test CLI help flag."""
        with pytest.raises(SystemExit) as exc_info:
            main()
        # Help exits with 0
        assert exc_info.value.code == 0

    @patch('sys.argv', ['tmwin', 'closew', '--help'])
    def test_subcommand_help(self):
        """Test subcommand help flag."""
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0


class TestCLIArgumentParsing:
    """Tests for argument parsing."""

    @patch('sys.argv', ['tmwin', 'closew', '4..10'])
    @patch('tmux_manager.cli.TmuxWindowManager')
    def test_range_parsing(self, mock_manager_class):
        """Test parsing of range specification."""
        mock_manager = Mock()
        mock_manager._is_tmux_installed.return_value = True
        mock_manager.close_windows.return_value = True
        mock_manager_class.return_value = mock_manager

        with pytest.raises(SystemExit):
            main()

        # Verify the range string is passed correctly
        call_args = mock_manager.close_windows.call_args
        assert call_args[0][0] == '4..10'

    @patch('sys.argv', ['tmwin', 'closew', '1,7,8,11'])
    @patch('tmux_manager.cli.TmuxWindowManager')
    def test_comma_separated_parsing(self, mock_manager_class):
        """Test parsing of comma-separated specification."""
        mock_manager = Mock()
        mock_manager._is_tmux_installed.return_value = True
        mock_manager.close_windows.return_value = True
        mock_manager_class.return_value = mock_manager

        with pytest.raises(SystemExit):
            main()

        call_args = mock_manager.close_windows.call_args
        assert call_args[0][0] == '1,7,8,11'


class TestIntegrationScenarios:
    """Integration tests for common usage scenarios."""

    @patch('sys.argv', ['tmwin', 'mvw', '-i', '0', '-t', 'my_session'])
    @patch('tmux_manager.cli.TmuxWindowManager')
    def test_move_to_first_position(self, mock_manager_class):
        """Test moving window to first position in a session."""
        mock_manager = Mock()
        mock_manager._is_tmux_installed.return_value = True
        mock_manager.move_window_same_session.return_value = True
        mock_manager_class.return_value = mock_manager

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        mock_manager.move_window_same_session.assert_called_once_with(
            target_index=0, source_index=None, session_name='my_session'
        )

    @patch('sys.argv', ['tmwin', 'closew', '0..5', '-t', 'cleanup_session'])
    @patch('tmux_manager.cli.TmuxWindowManager')
    def test_bulk_window_cleanup(self, mock_manager_class):
        """Test closing multiple windows for cleanup."""
        mock_manager = Mock()
        mock_manager._is_tmux_installed.return_value = True
        mock_manager.close_windows.return_value = True
        mock_manager_class.return_value = mock_manager

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        mock_manager.close_windows.assert_called_once_with('0..5', 'cleanup_session')
