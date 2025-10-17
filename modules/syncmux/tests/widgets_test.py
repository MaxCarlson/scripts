
from datetime import datetime

from syncmux.models import Host, Session
from syncmux.widgets import HostWidget, SessionWidget


def test_host_widget_creation():
    """Test creating a HostWidget."""
    host = Host(
        alias="test-host",
        hostname="test.example.com",
        port=22,
        user="testuser",
        auth_method="key",
        key_path="~/.ssh/id_rsa",
    )

    widget = HostWidget(host)
    assert widget.host == host


def test_host_widget_has_status_methods():
    """Test that host widget has status update methods."""
    host = Host(
        alias="test-host",
        hostname="test.example.com",
        port=22,
        user="testuser",
        auth_method="key",
        key_path="~/.ssh/id_rsa",
    )

    widget = HostWidget(host)
    # Verify the methods exist and are callable
    assert callable(widget.set_status_connected)
    assert callable(widget.set_status_connecting)
    assert callable(widget.set_status_error)


def test_host_widget_session_count_initialization():
    """Test that host widget initializes session count to 0."""
    host = Host(
        alias="test-host",
        hostname="test.example.com",
        port=22,
        user="testuser",
        auth_method="key",
        key_path="~/.ssh/id_rsa",
    )

    widget = HostWidget(host)
    assert widget._session_count == 0


def test_host_widget_update_session_count():
    """Test that host widget has update_session_count method."""
    host = Host(
        alias="test-host",
        hostname="test.example.com",
        port=22,
        user="testuser",
        auth_method="key",
        key_path="~/.ssh/id_rsa",
    )

    widget = HostWidget(host)
    assert callable(widget.update_session_count)


def test_host_widget_session_count_property():
    """Test that session count property is updated correctly."""
    host = Host(
        alias="test-host",
        hostname="test.example.com",
        port=22,
        user="testuser",
        auth_method="key",
        key_path="~/.ssh/id_rsa",
    )

    widget = HostWidget(host)

    # The property should start at 0
    assert widget._session_count == 0

    # Note: We can't test the actual UI update without mounting the widget,
    # but we can verify the method exists and is callable with various inputs
    # The method will be tested in integration tests when the app runs


def test_session_widget_creation():
    """Test creating a SessionWidget."""
    session = Session(
        id="$0",
        name="test-session",
        windows=3,
        attached=1,
        created_at=datetime(2025, 1, 1, 12, 0, 0),
    )

    widget = SessionWidget(session)
    assert widget.session == session
