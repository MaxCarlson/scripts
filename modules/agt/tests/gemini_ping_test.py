from __future__ import annotations

from agt.client import WebAIClient

def test_gemini_ping_posts_expected_payload(monkeypatch):
    client = WebAIClient("http://x")

    captured = {}
    class R:
        def raise_for_status(self): return None
        def json(self): return {"response": "pong"}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return R()

    monkeypatch.setattr("requests.post", fake_post)

    out = client.gemini_ping("ping", model="gemini-2.0-flash")
    assert out["response"] == "pong"
    assert captured["url"].endswith("/gemini")
    assert captured["json"]["message"] == "ping"
    assert captured["json"]["model"] == "gemini-2.0-flash"
