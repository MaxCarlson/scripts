# tests/integration_test.py
import pytest
from agt.client import WebAIClient, DEFAULT_URL

@pytest.fixture(scope="module")
def live_client():
    """Fixture to get a client to a live server, skipping tests if unavailable."""
    client = WebAIClient(DEFAULT_URL)
    try:
        ok, detail = client.health_detail()
        if not ok:
            pytest.skip(f"Server at {DEFAULT_URL} is not responsive: {detail}")
    except Exception as e:
        pytest.skip(f"Failed to connect to server at {DEFAULT_URL}: {e}")
    return client

def test_integration_health(live_client: WebAIClient):
    """Tests the health check against a live server."""
    ok, detail = live_client.health_detail()
    assert ok is True

def test_integration_chat_once(live_client: WebAIClient):
    """Tests a simple non-streaming chat against a live server."""
    messages = [{"role": "user", "content": "What is 2+2?"}]
    resp = live_client.chat_once(messages, model="gemini-2.0-flash")
    assert "choices" in resp
    assert len(resp["choices"]) > 0
    content = resp["choices"][0].get("message", {}).get("content", "")
    assert "4" in content

def test_integration_chat_stream(live_client: WebAIClient):
    """Tests a simple streaming chat against a live server."""
    messages = [{"role": "user", "content": "What is the capital of France?"}]
    events = list(live_client.chat_stream_events(messages, model="gemini-2.0-flash"))
    
    assert len(events) > 1
    assert any(e["event"] == "content" for e in events)
    assert any(e["event"] == "done" for e in events)

    content_events = [e["text"] for e in events if e["event"] == "content"]
    full_content = "".join(content_events)
    assert "Paris" in full_content
