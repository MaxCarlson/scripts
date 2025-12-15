from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Iterator

from lmstui.http_client import HttpClient, now_seconds
from lmstui.sse import iter_sse_events


@dataclass(frozen=True)
class ChatStreamChunk:
    text: str


@dataclass(frozen=True)
class ChatResult:
    text: str
    raw: dict[str, Any] | None
    stats: dict[str, Any] | None
    usage: dict[str, Any] | None
    model_info: dict[str, Any] | None
    runtime: dict[str, Any] | None
    client_metrics: dict[str, Any]


class LMStudioAPI:
    def __init__(self, base_url: str, api_mode: str, http: HttpClient) -> None:
        self._base = base_url.rstrip("/")
        self._mode = api_mode
        self._http = http

    def resolve_mode(self) -> str:
        if self._mode in ("rest", "openai"):
            return self._mode

        code, _ = self._http.get_json(f"{self._base}/api/v0/models")
        if code == 200:
            return "rest"

        code2, _ = self._http.get_json(f"{self._base}/v1/models")
        if code2 == 200:
            return "openai"

        return "rest"

    def list_models(self) -> dict[str, Any] | str:
        mode = self.resolve_mode()
        if mode == "rest":
            code, payload = self._http.get_json(f"{self._base}/api/v0/models")
            if code != 200:
                raise RuntimeError(f"REST models failed: {payload}")
            if not isinstance(payload, dict):
                raise RuntimeError(f"REST models returned non-json: {payload}")
            return payload

        code, payload = self._http.get_json(f"{self._base}/v1/models")
        if code != 200:
            raise RuntimeError(f"OpenAI models failed: {payload}")
        if not isinstance(payload, dict):
            raise RuntimeError(f"OpenAI models returned non-json: {payload}")
        return payload

    def model_info(self, model_id: str) -> dict[str, Any]:
        mode = self.resolve_mode()
        if mode == "rest":
            code, payload = self._http.get_json(f"{self._base}/api/v0/models/{model_id}")
            if code != 200 or not isinstance(payload, dict):
                raise RuntimeError(f"REST model info failed: {payload}")
            return payload

        models = self.list_models()
        if not isinstance(models, dict):
            raise RuntimeError("Unexpected models format")
        for item in models.get("data", []):
            if isinstance(item, dict) and item.get("id") == model_id:
                return item
        raise RuntimeError(f"Model not found: {model_id}")

    def chat(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        stream: bool,
        use_rest: bool | None = None,
    ) -> ChatResult | Iterator[ChatStreamChunk]:
        mode = self.resolve_mode() if use_rest is None else ("rest" if use_rest else "openai")
        if stream:
            return self._chat_stream(mode, model_id, messages, temperature, max_tokens)
        return self._chat_once(mode, model_id, messages, temperature, max_tokens)

    def embeddings(self, model_id: str, inputs: list[str], use_rest: bool | None = None) -> dict[str, Any]:
        mode = self.resolve_mode() if use_rest is None else ("rest" if use_rest else "openai")
        url = f"{self._base}/api/v0/embeddings" if mode == "rest" else f"{self._base}/v1/embeddings"
        payload = {"model": model_id, "input": inputs if len(inputs) > 1 else inputs[0]}
        code, body = self._http.post_json(url, payload)
        if code != 200 or not isinstance(body, dict):
            raise RuntimeError(f"Embeddings failed: {body}")
        return body

    def _chat_once(
        self,
        mode: str,
        model_id: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> ChatResult:
        url = f"{self._base}/api/v0/chat/completions" if mode == "rest" else f"{self._base}/v1/chat/completions"
        payload = {
            "model": model_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        t0 = now_seconds()
        code, body = self._http.post_json(url, payload)
        t1 = now_seconds()

        if code != 200 or not isinstance(body, dict):
            raise RuntimeError(f"Chat failed: {body}")

        text = (
            (((body.get("choices") or [{}])[0] or {}).get("message") or {}).get("content")
            or (((body.get("choices") or [{}])[0] or {}).get("text"))
            or ""
        )

        stats = body.get("stats") if isinstance(body.get("stats"), dict) else None
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else None
        model_info = body.get("model_info") if isinstance(body.get("model_info"), dict) else None
        runtime = body.get("runtime") if isinstance(body.get("runtime"), dict) else None

        client_metrics = {
            "client_total_seconds": round(t1 - t0, 6),
        }

        return ChatResult(
            text=text,
            raw=body,
            stats=stats,
            usage=usage,
            model_info=model_info,
            runtime=runtime,
            client_metrics=client_metrics,
        )

    def _chat_stream(
        self,
        mode: str,
        model_id: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> Iterator[ChatStreamChunk]:
        url = f"{self._base}/api/v0/chat/completions" if mode == "rest" else f"{self._base}/v1/chat/completions"
        payload = {
            "model": model_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        stream_resp = self._http.post_json_stream(url, payload)

        if stream_resp.status != 200:
            raise RuntimeError(f"Streaming chat failed with HTTP {stream_resp.status}")

        for event in iter_sse_events(stream_resp.stream):
            data = event.data.strip()
            if data == "[DONE]":
                return

            try:
                obj = json.loads(data)
            except Exception:
                continue

            for chunk_text in _extract_stream_text(obj):
                if chunk_text:
                    yield ChatStreamChunk(text=chunk_text)


def _extract_stream_text(obj: dict[str, Any]) -> Iterable[str]:
    """
    Works with typical OpenAI Chat Completions streaming:
      choices[0].delta.content
    Some servers may emit:
      choices[0].text
    """
    choices = obj.get("choices")
    if not isinstance(choices, list):
        return []

    out: list[str] = []
    for choice in choices:
        if not isinstance(choice, dict):
            continue

        delta = choice.get("delta")
        if isinstance(delta, dict):
            content = delta.get("content")
            if isinstance(content, str) and content:
                out.append(content)
                continue

        text = choice.get("text")
        if isinstance(text, str) and text:
            out.append(text)
            continue

        message = choice.get("message")
        if isinstance(message, dict):
            content2 = message.get("content")
            if isinstance(content2, str) and content2:
                out.append(content2)

    return out
