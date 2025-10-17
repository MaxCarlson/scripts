
import pytest
from unittest.mock import AsyncMock, MagicMock

from syncmux.tmux_controller import TmuxController


@pytest.fixture
def tmux_controller():
    """Create a TmuxController instance."""
    return TmuxController()


@pytest.mark.asyncio
async def test_check_tmux_available_success(tmux_controller):
    """Test successful tmux availability check."""
    mock_conn = MagicMock()
    mock_result = MagicMock()
    mock_result.exit_status = 0
    mock_result.stdout = "tmux 3.3a\n"
    mock_conn.run = AsyncMock(return_value=mock_result)

    is_available, message = await tmux_controller.check_tmux_available(mock_conn)

    assert is_available is True
    assert "tmux is available" in message
    assert "3.3a" in message
    mock_conn.run.assert_called_once_with("tmux -V", check=False)


@pytest.mark.asyncio
async def test_check_tmux_available_not_installed(tmux_controller):
    """Test tmux not installed."""
    mock_conn = MagicMock()
    mock_conn.run = AsyncMock(side_effect=Exception("Command not found"))

    is_available, message = await tmux_controller.check_tmux_available(mock_conn)

    assert is_available is False
    assert "Error checking tmux availability" in message


@pytest.mark.asyncio
async def test_check_tmux_available_error_exit_code(tmux_controller):
    """Test tmux command returns error exit code."""
    mock_conn = MagicMock()
    mock_result = MagicMock()
    mock_result.exit_status = 1
    mock_result.stdout = ""
    mock_conn.run = AsyncMock(return_value=mock_result)

    is_available, message = await tmux_controller.check_tmux_available(mock_conn)

    assert is_available is False
    assert "returned an error" in message


@pytest.mark.asyncio
async def test_check_tmux_available_different_versions(tmux_controller):
    """Test detection of different tmux versions."""
    mock_conn = MagicMock()

    # Test version 2.x
    mock_result = MagicMock()
    mock_result.exit_status = 0
    mock_result.stdout = "tmux 2.8"
    mock_conn.run = AsyncMock(return_value=mock_result)

    is_available, message = await tmux_controller.check_tmux_available(mock_conn)
    assert is_available is True
    assert "2.8" in message

    # Test version 3.x
    mock_result.stdout = "tmux 3.4"
    is_available, message = await tmux_controller.check_tmux_available(mock_conn)
    assert is_available is True
    assert "3.4" in message
