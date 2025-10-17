
import pytest

from syncmux.screens import ErrorDialog, HelpScreen, NewSessionScreen, ConfirmKillSessionScreen


def test_help_screen_creation():
    """Test that HelpScreen can be created."""
    screen = HelpScreen()
    assert screen is not None


def test_help_screen_has_escape_binding():
    """Test that HelpScreen has escape key binding."""
    screen = HelpScreen()
    # Check that escape binding exists
    assert any("escape" in str(binding) for binding in screen.BINDINGS)


def test_error_dialog_creation():
    """Test that ErrorDialog can be created with title and message."""
    dialog = ErrorDialog("Test Error", "This is a test error message")
    assert dialog is not None
    assert dialog.title == "Test Error"
    assert dialog.message == "This is a test error message"
    assert dialog.details == ""


def test_error_dialog_with_details():
    """Test ErrorDialog with optional details."""
    dialog = ErrorDialog(
        "Connection Error",
        "Failed to connect to host",
        "Details: Network timeout after 10 seconds"
    )
    assert dialog.title == "Connection Error"
    assert dialog.message == "Failed to connect to host"
    assert dialog.details == "Details: Network timeout after 10 seconds"


def test_error_dialog_has_escape_binding():
    """Test that ErrorDialog has escape key binding."""
    dialog = ErrorDialog("Error", "Test")
    assert any("escape" in str(binding) for binding in dialog.BINDINGS)


def test_new_session_screen_has_validation():
    """Test that NewSessionScreen exists and is properly initialized."""
    screen = NewSessionScreen()
    assert screen is not None
    # The screen should use TmuxController.sanitize_session_name for validation
    # This is verified in the screen_validation_test.py file


def test_confirm_kill_session_screen():
    """Test that ConfirmKillSessionScreen is properly initialized."""
    screen = ConfirmKillSessionScreen("test-session")
    assert screen is not None
    assert screen.session_name == "test-session"
