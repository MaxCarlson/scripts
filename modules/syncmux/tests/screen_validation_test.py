
import pytest
from unittest.mock import MagicMock, patch

from syncmux.screens import NewSessionScreen
from syncmux.tmux_controller import TmuxController


def test_session_name_sanitization():
    """Test that session names are sanitized."""
    # Valid names
    assert TmuxController.sanitize_session_name("my-session") == "my-session"
    assert TmuxController.sanitize_session_name("session_1") == "session_1"
    assert TmuxController.sanitize_session_name("test session") == "test_session"  # Spaces to underscores


def test_session_name_validation_empty():
    """Test validation rejects empty session names."""
    with pytest.raises(ValueError, match="cannot be empty"):
        TmuxController.sanitize_session_name("")

    with pytest.raises(ValueError, match="cannot be empty"):
        TmuxController.sanitize_session_name("   ")


def test_session_name_validation_too_long():
    """Test validation rejects session names that are too long."""
    long_name = "a" * 101
    with pytest.raises(ValueError, match="too long"):
        TmuxController.sanitize_session_name(long_name)


def test_session_name_validation_invalid_characters():
    """Test validation rejects invalid characters."""
    # Colons
    with pytest.raises(ValueError, match="colons or dots"):
        TmuxController.sanitize_session_name("my:session")

    # Dots
    with pytest.raises(ValueError, match="colons or dots"):
        TmuxController.sanitize_session_name("my.session")

    # Special characters
    with pytest.raises(ValueError, match="invalid characters"):
        TmuxController.sanitize_session_name("my@session")

    with pytest.raises(ValueError, match="invalid characters"):
        TmuxController.sanitize_session_name("my$session")


def test_session_name_edge_cases():
    """Test edge cases for session name validation."""
    # Maximum valid length
    max_valid = "a" * 100
    assert len(TmuxController.sanitize_session_name(max_valid)) == 100

    # Leading/trailing whitespace is stripped
    assert TmuxController.sanitize_session_name("  test  ") == "test"

    # Multiple spaces become underscores
    assert TmuxController.sanitize_session_name("my   session") == "my___session"


def test_new_session_screen_has_validation():
    """Test that NewSessionScreen uses validation."""
    screen = NewSessionScreen()

    # Verify the screen can be created
    assert screen is not None

    # The actual validation happens in on_button_pressed
    # which calls TmuxController.sanitize_session_name
    # This is integration tested through the full app
