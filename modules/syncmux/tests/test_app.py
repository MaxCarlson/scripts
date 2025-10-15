
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from textual.widgets import ListView, RichLog

from syncmux.app import SyncMuxApp
from syncmux.models import Host, Session


@pytest.fixture
def app():
    return SyncMuxApp()


@pytest.mark.asyncio
async def test_create_session(app):
    """Test creating a new session."""
    # Setup mocks
    app.conn_manager = AsyncMock()
    app.tmux_controller = AsyncMock()
    app.tmux_controller.create_session.return_value = True
    app.hosts = [Host(alias="test", hostname="localhost", user="test", auth_method="agent")]
    app.selected_host_alias = "test"

    # Mock query_one to return a mock RichLog
    log_mock = MagicMock(spec=RichLog)
    app.query_one = MagicMock(return_value=log_mock)

    # Mock push_screen
    app.push_screen = MagicMock()

    # Execute the action
    await app.action_create_session()

    # Verify push_screen was called
    assert app.push_screen.called

    # Get the callback from the push_screen call
    callback = app.push_screen.call_args[0][1]

    # Mock call_later to execute the coroutine immediately
    called_coro = None

    def mock_call_later(coro):
        nonlocal called_coro
        called_coro = coro

    app.call_later = mock_call_later

    # Call the callback with a session name (callback is async)
    await callback("new-session")

    # Execute the scheduled coroutine
    if called_coro:
        await called_coro()

    # Verify the tmux controller was called
    app.tmux_controller.create_session.assert_called_once()


@pytest.mark.asyncio
async def test_kill_session(app):
    """Test killing a session."""
    # Setup mocks
    app.conn_manager = AsyncMock()
    app.tmux_controller = AsyncMock()
    app.tmux_controller.kill_session.return_value = True
    app.hosts = [Host(alias="test", hostname="localhost", user="test", auth_method="agent")]
    app.selected_host_alias = "test"

    session = Session(
        id="1",
        name="test-session",
        windows=1,
        attached=0,
        created_at=datetime.now()
    )
    session_widget = MagicMock()
    session_widget.session = session

    # Mock query_one
    log_mock = MagicMock(spec=RichLog)

    def query_one_side_effect(selector, *args):
        if selector == "#log-view":
            return log_mock
        elif selector == "#session-list":
            session_list_mock = MagicMock(spec=ListView)
            session_list_mock.highlighted = session_widget
            return session_list_mock
        return MagicMock()

    app.query_one = MagicMock(side_effect=query_one_side_effect)

    # Mock push_screen
    app.push_screen = MagicMock()

    # Execute the action
    await app.action_kill_session()

    # Verify push_screen was called
    assert app.push_screen.called

    # Get the callback from the push_screen call
    callback = app.push_screen.call_args[0][1]

    # Mock call_later to execute the coroutine immediately
    called_coro = None

    def mock_call_later(coro):
        nonlocal called_coro
        called_coro = coro

    app.call_later = mock_call_later

    # Call the callback with confirmation
    callback(True)

    # Execute the scheduled coroutine
    if called_coro:
        await called_coro()

    # Verify the tmux controller was called
    app.tmux_controller.kill_session.assert_called_once()
