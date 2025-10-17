
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock

import pytest

from syncmux.models import Session
from syncmux.tmux_controller import TmuxController


@pytest.fixture
def tmux_controller():
    return TmuxController()


@pytest.mark.asyncio
async def test_list_sessions_success(tmux_controller):
    mock_conn = AsyncMock()
    now = datetime.now()
    timestamp = int(now.timestamp())
    mock_conn.run.return_value = MagicMock(
        stdout=f"$1|test1|1|0|{timestamp}\n$2|test2|2|1|{timestamp}", exit_status=0
    )

    sessions = await tmux_controller.list_sessions(mock_conn)

    assert len(sessions) == 2
    assert isinstance(sessions[0], Session)
    assert sessions[0].name == "test1"
    assert sessions[1].windows == 2
    assert sessions[1].attached == 1


@pytest.mark.asyncio
async def test_list_sessions_no_sessions(tmux_controller):
    mock_conn = AsyncMock()
    mock_conn.run.return_value = MagicMock(stdout="", exit_status=0)

    sessions = await tmux_controller.list_sessions(mock_conn)

    assert len(sessions) == 0


@pytest.mark.asyncio
async def test_list_sessions_error(tmux_controller):
    mock_conn = AsyncMock()
    mock_conn.run.return_value = MagicMock(exit_status=1)

    sessions = await tmux_controller.list_sessions(mock_conn)

    assert len(sessions) == 0


@pytest.mark.asyncio
async def test_create_session(tmux_controller):
    mock_conn = AsyncMock()
    mock_conn.run.return_value = MagicMock(exit_status=0)

    result = await tmux_controller.create_session(mock_conn, "test-session")

    assert result is True
    mock_conn.run.assert_called_with("tmux new-session -d -s test-session")


@pytest.mark.asyncio
async def test_kill_session(tmux_controller):
    mock_conn = AsyncMock()
    mock_conn.run.return_value = MagicMock(exit_status=0)

    result = await tmux_controller.kill_session(mock_conn, "test-session")

    assert result is True
    mock_conn.run.assert_called_with("tmux kill-session -t test-session")


@pytest.mark.asyncio
async def test_session_exists(tmux_controller):
    mock_conn = AsyncMock()
    mock_conn.run.return_value = MagicMock(exit_status=0)

    result = await tmux_controller.session_exists(mock_conn, "test-session")

    assert result is True
    mock_conn.run.assert_called_with("tmux has-session -t test-session")

