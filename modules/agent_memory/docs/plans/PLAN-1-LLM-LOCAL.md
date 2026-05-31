# llm_local — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`
> (recommended) or `superpowers:executing-plans` to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a minimal, stdlib-only local LLM inference client that calls
LM Studio at `localhost:1234/v1` and returns `None` gracefully when unreachable.

**Architecture:** Single `complete()` function in `llm_local/client.py`, exported
from `llm_local/__init__.py`. Uses `urllib.request` + `json` only. Every error
path returns `None` — callers never need try/except.

**Tech Stack:** Python 3.11+, stdlib only (`urllib.request`, `json`, `logging`,
`os`), `uv run pytest` for tests.

**Prerequisites:** None. This module has no dependencies.

**Working directory:** `/home/mcarls/scripts/modules/llm_local/`

---

## File Map

| File | Responsibility |
|---|---|
| `llm_local/__init__.py` | Re-export `complete` |
| `llm_local/client.py` | `complete()` implementation |
| `tests/llm_local_test.py` | All tests |
| `pyproject.toml` | Already created — no changes needed |

---

## Task 1: `complete()` — happy path

**Files:**
- Create: `llm_local/client.py`
- Modify: `llm_local/__init__.py`
- Create: `tests/llm_local_test.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/mcarls/scripts/modules/llm_local
uv run pytest tests/llm_local_test.py -v --tb=short
```

Expected: `ImportError: cannot import name 'complete' from 'llm_local'`

- [ ] **Step 3: Write `llm_local/client.py`**

```python
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_URL = "http://localhost:1234/v1"


def complete(
    prompt: str,
    *,
    model: Optional[str] = None,
    url: Optional[str] = None,
    timeout: float = 5.0,
    system: Optional[str] = None,
) -> Optional[str]:
    """Call local LM Studio inference endpoint.

    Returns the model's reply string, or None if the server is unreachable
    or returns an unexpected response. Never raises.

    Args:
        prompt: The user message to send.
        model: Model name/ID. If None, LM Studio uses whichever model is loaded.
        url: Base URL override. Defaults to LM_STUDIO_URL env var or
            http://localhost:1234/v1.
        timeout: HTTP timeout in seconds.
        system: Optional system message prepended to the conversation.
    """
    base_url = (url or os.environ.get("LM_STUDIO_URL", _DEFAULT_URL)).rstrip("/")
    endpoint = f"{base_url}/chat/completions"

    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload: dict = {"messages": messages, "stream": False}
    if model:
        payload["model"] = model

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
    except Exception as exc:
        logger.debug("llm_local: inference failed (%s): %s", type(exc).__name__, exc)
        return None
```

- [ ] **Step 4: Update `llm_local/__init__.py`**

```python
"""llm_local — minimal local LLM inference client for LM Studio."""

__version__ = "0.1.0"

from llm_local.client import complete

__all__ = ["complete"]
```

- [ ] **Step 5: Run tests**

```bash
cd /home/mcarls/scripts/modules/llm_local
uv run pytest tests/llm_local_test.py -v --tb=short
```

Expected: All 4 tests pass.

- [ ] **Step 6: Commit**

```bash
cd /home/mcarls/scripts/modules/llm_local
git add llm_local/ tests/llm_local_test.py
git commit -m "feat(llm_local): add complete() — happy path + system + model"
```

---

## Task 2: Error handling — all failure modes return `None`

**Files:**
- Modify: `tests/llm_local_test.py` (append tests)
- No code changes needed — errors are already caught in Task 1's `except Exception`

- [ ] **Step 1: Add failing tests for error cases**

Append to `tests/llm_local_test.py`:

```python
import socket
import urllib.error


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

    def fake_urlopen(req, timeout=None):  # type: ignore[no-untyped-def]
        captured_urls.append(req.full_url)
        return _mock_response("ok")

    with patch("llm_local.client.urllib.request.urlopen", side_effect=fake_urlopen):
        complete("prompt", url="http://myserver:5678/v1")

    assert "myserver:5678" in captured_urls[0]


def test_complete_uses_env_var_url(monkeypatch: object) -> None:
    import pytest
    captured_urls: list[str] = []

    def fake_urlopen(req, timeout=None):  # type: ignore[no-untyped-def]
        captured_urls.append(req.full_url)
        return _mock_response("ok")

    import os
    monkeypatch.setenv("LM_STUDIO_URL", "http://envserver:9999/v1")  # type: ignore[attr-defined]
    with patch("llm_local.client.urllib.request.urlopen", side_effect=fake_urlopen):
        complete("prompt")

    assert "envserver:9999" in captured_urls[0]
```

- [ ] **Step 2: Run to confirm they pass (error handling was already in Task 1)**

```bash
cd /home/mcarls/scripts/modules/llm_local
uv run pytest tests/llm_local_test.py -v --tb=short
```

Expected: All 10 tests pass. If `test_complete_returns_none_on_missing_choices_key`
fails, the `except Exception` in `client.py` catches `KeyError` — it should pass.

- [ ] **Step 3: Run full test suite and verify clean**

```bash
cd /home/mcarls/scripts/modules/llm_local
uv run pytest tests/ -v --tb=short
```

Expected: 10 passed.

- [ ] **Step 4: Commit**

```bash
cd /home/mcarls/scripts/modules/llm_local
git add tests/llm_local_test.py
git commit -m "test(llm_local): add error handling and env var tests"
```

---

## Task 3: Install as editable package

- [ ] **Step 1: Install into scripts .venv**

```bash
cd /home/mcarls/scripts/modules/llm_local
pip install -e . -q
```

- [ ] **Step 2: Verify import from outside the module dir**

```bash
cd /home/mcarls
python -c "from llm_local import complete; print('llm_local OK, complete =', complete)"
```

Expected: `llm_local OK, complete = <function complete at 0x...>`

- [ ] **Step 3: Update PROJECT_STATUS.md**

In `/home/mcarls/scripts/modules/agent_memory/docs/PROJECT_STATUS.md`,
change `Phase 1 — llm_local module ⏳ NOT STARTED` to `✅ COMPLETE`.

- [ ] **Step 4: Commit**

```bash
cd /home/mcarls/scripts
git add modules/llm_local/
git commit -m "feat(llm_local): Phase 1 complete — stdlib inference client, 10 tests passing"
```

---

## Phase 1 Definition of Done

- [ ] `from llm_local import complete` works after `pip install -e .`
- [ ] `complete("prompt")` returns a string when LM Studio is running
- [ ] `complete("prompt")` returns `None` when LM Studio is off (no exception raised)
- [ ] `complete("prompt", system="...", model="...", url="...", timeout=2.0)` all accepted
- [ ] `LM_STUDIO_URL` env var respected
- [ ] 10 tests passing, no imports outside stdlib
