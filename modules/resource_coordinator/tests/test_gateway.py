import asyncio
from types import SimpleNamespace
import pytest
import httpx
from starlette.applications import Starlette
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from resource_coordinator.adapters.lmstudio.gateway import LMStudioGateway, StreamCompletionDetector
from resource_coordinator.core.events import EventDispatcher, VetoOperation
from resource_coordinator.core.leases import LeaseManager, LeaseType


def test_recovery_accepts_configured_shared_operator_and_legacy_recovery_tokens(monkeypatch):
    gateway = LMStudioGateway(recovery_token="legacy-recovery-token")
    monkeypatch.setenv("RESOURCE_COORDINATOR_OPERATOR_TOKEN", "shared-operator-token")
    monkeypatch.delenv("RESOURCE_COORDINATOR_TOKEN_FILE", raising=False)

    assert gateway._recovery_authorized(
        SimpleNamespace(headers={"authorization": "Bearer shared-operator-token"})
    )
    assert gateway._recovery_authorized(
        SimpleNamespace(headers={"authorization": "Bearer legacy-recovery-token"})
    )
    assert not gateway._recovery_authorized(
        SimpleNamespace(headers={"authorization": "Bearer wrong-token"})
    )


def test_recovery_does_not_trust_an_insecure_shared_credential_file(tmp_path, monkeypatch):
    from resource_coordinator.core import operator_credentials

    path = tmp_path / "operator-token"
    path.write_text("E" * 64, encoding="ascii")
    monkeypatch.setenv("RESOURCE_COORDINATOR_TOKEN_FILE", str(path))
    monkeypatch.delenv("RESOURCE_COORDINATOR_OPERATOR_TOKEN", raising=False)
    monkeypatch.delenv("RESOURCE_COORDINATOR_RECOVERY_TOKEN", raising=False)
    monkeypatch.setattr(operator_credentials, "_acl_is_restricted", lambda _path: False)
    gateway = LMStudioGateway(standalone=True)

    assert "E" * 64 not in gateway._recovery_tokens()


def test_model_load_stream_requires_documented_terminal_event():
    detector = StreamCompletionDetector(operation_type="model_load")
    detector.feed(b'data: {"type":"model_load.progress","progress":0.75}\n\n')
    assert detector.finalize() is False

    detector.feed(b'data: {"type":"model_load.end","status":"loaded","instance_id":"inst-1"}\n\n')
    assert detector.finalize() is True


def test_synchronous_model_load_requires_loaded_status_and_instance_identifier():
    assert StreamCompletionDetector.check_non_streaming(
        200,
        b'{"status":"loaded","instance_id":"inst-1"}',
        "/api/v1/models/load",
    )
    assert not StreamCompletionDetector.check_non_streaming(
        200,
        b'{"status":"loaded","model":"qwen38"}',
        "/api/v1/models/load",
    )


@pytest.mark.parametrize(
    "frames",
    [
        b'data: {"type":"model_load.progress","progress":1.0}\n\n',
        b'data: {"type":"model_load.end"',
        b'data: [DONE]\n\n',
    ],
)
def test_model_load_stream_rejects_partial_error_or_inference_terminal_frames(frames):
    detector = StreamCompletionDetector(operation_type="model_load")
    detector.feed(frames)
    assert detector.finalize() is False


def test_model_load_failure_end_is_terminal_but_not_successful():
    detector = StreamCompletionDetector(operation_type="model_load")
    detector.feed(b'data: {"type":"model_load.end","status":"failed","error":"load failed"}\n\n')

    assert detector.finalize() is True
    assert detector.termination_state == "verified_model_load_failure"


@pytest.mark.asyncio
async def test_status_exposes_durable_recovery_request_details(tmp_path):
    from resource_coordinator.core.durable_state import RequestPhase, StateCodec

    journal = tmp_path / "coordinator-state.json"
    StateCodec.initialize(journal)
    StateCodec.record_request_phase(
        journal,
        "coord-test-timeout",
        "gpu.inference",
        RequestPhase.UNCERTAIN,
        model="test-model",
        path="/api/v1/models/load",
        details={
            "operation_type": "model_load",
            "terminal_evidence": "upstream_execution_uncertain",
            "configured_timeout_seconds": 0.1,
            "prompt": "private diagnostic prompt",
        },
    )
    gateway = LMStudioGateway(state_persistence_path=str(journal))
    await gateway.lease_mgr.inhibit_restart(
        "gpu.inference",
        "upstream_read_timeout",
        "coord-test-timeout",
        {"request_id": "coord-test-timeout"},
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway.create_app()), base_url="http://gateway"
    ) as client:
        response = await client.get("/_coordinator/status")

    assert response.status_code == 200
    recovery = response.json()["gpu_inference"]["recovery"]
    assert recovery["required"] is True
    assert recovery["journal_status"] == "available"
    assert recovery["requests"][0]["request_id"] == "coord-test-timeout"
    assert recovery["requests"][0]["details"]["terminal_evidence"] == "upstream_execution_uncertain"
    assert "private diagnostic prompt" not in response.text
    await gateway.close()


@pytest.mark.asyncio
async def test_read_timeout_records_uncertain_operation_and_keeps_restart_inhibited(tmp_path):
    from resource_coordinator.core.durable_state import RequestPhase, StateCodec

    journal = tmp_path / "coordinator-state.json"
    StateCodec.initialize(journal)

    async def upstream(_request):
        raise httpx.ReadTimeout("sensitive upstream detail")

    gateway = LMStudioGateway(
        standalone=True,
        timeout_seconds=0.05,
        state_persistence_path=str(journal),
    )
    gateway._http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(upstream), base_url="http://mock-upstream"
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway.create_app()), base_url="http://gateway"
    ) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "test-model", "messages": [{"role": "user", "content": "private prompt"}]},
        )

    assert response.status_code == 502
    assert response.json()["error"]["type"] == "upstream_read_timeout"
    assert "may still be active" in response.json()["error"]["message"]
    assert "sensitive upstream detail" not in response.text
    assert "private prompt" not in response.text
    assert gateway.lease_mgr.is_restart_inhibited("gpu.inference") is True
    state = StateCodec.load(journal)
    request = next(iter(state.requests.values()))
    assert request.phase == RequestPhase.UNCERTAIN.value
    assert request.details["operation_type"] == "inference"
    assert request.details["timeout_phase"] == "upstream_read_timeout"
    assert request.details["terminal_evidence"] == "upstream_execution_uncertain"
    assert request.details["recovery_recommendation"]
    await gateway.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "frames,expect_restart",
    [
        (
            [
                b'data: {"type":"model_load.progress","progress":0.5}\n\n',
                b'data: {"type":"model_load.end","status":"loaded","instance_id":"i-1"}\n\n',
            ],
            True,
        ),
        ([b'data: {"type":"model_load.progress","progress":1.0}\n\n'], False),
        ([b'data: {"type":"model_load.end"'], False),
    ],
)
async def test_streaming_model_load_terminal_controls_fake_miner_restart(tmp_path, frames, expect_restart):
    from resource_coordinator.config import CoordinatorConfig, build_system
    from resource_coordinator.core.service import CoordinatorService

    config = CoordinatorConfig.from_dict(
        {
            "version": "1.0",
            "processes": {"krig": {"backend": "fake"}},
            "policies": [
                {
                    "name": "stop-for-inference",
                    "trigger_event": "lmstudio.inference_requested",
                    "target_process": "krig",
                    "resource": "gpu.inference",
                    "lease_type": "shared",
                    "cooldown_seconds": 0.02,
                },
                {
                    "name": "stop-for-model-load",
                    "trigger_event": "lmstudio.model_load_requested",
                    "target_process": "krig",
                    "resource": "gpu.inference",
                    "lease_type": "exclusive",
                    "cooldown_seconds": 0.02,
                }
            ],
        }
    )
    system = build_system(config, use_fake_processes=True)
    service = CoordinatorService(system, start_miner_on_ready=True)
    assert await service.start()
    backend = system.supervisors["krig"].backend

    async def load(_request):
        async def body():
            for frame in frames:
                yield frame

        return StreamingResponse(body(), media_type="text/event-stream")

    upstream = Starlette(routes=[Route("/api/v0/model/load", load, methods=["POST"])])
    system.gateway._http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=upstream), base_url="http://mock-lmstudio"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=system.gateway.create_app(service)), base_url="http://gateway"
    ) as client:
        response = await client.post("/api/v0/model/load", json={"model": "test-model"})

    assert response.status_code == 200
    await asyncio.sleep(0.05)
    if expect_restart:
        assert not system.lease_mgr.is_restart_inhibited("gpu.inference")
        assert (await system.supervisors["krig"].status()).state.value == "running"
        assert backend.generation == 2
    else:
        assert system.lease_mgr.is_restart_inhibited("gpu.inference")
        assert (await system.supervisors["krig"].status()).state.value == "stopped"
    await service.stop()


@pytest.mark.asyncio
async def test_model_load_timeout_requires_operator_recovery_then_restarts_fake_miner_once(tmp_path):
    from resource_coordinator.config import CoordinatorConfig, build_system
    from resource_coordinator.core.durable_state import RequestPhase, StateCodec
    from resource_coordinator.core.processes import ProcessState
    from resource_coordinator.core.service import CoordinatorService

    journal = tmp_path / "coordinator-state.json"
    StateCodec.initialize(journal)
    config = CoordinatorConfig.from_dict(
        {
            "version": "1.0",
            "service": {"state_persistence_path": str(journal)},
            "processes": {"krig": {"backend": "fake"}},
            "policies": [
                {
                    "name": "stop-for-inference",
                    "trigger_event": "lmstudio.inference_requested",
                    "target_process": "krig",
                    "resource": "gpu.inference",
                    "lease_type": "shared",
                    "cooldown_seconds": 0.02,
                },
                {
                    "name": "stop-for-model-load",
                    "trigger_event": "lmstudio.model_load_requested",
                    "target_process": "krig",
                    "resource": "gpu.inference",
                    "lease_type": "exclusive",
                    "cooldown_seconds": 0.02,
                },
            ],
        }
    )
    system = build_system(config, use_fake_processes=True)
    system.gateway.recovery_token = "test-recovery-token"
    service = CoordinatorService(system, start_miner_on_ready=True, first_boot=True)
    assert await service.start()
    backend = system.supervisors["krig"].backend

    async def upstream(_request):
        raise httpx.ReadTimeout("private upstream diagnostic")

    system.gateway.timeout_seconds = 0.05
    system.gateway._http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(upstream), base_url="http://mock-lmstudio"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=system.gateway.create_app(service)), base_url="http://gateway"
    ) as client:
        response = await client.post("/api/v1/models/load", json={"model": "test-model"})
        assert response.status_code == 502
        assert response.json()["error"]["operation_type"] == "model_load"
        assert "private upstream diagnostic" not in response.text

        state = StateCodec.load(journal)
        request_id, request_record = next(iter(state.requests.items()))
        assert request_record.phase == RequestPhase.UNCERTAIN.value
        assert request_record.details["timeout_phase"] == "upstream_read_timeout"
        assert system.lease_mgr.is_restart_inhibited("gpu.inference")
        assert (await system.supervisors["krig"].status()).state == ProcessState.STOPPED
        await asyncio.sleep(0.06)
        assert system.lease_mgr.is_restart_inhibited("gpu.inference")
        assert (await system.supervisors["krig"].status()).state == ProcessState.STOPPED

        recovery = await client.post(
            "/_coordinator/recover?resource=gpu.inference",
            headers={"Authorization": "Bearer test-recovery-token"},
            json={"override": True, "operator": "test-operator", "reason": "Verified upstream idle"},
        )
        assert recovery.status_code == 200
        assert request_id in recovery.json()["resolved_request_ids"]
        assert recovery.json()["upstream_verified_idle"] is False

    resolved = StateCodec.load(journal).requests[request_id]
    assert resolved.phase == RequestPhase.OPERATOR_RESOLVED.value
    assert resolved.details["resolved_by"] == "operator_override:test-operator:Verified upstream idle"
    await asyncio.sleep(0.06)
    assert (await system.supervisors["krig"].status()).state == ProcessState.RUNNING
    assert backend.generation == 2
    await service.stop()


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
        return JSONResponse(
            {"id": "chat-123", "choices": [{"finish_reason": "stop", "message": {"content": "Hello World"}}]}
        )

    async def handle_error(request):
        return JSONResponse({"error": "Model overloaded"}, status_code=500)

    async def handle_load(request):
        body = await request.json()
        return JSONResponse({"status": "loaded", "instance_id": "loaded-instance", "model": body.get("model", "")})

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
        standalone=True,
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
        standalone=True,
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
async def test_standalone_gateway_model_load_is_rejected_even_with_stop_hook():
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
        resource="gpu.inference",
        lease_type=LeaseType.EXCLUSIVE,
        cooldown_seconds=0.1,
        after_release_actions=[StartProcessAction(supervisor=supervisor, only_if_stopped_by_coordinator=True)],
    )
    policy_engine.register_policy(policy)

    gateway = LMStudioGateway(
        standalone=True,
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

    # Without a managed service, the gateway cannot verify configured process
    # ownership and must reject the mutation even though a stop hook exists.
    resp = await client.post("/api/v0/model/load", json={"model": "qwen38_23GB"})
    assert resp.status_code == 503
    assert backend.running is True
    assert lease_mgr.active_count("gpu.inference") == 0


@pytest.mark.asyncio
async def test_managed_model_load_stops_process_before_upstream_forwarding():
    from resource_coordinator.config import CoordinatorConfig, build_system
    from resource_coordinator.core.service import CoordinatorService

    config = CoordinatorConfig.from_dict(
        {
            "version": "1.0",
            "processes": {"worker": {"backend": "fake"}},
            "policies": [
                {
                    "name": "stop-for-inference",
                    "trigger_event": "lmstudio.inference_requested",
                    "target_process": "worker",
                    "resource": "gpu.inference",
                    "lease_type": "shared",
                    "cooldown_seconds": 0.05,
                },
                {
                    "name": "stop-for-model-load",
                    "trigger_event": "lmstudio.model_load_requested",
                    "target_process": "worker",
                    "resource": "gpu.inference",
                    "lease_type": "exclusive",
                    "cooldown_seconds": 0.05,
                },
            ],
        }
    )
    system = build_system(config, use_fake_processes=True)
    supervisor = system.supervisors["worker"]
    await supervisor.start(only_if_stopped_by_coordinator=False)
    backend = supervisor.backend
    service = CoordinatorService(system)
    assert await service.start()

    state_at_forward = []

    async def load(request):
        state_at_forward.append(backend.running)
        return JSONResponse({"status": "loaded", "instance_id": "loaded-instance", "model": "test-model"})

    upstream = Starlette(routes=[Route("/api/v0/model/load", load, methods=["POST"])])
    system.gateway._http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=upstream),
        base_url="http://mock-lmstudio",
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=system.gateway.create_app(service)), base_url="http://gateway"
    )

    response = await client.post("/api/v0/model/load", json={"model": "test-model"})
    assert response.status_code == 200
    assert state_at_forward == [False]
    assert system.lease_mgr.is_cooling_down("gpu.inference")
    await asyncio.sleep(0.08)
    assert (await supervisor.status()).state.value == "running"
    assert backend.generation == 2
    await service.stop()
