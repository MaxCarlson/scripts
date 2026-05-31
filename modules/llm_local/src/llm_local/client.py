from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

_DEFAULT_URL = "http://localhost:1234/v1"


def complete(
    prompt: str,
    *,
    model: str | None = None,
    url: str | None = None,
    timeout: float = 5.0,
    system: str | None = None,
) -> str | None:
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

    Returns:
        The model's reply string, or None if the server is unreachable
        or returns an unexpected response.
    """
    base_url = (url or os.environ.get("LM_STUDIO_URL", _DEFAULT_URL)).rstrip("/")
    endpoint = f"{base_url}/chat/completions"

    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload: dict[str, object] = {"messages": messages, "stream": False}
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
