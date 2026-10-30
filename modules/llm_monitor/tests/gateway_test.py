import json
import asyncio
import time

import httpx
import pytest

from llm_monitor.gateway import MAX_REQUEST_BYTES, OpenAIInferenceGateway, RequestEventHub, _frame_boundary, _usage_payload, validate_gateway_upstream
from llm_monitor.live_store import LiveInferenceStore


def test_gateway_rejects_non_loopback_and_unpinned_upstreams():
    for endpoint in ("http://10.0.0.1:1234", "https://user:pass@127.0.0.1:1234", "http://127.0.0.1:1234/path", "http://127.0.0.1"):
        with pytest.raises(ValueError):
            validate_gateway_upstream(endpoint)
    assert validate_gateway_upstream("http://127.0.0.1:1234") == "http://127.0.0.1:1234"


def test_gateway_rejects_localhost_if_name_resolution_is_not_loopback(monkeypatch):
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("203.0.113.8", 1234))],
    )
    with pytest.raises(ValueError, match="resolved outside loopback"):
        validate_gateway_upstream("http://localhost:1234")


def test_gateway_rejects_non_json_content_and_cross_origin_browser_requests():
    from fastapi import HTTPException
    from llm_monitor.gateway import _validate_gateway_request_headers

    with pytest.raises(HTTPException) as wrong_type:
        _validate_gateway_request_headers("text/plain", None, "none", "http://127.0.0.1:8788")
    assert wrong_type.value.status_code == 415
    with pytest.raises(HTTPException) as cross_origin:
        _validate_gateway_request_headers("application/json", "https://attacker.example", "cross-site", "http://127.0.0.1:8788")
    assert cross_origin.value.status_code == 403
    _validate_gateway_request_headers("application/json", None, "none", "http://127.0.0.1:8788")


@pytest.mark.asyncio
async def test_stream_is_byte_exact_and_forwards_before_sse_frame_finishes():
    class ChunkStream(httpx.AsyncByteStream):
        def __init__(self, chunks):
            self.chunks = chunks

        async def __aiter__(self):
            for chunk in self.chunks:
                yield chunk

        async def aclose(self):
            return None

    store = LiveInferenceStore()
    hub = RequestEventHub()
    gateway = OpenAIInferenceGateway("http://127.0.0.1:1234", store, hub)
    identity = {"request_id": "large-frame", "server_instance_id": "server"}
    from llm_monitor.inference_models import InferenceRequest

    store.add_request(InferenceRequest(request_id="large-frame", server_instance_id="server", source="gateway", state="active"))
    first = b"data: {\"choices\":[{\"delta\":{\"content\":\"" + b"x" * 100_000
    second = b"y\"}}]}\r\n\r\n"
    upstream = httpx.Response(
        200,
        stream=ChunkStream([first, second]),
        request=httpx.Request("POST", "http://127.0.0.1:1234/v1/chat/completions"),
    )
    iterator = gateway._stream(upstream, "large-frame", identity, time.monotonic(), "start")
    delivered = bytearray()
    first_downstream = await asyncio.wait_for(anext(iterator), timeout=3)
    assert first_downstream != first + second
    delivered.extend(first_downstream)
    async for chunk in iterator:
        delivered.extend(chunk)
    assert bytes(delivered) == first + second
    assert store.requests()[0].state == "completed"


@pytest.mark.asyncio
async def test_stream_marks_midstream_upstream_failure_and_emits_client_error_frame():
    class BrokenStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"data: {\"choices\":[]}\n\n"
            raise httpx.ReadError("synthetic disconnect")

        async def aclose(self):
            return None

    store = LiveInferenceStore()
    from llm_monitor.inference_models import InferenceRequest

    store.add_request(InferenceRequest(request_id="broken", server_instance_id="server", source="gateway", state="active"))
    gateway = OpenAIInferenceGateway("http://127.0.0.1:1234", store, RequestEventHub())
    upstream = httpx.Response(200, stream=BrokenStream(), request=httpx.Request("POST", "http://127.0.0.1:1234/v1/chat/completions"))
    iterator = gateway._stream(upstream, "broken", {"request_id": "broken"}, time.monotonic(), "start")
    first = await anext(iterator)
    assert first == b"data: {\"choices\":[]}\n\n"
    failure = await anext(iterator)
    assert b'"type":"gateway_upstream_error"' in failure
    with pytest.raises(StopAsyncIteration):
        await anext(iterator)
    assert store.requests()[0].state == "failed"


@pytest.mark.asyncio
async def test_nonstream_upstream_error_body_interruption_is_not_reported_as_success():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    class BrokenBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"partial-error"
            raise httpx.ReadError("synthetic error-body disconnect")

        async def aclose(self):
            return None

    store = LiveInferenceStore()

    async def upstream(request):
        return httpx.Response(502, stream=BrokenBody(), request=request)

    gateway = OpenAIInferenceGateway(
        "http://127.0.0.1:1234",
        store,
        RequestEventHub(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(upstream)),
    )
    app = FastAPI()
    app.include_router(gateway.router())
    with TestClient(app) as test_client:
        response = test_client.post("/v1/chat/completions", json={"model": "m", "messages": []})
    assert response.status_code == 502
    assert store.requests()[0].state == "failed"


@pytest.mark.asyncio
async def test_minimal_forwarding_mode_does_not_publish_or_capture_requests():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    async def upstream(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    store = LiveInferenceStore()
    hub = RequestEventHub()
    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    gateway = OpenAIInferenceGateway("http://127.0.0.1:1234", store, hub, client=client, capture_enabled=False)
    app = FastAPI()
    app.include_router(gateway.router())
    with TestClient(app) as test_client:
        response = test_client.post("/v1/chat/completions", json={"model": "m", "messages": [{"role": "user", "content": "synthetic"}]})
    assert response.status_code == 200
    assert store.requests() == ()
    assert hub.sequence == 0


def test_frame_boundary_accepts_mixed_lf_and_crlf_delimiters():
    from llm_monitor.gateway import _frame_boundary

    assert _frame_boundary(bytearray(b"data: one\r\n\ndata: two\n\r\n")) == len(b"data: one\r\n\n")


@pytest.mark.asyncio
async def test_gateway_timing_sink_contains_boundaries_but_no_request_content():
    from fastapi import FastAPI

    timings = []

    async def upstream(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "secret-output"}}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    gateway = OpenAIInferenceGateway("http://127.0.0.1:1234", LiveInferenceStore(), RequestEventHub(), client=client, timing_sink=timings.append)
    app = FastAPI()
    app.include_router(gateway.router())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as test_client:
        response = await test_client.post(
            "/v1/chat/completions",
            json={"model": "test-model", "messages": [{"role": "user", "content": "secret-input"}]},
        )
    assert response.status_code == 200
    assert len(timings) == 1
    assert {"request_received_ms", "body_read_ms", "normalization_ms", "upstream_headers_ms", "body_complete_ms", "finalization_ms"} <= set(timings[0])
    assert "secret-input" not in repr(timings[0])
    assert "secret-output" not in repr(timings[0])


def test_sse_frame_boundary_accepts_fragmented_lf_and_crlf():
    partial = bytearray(b"data: {\"choices\":[] }\r\n\r")
    assert _frame_boundary(partial) is None
    partial.extend(b"\n")
    assert _frame_boundary(partial) == len(partial)


def test_usage_does_not_guess_visible_output_tokens_when_reasoning_is_in_completion_total():
    usage = _usage_payload({"prompt_tokens": 8, "completion_tokens": 10, "completion_tokens_details": {"reasoning_tokens": 10}})
    assert usage == {"input_tokens": 8, "reasoning_tokens": 10, "output_tokens": None, "generated_tokens": 10}


def test_malformed_sse_is_forwardable_but_marks_a_gap_and_unsupported_reasoning_is_ignored():
    gateway = OpenAIInferenceGateway("http://127.0.0.1:1234", LiveInferenceStore(), RequestEventHub())
    gateway._capture_sse("r", {"request_id": "r"}, b'data: {broken json}\n\n')
    assert gateway.events.sequence == 1
    gateway._capture_sse("r", {"request_id": "r"}, b'data: {"choices":[{"delta":{"reasoning":"unsupported field"}}]}\n\n')
    assert gateway.events.sequence == 1


@pytest.mark.asyncio
async def test_client_cancellation_closes_upstream_and_marks_request_cancelled():
    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"first"}}]}\n\n'
            await asyncio.Event().wait()

        async def aclose(self):
            return None

    store = LiveInferenceStore()
    hub = RequestEventHub()
    gateway = OpenAIInferenceGateway("http://127.0.0.1:1234", store, hub)
    from llm_monitor.inference_models import InferenceRequest

    identity = {"request_id": "cancel-me", "server_instance_id": "s"}
    store.add_request(InferenceRequest(request_id="cancel-me", server_instance_id="s", source="gateway", state="active"))
    upstream = httpx.Response(200, stream=SlowStream(), request=httpx.Request("POST", "http://127.0.0.1:1234/v1/chat/completions"))
    iterator = gateway._stream(upstream, "cancel-me", identity, time.monotonic(), "start")
    assert b"first" in await anext(iterator)
    task = asyncio.create_task(anext(iterator))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert store.requests()[0].state == "cancelled"


@pytest.mark.asyncio
async def test_observer_queues_are_bounded_and_signal_overflow():
    hub = RequestEventHub(queue_size=1, max_observers=1)
    stream = hub.subscribe()
    waiter = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    hub.publish({"type": "first", "request": {"request_id": "r"}})
    assert (await waiter)["type"] == "first"
    hub.publish({"type": "second", "request": {"request_id": "r"}})
    hub.publish({"type": "third", "request": {"request_id": "r"}})
    assert (await anext(stream))["type"] == "telemetry.gap"
    other = hub.subscribe()
    with pytest.raises(RuntimeError, match="observer_capacity"):
        await anext(other)
    await stream.aclose()


def test_sse_events_capture_reasoning_output_usage_and_per_request_sequences():
    store = LiveInferenceStore()
    hub = RequestEventHub()
    gateway = OpenAIInferenceGateway("http://127.0.0.1:1234", store, hub)
    identity = {"request_id": "request-a", "server_instance_id": "server", "model_instance_id": "model"}
    from llm_monitor.inference_models import InferenceRequest

    store.add_request(InferenceRequest(request_id="request-a", server_instance_id="server", source="gateway", state="active"))
    gateway._capture_sse("request-a", identity, b'data: {"choices":[{"delta":{"reasoning_content":"plan"}}]}\n\n')
    gateway._capture_sse("request-a", identity, b'data: {"choices":[{"delta":{"reasoning_content":" more"}}]}\n\n')
    gateway._capture_sse("request-a", identity, b'data: {"choices":[{"delta":{"content":"answer"},"finish_reason":"stop"}],"usage":{"prompt_tokens":3,"completion_tokens":2}}\n\n')
    segments = store.requests()[0].content
    assert [(item.kind, item.text) for item in segments] == [("reasoning", "plan more"), ("assistant", "answer")]
    assert segments[0].sequence == 2
    pair = (hub.publish({"type": "a", "request": identity}), hub.publish({"type": "b", "request": identity}))
    assert pair[1]["sequence"] == pair[0]["sequence"] + 1
    assert store.requests()[0].input_tokens == 3
    assert store.requests()[0].output_tokens == 2


@pytest.mark.asyncio
async def test_nonstreaming_request_is_forwarded_and_captured():
    store = LiveInferenceStore()
    hub = RequestEventHub()

    async def upstream(request):
        payload = json.loads(request.content)
        assert payload["messages"][0]["content"] == "synthetic"
        return httpx.Response(200, json={"id": "provider-id", "choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    gateway = OpenAIInferenceGateway("http://127.0.0.1:1234", store, hub, client=client)
    # Exercise the production route through ASGI while the upstream is isolated in MockTransport.
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(gateway.router())
    with TestClient(app) as test_client:
        response = test_client.post("/v1/chat/completions", json={"model": "m", "stream": False, "messages": [{"role": "user", "content": "synthetic"}]})
    assert response.status_code == 200
    assert response.json()["id"] == "provider-id"
    assert len(store.requests()) == 1
    assert store.requests()[0].state == "completed"
    assert store.requests()[0].content[-1].text == "ok"


@pytest.mark.asyncio
async def test_concurrent_requests_keep_inputs_and_outputs_isolated():
    from fastapi import FastAPI

    async def upstream(request):
        payload = json.loads(request.content)
        value = payload["messages"][0]["content"]
        return httpx.Response(
            200,
            json={"id": f"provider-{value}", "choices": [{"message": {"content": f"reply-{value}"}}]},
            request=request,
        )

    store = LiveInferenceStore()
    gateway = OpenAIInferenceGateway(
        "http://127.0.0.1:1234",
        store,
        RequestEventHub(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(upstream)),
    )
    app = FastAPI()
    app.include_router(gateway.router())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        responses = await asyncio.gather(*(
            client.post("/v1/chat/completions", json={"model": "m", "messages": [{"role": "user", "content": value}]})
            for value in ("alpha", "beta")
        ))

    assert [response.status_code for response in responses] == [200, 200]
    requests = {request.provider_request_id: request for request in store.requests()}
    assert set(requests) == {"provider-alpha", "provider-beta"}
    assert requests["provider-alpha"].content[0].text == "alpha"
    assert requests["provider-alpha"].content[-1].text == "reply-alpha"
    assert requests["provider-beta"].content[0].text == "beta"
    assert requests["provider-beta"].content[-1].text == "reply-beta"


def test_gateway_rejects_oversized_request_before_upstream_forwarding():
    store = LiveInferenceStore()
    gateway = OpenAIInferenceGateway("http://127.0.0.1:1234", store, RequestEventHub(), client=httpx.AsyncClient(transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(AssertionError("must not forward")))))
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(gateway.router())
    with TestClient(app) as test_client:
        result = test_client.post("/v1/chat/completions", content=b"{}", headers={"content-type": "application/json", "content-length": str(MAX_REQUEST_BYTES + 1)})
    assert result.status_code == 413
    assert store.requests() == ()
