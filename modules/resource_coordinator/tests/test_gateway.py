import asyncio
import pytest
import httpx
from starlette.applications import Starlette
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from resource_coordinator.adapters.lmstudio.gateway import LMStudioGateway
from resource_coordinator.core.events import EventDispatcher, VetoOperation
from resource_coordinator.core.leases import LeaseManager, LeaseType


def create_mock_upstream_app(gateway: LMStudioGateway):
    async def handle_models(request):
        return JSONResponse({"data": [{"id": "qwen38", "object": "model"}]})

    active_during_stream = []

    async def handle_chat(request):
        body = await request.json()
        if body.get("stream"):

            async def event_generator():
                active_during_stream.append(gateway.lease_mgr.active_count("gpu.inference"))
                yield b'data: {"choices": [{"delta": {"content": "Hello"}}]}\n\n'
                await asyncio.sleep(0.02)
                yield b'data: {"choices": [{"delta": {"content": " World"}}]}\n\n'
                yield b"data: [DONE]\n\n"

            return StreamingResponse(event_generator(), media_type="text/event-stream")
        return JSONResponse({"id": "chat-123", "choices": [{"message": {"content": "Hello World"}}]})

    async def handle_error(request):
        return JSONResponse({"error": "Model overloaded"}, status_code=500)

    async def handle_load(request):
        body = await request.json()
        return JSONResponse({"status": "loaded", "model": body.get("model", "")})

    routes = [
        Route("/v1/models", handle_models, methods=["GET"]),
        Route("/v1/chat/completions", handle_chat, methods=["POST"]),
        Route("/v1/error", handle_error, methods=["POST"]),
        Route("/api/v0/model/load", handle_load, methods=["POST"]),
    ]
    return Starlette(routes=routes), active_during_stream


@pytest.fixture
def mock_gateway():
    dispatcher = EventDispatcher()
    lease_mgr = LeaseManager(default_cooldown_seconds=0.1, event_dispatcher=dispatcher)

    gateway = LMStudioGateway(
        upstream_url="http://mock-lmstudio",
        event_dispatcher=dispatcher,
        lease_manager=lease_mgr,
    )
    upstream_app, active_tracker = create_mock_upstream_app(gateway)
    gateway._active_tracker = active_tracker
    gateway._http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=upstream_app),
        base_url="http://mock-lmstudio",
    )
    return gateway


@pytest.mark.asyncio
async def test_gateway_metadata_bypasses_leases(mock_gateway):
    app = mock_gateway.create_app()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway")

    resp = await client.get("/v1/models")
    assert resp.status_code == 200
    assert resp.json()["data"][0]["id"] == "qwen38"

    # Metadata request must NOT acquire an inference lease or start cooldown
    assert mock_gateway.lease_mgr.active_count("gpu.inference") == 0
    assert mock_gateway.lease_mgr.is_cooling_down("gpu.inference") is False


@pytest.mark.asyncio
async def test_gateway_non_streaming_inference(mock_gateway):
    app = mock_gateway.create_app()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway")

    requested_events = []
    finished_events = []
    mock_gateway.dispatcher.on("lmstudio.inference_requested", lambda e: requested_events.append(e.data))
    mock_gateway.dispatcher.on("lmstudio.inference_finished", lambda e: finished_events.append(e.data))

    resp = await client.post(
        "/v1/chat/completions", json={"model": "qwen38", "messages": [{"role": "user", "content": "hi"}]}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["choices"][0]["message"]["content"] == "Hello World"
    assert "x-coordinator-request-id" in resp.headers

    # Events fired
    assert len(requested_events) == 1
    assert requested_events[0]["model"] == "qwen38"
    assert len(finished_events) == 1
    assert finished_events[0]["status"] == "completed"

    # Lease was held and released; cooldown started
    assert mock_gateway.lease_mgr.active_count("gpu.inference") == 0
    assert mock_gateway.lease_mgr.is_cooling_down("gpu.inference") is True


@pytest.mark.asyncio
async def test_gateway_streaming_inference(mock_gateway):
    app = mock_gateway.create_app()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway")

    chunks = []
    async with client.stream(
        "POST",
        "/v1/chat/completions",
        json={"model": "qwen38", "stream": True, "messages": [{"role": "user", "content": "hi"}]},
    ) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        async for chunk in resp.aiter_text():
            chunks.append(chunk)

    # During streaming, the lease must have been active!
    assert mock_gateway._active_tracker == [1]

    # After streaming completes, lease is released and cooldown starts
    assert mock_gateway.lease_mgr.active_count("gpu.inference") == 0
    assert mock_gateway.lease_mgr.is_cooling_down("gpu.inference") is True
    full_text = "".join(chunks)
    assert "Hello" in full_text
    assert "World" in full_text


@pytest.mark.asyncio
async def test_gateway_veto_rejects_with_503(mock_gateway):
    # Hook that vetos inference (e.g. miner failed to stop)
    async def veto_hook(event):
        raise VetoOperation("Could not stop competing miner process safely")

    mock_gateway.dispatcher.on("lmstudio.inference_requested", veto_hook, is_blocking=True)

    app = mock_gateway.create_app()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway")

    resp = await client.post("/v1/chat/completions", json={"model": "qwen38", "messages": []})
    assert resp.status_code == 503
    err_body = resp.json()
    assert "Could not stop competing miner" in err_body["error"]["message"]

    # Lease must never have been acquired
    assert mock_gateway.lease_mgr.active_count("gpu.inference") == 0


@pytest.mark.asyncio
async def test_gateway_coordinator_status_endpoint(mock_gateway):
    app = mock_gateway.create_app()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway")

    resp = await client.get("/_coordinator/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "online"
    assert "gpu_inference" in data


@pytest.mark.asyncio
async def test_gateway_concurrent_requests_share_stop():
    from resource_coordinator.core.actions import StartProcessAction, StopProcessAction
    from resource_coordinator.core.conditions import ProcessRunningCondition
    from resource_coordinator.core.policies import Policy, PolicyEngine
    from resource_coordinator.core.processes import FakeProcessBackend, ProcessSupervisor

    dispatcher = EventDispatcher()
    lease_mgr = LeaseManager(default_cooldown_seconds=0.1, event_dispatcher=dispatcher)
    policy_engine = PolicyEngine(event_dispatcher=dispatcher, lease_manager=lease_mgr)

    backend = FakeProcessBackend(name="krig", running=True)
    supervisor = ProcessSupervisor(backend=backend, event_dispatcher=dispatcher)

    # Register mining coordination policy
    policy = Policy(
        name="prioritize-local-inference",
        trigger_event="lmstudio.inference_requested",
        condition=ProcessRunningCondition(supervisor),
        actions=[StopProcessAction(supervisor=supervisor, wait_until_stopped=True)],
        resource="gpu.inference",
        cooldown_seconds=0.1,
        after_release_actions=[StartProcessAction(supervisor=supervisor, only_if_stopped_by_coordinator=True)],
    )
    policy_engine.register_policy(policy)

    gateway = LMStudioGateway(
        upstream_url="http://mock-lmstudio",
        event_dispatcher=dispatcher,
        lease_manager=lease_mgr,
    )
    upstream_app, _ = create_mock_upstream_app(gateway)
    gateway._http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=upstream_app),
        base_url="http://mock-lmstudio",
    )

    app = gateway.create_app()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway")

    # Initial state: miner is running
    assert backend.running is True

    # 3 concurrent inference requests
    req1 = client.post("/v1/chat/completions", json={"model": "qwen38", "messages": [{"role": "user", "content": "1"}]})
    req2 = client.post("/v1/chat/completions", json={"model": "qwen38", "messages": [{"role": "user", "content": "2"}]})
    req3 = client.post("/v1/chat/completions", json={"model": "qwen38", "messages": [{"role": "user", "content": "3"}]})

    resps = await asyncio.gather(req1, req2, req3)
    for r in resps:
        assert r.status_code == 200

    # During inference, miner was stopped
    assert backend.running is False

    # Leases are now released; cooldown started
    assert lease_mgr.active_count("gpu.inference") == 0
    assert lease_mgr.is_cooling_down("gpu.inference") is True

    # Wait for cooldown to expire
    await asyncio.sleep(0.15)

    # Miner has automatically resumed
    assert backend.running is True


@pytest.mark.asyncio
async def test_gateway_model_load_and_mining_resumption():
    from resource_coordinator.core.actions import StartProcessAction, StopProcessAction
    from resource_coordinator.core.conditions import ProcessRunningCondition
    from resource_coordinator.core.policies import Policy, PolicyEngine
    from resource_coordinator.core.processes import FakeProcessBackend, ProcessSupervisor

    dispatcher = EventDispatcher()
    lease_mgr = LeaseManager(default_cooldown_seconds=0.1, event_dispatcher=dispatcher)
    policy_engine = PolicyEngine(event_dispatcher=dispatcher, lease_manager=lease_mgr)

    backend = FakeProcessBackend(name="krig", running=True)
    supervisor = ProcessSupervisor(backend=backend, event_dispatcher=dispatcher)

    # Policy: stop miner during model load
    policy = Policy(
        name="stop-miner-on-model-load",
        trigger_event="lmstudio.model_load_requested",
        condition=ProcessRunningCondition(supervisor),
        actions=[StopProcessAction(supervisor=supervisor, wait_until_stopped=True)],
        resource="gpu.model_loading",
        lease_type=LeaseType.EXCLUSIVE,
        cooldown_seconds=0.1,
        after_release_actions=[StartProcessAction(supervisor=supervisor, only_if_stopped_by_coordinator=True)],
    )
    policy_engine.register_policy(policy)

    gateway = LMStudioGateway(
        upstream_url="http://mock-lmstudio",
        event_dispatcher=dispatcher,
        lease_manager=lease_mgr,
    )
    upstream_app, _ = create_mock_upstream_app(gateway)
    gateway._http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=upstream_app),
        base_url="http://mock-lmstudio",
    )

    app = gateway.create_app()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway")

    assert backend.running is True

    # Trigger model load
    resp = await client.post("/api/v0/model/load", json={"model": "qwen38_23GB"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "loaded"

    # Miner was stopped during load
    assert backend.running is False

    # Model load completed; model remains in memory; cooldown starts
    assert lease_mgr.is_cooling_down("gpu.model_loading") is True

    # Wait for cooldown to expire
    await asyncio.sleep(0.15)

    # Mining resumes even though the model is loaded!
    assert backend.running is True
