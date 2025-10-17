
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from syncmux.connection import ConnectionManager
from syncmux.models import Host


@pytest.fixture
def sample_host():
    """Create a sample host for testing."""
    return Host(
        alias="test-host",
        hostname="test.example.com",
        port=22,
        user="testuser",
        auth_method="key",
        key_path="~/.ssh/id_rsa",
    )


@pytest.fixture
def connection_manager():
    """Create a ConnectionManager instance."""
    return ConnectionManager()


@pytest.mark.asyncio
async def test_get_connection_key_auth(connection_manager, sample_host):
    """Test getting a connection with key authentication."""
    mock_connection = MagicMock()
    mock_connection.is_closed.return_value = False

    with patch("syncmux.connection.asyncssh.connect", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = mock_connection

        conn = await connection_manager.get_connection(sample_host)

        assert conn == mock_connection
        mock_connect.assert_called_once_with(
            sample_host.hostname,
            port=sample_host.port,
            username=sample_host.user,
            password=None,
            client_keys=[sample_host.key_path],
            agent_forwarding=False,
        )


@pytest.mark.asyncio
async def test_get_connection_password_auth(connection_manager):
    """Test getting a connection with password authentication."""
    host = Host(
        alias="test-host",
        hostname="test.example.com",
        port=22,
        user="testuser",
        auth_method="password",
        password="testpass",
    )

    mock_connection = MagicMock()
    mock_connection.is_closed.return_value = False

    with patch("syncmux.connection.asyncssh.connect", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = mock_connection

        conn = await connection_manager.get_connection(host)

        assert conn == mock_connection
        mock_connect.assert_called_once_with(
            host.hostname,
            port=host.port,
            username=host.user,
            password="testpass",
            client_keys=None,
            agent_forwarding=False,
        )


@pytest.mark.asyncio
async def test_get_connection_agent_auth(connection_manager):
    """Test getting a connection with agent authentication."""
    host = Host(
        alias="test-host",
        hostname="test.example.com",
        port=22,
        user="testuser",
        auth_method="agent",
    )

    mock_connection = MagicMock()
    mock_connection.is_closed.return_value = False

    with patch("syncmux.connection.asyncssh.connect", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = mock_connection

        conn = await connection_manager.get_connection(host)

        assert conn == mock_connection
        mock_connect.assert_called_once_with(
            host.hostname,
            port=host.port,
            username=host.user,
            password=None,
            client_keys=None,
            agent_forwarding=True,
        )


@pytest.mark.asyncio
async def test_get_connection_cached(connection_manager, sample_host):
    """Test that connections are cached."""
    mock_connection = MagicMock()
    mock_connection.is_closed.return_value = False

    with patch("syncmux.connection.asyncssh.connect", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = mock_connection

        # First call should create a connection
        conn1 = await connection_manager.get_connection(sample_host)
        assert conn1 == mock_connection
        assert mock_connect.call_count == 1

        # Second call should return cached connection
        conn2 = await connection_manager.get_connection(sample_host)
        assert conn2 == mock_connection
        assert conn2 is conn1
        # Connect should still only be called once
        assert mock_connect.call_count == 1


@pytest.mark.asyncio
async def test_get_connection_reconnect_if_closed(connection_manager, sample_host):
    """Test that a new connection is created if cached one is closed."""
    mock_connection1 = MagicMock()
    mock_connection1.is_closed.return_value = True

    mock_connection2 = MagicMock()
    mock_connection2.is_closed.return_value = False

    with patch("syncmux.connection.asyncssh.connect", new_callable=AsyncMock) as mock_connect:
        mock_connect.side_effect = [mock_connection1, mock_connection2]

        # First call creates a connection
        conn1 = await connection_manager.get_connection(sample_host)
        assert conn1 == mock_connection1

        # Second call should detect closed connection and create new one
        conn2 = await connection_manager.get_connection(sample_host)
        assert conn2 == mock_connection2
        assert mock_connect.call_count == 2


@pytest.mark.asyncio
async def test_get_connection_error(connection_manager, sample_host):
    """Test that connection errors are properly raised."""
    with patch("syncmux.connection.asyncssh.connect", new_callable=AsyncMock) as mock_connect:
        mock_connect.side_effect = OSError("Connection failed")

        with pytest.raises(ConnectionError, match="Failed to connect to test-host"):
            await connection_manager.get_connection(sample_host)


@pytest.mark.asyncio
async def test_close_all(connection_manager, sample_host):
    """Test closing all cached connections."""
    mock_connection = MagicMock()
    mock_connection.is_closed.return_value = False

    with patch("syncmux.connection.asyncssh.connect", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = mock_connection

        # Create a connection
        await connection_manager.get_connection(sample_host)

        # Close all connections
        await connection_manager.close_all()

        # Verify close was called
        mock_connection.close.assert_called_once()

        # Verify cache was cleared
        assert len(connection_manager._connections) == 0
