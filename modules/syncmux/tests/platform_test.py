
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from syncmux.models import Host


@pytest.fixture
def sample_host():
    """Create a sample host for testing."""
    return Host(
        alias="test-host",
        hostname="test.example.com",
        port=2222,
        user="testuser",
        auth_method="key",
        key_path="~/.ssh/id_rsa",
    )


@pytest.fixture
def app_with_ssh_method():
    """Create an app instance with just the _get_ssh_command method."""
    from syncmux.app import SyncMuxApp

    app = SyncMuxApp()
    return app


def test_get_ssh_command_unix(app_with_ssh_method, sample_host):
    """Test SSH command generation on Unix-like systems."""
    with patch("sys.platform", "linux"), \
         patch("os.path.exists", return_value=False):
        cmd = app_with_ssh_method._get_ssh_command(sample_host, "test-session")

        assert cmd[0] == "ssh"
        assert f"{sample_host.user}@{sample_host.hostname}" in cmd
        assert "-p" in cmd
        assert str(sample_host.port) in cmd
        assert "-t" in cmd
        assert "tmux" in cmd
        assert "attach-session" in cmd
        assert "test-session" in cmd


def test_get_ssh_command_termux(app_with_ssh_method, sample_host):
    """Test SSH command generation on Termux."""
    with patch("sys.platform", "linux"), \
         patch("os.path.exists") as mock_exists:
        # Termux-specific path exists
        mock_exists.side_effect = lambda path: path == "/data/data/com.termux"

        cmd = app_with_ssh_method._get_ssh_command(sample_host, "my-session")

        # Should still use 'ssh' from PATH on Termux
        assert cmd[0] == "ssh"
        assert "my-session" in cmd


def test_get_ssh_command_windows_system32(app_with_ssh_method, sample_host):
    """Test SSH command generation on Windows with System32 SSH."""
    with patch("sys.platform", "win32"), \
         patch("os.path.exists") as mock_exists:
        # System32 SSH exists
        mock_exists.side_effect = lambda path: path == r"C:\Windows\System32\OpenSSH\ssh.exe"

        cmd = app_with_ssh_method._get_ssh_command(sample_host, "win-session")

        assert cmd[0] == r"C:\Windows\System32\OpenSSH\ssh.exe"
        assert f"{sample_host.user}@{sample_host.hostname}" in cmd
        assert "-t" in cmd
        assert "win-session" in cmd


def test_get_ssh_command_windows_git(app_with_ssh_method, sample_host):
    """Test SSH command generation on Windows with Git SSH."""
    with patch("sys.platform", "win32"), \
         patch("os.path.exists") as mock_exists:
        # Only Git SSH exists
        def exists_check(path):
            if path == r"C:\Windows\System32\OpenSSH\ssh.exe":
                return False
            elif path == r"C:\Program Files\Git\usr\bin\ssh.exe":
                return True
            return False

        mock_exists.side_effect = exists_check

        cmd = app_with_ssh_method._get_ssh_command(sample_host, "session")

        assert cmd[0] == r"C:\Program Files\Git\usr\bin\ssh.exe"


def test_get_ssh_command_windows_fallback(app_with_ssh_method, sample_host):
    """Test SSH command generation on Windows with no SSH found (fallback to PATH)."""
    with patch("sys.platform", "win32"), \
         patch("os.path.exists", return_value=False):
        cmd = app_with_ssh_method._get_ssh_command(sample_host, "session")

        # Should fallback to 'ssh' in PATH
        assert cmd[0] == "ssh"


def test_ssh_command_port_conversion(app_with_ssh_method, sample_host):
    """Test that port number is properly converted to string."""
    with patch("sys.platform", "linux"), \
         patch("os.path.exists", return_value=False):
        cmd = app_with_ssh_method._get_ssh_command(sample_host, "test")

        # Find the port in the command
        port_idx = cmd.index("-p")
        port_value = cmd[port_idx + 1]

        assert isinstance(port_value, str)
        assert port_value == "2222"
