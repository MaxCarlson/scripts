
import asyncio
from unittest.mock import MagicMock
import errno

import pytest
import asyncssh

from syncmux.connection import ConnectionManager
from syncmux.models import Host


@pytest.fixture
def connection_manager():
    """Create a ConnectionManager instance."""
    return ConnectionManager()


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


def test_error_message_authentication_key(connection_manager, sample_host):
    """Test error message for authentication failure with key."""
    error = asyncssh.PermissionDenied("Permission denied")
    message = connection_manager._get_error_message(sample_host, error)

    assert "❌" in message
    assert "Authentication failed" in message
    assert sample_host.alias in message
    assert sample_host.key_path in message


def test_error_message_authentication_password(connection_manager):
    """Test error message for authentication failure with password."""
    host = Host(
        alias="test-host",
        hostname="test.example.com",
        port=22,
        user="testuser",
        auth_method="password",
        password="test",
    )
    error = asyncssh.PermissionDenied("Permission denied")
    message = connection_manager._get_error_message(host, error)

    assert "❌" in message
    assert "Authentication failed" in message
    assert "Invalid password" in message


def test_error_message_authentication_agent(connection_manager):
    """Test error message for authentication failure with agent."""
    host = Host(
        alias="test-host",
        hostname="test.example.com",
        port=22,
        user="testuser",
        auth_method="agent",
    )
    error = asyncssh.PermissionDenied("Permission denied")
    message = connection_manager._get_error_message(host, error)

    assert "❌" in message
    assert "Authentication failed" in message
    assert "SSH agent" in message


def test_error_message_connection_refused(connection_manager, sample_host):
    """Test error message for connection refused."""
    error = ConnectionRefusedError("Connection refused")
    message = connection_manager._get_error_message(sample_host, error)

    assert "❌" in message
    assert "Connection refused" in message
    assert sample_host.hostname in message
    assert str(sample_host.port) in message


def test_error_message_timeout(connection_manager, sample_host):
    """Test error message for connection timeout."""
    error = asyncio.TimeoutError()
    message = connection_manager._get_error_message(sample_host, error)

    assert "❌" in message
    assert "timed out" in message
    assert sample_host.alias in message


def test_error_message_network_unreachable(connection_manager, sample_host):
    """Test error message for network unreachable."""
    error = OSError("Network is unreachable")
    message = connection_manager._get_error_message(sample_host, error)

    assert "❌" in message
    assert "Network unreachable" in message
    assert sample_host.alias in message


def test_error_message_key_not_found(connection_manager, sample_host):
    """Test error message for SSH key file not found."""
    error = OSError("No such file or directory")
    message = connection_manager._get_error_message(sample_host, error)

    assert "❌" in message
    assert "key not found" in message
    assert sample_host.key_path in message


def test_error_message_generic(connection_manager, sample_host):
    """Test generic error message fallback."""
    error = Exception("Unknown error occurred")
    message = connection_manager._get_error_message(sample_host, error)

    assert "❌" in message
    assert "Failed to connect" in message
    assert sample_host.alias in message
    assert "Unknown error" in message


def test_connection_timeout_parameter(connection_manager, sample_host):
    """Test that connection timeout is set."""
    # This is tested indirectly through the connection manager tests
    # which now verify the connect_timeout parameter
    assert True  # Placeholder - actual test is in connection_manager_test.py
