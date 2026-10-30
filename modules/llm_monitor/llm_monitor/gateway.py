"""Opt-in OpenAI-compatible loopback inference gateway with bounded live events."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import socket
import time
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
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
MAX_CAPTURE_FRAME_BYTES = 1024 * 1024
MAX_OBSERVER_QUEUE = 128
MAX_OBSERVERS = 8
_SSE_FRAME_SEPARATOR = re.compile(rb"(?:\r?\n){2}")
_LOGGER = logging.getLogger(__name__)


def validate_gateway_upstream(value: str) -> str:
    """Only allow an explicitly configured loopback HTTP(S) upstream."""
    parts = urlsplit(value)
    try:
        address = ipaddress.ip_address(parts.hostname or "")
    except ValueError as error:
        if (parts.hostname or "").lower() != "localhost":
            raise ValueError("gateway upstream must use a loopback IP or localhost") from error
        try:
            resolved = socket.getaddrinfo("localhost", parts.port, type=socket.SOCK_STREAM)
        except OSError as resolve_error:
            raise ValueError("gateway localhost upstream could not be resolved safely") from resolve_error
        addresses = []
        for result in resolved:
            try:
                address = ipaddress.ip_address(result[4][0])
            except ValueError as address_error:
                raise ValueError("gateway localhost upstream resolved to a non-IP address") from address_error
            if not address.is_loopback:
                raise ValueError("gateway localhost upstream resolved outside loopback")
            addresses.append(address)
        if not addresses:
            raise ValueError("gateway localhost upstream has no loopback address")
        # Pin the validated resolution so a later DNS lookup cannot change the destination.
        address = addresses[0]
    else:
        if not address.is_loopback:
            raise ValueError("gateway upstream must be loopback-only")
    if parts.scheme not in {"http", "https"} or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("gateway upstream must be an HTTP(S) loopback URL without credentials/query/fragment")
    if parts.path not in {"", "/"}:
        raise ValueError("gateway upstream must be a base origin")
    if parts.port is None or not 1 <= parts.port <= 65535:
        raise ValueError("gateway upstream must include an explicit port")
    if parts.hostname and parts.hostname.lower() == "localhost":
        host = f"[{address}]" if address.version == 6 else str(address)
        return f"{parts.scheme.lower()}://{host}:{parts.port}"
    return value.rstrip("/")


class _GatewayTiming:
    """Collect monotonic stage timings without retaining request or response content."""

    def __init__(self, sink: Callable[[dict[str, Any]], None] | None) -> None:
        self.sink = sink
        self.started_ns = time.perf_counter_ns()
        self.process_started_ns = time.process_time_ns() if sink is not None else None
        self.points: dict[str, float] = {"request_received_ms": 0.0}
        self.counters: dict[str, float] = {"event_publication_ms": 0.0, "content_store_update_ms": 0.0}

    def mark(self, name: str) -> None:
        self.points[name] = (time.perf_counter_ns() - self.started_ns) / 1_000_000

    def add(self, name: str, elapsed_ns: int) -> None:
        self.counters[name] += elapsed_ns / 1_000_000

    def emit(self, request_id: str) -> None:
        if self.sink is None:
            return
        payload = {"request_id": request_id, **self.points, **self.counters}
        if self.process_started_ns is not None:
            payload["gateway_process_cpu_ms"] = (time.process_time_ns() - self.process_started_ns) / 1_000_000
            try:
                import psutil

                payload["gateway_process_rss_bytes"] = psutil.Process().memory_info().rss
            except Exception:
                payload["gateway_process_rss_bytes"] = None
        try:
            self.sink(payload)
        except Exception:
            _LOGGER.exception("gateway timing sink failed")


def _validate_gateway_request_headers(content_type: str, origin: str | None, fetch_site: str, expected_origin: str) -> None:
    """Permit CLI clients and same-origin browser calls while rejecting cross-site requests."""
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(status_code=415, detail="Gateway requires application/json")
    if fetch_site.lower() == "cross-site" or (origin is not None and origin.rstrip("/") != expected_origin):
        raise HTTPException(status_code=403, detail="Cross-origin browser requests are not accepted")


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

    def __init__(self, upstream: str, store: LiveInferenceStore, events: RequestEventHub, *, server_instance_id: str = "lmstudio-gateway", client: httpx.AsyncClient | None = None, timing_sink: Callable[[dict[str, Any]], None] | None = None, capture_enabled: bool = True) -> None:
        self.upstream = validate_gateway_upstream(upstream)
        self.store = store
        self.events = events
        self.server_instance_id = server_instance_id
        self._client = client or httpx.AsyncClient(timeout=None, follow_redirects=False, trust_env=False)
        self.timing_sink = timing_sink
        self.capture_enabled = capture_enabled

    async def close(self) -> None:
        await self._client.aclose()

    def router(self) -> APIRouter:
        router = APIRouter(prefix="/v1")

        @router.post("/chat/completions")
        async def chat_completions(request: Request) -> Response:
            timing = _GatewayTiming(self.timing_sink)
            request_id = str(uuid.uuid4())
            started = time.monotonic()
            started_at = _now()
            expected_origin = f"{request.url.scheme}://{request.url.netloc}"
            _validate_gateway_request_headers(
                request.headers.get("content-type", ""),
                request.headers.get("origin"),
                request.headers.get("sec-fetch-site", ""),
                expected_origin,
            )
            length = request.headers.get("content-length")
            if length and (not length.isdecimal() or int(length) > MAX_REQUEST_BYTES):
                raise HTTPException(status_code=413, detail="Request body exceeds gateway limit")
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > MAX_REQUEST_BYTES:
                    raise HTTPException(status_code=413, detail="Request body exceeds gateway limit")
                body.extend(chunk)
            body = bytes(body)
            timing.mark("body_read_ms")
            try:
                payload = json.loads(body)
                if not isinstance(payload, dict) or not isinstance(payload.get("messages"), list):
                    raise ValueError
            except (ValueError, json.JSONDecodeError) as error:
                raise HTTPException(status_code=400, detail="Expected a chat-completions JSON request") from error
            if not self.capture_enabled:
                return await self._forward_request(request, body, payload)
            timing.mark("normalization_ms")
            model_id = payload.get("model") if isinstance(payload.get("model"), str) else None
            identity = {"request_id": request_id, "server_instance_id": self.server_instance_id, "model_instance_id": model_id, "provider_model_id": model_id, "model_name": model_id}
            segments = tuple(ContentSegment(kind=str(message.get("role", "other")), role=str(message.get("role", "other")), text=_message_text(message.get("content")), source="gateway_client") for message in payload["messages"] if isinstance(message, dict))
            record = InferenceRequest(request_id=request_id, server_instance_id=self.server_instance_id, model_instance_id=model_id, provider_model_id=model_id, model_name=model_id, source="gateway_openai_chat_completions", state="active", started_at=started_at, coverage={"request_lifecycle": "complete", "structured_input": "available", "reasoning_text": "streaming", "output_text": "streaming", "token_usage": "unavailable", "request_timing": "gateway_timed"}, content=segments)
            self.store.add_request(record)
            self._publish({"type": "request.started", "request": identity, "timestamp": started_at, "content": [segment.to_dict() for segment in segments]}, timing)
            url = f"{self.upstream}/v1/chat/completions"
            headers = {key: value for key, value in request.headers.items() if key.lower() in {"authorization", "content-type", "accept"}}
            headers["content-type"] = "application/json"
            headers["accept-encoding"] = "identity"
            try:
                timing.mark("upstream_dispatch_ms")
                upstream_request = self._client.build_request("POST", url, content=body, headers=headers)
                upstream = await self._client.send(upstream_request, stream=True)
                timing.mark("upstream_headers_ms")
            except httpx.HTTPError:
                self._terminal(request_id, identity, "request.failed", started, started_at, "upstream_error", timing)
                raise HTTPException(status_code=502, detail="Configured inference upstream is unavailable")
            if upstream.status_code >= 400:
                try:
                    raw = await upstream.aread()
                except (httpx.HTTPError, OSError):
                    timing.mark("body_complete_ms")
                    self._terminal(request_id, identity, "request.failed", started, started_at, "upstream_error_body", timing)
                    raise HTTPException(status_code=502, detail="Configured inference upstream error response was interrupted")
                finally:
                    await upstream.aclose()
                timing.mark("body_complete_ms")
                self._terminal(request_id, identity, "request.failed", started, started_at, "upstream_error", timing)
                return Response(raw, status_code=upstream.status_code, headers=_response_headers(upstream.headers), media_type=upstream.headers.get("content-type"))
            if not payload.get("stream"):
                try:
                    raw = await upstream.aread()
                    timing.mark("first_upstream_byte_ms")
                    timing.mark("first_downstream_byte_ms")
                except (httpx.HTTPError, OSError):
                    timing.mark("body_complete_ms")
                    self._terminal(request_id, identity, "request.failed", started, started_at, "upstream_body_error", timing)
                    raise HTTPException(status_code=502, detail="Configured inference upstream response was interrupted")
                finally:
                    await upstream.aclose()
                timing.mark("body_complete_ms")
                self._capture_json(request_id, identity, raw, timing=timing)
                self._terminal(request_id, identity, "request.completed", started, started_at, timing=timing)
                return Response(raw, status_code=upstream.status_code, headers=_response_headers(upstream.headers), media_type=upstream.headers.get("content-type"))
            return StreamingResponse(self._stream(upstream, request_id, identity, started, started_at, timing), status_code=upstream.status_code, headers=_response_headers(upstream.headers), media_type=upstream.headers.get("content-type", "text/event-stream"))

        return router

    async def _forward_request(self, request: Request, body: bytes, payload: dict[str, Any]) -> Response:
        headers = {key: value for key, value in request.headers.items() if key.lower() in {"authorization", "content-type", "accept"}}
        headers["accept-encoding"] = "identity"
        upstream_request = self._client.build_request("POST", f"{self.upstream}/v1/chat/completions", content=body, headers=headers)
        try:
            upstream = await self._client.send(upstream_request, stream=True)
        except httpx.HTTPError as error:
            raise HTTPException(status_code=502, detail="Configured inference upstream is unavailable") from error
        response_headers = _response_headers(upstream.headers)
        if upstream.status_code >= 400 or not payload.get("stream"):
            try:
                raw = await upstream.aread()
            except (httpx.HTTPError, OSError) as error:
                raise HTTPException(status_code=502, detail="Configured inference upstream response was interrupted") from error
            finally:
                await upstream.aclose()
            return Response(raw, status_code=upstream.status_code, headers=response_headers, media_type=upstream.headers.get("content-type"))
        return StreamingResponse(self._forward_stream(upstream), status_code=upstream.status_code, headers=response_headers, media_type=upstream.headers.get("content-type", "text/event-stream"))

    async def _forward_stream(self, upstream: httpx.Response) -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        except (httpx.HTTPError, OSError):
            yield b'data: {"error":{"message":"Inference upstream stream interrupted","type":"gateway_upstream_error"}}\n\n'
        finally:
            await upstream.aclose()

    async def _stream(self, upstream: httpx.Response, request_id: str, identity: dict[str, Any], started: float, started_at: str, timing: _GatewayTiming | None = None) -> AsyncIterator[bytes]:
        pending = bytearray()
        timing = timing or _GatewayTiming(self.timing_sink)
        timing.mark("upstream_headers_ms")
        try:
            async for chunk in upstream.aiter_bytes():
                if "first_upstream_byte_ms" not in timing.points:
                    timing.mark("first_upstream_byte_ms")
                pending.extend(chunk)
                while (boundary := _frame_boundary(pending)) is not None:
                    frame = bytes(pending[:boundary])
                    del pending[:boundary]
                    self._capture_sse(request_id, identity, frame, timing=timing)
                if len(pending) > MAX_CAPTURE_FRAME_BYTES:
                    self._publish({"type": "telemetry.gap", "request": identity, "timestamp": _now(), "reason": "upstream_event_too_large"}, timing)
                    pending.clear()
                if "first_downstream_byte_ms" not in timing.points:
                    timing.mark("first_downstream_byte_ms")
                # Forward exact upstream bytes immediately; parsing is an independent bounded side path.
                yield chunk
            if pending:
                self._capture_sse(request_id, identity, bytes(pending), timing=timing)
            timing.mark("body_complete_ms")
            self._terminal(request_id, identity, "request.completed", started, started_at, timing=timing)
        except asyncio.CancelledError:
            self._terminal(request_id, identity, "request.cancelled", started, started_at, timing=timing)
            raise
        except (httpx.HTTPError, OSError):
            self._publish({"type": "stream.interrupted", "request": identity, "timestamp": _now()}, timing)
            self._terminal(request_id, identity, "request.failed", started, started_at, "upstream_stream_error", timing)
            # The HTTP status is already committed; an SSE error frame makes the partial result explicit.
            yield b'data: {"error":{"message":"Inference upstream stream interrupted","type":"gateway_upstream_error"}}\n\n'
        finally:
            await upstream.aclose()

    def _capture_sse(self, request_id: str, identity: dict[str, Any], frame: bytes, *, timing: _GatewayTiming | None = None) -> None:
        if len(frame) > MAX_EVENT_BYTES:
            self._publish({"type": "telemetry.gap", "request": identity, "timestamp": _now(), "reason": "upstream_event_too_large"}, timing)
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
                self._publish({"type": "telemetry.gap", "request": identity, "timestamp": _now(), "reason": "malformed_upstream_sse"}, timing)
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
                                emitted = self._publish({"type": kind, "request": identity, "timestamp": _now(), "delta": value}, timing)
                                self._append_content(request_id, ContentSegment(kind=segment_kind, role="assistant", text=value, observed_at=emitted["timestamp"], sequence=emitted["sequence"], source="gateway_sse"), timing)
                        for tool in delta.get("tool_calls", []) if isinstance(delta.get("tool_calls"), list) else []:
                            function = tool.get("function") if isinstance(tool, dict) else None
                            if isinstance(function, dict) and isinstance(function.get("arguments"), str):
                                value = function["arguments"]
                                emitted = self._publish({"type": "tool_call.delta", "request": identity, "timestamp": _now(), "delta": value}, timing)
                                self._append_content(request_id, ContentSegment(kind="tool_call", role="assistant", text=value, observed_at=emitted["timestamp"], sequence=emitted["sequence"], source="gateway_sse"), timing)
                    if isinstance(choice, dict) and choice.get("finish_reason"):
                        self._update_fields(request_id, finish_reason=choice["finish_reason"])
                        self._publish({"type": "request.updated", "request": identity, "timestamp": _now(), "payload": {"finish_reason": choice["finish_reason"]}}, timing)
            if isinstance(event, dict) and isinstance(event.get("id"), str):
                self._update_fields(request_id, provider_request_id=event["id"])
            usage = event.get("usage") if isinstance(event, dict) else None
            if isinstance(usage, dict):
                self._publish({"type": "usage.reported", "request": identity, "timestamp": _now(), "source": "provider_reported", "payload": _usage_payload(usage)}, timing)
                self._update_usage(request_id, usage)

    def _capture_json(self, request_id: str, identity: dict[str, Any], raw: bytes, *, timing: _GatewayTiming | None = None) -> None:
        try:
            result = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._publish({"type": "telemetry.gap", "request": identity, "timestamp": _now(), "reason": "malformed_upstream_json"}, timing)
            return
        for choice in result.get("choices", []) if isinstance(result, dict) else []:
            message = choice.get("message", {}) if isinstance(choice, dict) else {}
            if isinstance(message, dict):
                for field, kind in (("reasoning_content", "reasoning.delta"), ("content", "output.delta")):
                    if isinstance(message.get(field), str) and message[field]:
                        emitted = self._publish({"type": kind, "request": identity, "timestamp": _now(), "delta": message[field]}, timing)
                        self._append_content(request_id, ContentSegment(kind="reasoning" if field == "reasoning_content" else "assistant", role="assistant", text=message[field], observed_at=emitted["timestamp"], sequence=emitted["sequence"], source="gateway_json"), timing)
            if isinstance(choice, dict) and isinstance(choice.get("finish_reason"), str):
                self._update_fields(request_id, finish_reason=choice["finish_reason"])
        if isinstance(result, dict) and isinstance(result.get("id"), str):
            self._update_fields(request_id, provider_request_id=result["id"])
        usage = result.get("usage") if isinstance(result, dict) else None
        if isinstance(usage, dict):
            self._update_usage(request_id, usage)
            self._publish({"type": "usage.reported", "request": identity, "timestamp": _now(), "source": "provider_reported", "payload": _usage_payload(usage)}, timing)

    def _publish(self, event: dict[str, Any], timing: _GatewayTiming | None) -> dict[str, Any]:
        started_ns = time.perf_counter_ns()
        result = self.events.publish(event)
        if timing is not None:
            timing.add("event_publication_ms", time.perf_counter_ns() - started_ns)
        return result

    def _append_content(self, request_id: str, segment: ContentSegment, timing: _GatewayTiming | None) -> None:
        started_ns = time.perf_counter_ns()
        self.store.append_content(request_id, segment)
        if timing is not None:
            timing.add("content_store_update_ms", time.perf_counter_ns() - started_ns)

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

    def _terminal(self, request_id: str, identity: dict[str, Any], kind: str, started: float, started_at: str, error: str | None = None, timing: _GatewayTiming | None = None) -> None:
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
        self._publish(event, timing)
        if timing is not None:
            timing.mark("finalization_ms")
            timing.emit(request_id)


def _message_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return None


def _frame_boundary(pending: bytearray) -> int | None:
    match = _SSE_FRAME_SEPARATOR.search(pending)
    return match.end() if match is not None else None


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
