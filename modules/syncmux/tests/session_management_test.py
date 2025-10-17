
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from syncmux.models import Session
from syncmux.screens import RenameSessionScreen, SessionInfoScreen
from syncmux.tmux_controller import TmuxController


@pytest.fixture
def tmux_controller():
    """Create a TmuxController instance."""
    return TmuxController()


@pytest.fixture
def sample_session():
    """Create a sample session for testing."""
    return Session(
        id="$0",
        name="test-session",
        windows=3,
        attached=1,
        created_at=datetime(2024, 1, 1, 12, 0, 0),
    )


@pytest.mark.asyncio
async def test_rename_session_success(tmux_controller):
    """Test successful session rename."""
    mock_conn = MagicMock()
    mock_result = MagicMock()
    mock_result.exit_status = 0
    mock_conn.run = AsyncMock(return_value=mock_result)

    success = await tmux_controller.rename_session(mock_conn, "old-name", "new-name")

    assert success is True
    mock_conn.run.assert_called_once_with("tmux rename-session -t old-name new-name")


@pytest.mark.asyncio
async def test_rename_session_with_sanitization(tmux_controller):
    """Test that rename sanitizes the new session name."""
    mock_conn = MagicMock()
    mock_result = MagicMock()
    mock_result.exit_status = 0
    mock_conn.run = AsyncMock(return_value=mock_result)

    # Name with spaces should be converted to underscores
    success = await tmux_controller.rename_session(mock_conn, "old", "new session")

    assert success is True
    mock_conn.run.assert_called_once_with("tmux rename-session -t old new_session")


@pytest.mark.asyncio
async def test_rename_session_failure(tmux_controller):
    """Test failed session rename."""
    mock_conn = MagicMock()
    mock_result = MagicMock()
    mock_result.exit_status = 1
    mock_conn.run = AsyncMock(return_value=mock_result)

    success = await tmux_controller.rename_session(mock_conn, "old", "new")

    assert success is False


@pytest.mark.asyncio
async def test_rename_session_empty_name(tmux_controller):
    """Test rename with empty session name."""
    mock_conn = MagicMock()

    with pytest.raises(ValueError, match="Session name cannot be empty"):
        await tmux_controller.rename_session(mock_conn, "old", "")


@pytest.mark.asyncio
async def test_rename_session_invalid_characters(tmux_controller):
    """Test rename with invalid characters in session name."""
    mock_conn = MagicMock()

    with pytest.raises(ValueError, match="colons or dots"):
        await tmux_controller.rename_session(mock_conn, "old", "bad:name")


@pytest.mark.asyncio
async def test_list_windows_success(tmux_controller):
    """Test successful window listing."""
    mock_conn = MagicMock()
    mock_result = MagicMock()
    mock_result.exit_status = 0
    mock_result.stdout = "vim\nshell\nlogs\n"
    mock_conn.run = AsyncMock(return_value=mock_result)

    windows = await tmux_controller.list_windows(mock_conn, "test-session")

    assert windows == ["vim", "shell", "logs"]
    mock_conn.run.assert_called_once_with('tmux list-windows -t test-session -F "#{window_name}"')


@pytest.mark.asyncio
async def test_list_windows_empty(tmux_controller):
    """Test listing windows for session with no windows."""
    mock_conn = MagicMock()
    mock_result = MagicMock()
    mock_result.exit_status = 0
    mock_result.stdout = ""
    mock_conn.run = AsyncMock(return_value=mock_result)

    windows = await tmux_controller.list_windows(mock_conn, "test-session")

    assert windows == []


@pytest.mark.asyncio
async def test_list_windows_error(tmux_controller):
    """Test listing windows when command fails."""
    mock_conn = MagicMock()
    mock_result = MagicMock()
    mock_result.exit_status = 1
    mock_conn.run = AsyncMock(return_value=mock_result)

    windows = await tmux_controller.list_windows(mock_conn, "test-session")

    assert windows == []


@pytest.mark.asyncio
async def test_list_windows_with_whitespace(tmux_controller):
    """Test that window names are properly stripped."""
    mock_conn = MagicMock()
    mock_result = MagicMock()
    mock_result.exit_status = 0
    mock_result.stdout = "  vim  \n  shell  \n  logs  \n"
    mock_conn.run = AsyncMock(return_value=mock_result)

    windows = await tmux_controller.list_windows(mock_conn, "test-session")

    assert windows == ["vim", "shell", "logs"]


def test_rename_session_screen_creation():
    """Test that RenameSessionScreen can be created."""
    screen = RenameSessionScreen("test-session")
    assert screen is not None
    assert screen.current_name == "test-session"


def test_session_info_screen_creation(sample_session):
    """Test that SessionInfoScreen can be created."""
    windows = ["vim", "shell", "logs"]
    screen = SessionInfoScreen(sample_session, windows)
    assert screen is not None
    assert screen.session == sample_session
    assert screen.windows == windows


def test_session_info_screen_has_escape_binding(sample_session):
    """Test that SessionInfoScreen has escape key binding."""
    screen = SessionInfoScreen(sample_session, [])
    assert any("escape" in str(binding) for binding in screen.BINDINGS)


def test_session_info_screen_empty_windows(sample_session):
    """Test SessionInfoScreen with no windows."""
    screen = SessionInfoScreen(sample_session, [])
    assert screen.windows == []


def test_session_info_screen_many_windows(sample_session):
    """Test SessionInfoScreen with many windows."""
    windows = [f"window-{i}" for i in range(10)]
    screen = SessionInfoScreen(sample_session, windows)
    assert len(screen.windows) == 10
