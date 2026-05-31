# tests/llm_local_test.py
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from llm_local import complete


def _mock_response(content: str) -> MagicMock:
    """Return a mock context-manager response that yields the given content."""
    body = json.dumps({
        "choices": [{"message": {"content": content}}]
    }).encode("utf-8")
    mock = MagicMock()
    mock.read.return_value = body
    mock.__enter__ = lambda s: s
    mock.__exit__ = MagicMock(return_value=False)
    return mock


def test_complete_returns_string_on_success() -> None:
    with patch("llm_local.client.urllib.request.urlopen", return_value=_mock_response("hello")):
        result = complete("say hello")
    assert result == "hello"


def test_complete_sends_user_message() -> None:
    captured: list[str] = []

    def fake_urlopen(req, timeout=None):  # type: ignore[no-untyped-def]
        captured.append(json.loads(req.data.decode())["messages"][-1]["content"])
        return _mock_response("ok")

    with patch("llm_local.client.urllib.request.urlopen", side_effect=fake_urlopen):
        complete("my prompt")

    assert captured == ["my prompt"]


def test_complete_includes_system_message_when_given() -> None:
    captured_messages: list[list[dict]] = []

    def fake_urlopen(req, timeout=None):  # type: ignore[no-untyped-def]
        captured_messages.append(json.loads(req.data.decode())["messages"])
        return _mock_response("ok")

    with patch("llm_local.client.urllib.request.urlopen", side_effect=fake_urlopen):
        complete("user prompt", system="you are helpful")

    messages = captured_messages[0]
    assert messages[0] == {"role": "system", "content": "you are helpful"}
    assert messages[1] == {"role": "user", "content": "user prompt"}


def test_complete_sends_model_when_specified() -> None:
    captured_payload: list[dict] = []

    def fake_urlopen(req, timeout=None):  # type: ignore[no-untyped-def]
        captured_payload.append(json.loads(req.data.decode()))
        return _mock_response("ok")

    with patch("llm_local.client.urllib.request.urlopen", side_effect=fake_urlopen):
        complete("prompt", model="llama-3.1-8b")

    assert captured_payload[0]["model"] == "llama-3.1-8b"
