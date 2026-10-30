"""Opt-in OpenAI-compatible loopback inference gateway with bounded live events."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import time
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from .inference_models import ContentSegment, InferenceRequest
from .live_store import LiveInferenceStore

MAX_REQUEST_BYTES = 4 * 1024 * 1024
MAX_EVENT_BYTES = 64 * 1024
MAX_OBSERVER_QUEUE = 128
MAX_OBSERVERS = 8


def validate_gateway_upstream(value: str) -> str:
    """Only allow an explicitly configured loopback HTTP(S) upstream."""
    parts = urlsplit(value)
    try:
        address = ipaddress.ip_address(parts.hostname or "")
    except ValueError as error:
        if (parts.hostname or "").lower() not in {"localhost"}:
            raise ValueError("gateway upstream must use a loopback IP or localhost") from error
    else:
        if not address.is_loopback:
            raise ValueError("gateway upstream must be loopback-only")
    if parts.scheme not in {"http", "https"} or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("gateway upstream must be an HTTP(S) loopback URL without credentials/query/fragment")
    if parts.path not in {"", "/"}:
        raise ValueError("gateway upstream must be a base origin")
    if parts.port is None or not 1 <= parts.port <= 65535:
        raise ValueError("gateway upstream must include an explicit port")
    return value.rstrip("/")


class RequestEventHub:
    """Bounded per-observer event fanout; slow browsers get an explicit gap marker."""

    def __init__(self, *, queue_size: int = MAX_OBSERVER_QUEUE, max_observers: int = MAX_OBSERVERS) -> None:
        self.queue_size = queue_size
        self.max_observers = max_observers
        self.sequence = 0
        self._request_sequences: OrderedDict[str, int] = OrderedDict()
        self._queues: set[asyncio.Queue[dict[str, Any]]] = set()

    def publish(self, event: dict[str, Any]) -> dict[str, Any]:
        self.sequence += 1
        identity = event.get("request") or {}
        request_id = identity.get("request_id") if isinstance(identity, dict) else None
        request_sequence = self._request_sequences.get(request_id, 0) + 1 if request_id else self.sequence
        if request_id:
            self._request_sequences[request_id] = request_sequence
            self._request_sequences.move_to_end(request_id)
            while len(self._request_sequences) > 500:
                self._request_sequences.popitem(last=False)
        item = {**event, "sequence": request_sequence, "revision": self.sequence}
        for queue in tuple(self._queues):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                gap = {"type": "telemetry.gap", "sequence": self.sequence, "request": item.get("request"), "reason": "observer_queue_overflow"}
                try:
                    queue.put_nowait(gap)
                except asyncio.QueueFull:
                    pass
                continue
            queue.put_nowait(item)
        return item

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        if len(self._queues) >= self.max_observers:
            raise RuntimeError("observer_capacity_reached")
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(self.queue_size)
        self._queues.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._queues.discard(queue)


class OpenAIInferenceGateway:
    """Forward chat completions to a fixed loopback upstream and observe this request."""

    def __init__(self, upstream: str, store: LiveInferenceStore, events: RequestEventHub, *, server_instance_id: str = "lmstudio-gateway", client: httpx.AsyncClient | None = None) -> None:
        self.upstream = validate_gateway_upstream(upstream)
        self.store = store
        self.events = events
        self.server_instance_id = server_instance_id
        self._client = client or httpx.AsyncClient(timeout=None, follow_redirects=False, trust_env=False)

    async def close(self) -> None:
        await self._client.aclose()

    def router(self) -> APIRouter:
        router = APIRouter(prefix="/v1")

        @router.post("/chat/completions")
        async def chat_completions(request: Request) -> Response:
            length = request.headers.get("content-length")
            if length and (not length.isdecimal() or int(length) > MAX_REQUEST_BYTES):
                raise HTTPException(status_code=413, detail="Request body exceeds gateway limit")
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > MAX_REQUEST_BYTES:
                    raise HTTPException(status_code=413, detail="Request body exceeds gateway limit")
                body.extend(chunk)
            body = bytes(body)
            try:
                payload = json.loads(body)
                if not isinstance(payload, dict) or not isinstance(payload.get("messages"), list):
                    raise ValueError
            except (ValueError, json.JSONDecodeError) as error:
                raise HTTPException(status_code=400, detail="Expected a chat-completions JSON request") from error
            request_id = str(uuid.uuid4())
            started = time.monotonic()
            started_at = _now()
            model_id = payload.get("model") if isinstance(payload.get("model"), str) else None
            identity = {"request_id": request_id, "server_instance_id": self.server_instance_id, "model_instance_id": model_id, "provider_model_id": model_id, "model_name": model_id}
            segments = tuple(ContentSegment(kind=str(message.get("role", "other")), role=str(message.get("role", "other")), text=_message_text(message.get("content")), source="gateway_client") for message in payload["messages"] if isinstance(message, dict))
            record = InferenceRequest(request_id=request_id, server_instance_id=self.server_instance_id, model_instance_id=model_id, provider_model_id=model_id, model_name=model_id, source="gateway_openai_chat_completions", state="active", started_at=started_at, coverage={"request_lifecycle": "complete", "structured_input": "available", "reasoning_text": "streaming", "output_text": "streaming", "token_usage": "unavailable", "request_timing": "gateway_timed"}, content=segments)
            self.store.add_request(record)
            self.events.publish({"type": "request.started", "request": identity, "timestamp": started_at, "content": [segment.to_dict() for segment in segments]})
            url = f"{self.upstream}/v1/chat/completions"
            headers = {key: value for key, value in request.headers.items() if key.lower() in {"authorization", "content-type", "accept"}}
            headers["content-type"] = "application/json"
            headers["accept-encoding"] = "identity"
            try:
                upstream_request = self._client.build_request("POST", url, content=body, headers=headers)
                upstream = await self._client.send(upstream_request, stream=bool(payload.get("stream")))
            except httpx.HTTPError:
                self._terminal(request_id, identity, "request.failed", started, started_at, "upstream_error")
                raise HTTPException(status_code=502, detail="Configured inference upstream is unavailable")
            if upstream.status_code >= 400:
                raw = await upstream.aread()
                await upstream.aclose()
                self._terminal(request_id, identity, "request.failed", started, started_at, "upstream_error")
                return Response(raw, status_code=upstream.status_code, headers=_response_headers(upstream.headers), media_type=upstream.headers.get("content-type"))
            if not payload.get("stream"):
                raw = await upstream.aread()
                await upstream.aclose()
                self._capture_json(request_id, identity, raw)
                self._terminal(request_id, identity, "request.completed", started, started_at)
                return Response(raw, status_code=upstream.status_code, headers=_response_headers(upstream.headers), media_type=upstream.headers.get("content-type"))
            return StreamingResponse(self._stream(upstream, request_id, identity, started, started_at), status_code=upstream.status_code, headers=_response_headers(upstream.headers), media_type=upstream.headers.get("content-type", "text/event-stream"))

        return router

    async def _stream(self, upstream: httpx.Response, request_id: str, identity: dict[str, Any], started: float, started_at: str) -> AsyncIterator[bytes]:
        pending = bytearray()
        try:
            async for chunk in upstream.aiter_bytes():
                if len(pending) + len(chunk) > MAX_EVENT_BYTES:
                    self.events.publish({"type": "telemetry.gap", "request": identity, "timestamp": _now(), "reason": "upstream_event_too_large"})
                    pending.clear()
                pending.extend(chunk)
                while (boundary := _frame_boundary(pending)) is not None:
                    frame = bytes(pending[:boundary])
                    del pending[:boundary]
                    self._capture_sse(request_id, identity, frame)
                    yield frame
            if pending:
                frame = bytes(pending)
                self._capture_sse(request_id, identity, frame)
                yield frame
            self._terminal(request_id, identity, "request.completed", started, started_at)
        except asyncio.CancelledError:
            self._terminal(request_id, identity, "request.cancelled", started, started_at)
            raise
        except (httpx.HTTPError, OSError):
            self.events.publish({"type": "stream.interrupted", "request": identity, "timestamp": _now()})
            self._terminal(request_id, identity, "request.failed", started, started_at, "upstream_stream_error")
        finally:
            await upstream.aclose()

    def _capture_sse(self, request_id: str, identity: dict[str, Any], frame: bytes) -> None:
        if len(frame) > MAX_EVENT_BYTES:
            self.events.publish({"type": "telemetry.gap", "request": identity, "timestamp": _now(), "reason": "upstream_event_too_large"})
            return
        for line in frame.splitlines():
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if data == b"[DONE]":
                continue
            try:
                event = json.loads(data)
            except (UnicodeDecodeError, json.JSONDecodeError):
                self.events.publish({"type": "telemetry.gap", "request": identity, "timestamp": _now(), "reason": "malformed_upstream_sse"})
                continue
            choices = event.get("choices") if isinstance(event, dict) else None
            if isinstance(choices, list):
                for choice in choices:
                    delta = choice.get("delta") if isinstance(choice, dict) else None
                    if isinstance(delta, dict):
                        for field, kind in (("reasoning_content", "reasoning.delta"), ("content", "output.delta")):
                            value = delta.get(field)
                            if isinstance(value, str) and value:
                                segment_kind = "reasoning" if field == "reasoning_content" else "assistant"
                                emitted = self.events.publish({"type": kind, "request": identity, "timestamp": _now(), "delta": value})
                                self.store.append_content(request_id, ContentSegment(kind=segment_kind, role="assistant", text=value, observed_at=emitted["timestamp"], sequence=emitted["sequence"], source="gateway_sse"))
                        for tool in delta.get("tool_calls", []) if isinstance(delta.get("tool_calls"), list) else []:
                            function = tool.get("function") if isinstance(tool, dict) else None
                            if isinstance(function, dict) and isinstance(function.get("arguments"), str):
                                value = function["arguments"]
                                emitted = self.events.publish({"type": "tool_call.delta", "request": identity, "timestamp": _now(), "delta": value})
                                self.store.append_content(request_id, ContentSegment(kind="tool_call", role="assistant", text=value, observed_at=emitted["timestamp"], sequence=emitted["sequence"], source="gateway_sse"))
                    if isinstance(choice, dict) and choice.get("finish_reason"):
                        self._update_fields(request_id, finish_reason=choice["finish_reason"])
                        self.events.publish({"type": "request.updated", "request": identity, "timestamp": _now(), "payload": {"finish_reason": choice["finish_reason"]}})
            if isinstance(event, dict) and isinstance(event.get("id"), str):
                self._update_fields(request_id, provider_request_id=event["id"])
            usage = event.get("usage") if isinstance(event, dict) else None
            if isinstance(usage, dict):
                self.events.publish({"type": "usage.reported", "request": identity, "timestamp": _now(), "source": "provider_reported", "payload": _usage_payload(usage)})
                self._update_usage(request_id, usage)

    def _capture_json(self, request_id: str, identity: dict[str, Any], raw: bytes) -> None:
        try:
            result = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.events.publish({"type": "telemetry.gap", "request": identity, "timestamp": _now(), "reason": "malformed_upstream_json"})
            return
        for choice in result.get("choices", []) if isinstance(result, dict) else []:
            message = choice.get("message", {}) if isinstance(choice, dict) else {}
            if isinstance(message, dict):
                for field, kind in (("reasoning_content", "reasoning.delta"), ("content", "output.delta")):
                    if isinstance(message.get(field), str) and message[field]:
                        emitted = self.events.publish({"type": kind, "request": identity, "timestamp": _now(), "delta": message[field]})
                        self.store.append_content(request_id, ContentSegment(kind="reasoning" if field == "reasoning_content" else "assistant", role="assistant", text=message[field], observed_at=emitted["timestamp"], sequence=emitted["sequence"], source="gateway_json"))
            if isinstance(choice, dict) and isinstance(choice.get("finish_reason"), str):
                self._update_fields(request_id, finish_reason=choice["finish_reason"])
        if isinstance(result, dict) and isinstance(result.get("id"), str):
            self._update_fields(request_id, provider_request_id=result["id"])
        usage = result.get("usage") if isinstance(result, dict) else None
        if isinstance(usage, dict):
            self._update_usage(request_id, usage)
            self.events.publish({"type": "usage.reported", "request": identity, "timestamp": _now(), "source": "provider_reported", "payload": _usage_payload(usage)})

    def _update_usage(self, request_id: str, usage: dict[str, Any]) -> None:
        existing = next((item for item in self.store.requests() if item.request_id == request_id), None)
        if existing:
            details = usage.get("completion_tokens_details") if isinstance(usage.get("completion_tokens_details"), dict) else {}
            reasoning = _int_or_none(details.get("reasoning_tokens"))
            completion = _int_or_none(usage.get("completion_tokens"))
            self.store.add_request(InferenceRequest(**{**existing.__dict__, "input_tokens": _int_or_none(usage.get("prompt_tokens")), "reasoning_tokens": reasoning, "output_tokens": completion if reasoning is None else None, "generated_tokens": completion, "usage_source": "provider_reported"}))

    def _update_fields(self, request_id: str, **fields: Any) -> None:
        existing = next((item for item in self.store.requests() if item.request_id == request_id), None)
        if existing:
            self.store.add_request(InferenceRequest(**{**existing.__dict__, **fields}))

    def _terminal(self, request_id: str, identity: dict[str, Any], kind: str, started: float, started_at: str, error: str | None = None) -> None:
        ended = _now()
        existing = next((item for item in self.store.requests() if item.request_id == request_id), None)
        if existing:
            elapsed = time.monotonic() - started
            self.store.add_request(InferenceRequest(**{**existing.__dict__, "state": kind.removeprefix("request."), "ended_at": ended, "elapsed_seconds": elapsed}))
        else:
            elapsed = time.monotonic() - started
        event = {"type": kind, "request": identity, "timestamp": ended, "elapsed_seconds": elapsed}
        if error:
            event["error_category"] = error
        self.events.publish(event)


def _message_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return None


def _frame_boundary(pending: bytearray) -> int | None:
    matches = [(pending.find(delimiter), len(delimiter)) for delimiter in (b"\n\n", b"\r\n\r\n")]
    matches = [(index, length) for index, length in matches if index >= 0]
    return min(matches)[0] + min(matches)[1] if matches else None


def _response_headers(headers: httpx.Headers) -> dict[str, str]:
    allowed = {"content-type", "cache-control", "retry-after"}
    return {key: value for key, value in headers.items() if key.lower() in allowed}


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _usage_payload(usage: dict[str, Any]) -> dict[str, Any]:
    details = usage.get("completion_tokens_details") if isinstance(usage.get("completion_tokens_details"), dict) else {}
    reasoning = _int_or_none(details.get("reasoning_tokens"))
    completion = _int_or_none(usage.get("completion_tokens"))
    return {"input_tokens": _int_or_none(usage.get("prompt_tokens")), "reasoning_tokens": reasoning, "output_tokens": completion if reasoning is None else None, "generated_tokens": completion}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
