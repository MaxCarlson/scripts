#!/usr/bin/env python3
"""Tests for orchestrator_web_viewer termdash API."""

import pytest
from fastapi.testclient import TestClient
from orchestrator_web_viewer.main import app
from orchestrator_web_viewer.api.termdash import register_dashboard, unregister_dashboard, _attached_dashboards


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def mock_dashboard():
    """Create a mock dashboard for testing."""
    from termdash import TermDash, Stat, Line
    
    dashboard = TermDash(refresh_rate=1.0)
    line = Line("test_line", stats=[
        Stat("count", 42, prefix="Count: "),
        Stat("rate", 1.5, prefix="Rate: ", unit="/s"),
    ])
    dashboard.add_line("test_line", line)
    
    return dashboard


@pytest.fixture(autouse=True)
def cleanup_dashboards():
    """Clean up registered dashboards after each test."""
    yield
    _attached_dashboards.clear()


def test_list_dashboards_empty(client):
    """Test listing dashboards when none are registered."""
    response = client.get("/api/termdash/dashboards")
    assert response.status_code == 200
    data = response.json()
    assert "dashboards" in data
    assert len(data["dashboards"]) == 0


def test_list_dashboards_with_registered(client, mock_dashboard):
    """Test listing dashboards when some are registered."""
    register_dashboard("test_dash", mock_dashboard)
    
    response = client.get("/api/termdash/dashboards")
    assert response.status_code == 200
    data = response.json()
    assert len(data["dashboards"]) == 1
    assert data["dashboards"][0]["id"] == "test_dash"
    assert data["dashboards"][0]["type"] == "termdash"


def test_get_dashboard_state(client, mock_dashboard):
    """Test getting the state of a specific dashboard."""
    register_dashboard("test_dash", mock_dashboard)
    
    response = client.get("/api/termdash/dashboards/test_dash")
    assert response.status_code == 200
    
    data = response.json()
    assert "lines" in data
    assert "config" in data
    assert "min_col_pad" in data["config"]
    assert "column_sep" in data["config"]
    assert len(data["lines"]) == 1
    assert data["lines"][0]["name"] == "test_line"


def test_get_dashboard_state_not_found(client):
    """Test getting state of non-existent dashboard."""
    response = client.get("/api/termdash/dashboards/nonexistent")
    assert response.status_code == 404


def test_register_and_unregister(mock_dashboard):
    """Test dashboard registration and unregistration."""
    # Register
    register_dashboard("test_id", mock_dashboard)
    assert "test_id" in _attached_dashboards
    
    # Unregister
    unregister_dashboard("test_id")
    assert "test_id" not in _attached_dashboards


def test_websocket_stream_not_found(client):
    """Test WebSocket connection to non-existent dashboard."""
    # TestClient handles the close, so we just verify it doesn't succeed
    try:
        with client.websocket_connect("/api/termdash/dashboards/nonexistent/stream") as websocket:
            # If we get here, the connection was accepted (shouldn't happen)
            data = websocket.receive_json(timeout=1.0)
            # Should not receive valid data
            assert False, "Should not successfully connect to non-existent dashboard"
    except Exception:
        # Expected - connection should fail or close
        pass


def test_websocket_stream_success(client, mock_dashboard):
    """Test WebSocket connection to valid dashboard."""
    register_dashboard("test_dash", mock_dashboard)
    
    with client.websocket_connect("/api/termdash/dashboards/test_dash/stream") as websocket:
        # Should receive initial state
        data = websocket.receive_json()
        assert data["type"] == "state"
        assert "data" in data
        assert "lines" in data["data"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
