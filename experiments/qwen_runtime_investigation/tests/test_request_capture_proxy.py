from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys

import httpx
from starlette.testclient import TestClient


EXPERIMENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXPERIMENT_DIR))

from request_capture_proxy import create_app  # noqa: E402


class _SSEStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield (
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1",'
            b'"type":"function","function":{"name":"read","arguments":"{}"}}]}}]}\n\n'
        )
        yield b"data: [DONE]\n\n"


class _BytesStream(httpx.AsyncByteStream):
    def __init__(self, body: bytes) -> None:
        self.body = body

    async def __aiter__(self):
        yield self.body


def test_proxy_forwards_live_request_but_persists_only_allowlisted_values(tmp_path: Path) -> None:
    forwarded: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        forwarded.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream", "cache-control": "no-cache"},
            stream=_SSEStream(),
        )

    capture_path = tmp_path / "outbound-params.jsonl"
    app = create_app(
        capture_path,
        upstream_transport=httpx.MockTransport(upstream),
        upstream_base_url="http://lmstudio.test/v1",
    )
    payload = {
        "model": "qwen38_23GB",
        "messages": [{"role": "user", "content": "synthetic private prompt"}],
        "reasoning_effort": "none",
        "max_tokens": 8192,
        "stream": True,
        "tools": [{"type": "function", "function": {"name": "read"}}],
    }

    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json=payload,
            headers={"Authorization": "Bearer synthetic-secret"},
        )

    assert response.status_code == 200
    assert response.content == (
        b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1",'
        b'"type":"function","function":{"name":"read","arguments":"{}"}}]}}]}\n\n'
        b"data: [DONE]\n\n"
    )
    assert len(forwarded) == 1
    assert json.loads(forwarded[0].content) == payload
    assert forwarded[0].headers["authorization"] == "Bearer synthetic-secret"

    record = json.loads(capture_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["parameters"] == {"reasoning_effort": "none", "max_tokens": 8192, "stream": True}
    assert record["model"] == "qwen38_23GB"
    assert record["tool_count"] == 1
    serialized = json.dumps(record)
    assert "synthetic private prompt" not in serialized
    assert "synthetic-secret" not in serialized
    assert "messages" in record["request_fields"]


def test_proxy_preserves_upstream_error_status_headers_and_body(tmp_path: Path) -> None:
    error_body = b'{"error":{"type":"invalid_request_error","code":"unsupported_value"}}'
    app = create_app(
        tmp_path / "outbound-params.jsonl",
        upstream_transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                400,
                headers={"content-type": "application/json", "x-private": "not-forwarded"},
                stream=_BytesStream(error_body),
            )
        ),
        upstream_base_url="http://lmstudio.test/v1",
    )

    with TestClient(app) as client:
        response = client.post("/v1/chat/completions", json={"model": "qwen38_23GB", "max_tokens": 12})

    assert response.status_code == 400
    assert response.headers["content-type"] == "application/json"
    assert "x-private" not in response.headers
    assert response.content == error_body


def test_proxy_closes_upstream_stream_when_client_disconnects(tmp_path: Path) -> None:
    async def exercise_disconnect() -> None:
        upstream_closed = asyncio.Event()
        first_chunk_sent = asyncio.Event()

        class PendingStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b"data: {\"choices\":[{\"delta\":{}}]}\n\n"
                await asyncio.Event().wait()

            async def aclose(self) -> None:
                upstream_closed.set()

        app = create_app(
            tmp_path / "outbound-params.jsonl",
            upstream_transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, stream=PendingStream())
            ),
            upstream_base_url="http://lmstudio.test/v1",
        )

        async with app.router.lifespan_context(app):
            sent_request = False

            async def receive():
                nonlocal sent_request
                if not sent_request:
                    sent_request = True
                    body = json.dumps({"model": "qwen38_23GB", "stream": True}).encode()
                    return {
                        "type": "http.request",
                        "body": body,
                        "more_body": False,
                    }
                await first_chunk_sent.wait()
                return {"type": "http.disconnect"}

            async def send(message):
                if message["type"] == "http.response.body" and message.get("body"):
                    first_chunk_sent.set()

            scope = {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.3"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/v1/chat/completions",
                "raw_path": b"/v1/chat/completions",
                "query_string": b"",
                "headers": [(b"content-type", b"application/json")],
                "client": ("127.0.0.1", 12345),
                "server": ("127.0.0.1", 1235),
            }

            await asyncio.wait_for(app(scope, receive, send), timeout=3)
            await asyncio.wait_for(upstream_closed.wait(), timeout=1)

    asyncio.run(exercise_disconnect())


def test_proxy_fails_closed_for_unexpected_model_and_noninference_path(tmp_path: Path) -> None:
    forwarded = 0

    def upstream(_request: httpx.Request) -> httpx.Response:
        nonlocal forwarded
        forwarded += 1
        return httpx.Response(200, json={"ok": True})

    app = create_app(
        tmp_path / "outbound-params.jsonl",
        upstream_transport=httpx.MockTransport(upstream),
        upstream_base_url="http://lmstudio.test/v1",
    )

    with TestClient(app) as client:
        wrong_model = client.post("/v1/chat/completions", json={"model": "other-model"})
        wrong_path = client.post("/v1/embeddings", json={"model": "qwen38_23GB"})

    assert wrong_model.status_code == 409
    assert wrong_path.status_code == 404
    assert forwarded == 0
    assert not (tmp_path / "outbound-params.jsonl").exists()
