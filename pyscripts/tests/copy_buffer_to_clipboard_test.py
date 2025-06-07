import pytest
import sys
from unittest.mock import patch, MagicMock

# Since the script is not in a package, we need to adjust the path to import it
# This assumes the tests are run from the project root.
sys.path.insert(0, '.')
from copy_buffer_to_clipboard import copy_buffer_to_clipboard_main

@pytest.fixture
def mock_dependencies(monkeypatch):
    """Mock all external dependencies for the script."""
    mock_system_utils = MagicMock()
    mock_tmux_manager = MagicMock()
    mock_set_clipboard = MagicMock()

    monkeypatch.setattr('copy_buffer_to_clipboard.SystemUtils', MagicMock(return_value=mock_system_utils))
    monkeypatch.setattr('copy_buffer_to_clipboard.TmuxManager', MagicMock(return_value=mock_tmux_manager))
    monkeypatch.setattr('copy_buffer_to_clipboard.set_clipboard', mock_set_clipboard)
    
    return mock_system_utils, mock_tmux_manager, mock_set_clipboard

def test_not_in_tmux_session(mock_dependencies, capsys):
    mock_system_utils, _, _ = mock_dependencies
    mock_system_utils.is_tmux.return_value = False

    exit_code = copy_buffer_to_clipboard_main(full=False, no_stats=False)
    
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "ERROR" in captured.err
    assert "designed to run inside a tmux session" in captured.err

def test_tmux_capture_fails(mock_dependencies, capsys):
    mock_system_utils, mock_tmux_manager, _ = mock_dependencies
    mock_system_utils.is_tmux.return_value = True
    mock_tmux_manager.capture_pane.return_value = None

    exit_code = copy_buffer_to_clipboard_main(full=False, no_stats=False)

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "ERROR" in captured.err
    assert "Failed to capture tmux pane buffer" in captured.err

def test_copy_since_last_clear_success(mock_dependencies):
    mock_system_utils, mock_tmux_manager, mock_set_clipboard = mock_dependencies
    mock_system_utils.is_tmux.return_value = True
    
    clear_sequence = "\x1b[H\x1b[2J"
    buffer_content = f"some old stuff\n{clear_sequence}the new stuff\nthat I want"
    mock_tmux_manager.capture_pane.return_value = buffer_content
    
    exit_code = copy_buffer_to_clipboard_main(full=False, no_stats=True)

    assert exit_code == 0
    mock_set_clipboard.assert_called_once_with("the new stuff\nthat I want")

def test_copy_full_buffer(mock_dependencies):
    mock_system_utils, mock_tmux_manager, mock_set_clipboard = mock_dependencies
    mock_system_utils.is_tmux.return_value = True
    
    clear_sequence = "\x1b[H\x1b[2J"
    buffer_content = f"some old stuff\n{clear_sequence}the new stuff"
    mock_tmux_manager.capture_pane.return_value = buffer_content
    
    exit_code = copy_buffer_to_clipboard_main(full=True, no_stats=True)

    assert exit_code == 0
    # The strip() in the main script will remove leading/trailing whitespace
    mock_set_clipboard.assert_called_once_with(buffer_content.strip())

def test_no_clear_sequence_found(mock_dependencies, capsys):
    mock_system_utils, mock_tmux_manager, mock_set_clipboard = mock_dependencies
    mock_system_utils.is_tmux.return_value = True
    
    buffer_content = "some stuff\nwithout a clear"
    mock_tmux_manager.capture_pane.return_value = buffer_content

    exit_code = copy_buffer_to_clipboard_main(full=False, no_stats=True)

    assert exit_code == 0
    mock_set_clipboard.assert_called_once_with(buffer_content)
    captured = capsys.readouterr()
    assert "WARNING" in captured.err
    assert "Could not find a standard 'clear' sequence" in captured.err

def test_empty_buffer_after_processing(mock_dependencies):
    mock_system_utils, mock_tmux_manager, mock_set_clipboard = mock_dependencies
    mock_system_utils.is_tmux.return_value = True
    
    clear_sequence = "\x1b[H\x1b[2J"
    buffer_content = f"some old stuff\n{clear_sequence}   \n   " # only whitespace after clear
    mock_tmux_manager.capture_pane.return_value = buffer_content

    exit_code = copy_buffer_to_clipboard_main(full=False, no_stats=True)

    assert exit_code == 0
    mock_set_clipboard.assert_not_called()

def test_set_clipboard_fails(mock_dependencies, capsys):
    mock_system_utils, mock_tmux_manager, mock_set_clipboard = mock_dependencies
    mock_system_utils.is_tmux.return_value = True
    mock_tmux_manager.capture_pane.return_value = "some content"
    mock_set_clipboard.side_effect = Exception("Clipboard is broken")

    exit_code = copy_buffer_to_clipboard_main(full=False, no_stats=True)

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "ERROR" in captured.err
    assert "Failed to set clipboard" in captured.err
