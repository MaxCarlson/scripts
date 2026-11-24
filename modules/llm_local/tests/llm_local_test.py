# tests/llm_local_test.py
from __future__ import annotations

import json
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch

import pytest

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


def test_complete_returns_none_on_connection_refused() -> None:
    with patch("llm_local.client.urllib.request.urlopen",
               side_effect=urllib.error.URLError("Connection refused")):
        result = complete("prompt")
    assert result is None


def test_complete_returns_none_on_timeout() -> None:
    with patch("llm_local.client.urllib.request.urlopen",
               side_effect=TimeoutError("timed out")):
        result = complete("prompt")
    assert result is None


def test_complete_returns_none_on_malformed_json() -> None:
    mock = MagicMock()
    mock.read.return_value = b"not json {"
    mock.__enter__ = lambda s: s
    mock.__exit__ = MagicMock(return_value=False)

    with patch("llm_local.client.urllib.request.urlopen", return_value=mock):
        result = complete("prompt")
    assert result is None


def test_complete_returns_none_on_missing_choices_key() -> None:
    mock = MagicMock()
    mock.read.return_value = json.dumps({"error": "model not loaded"}).encode()
    mock.__enter__ = lambda s: s
    mock.__exit__ = MagicMock(return_value=False)

    with patch("llm_local.client.urllib.request.urlopen", return_value=mock):
        result = complete("prompt")
    assert result is None


def test_complete_uses_custom_url() -> None:
    captured_urls: list[str] = []

    def fake_urlopen(req: urllib.request.Request, timeout: float | None = None) -> MagicMock:
        captured_urls.append(req.full_url)
        return _mock_response("ok")

    with patch("llm_local.client.urllib.request.urlopen", side_effect=fake_urlopen):
        complete("prompt", url="http://myserver:5678/v1")

    assert "myserver:5678" in captured_urls[0]


def test_complete_uses_env_var_url(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_urls: list[str] = []

    def fake_urlopen(req: urllib.request.Request, timeout: float | None = None) -> MagicMock:
        captured_urls.append(req.full_url)
        return _mock_response("ok")

    monkeypatch.setenv("LM_STUDIO_URL", "http://envserver:9999/v1")
    with patch("llm_local.client.urllib.request.urlopen", side_effect=fake_urlopen):
        complete("prompt")

    assert "envserver:9999" in captured_urls[0]
