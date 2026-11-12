import asyncio
import json
import time
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

    detector.feed(
        b'data: {"type":"model_load.end","model_instance_id":"inst-1","load_time_seconds":12.3}\n\n'
    )
    assert detector.finalize() is True
    assert detector.model_load_reported_seconds == 12.3


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


def test_model_load_end_with_failure_shape_is_not_documented_terminal_evidence():
    detector = StreamCompletionDetector(operation_type="model_load")
    detector.feed(b'data: {"type":"model_load.end","status":"failed","error":"load failed"}\n\n')

    assert detector.finalize() is False
    assert detector.termination_state != "verified_model_load_failure"


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "model_load.end"},
        {"type": "model_load.end", "model_instance_id": "i-1"},
        {"type": "model_load.end", "model_instance_id": "", "load_time_seconds": 1.0},
        {"type": "model_load.end", "model_instance_id": "i-1", "load_time_seconds": -1.0},
        {"type": "model_load.end", "model_instance_id": "i-1", "load_time_seconds": float("nan")},
    ],
)
def test_model_load_end_requires_documented_success_fields(payload):
    detector = StreamCompletionDetector(operation_type="model_load")
    detector.feed(f"data: {json.dumps(payload)}\n\n".encode())
    assert detector.finalize() is False


@pytest.mark.parametrize(
    "trailing_data",
    [
        b'data: {"type":"error","error":{"message":"later failure"}}\n\n',
        b'data: {"type":"prompt_processing.start"',
    ],
)
def test_model_load_end_followed_by_error_or_truncation_is_not_clean_completion(trailing_data):
    detector = StreamCompletionDetector(operation_type="model_load")
    detector.feed(b'data: {"type":"model_load.end","model_instance_id":"i-1","load_time_seconds":3.1}\n\n')
    detector.feed(trailing_data)
    assert detector.finalize() is False


def test_model_load_end_is_not_terminal_for_inference_and_chat_end_requires_clean_frame():
    detector = StreamCompletionDetector(operation_type="inference")
    detector.feed(b'data: {"type":"model_load.end","status":"loaded","instance_id":"i-1"}\n\n')
    assert detector.finalize() is False
    assert detector.termination_state == "active"

    detector.feed(b'data: {"type":"prompt_processing.start"}\n\n')
    detector.feed(b'data: {"type":"chat.end","result":{"output":[{"type":"text","content":"ok"}]}}\n\n')
    assert detector.finalize() is True
    assert detector.termination_state == "confirmed_chat_end"


@pytest.mark.parametrize(
    "frames",
    [
        [b'data: {"type":"model_load.end","status":"loaded"}\n\n', b'data: {"type":"error"}\n\n'],
        [b'data: {"type":"chat.end","result":{"output":[]}'],
        [b'data: {"type":"prompt_processing.start"}\n\n'],
    ],
)
def test_inference_rejects_load_end_error_and_incomplete_chat_terminal(frames):
    detector = StreamCompletionDetector(operation_type="inference")
    for frame in frames:
        detector.feed(frame)
    assert detector.finalize() is False


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
async def test_stream_read_timeout_is_classified_as_inactivity_and_persisted(tmp_path):
    from resource_coordinator.core.durable_state import RequestPhase, StateCodec

    class ReadTimeoutStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
            raise httpx.ReadTimeout("private read-timeout detail")

        async def aclose(self):
            return None

    journal = tmp_path / "coordinator-state.json"
    StateCodec.initialize(journal)

    async def upstream(_request):
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=ReadTimeoutStream(),
        )

    gateway = LMStudioGateway(standalone=True, state_persistence_path=str(journal))
    gateway._http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(upstream), base_url="http://mock-lmstudio"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway.create_app(), raise_app_exceptions=False),
        base_url="http://gateway",
    ) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "test-model", "stream": True, "messages": [{"role": "user", "content": "hi"}]},
        )

    assert response.status_code == 200
    request_id = response.headers["x-coordinator-request-id"]
    record = StateCodec.load(journal).requests[request_id]
    assert record.phase == RequestPhase.UNCERTAIN.value
    assert record.details["failure_kind"] == "upstream_read_timeout"
    assert record.details["timeout_phase"] == "upstream_read_timeout"
    assert gateway.lease_mgr.is_restart_inhibited("gpu.inference")
    assert "private read-timeout detail" not in response.text
    await gateway.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "frames,expect_restart",
    [
        (
            [
                b'data: {"type":"model_load.progress","progress":0.5}\n\n',
                b'data: {"type":"model_load.end","model_instance_id":"i-1","load_time_seconds":12.3}\n\n',
            ],
            True,
        ),
        ([b'data: {"type":"model_load.progress","progress":1.0}\n\n'], False),
        ([b'data: {"type":"model_load.end"'], False),
    ],
)
async def test_streaming_model_load_terminal_controls_fake_miner_restart(tmp_path, frames, expect_restart):
    from resource_coordinator.config import CoordinatorConfig, build_system
    from resource_coordinator.core.durable_state import StateCodec
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
    record = next(iter(StateCodec.load(journal).requests.values()))
    assert record.details["outcome"] == ("succeeded" if expect_restart else "execution_uncertain")
    assert record.details["model_load_reported_seconds"] == (12.3 if expect_restart else None)
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
async def test_compatible_loaded_model_is_reused_without_stopping_fake_miner(tmp_path):
    from resource_coordinator.config import CoordinatorConfig, build_system
    from resource_coordinator.core.processes import ProcessState
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
                    "cooldown_seconds": 0.01,
                },
                {
                    "name": "stop-for-model-load",
                    "trigger_event": "lmstudio.model_load_requested",
                    "target_process": "krig",
                    "resource": "gpu.inference",
                    "lease_type": "exclusive",
                    "cooldown_seconds": 0.01,
                }
            ],
        }
    )
    system = build_system(config, use_fake_processes=True)
    service = CoordinatorService(system, start_miner_on_ready=True)
    assert await service.start()
    backend = system.supervisors["krig"].backend
    seen = []

    async def upstream(request):
        seen.append(request.url.path)
        if request.method == "GET" and request.url.path == "/api/v1/models":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "key": "test-model",
                            "loaded_instances": [
                                {"id": "instance-1", "config": {"context_length": 8192}}
                            ],
                        }
                    ]
                },
            )
        raise AssertionError(f"Compatible model should be reused, got {request.method} {request.url.path}")

    system.gateway._http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(upstream), base_url="http://mock-lmstudio"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=system.gateway.create_app(service)), base_url="http://gateway"
    ) as client:
        response = await client.post(
            "/api/v1/models/load", json={"model": "test-model", "context_length": 8192}
        )

    assert response.status_code == 200
    assert response.json()["status"] == "loaded"
    assert response.json()["instance_id"] == "instance-1"
    assert response.headers["x-coordinator-model-instance-reused"] == "true"
    assert seen == ["/api/v1/models"]
    assert system.lease_mgr.active_count("gpu.inference") == 0
    assert (await system.supervisors["krig"].status()).state == ProcessState.RUNNING
    assert backend.generation == 1
    await service.stop()


@pytest.mark.asyncio
async def test_loaded_model_reuse_requires_positive_configuration_match():
    from resource_coordinator.adapters.lmstudio.gateway import LMStudioGateway

    async def upstream(_request):
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "key": "test-model",
                        "loaded_instances": [
                            {"id": "instance-1", "config": {"context_length": 8192, "flash_attention": True}}
                        ],
                    }
                ]
            },
        )

    gateway = LMStudioGateway(standalone=True)
    gateway._http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(upstream), base_url="http://mock-lmstudio"
    )
    assert await gateway._compatible_loaded_instance(
        b'{"model":"test-model","context_length":8192,"flash_attention":true}'
    ) == "instance-1"
    assert await gateway._compatible_loaded_instance(
        b'{"model":"test-model","context_length":16384,"flash_attention":true}'
    ) is None
    assert await gateway._compatible_loaded_instance(b'{"model":"test-model"}') is None
    assert await gateway._compatible_loaded_instance(
        b'{"model":"test-model","context_length":8192,"unverified_option":true}'
    ) is None
    await gateway.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [400, 500, 502])
async def test_unclassified_model_load_http_errors_remain_uncertain(status_code, tmp_path):
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
                    "cooldown_seconds": 0.01,
                },
                {
                    "name": "stop-for-model-load",
                    "trigger_event": "lmstudio.model_load_requested",
                    "target_process": "krig",
                    "resource": "gpu.inference",
                    "lease_type": "exclusive",
                    "cooldown_seconds": 0.01,
                },
            ],
        }
    )
    system = build_system(config, use_fake_processes=True)
    service = CoordinatorService(system, start_miner_on_ready=True)
    assert await service.start()
    backend = system.supervisors["krig"].backend
    upstream_requests = []

    async def upstream(_request):
        upstream_requests.append(_request.url.path)
        return httpx.Response(status_code, json={"error": "backend rejected load"})

    system.gateway._http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(upstream), base_url="http://mock-lmstudio"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=system.gateway.create_app(service)), base_url="http://gateway"
    ) as client:
        response = await client.post("/api/v1/models/load", json={"model": "test-model"})

    assert response.status_code == status_code
    assert system.lease_mgr.is_restart_inhibited("gpu.inference")
    assert (await system.supervisors["krig"].status()).state == ProcessState.STOPPED
    assert backend.generation == 1
    record = next(iter(StateCodec.load(journal).requests.values()))
    assert record.phase == RequestPhase.UNCERTAIN.value
    assert record.details["terminal_evidence"] == "non_streaming_response_not_terminal"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=system.gateway.create_app(service)), base_url="http://gateway"
    ) as client:
        retry = await client.post("/api/v1/models/load", json={"model": "test-model"})
        inference_retry = await client.post(
            "/v1/chat/completions", json={"model": "test-model", "messages": [{"role": "user", "content": "hi"}]}
        )
    assert retry.status_code == 503
    assert retry.json()["error"]["type"] == "recovery_required"
    assert inference_retry.status_code == 503
    assert inference_retry.json()["error"]["type"] == "recovery_required"
    assert upstream_requests == ["/api/v1/models/load"]
    assert backend.generation == 1
    await service.stop()


@pytest.mark.asyncio
async def test_chat_model_load_end_does_not_release_inference_lease_before_chat_end():
    from resource_coordinator.config import CoordinatorConfig, build_system
    from resource_coordinator.core.processes import ProcessState
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
    observed = []

    async def chat(_request):
        async def events():
            yield b'data: {"type":"model_load.end","model_instance_id":"i-1","load_time_seconds":3.1}\n\n'
            observed.append(
                (
                    system.lease_mgr.active_count("gpu.inference"),
                    (await system.supervisors["krig"].status()).state,
                    system.lease_mgr.is_restart_inhibited("gpu.inference"),
                )
            )
            yield b'data: {"type":"prompt_processing.start"}\n\n'
            yield b'data: {"type":"message.delta","content":"answer"}\n\n'
            observed.append(
                (
                    system.lease_mgr.active_count("gpu.inference"),
                    (await system.supervisors["krig"].status()).state,
                    system.lease_mgr.is_restart_inhibited("gpu.inference"),
                )
            )
            yield b'data: {"type":"chat.end","result":{"output":[{"type":"text","content":"answer"}]}}\n\n'

        return StreamingResponse(events(), media_type="text/event-stream")

    upstream = Starlette(routes=[Route("/api/v1/chat", chat, methods=["POST"])])
    system.gateway._http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=upstream), base_url="http://mock-lmstudio"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=system.gateway.create_app(service)), base_url="http://gateway"
    ) as client:
        response = await client.post("/api/v1/chat", json={"model": "test-model", "stream": True})

    assert response.status_code == 200
    assert len(observed) == 2
    assert all(active == 1 for active, _, _ in observed)
    assert all(state == ProcessState.STOPPED for _, state, _ in observed)
    assert all(not inhibited for _, _, inhibited in observed)
    await asyncio.sleep(0.05)
    assert (await system.supervisors["krig"].status()).state == ProcessState.RUNNING
    assert backend.generation == 2
    await service.stop()


@pytest.mark.asyncio
async def test_slow_model_load_uses_separate_bounded_deadline():
    from resource_coordinator.config import CoordinatorConfig, build_system
    from resource_coordinator.core.service import CoordinatorService

    async def upstream(_request):
        await asyncio.sleep(0.08)
        return httpx.Response(200, json={"status": "loaded", "instance_id": "slow-load-1"})

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
    system.gateway.timeout_seconds = 0.02
    system.gateway.model_load_timeout_seconds = 0.3
    system.gateway._http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(upstream), base_url="http://mock-lmstudio"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=system.gateway.create_app(service)), base_url="http://gateway"
    ) as client:
        response = await client.post("/api/v1/models/load", json={"model": "test-model"})

    assert response.status_code == 200
    assert not system.lease_mgr.is_restart_inhibited("gpu.inference")
    await service.stop()


@pytest.mark.asyncio
async def test_real_httpx_model_load_read_timeout_and_runtime_measurements(tmp_path):
    from resource_coordinator.config import CoordinatorConfig, build_system
    from resource_coordinator.core.durable_state import RequestPhase, StateCodec
    from resource_coordinator.core.processes import ProcessState
    from resource_coordinator.core.service import CoordinatorService

    journal = tmp_path / "coordinator-state.json"
    StateCodec.initialize(journal)
    system_ref = {}
    upstream_observations = []

    async def upstream(reader, writer):
        try:
            headers = await reader.readuntil(b"\r\n\r\n")
            request_line = headers.split(b"\r\n", 1)[0]
            header_map = {
                line.split(b":", 1)[0].strip().lower(): line.split(b":", 1)[1].strip()
                for line in headers.split(b"\r\n")[1:]
                if b":" in line
            }
            body_length = int(header_map.get(b"content-length", b"0"))
            if body_length:
                await reader.readexactly(body_length)
            system = system_ref["system"]
            upstream_observations.append(
                {
                    "path": request_line.split(b" ")[1].decode("ascii"),
                    "active_leases": system.lease_mgr.active_count("gpu.inference"),
                    "miner_state": (await system.supervisors["krig"].status()).state,
                }
            )
            # Longer than the accelerated inference read timeout, with no response headers or bytes.
            await asyncio.sleep(0.2)
            payload = json.dumps(
                {
                    "status": "loaded",
                    "instance_id": "loopback-load-1",
                    "load_time_seconds": 0.2,
                }
            ).encode("utf-8")
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                + f"Content-Length: {len(payload)}\r\n".encode("ascii")
                + b"Connection: close\r\n\r\n"
                + payload
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(upstream, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    config = CoordinatorConfig.from_dict(
        {
            "version": "1.0",
            "service": {
                "upstream_url": f"http://127.0.0.1:{port}",
                "state_persistence_path": str(journal),
                "model_load_timeout_seconds": 0.4,
            },
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
    system_ref["system"] = system
    service = CoordinatorService(system, start_miner_on_ready=True)
    try:
        assert await service.start()
        recovery_events = []
        system.gateway.dispatcher.on(
            "resource_coordinator.recovery_required", lambda event: recovery_events.append(event.data)
        )
        # Accelerate the ordinary inference phase and lease timeout. The load-specific
        # request must still use its separately configured HTTPX timeout of 0.4 seconds.
        system.gateway.timeout_seconds = 0.1
        request_timeouts = []

        async def record_request_timeout(request):
            request_timeouts.append((request.url.path, dict(request.extensions["timeout"])))

        system.gateway.get_http_client().event_hooks["request"].append(record_request_timeout)
        backend = system.supervisors["krig"].backend

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=system.gateway.create_app(service)), base_url="http://gateway"
        ) as client:
            response = await client.post("/api/v1/models/load", json={"model": "test-model"})

        assert response.status_code == 200
        assert upstream_observations == [
            {"path": "/api/v1/models/load", "active_leases": 1, "miner_state": ProcessState.STOPPED}
        ]
        request_id = response.headers["x-coordinator-request-id"]
        timeout = request_timeouts[0][1]
        assert request_timeouts[0][0] == "/api/v1/models/load"
        assert timeout["connect"] == 10.0
        assert timeout["read"] == 0.4
        assert timeout["write"] == 0.4
        assert timeout["pool"] == 0.4

        record = StateCodec.load(journal).requests[request_id]
        assert record.phase == RequestPhase.TERMINAL_VERIFIED.value
        assert record.details["outcome"] == "succeeded"
        assert record.details["configured_timeout_seconds"] == 0.4
        assert record.details["lease_acquisition_timeout_seconds"] == 0.1
        assert record.details["connect_timeout_seconds"] == 10.0
        assert record.details["model_load_reported_seconds"] == 0.2
        assert record.details["upstream_elapsed_seconds"] >= 0.18
        assert recovery_events == []

        await asyncio.sleep(0.05)
        assert (await system.supervisors["krig"].status()).state == ProcessState.RUNNING
        assert backend.generation == 2
    finally:
        await service.stop()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_real_httpx_model_load_deadline_keeps_restart_inhibited(tmp_path):
    from resource_coordinator.config import CoordinatorConfig, build_system
    from resource_coordinator.core.durable_state import RequestPhase, StateCodec
    from resource_coordinator.core.processes import ProcessState
    from resource_coordinator.core.service import CoordinatorService

    journal = tmp_path / "coordinator-state.json"
    StateCodec.initialize(journal)

    async def upstream(_reader, writer):
        try:
            await writer.drain()
            await asyncio.sleep(0.2)
            payload = json.dumps({"status": "loaded", "instance_id": "late-load"}).encode("utf-8")
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                + f"Content-Length: {len(payload)}\r\n".encode("ascii")
                + b"Connection: close\r\n\r\n"
                + payload
            )
            try:
                await writer.drain()
            except ConnectionError:
                pass  # The client correctly timed out and closed its upstream connection.
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass

    server = await asyncio.start_server(upstream, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    config = CoordinatorConfig.from_dict(
        {
            "version": "1.0",
            "service": {
                "upstream_url": f"http://127.0.0.1:{port}",
                "state_persistence_path": str(journal),
                "model_load_timeout_seconds": 0.05,
            },
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
    service = CoordinatorService(system, start_miner_on_ready=True)
    try:
        assert await service.start()
        recovery_events = []
        system.gateway.dispatcher.on(
            "resource_coordinator.recovery_required", lambda event: recovery_events.append(event.data)
        )
        system.gateway.timeout_seconds = 0.01
        backend = system.supervisors["krig"].backend
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=system.gateway.create_app(service)), base_url="http://gateway"
        ) as client:
            response = await client.post("/api/v1/models/load", json={"model": "test-model"})

        assert response.status_code == 502
        assert response.json()["error"]["type"] in {"upstream_operation_deadline", "upstream_read_timeout"}
        assert system.lease_mgr.is_restart_inhibited("gpu.inference")
        assert (await system.supervisors["krig"].status()).state == ProcessState.STOPPED
        record = next(iter(StateCodec.load(journal).requests.values()))
        assert record.phase == RequestPhase.UNCERTAIN.value
        assert record.details["outcome"] == "execution_uncertain"
        assert record.details["configured_timeout_seconds"] == 0.05
        assert record.details["timeout_phase"] in {"overall_operation_deadline", "upstream_read_timeout"}
        assert len(recovery_events) == 1
        assert recovery_events[0]["request_id"] == response.json()["error"]["request_id"]
        assert recovery_events[0]["severity"] == "critical"
        assert recovery_events[0]["miner_state"] == "restart_inhibited"
        assert recovery_events[0]["event_key"].endswith(recovery_events[0]["request_id"])
        await asyncio.sleep(0.08)
        assert system.lease_mgr.is_restart_inhibited("gpu.inference")
        assert (await system.supervisors["krig"].status()).state == ProcessState.STOPPED
        assert backend.generation == 1
    finally:
        await service.stop()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_model_load_deadline_timeout_is_classified_and_keeps_restart_inhibited(tmp_path):
    from resource_coordinator.config import CoordinatorConfig, build_system
    from resource_coordinator.core.durable_state import RequestPhase, StateCodec
    from resource_coordinator.core.processes import ProcessState
    from resource_coordinator.core.service import CoordinatorService

    journal = tmp_path / "coordinator-state.json"
    StateCodec.initialize(journal)

    async def upstream(_request):
        await asyncio.sleep(0.2)
        return httpx.Response(200, json={"status": "loaded", "instance_id": "late-load"})

    config = CoordinatorConfig.from_dict(
        {
            "version": "1.0",
            "service": {
                "model_load_timeout_seconds": 0.04,
                "state_persistence_path": str(journal),
            },
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
    system.gateway.timeout_seconds = 0.2
    system.gateway._http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(upstream), base_url="http://mock-lmstudio"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=system.gateway.create_app(service)), base_url="http://gateway"
    ) as client:
        response = await client.post("/api/v1/models/load", json={"model": "test-model"})

    assert response.status_code == 502
    assert response.json()["error"]["type"] == "upstream_operation_deadline"
    assert response.json()["error"]["timeout_seconds"] == 0.04
    assert system.lease_mgr.is_restart_inhibited("gpu.inference")
    assert (await system.supervisors["krig"].status()).state == ProcessState.STOPPED
    request = next(iter(StateCodec.load(journal).requests.values()))
    assert request.phase == RequestPhase.UNCERTAIN.value
    assert request.details["failure_kind"] == "upstream_operation_deadline"
    assert request.details["timeout_phase"] == "overall_operation_deadline"
    await asyncio.sleep(0.05)
    assert system.lease_mgr.is_restart_inhibited("gpu.inference")
    assert (await system.supervisors["krig"].status()).state == ProcessState.STOPPED
    await service.stop()


@pytest.mark.asyncio
async def test_stream_response_deadline_covers_downstream_backpressure():
    from resource_coordinator.adapters.lmstudio.gateway import _CoordinatedStreamingResponse

    cleaned = []
    deadline_expired = []

    async def body():
        yield b"event"

    async def cleanup():
        cleaned.append(True)

    async def receive():
        await asyncio.Event().wait()

    async def send(_message):
        await asyncio.Event().wait()

    response = _CoordinatedStreamingResponse(
        body(),
        cleanup=cleanup,
        deadline=time.monotonic() + 0.03,
        deadline_callback=lambda: deadline_expired.append(True),
    )
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/models/load",
        "raw_path": b"/api/v1/models/load",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1),
        "server": ("127.0.0.1", 2),
    }

    with pytest.raises(asyncio.TimeoutError):
        await response(scope, receive, send)

    assert deadline_expired == [True]
    assert cleaned == [True]


@pytest.mark.asyncio
async def test_model_load_timeout_requires_operator_recovery_then_restarts_fake_miner_once(tmp_path, monkeypatch):
    from resource_coordinator.core import operator_credentials
    from resource_coordinator.config import CoordinatorConfig, build_system
    from resource_coordinator.core.durable_state import RequestPhase, StateCodec
    from resource_coordinator.core.processes import ProcessState
    from resource_coordinator.core.service import CoordinatorService

    journal = tmp_path / "coordinator-state.json"
    token_path = tmp_path / "operator-token"
    token = "T" * 64
    token_path.write_text(token, encoding="ascii")
    monkeypatch.setenv("RESOURCE_COORDINATOR_TOKEN_FILE", str(token_path))
    monkeypatch.delenv("RESOURCE_COORDINATOR_OPERATOR_TOKEN", raising=False)
    monkeypatch.delenv("RESOURCE_COORDINATOR_RECOVERY_TOKEN", raising=False)
    monkeypatch.setattr(operator_credentials, "_acl_is_restricted", lambda _path: True)
    StateCodec.initialize(journal)
    config = CoordinatorConfig.from_dict(
        {
            "version": "1.0",
            "service": {
                "state_persistence_path": str(journal),
                "model_load_timeout_seconds": 0.05,
            },
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
        assert response.json()["error"]["timeout_seconds"] == 0.05
        assert "private upstream diagnostic" not in response.text

        state = StateCodec.load(journal)
        request_id, request_record = next(iter(state.requests.items()))
        assert request_record.phase == RequestPhase.UNCERTAIN.value
        assert request_record.details["timeout_phase"] == "upstream_read_timeout"
        assert request_record.details["configured_timeout_seconds"] == 0.05
        assert system.lease_mgr.is_restart_inhibited("gpu.inference")
        assert (await system.supervisors["krig"].status()).state == ProcessState.STOPPED
        await asyncio.sleep(0.06)
        assert system.lease_mgr.is_restart_inhibited("gpu.inference")
        assert (await system.supervisors["krig"].status()).state == ProcessState.STOPPED

        recovery = await client.post(
            "/_coordinator/recover?resource=gpu.inference",
            headers={"Authorization": f"Bearer {token}"},
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
async def test_status_preserves_safe_diagnostics_and_all_sanitized_inhibition_holders(tmp_path):
    from resource_coordinator.core.durable_state import RequestPhase, StateCodec

    journal = tmp_path / "coordinator-state.json"
    StateCodec.initialize(journal)
    StateCodec.record_request_phase(
        journal, "request-safe-fields", "gpu.inference", RequestPhase.UNCERTAIN,
        details={"outcome": "timeout", "upstream_elapsed_seconds": 121.2,
                 "timeout_semantics": "read inactivity", "prompt": "must not leak"},
    )
    gateway = LMStudioGateway(state_persistence_path=str(journal))
    await gateway.lease_mgr.inhibit_restart(
        "gpu.inference", "primary uncertain request", "primary-holder",
        {"request_id": "request-safe-fields", "secret_payload": "nope"},
    )
    await gateway.lease_mgr.inhibit_restart(
        "gpu.inference", "secondary uncertain request", "secondary-holder",
        {"request_id": "secondary", "token": "nope"},
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway.create_app()), base_url="http://gateway"
    ) as client:
        response = await client.get("/_coordinator/status")
    assert response.status_code == 200
    body = response.json()
    inhibition = body["gpu_inference"]["inhibition"]
    assert inhibition["holder_id"] == "primary-holder"
    assert inhibition["details"]["additional_uncertain_holders"][0]["holder_id"] == "secondary-holder"
    request_details = body["gpu_inference"]["recovery"]["requests"][0]["details"]
    assert request_details["outcome"] == "timeout"
    assert request_details["upstream_elapsed_seconds"] == 121.2
    assert request_details["timeout_semantics"] == "read inactivity"
    assert "prompt" not in response.text and "secret_payload" not in response.text and "nope" not in response.text
    await gateway.close()


@pytest.mark.asyncio
async def test_inference_and_recovery_read_only_routes_are_available_without_managed_service():
    gateway = LMStudioGateway(standalone=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway.create_app()), base_url="http://gateway"
    ) as client:
        inference = await client.get("/_coordinator/inference/status")
        recovery = await client.get("/_coordinator/recovery/assessment")
    assert inference.status_code == recovery.status_code == 200
    assert inference.json()["classification"] == "unavailable"
    assert inference.json()["coverage"] == "unknown"
    assert recovery.json()["assessment_mode"] == "offline_diagnostic_only"
    assert recovery.json()["classification"] == "blocked"
    await gateway.close()


@pytest.mark.asyncio
async def test_lmstudio_observation_from_wrong_runtime_is_not_counted_as_coverage():
    from types import SimpleNamespace

    class Observer:
        async def observe(self, *, runtime_identity):
            return {"status": "available", "coverage": "complete", "observed_at": time.time(),
                    "runtime_identity": {"runtime_revision": "other-instance"}}

    service = SimpleNamespace(runtime_identity={"runtime_revision": "configured-instance"},
                               lmstudio_activity_observer=Observer())

    result = await LMStudioGateway._lmstudio_activity_observation(service)

    assert result == {"status": "unavailable", "reason_code": "observer_runtime_identity_mismatch"}


@pytest.mark.asyncio
async def test_lmstudio_observation_requires_valid_coverage_and_timestamp():
    from types import SimpleNamespace

    class Observer:
        async def observe(self, *, runtime_identity):
            return {"status": "available", "coverage": "complete", "runtime_identity": runtime_identity}

    service = SimpleNamespace(runtime_identity={"runtime_revision": "configured-instance"},
                               lmstudio_activity_observer=Observer())

    result = await LMStudioGateway._lmstudio_activity_observation(service)

    assert result == {"status": "unavailable", "reason_code": "observer_observation_metadata_missing"}


@pytest.mark.asyncio
async def test_stale_lmstudio_observation_is_not_counted_as_coverage():
    from types import SimpleNamespace

    class Observer:
        async def observe(self, *, runtime_identity):
            return {"status": "available", "coverage": "complete", "observed_at": time.time() - 60,
                    "runtime_identity": runtime_identity}

    service = SimpleNamespace(runtime_identity={"runtime_revision": "configured-instance"},
                               lmstudio_activity_observer=Observer())

    result = await LMStudioGateway._lmstudio_activity_observation(service)

    assert result == {"status": "unavailable", "reason_code": "observer_observation_stale"}


@pytest.mark.asyncio
async def test_system_status_reports_corrupt_gaming_journal_as_unavailable_not_500(tmp_path):
    from types import SimpleNamespace

    journal = tmp_path / "corrupt-state.json"
    journal.write_text("not-json", encoding="utf-8")
    gateway = LMStudioGateway(state_persistence_path=str(journal))
    service = SimpleNamespace(
        system=SimpleNamespace(
            supervisors={},
            config=SimpleNamespace(service=SimpleNamespace(state_persistence_path=str(journal))),
            lease_mgr=gateway.lease_mgr,
        ),
        state=SimpleNamespace(value="ready"), is_ready=True, runtime_identity={},
        stop_miner_on_shutdown=False,
        maintenance_manager=SimpleNamespace(status=lambda: {"state": "idle"}),
    )
    gateway.set_service(service)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway.create_app(service)), base_url="http://gateway"
    ) as client:
        response = await client.get("/_coordinator/status")
    assert response.status_code == 200
    assert response.json()["gaming"]["state"] == "unavailable"
    assert response.json()["gaming"]["status"] == "unavailable"
    await gateway.close()


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
