#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Generator, List, Optional, Tuple

import requests


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str | None = None


class WebAIClient:
    """
    Thin client for WebAI-to-API.

    Modes:
      - WebAI (Gemini): /docs and /v1/chat/completions are present; /v1/models may 404.
      - g4f: /v1/models and /v1/providers available.

    Env overrides:
      WAI_API_URL, WAI_MODEL, WAI_PROVIDER, WAI_TIMEOUT
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        *,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        timeout: Optional[int] = None,
        verbose: bool = False,
    ):
        # Default host is your LAN server; can be overridden by WAI_API_URL or -u
        self.base_url = (
            base_url or os.getenv("WAI_API_URL") or "http://192.168.50.100:6969"
        ).rstrip("/")
        self.model = model or os.getenv("WAI_MODEL")
        self.provider = provider or os.getenv("WAI_PROVIDER") or None
        self.timeout = int(timeout or os.getenv("WAI_TIMEOUT") or 300)
        self.verbose = verbose

    # ---------- URLs ----------
    @property
    def _chat_url(self) -> str:
        return f"{self.base_url}/v1/chat/completions"

    @property
    def _models_url(self) -> str:
        return f"{self.base_url}/v1/models"

    @property
    def _providers_url(self) -> str:
        return f"{self.base_url}/v1/providers"

    @property
    def _docs_url(self) -> str:
        return f"{self.base_url}/docs"

    # ---------- Probes ----------
    def health_detail(self) -> Tuple[bool, str]:
        """
        Returns (ok, detail).
        Order:
          1) /docs == 200 → healthy (WebAI / Gemini)
          2) /v1/models or /v1/providers == 200 → healthy (g4f)
          3) 404 on models/providers is OK in WebAI mode if /docs was fine
        """
        last_err = "unknown"
        try:
            if self.verbose:
                print(f"[debug] GET {self._docs_url}")
            r = requests.get(self._docs_url, timeout=10)
            if r.status_code == 200:
                return True, "docs ok (WebAI mode likely)"
            last_err = f"http {r.status_code} on /docs"
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"

        models_404 = providers_404 = False
        try:
            if self.verbose:
                print(f"[debug] GET {self._models_url}")
            r = requests.get(self._models_url, timeout=10)
            if r.ok:
                return True, "models ok (g4f mode)"
            if r.status_code == 404:
                models_404 = True
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"

        try:
            if self.verbose:
                print(f"[debug] GET {self._providers_url}")
            r = requests.get(self._providers_url, timeout=10)
            if r.ok:
                return True, "providers ok (g4f mode)"
            if r.status_code == 404:
                providers_404 = True
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"

        if models_404 and providers_404:
            # Expected in WebAI (Gemini) mode; connectivity is probably fine.
            return True, "webai mode (models/providers 404 as expected)"
        return False, last_err

    def health(self) -> bool:
        ok, _ = self.health_detail()
        return ok

    def list_models(self) -> Dict[str, Any]:
        if self.verbose:
            print(f"[debug] GET {self._models_url}")
        r = requests.get(self._models_url, timeout=10)
        r.raise_for_status()
        return r.json()

    def list_providers(self) -> Dict[str, Any]:
        if self.verbose:
            print(f"[debug] GET {self._providers_url}")
        r = requests.get(self._providers_url, timeout=10)
        r.raise_for_status()
        return r.json()

    # ---------- Chat High-level ----------
    def chat_once(
        self,
        messages: List[Dict[str, str]],
        *,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        payload = self._payload(messages, model=model, provider=provider, stream=False)
        if self.verbose:
            print(f"[debug] POST {self._chat_url} stream=False")
        r = requests.post(self._chat_url, json=payload, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def chat_stream_events(
        self,
        messages: List[Dict[str, str]],
        *,
        model: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        payload = self._payload(messages, model=model, provider=provider, stream=True)
        if self.verbose:
            print(f"[debug] POST {self._chat_url} stream=True")
        with requests.post(self._chat_url, json=payload, stream=True) as r:
            r.raise_for_status()
            for line in r.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if data == "[DONE]":
                    yield {"event": "done"}
                    break
                try:
                    obj = json.loads(data)
                except Exception:
                    yield {"event": "content", "text": line + "\n"}
                    continue
                ch = obj.get("choices", [{}])[0]
                delta = ch.get("delta", {})
                if isinstance(delta, dict):
                    if "content" in delta and delta["content"]:
                        yield {"event": "content", "text": delta["content"]}
                    if "reasoning" in delta and delta["reasoning"]:
                        yield {"event": "reasoning", "text": delta["reasoning"]}
                    if "reasoning_content" in delta and delta["reasoning_content"]:
                        yield {"event": "reasoning", "text": delta["reasoning_content"]}
                if "usage" in obj and isinstance(obj["usage"], dict):
                    yield {"event": "usage", "usage": obj["usage"]}

    # ---------- Helpers ----------
    def _payload(
        self,
        messages: List[Dict[str, str]],
        *,
        model: Optional[str],
        provider: Optional[str],
        stream: bool,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"messages": messages}
        use_model = model or self.model or "gemini-2.0-flash"
        payload["model"] = use_model
        if provider or self.provider:
            payload["provider"] = provider or self.provider
        if stream:
            payload["stream"] = True
        return payload

