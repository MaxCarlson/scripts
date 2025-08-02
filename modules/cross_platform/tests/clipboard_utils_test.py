import platform
import subprocess
import pytest
from unittest.mock import MagicMock, patch

from cross_platform.clipboard_utils import ClipboardUtils # Assuming this is the path

# Common mock for ClipboardUtils.run_command
def fake_run_command_clipboard_mock(self, command, sudo=False):
    if "termux-clipboard-get" in command: return "termux clipboard data"
    if "win32yank -o" in command: return "wsl2 clipboard data via win32yank"
    if "xclip -selection clipboard -o" in command: return "linux clipboard data via xclip"
    if "pbpaste" in command: return "macos clipboard data via pbpaste"
    if 'powershell -command "Get-Clipboard"' in command: return "windows clipboard data via powershell"
    # For set commands, run_command isn't usually called by clipboard_utils's set_clipboard; subprocess.run is.
    return f"unhandled_run_command_{command}"

@pytest.fixture
def cp_utils(monkeypatch):
    # Default platform for __init__, tests will override if necessary for os_name specific logic
    monkeypatch.setattr(platform, "system", lambda: "Linux") 
    # Mock run_command on the class, so all instances use it
    monkeypatch.setattr(ClipboardUtils, "run_command", fake_run_command_clipboard_mock)
    return ClipboardUtils()


def test_get_clipboard_linux(cp_utils, monkeypatch):
    # cp_utils already initialized with Linux platform due to fixture setup
    monkeypatch.setattr(cp_utils, "is_termux", lambda: False)
    monkeypatch.setattr(cp_utils, "is_wsl2", lambda: False)
    assert cp_utils.get_clipboard() == "linux clipboard data via xclip"

def test_get_clipboard_windows(cp_utils, monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows") # Affects next init or direct os_name set
    # Re-init or set os_name on the fixture instance
    cp_utils.os_name = "windows" # More direct for an existing instance
    monkeypatch.setattr(cp_utils, "is_termux", lambda: False)
    monkeypatch.setattr(cp_utils, "is_wsl2", lambda: False)
    assert cp_utils.get_clipboard() == "windows clipboard data via powershell"

def test_get_clipboard_macos(cp_utils, monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    cp_utils.os_name = "darwin"
    monkeypatch.setattr(cp_utils, "is_termux", lambda: False)
    monkeypatch.setattr(cp_utils, "is_wsl2", lambda: False) # WSL2 not relevant for macOS
    assert cp_utils.get_clipboard() == "macos clipboard data via pbpaste"

def test_get_clipboard_termux(cp_utils, monkeypatch):
    # is_termux will be True, platform can be Linux
    monkeypatch.setattr(cp_utils, "is_termux", lambda: True)
    # is_wsl2 check comes after is_termux, so doesn't matter here
    assert cp_utils.get_clipboard() == "termux clipboard data"
    
def test_get_clipboard_wsl2(cp_utils, monkeypatch):
    monkeypatch.setattr(cp_utils, "is_termux", lambda: False)
    monkeypatch.setattr(cp_utils, "is_wsl2", lambda: True)
    assert cp_utils.get_clipboard() == "wsl2 clipboard data via win32yank"


# Mocking subprocess.run for set_clipboard methods
@patch("cross_platform.clipboard_utils.subprocess.run")
@patch("cross_platform.clipboard_utils.print") # Mock print for OSC52
def test_set_clipboard_windows(mock_print_osc52, mock_sub_run, cp_utils, monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    cp_utils.os_name = "windows"
    monkeypatch.setattr(cp_utils, "is_termux", lambda: False)
    monkeypatch.setattr(cp_utils, "is_wsl2", lambda: False)
    
    test_text = "hello windows"
    cp_utils.set_clipboard(test_text)

    mock_print_osc52.assert_called_once() # Check OSC52 was attempted
    expected_args = ["powershell", "-command", f'Set-Clipboard -Value "{test_text}"']
    mock_sub_run.assert_called_once_with(expected_args, text=True, check=True)

@patch("cross_platform.clipboard_utils.subprocess.run")
@patch("cross_platform.clipboard_utils.print")
def test_set_clipboard_linux(mock_print_osc52, mock_sub_run, cp_utils, monkeypatch):
    # cp_utils already Linux by fixture default
    monkeypatch.setattr(cp_utils, "is_termux", lambda: False)
    monkeypatch.setattr(cp_utils, "is_wsl2", lambda: False)

    test_text = "hello linux"
    cp_utils.set_clipboard(test_text)

    mock_print_osc52.assert_called_once()
    expected_args = ["xclip", "-selection", "clipboard"]
    mock_sub_run.assert_called_once_with(expected_args, input=test_text, text=True, check=True)

@patch("cross_platform.clipboard_utils.subprocess.run")
@patch("cross_platform.clipboard_utils.print")
def test_set_clipboard_macos(mock_print_osc52, mock_sub_run, cp_utils, monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    cp_utils.os_name = "darwin"
    monkeypatch.setattr(cp_utils, "is_termux", lambda: False)
    # is_wsl2 not relevant

    test_text = "hello macos"
    cp_utils.set_clipboard(test_text)

    mock_print_osc52.assert_called_once()
    expected_args = ["pbcopy"]
    mock_sub_run.assert_called_once_with(expected_args, input=test_text, text=True, check=True)


@patch("cross_platform.clipboard_utils.subprocess.run")
@patch("cross_platform.clipboard_utils.print")
def test_set_clipboard_termux(mock_print_osc52, mock_sub_run, cp_utils, monkeypatch):
    monkeypatch.setattr(cp_utils, "is_termux", lambda: True)
    # is_wsl2 not relevant if Termux is true

    test_text = "hello termux"
    cp_utils.set_clipboard(test_text)

    mock_print_osc52.assert_called_once()
    expected_args = ["termux-clipboard-set"]
    mock_sub_run.assert_called_once_with(expected_args, input=test_text, text=True, check=True)

@patch("cross_platform.clipboard_utils.subprocess.run")
@patch("cross_platform.clipboard_utils.print")
def test_set_clipboard_wsl2(mock_print_osc52, mock_sub_run, cp_utils, monkeypatch):
    monkeypatch.setattr(cp_utils, "is_termux", lambda: False)
    monkeypatch.setattr(cp_utils, "is_wsl2", lambda: True)

    test_text = "hello wsl2"
    cp_utils.set_clipboard(test_text)

    mock_print_osc52.assert_called_once()
    expected_args = ["win32yank", "-i"]
    mock_sub_run.assert_called_once_with(expected_args, input=test_text, text=True, check=True)
