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


def test_gateway_rejects_oversized_request_before_upstream_forwarding():
    store = LiveInferenceStore()
    gateway = OpenAIInferenceGateway("http://127.0.0.1:1234", store, RequestEventHub(), client=httpx.AsyncClient(transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(AssertionError("must not forward")))))
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(gateway.router())
    with TestClient(app) as test_client:
        result = test_client.post("/v1/chat/completions", content=b"{}", headers={"content-length": str(MAX_REQUEST_BYTES + 1)})
    assert result.status_code == 413
    assert store.requests() == ()
