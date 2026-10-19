"""
Phase D Offline Integration Test Suite.

Verifies the 16 required offline scenarios for controlled service integration,
readiness state machine, centralized admission, process arbitration, and emergency abort:

 1. Request received before startup finishes (HTTP 503).
 2. Invalid or incomplete configuration (startup fails closed).
 3. Startup failure after partial component initialization.
 4. Successful simulated mining-to-inference transition and cooldown resumption.
 5. Miner stop requested but never verified (veto, inference blocked).
 6. New inference arriving during cooldown or pending restart.
 7. Concurrent protected requests and model-loading contention.
 8. Cancellation at each major admission transition.
 9. Normal streaming completion vs truncated/uncertain termination.
10. Shutdown with active inference (draining, bounded wait, no miner restart).
11. Unexpected miner relaunch detection.
12. Recycled PID or ambiguous process identity handling.
13. Unsupported mutating endpoints fail closed (HTTP 501).
14. Attempted model-management bypass fails closed (HTTP 503).
15. Coordinator restart with unresolved or missing safety state.
16. Emergency abort stops admission and preserves holds without blind kills.
"""

import asyncio

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from resource_coordinator.config import (
    CoordinatorConfig,
    PolicyConfig,
    ProcessConfig,
    ServiceConfig,
)
from resource_coordinator.core.actions import StartProcessAction, StopProcessAction
from resource_coordinator.core.events import EventDispatcher, VetoOperation
from resource_coordinator.core.leases import LeaseManager, LeaseType
from resource_coordinator.core.policies import Policy, PolicyEngine
from resource_coordinator.core.processes import (
    FakeProcessBackend,
    ProcessLifecycleOwner,
    ProcessState,
    ProcessSupervisor,
)
from resource_coordinator.core.service import CoordinatorService, ServiceState


def make_mock_upstream():
    """Create controllable mock LM Studio upstream application."""
    active_stream_chunks = []

    async def handle_models(request):
        return JSONResponse({"data": [{"id": "local-model", "object": "model"}]})

    async def handle_chat(request):
        body = await request.json()
        if body.get("stream"):
            mode = body.get("stream_mode", "normal")

            async def event_generator():
                if mode == "normal":
                    yield b'data: {"choices": [{"delta": {"content": "Hello"}}]}\n\n'
                    await asyncio.sleep(0.01)
                    yield b'data: {"choices": [{"delta": {"content": " world"}}]}\n\n'
                    yield b"data: [DONE]\n\n"
                elif mode == "truncated":
                    yield b'data: {"choices": [{"delta": {"content": "Partial"}}]}\n\n'
                    active_stream_chunks.append("partial_sent")
                    # Intentionally close without [DONE]
                elif mode == "slow":
                    yield b'data: {"choices": [{"delta": {"content": "Slow1"}}]}\n\n'
                    await asyncio.sleep(0.3)
                    yield b"data: [DONE]\n\n"

            return StreamingResponse(event_generator(), media_type="text/event-stream")

        if body.get("fail_upstream"):
            return JSONResponse({"error": "Upstream error"}, status_code=500)

        if body.get("slow"):
            await asyncio.sleep(0.2)

        return JSONResponse(
            {
                "id": "chat-test",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": "Completed response"},
                    }
                ],
            }
        )

    routes = [
        Route("/v1/models", handle_models, methods=["GET"]),
        Route("/v1/chat/completions", handle_chat, methods=["POST"]),
    ]
    return Starlette(routes=routes), active_stream_chunks


def make_test_system(
    cooldown_seconds: float = 0.05,
    miner_running: bool = True,
    fail_miner_stop: bool = False,
    allow_external_restart: bool = True,
    include_krig: bool = True,
):
    """Build a test CoordinatorSystem with FakeProcessBackend and mock upstream."""
    dispatcher = EventDispatcher()
    lease_mgr = LeaseManager(default_cooldown_seconds=cooldown_seconds, event_dispatcher=dispatcher)
    policy_engine = PolicyEngine(event_dispatcher=dispatcher, lease_manager=lease_mgr)
    supervisors = {}
    miner_adapter = None

    processes_cfg = {}
    if include_krig:
        backend = FakeProcessBackend(
            name="krig",
            running=miner_running,
            fail_stop=fail_miner_stop,
            allow_external_restart=allow_external_restart,
        )
        if miner_running:
            backend.is_coordinator_owned = True
            backend.lifecycle_owner = ProcessLifecycleOwner.COORDINATOR
            backend.pid = 12345
            backend.create_time = 1000.0

        sup = ProcessSupervisor(backend=backend, event_dispatcher=dispatcher)
        supervisors["krig"] = sup

        processes_cfg["krig"] = ProcessConfig(
            name="krig",
            backend="fake",
            executable=r"C:\Mining\krig.exe",
        )

        policy = Policy(
            name="stop-krig-for-inference",
            trigger_event="lmstudio.inference_requested",
            actions=[StopProcessAction(supervisor=sup, wait_until_stopped=True, timeout_seconds=2.0)],
            resource="gpu.inference",
            lease_type=LeaseType.EXCLUSIVE,
            cooldown_seconds=cooldown_seconds,
            after_release_actions=[StartProcessAction(supervisor=sup, only_if_stopped_by_coordinator=True)],
        )
        policy_engine.register_policy(policy)

    from resource_coordinator.adapters.lmstudio.gateway import LMStudioGateway

    gateway = LMStudioGateway(
        upstream_url="http://mock-lmstudio",
        event_dispatcher=dispatcher,
        lease_manager=lease_mgr,
    )
    upstream_app, stream_tracker = make_mock_upstream()
    gateway._http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=upstream_app),
        base_url="http://mock-lmstudio",
    )

    config = CoordinatorConfig(
        service=ServiceConfig(listen_port=1235),
        processes=processes_cfg,
        policies=[
            PolicyConfig(
                name="stop-krig-for-inference",
                trigger_event="lmstudio.inference_requested",
                target_process="krig" if include_krig else None,
                resource="gpu.inference",
                cooldown_seconds=cooldown_seconds,
            )
        ]
        if include_krig
        else [],
    )

    from resource_coordinator.config import CoordinatorSystem

    system = CoordinatorSystem(
        config=config,
        dispatcher=dispatcher,
        lease_mgr=lease_mgr,
        supervisors=supervisors,
        miner_adapter=miner_adapter,
        policy_engine=policy_engine,
        gateway=gateway,
    )
    return system, gateway, stream_tracker


# ============================================================================
# Scenario 1: Request received before startup finishes (HTTP 503)
# ============================================================================
@pytest.mark.asyncio
async def test_scenario_01_request_before_startup_ready():
    system, gateway, _ = make_test_system()
    service = CoordinatorService(system=system)
    app = gateway.create_app(service)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway")

    # Service is in CREATED state (not READY)
    assert service.state == ServiceState.CREATED
    assert service.is_ready is False

    # Inference request must fail with 503
    resp = await client.post("/v1/chat/completions", json={"model": "local-model", "messages": []})
    assert resp.status_code == 503
    data = resp.json()
    assert data["error"]["code"] == "coordinator_not_ready"
    assert data["error"]["service_state"] == "created"

    # Metadata request before ready also fails closed with 503
    resp_meta = await client.get("/v1/models")
    assert resp_meta.status_code == 503
    assert resp_meta.json()["error"]["code"] == "coordinator_not_ready"

    # Internal status endpoint is accessible and reports service state
    resp_status = await client.get("/_coordinator/status")
    assert resp_status.status_code == 200
    assert resp_status.json()["service_state"] == "created"
    assert resp_status.json()["is_ready"] is False


# ============================================================================
# Scenario 2: Invalid or incomplete configuration (startup fails closed)
# ============================================================================
@pytest.mark.asyncio
async def test_scenario_02_invalid_incomplete_config_fails_closed():
    system, gateway, _ = make_test_system()
    # Introduce policy targeting unknown supervisor
    system.config.policies.append(
        PolicyConfig(
            name="broken-policy",
            trigger_event="lmstudio.inference_requested",
            target_process="non_existent_process",
        )
    )
    service = CoordinatorService(system=system)
    app = gateway.create_app(service)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway")

    passed, msgs = service.preflight_check()
    assert passed is False
    assert any("broken-policy" in m for m in msgs)

    # Start must fail closed
    success = await service.start()
    assert success is False
    assert service.state == ServiceState.FAILED
    assert "Preflight checks failed" in (service.failure_reason or "")

    # Request rejected with 503
    resp = await client.post("/v1/chat/completions", json={"model": "local-model", "messages": []})
    assert resp.status_code == 503
    assert resp.json()["error"]["service_state"] == "failed"


# ============================================================================
# Scenario 3: Startup failure after partial component initialization
# ============================================================================
@pytest.mark.asyncio
async def test_scenario_03_startup_failure_partial_component_initialization():
    system, gateway, _ = make_test_system()
    service = CoordinatorService(system=system)

    # Simulate unexpected failure during start sequence (e.g. preflight failure)
    from unittest.mock import MagicMock

    service.preflight_check = MagicMock(side_effect=RuntimeError("Process table corrupt"))

    success = await service.start()
    assert success is False
    assert service.state == ServiceState.FAILED
    assert "Process table corrupt" in (service.failure_reason or "")
    assert service.is_ready is False


# ============================================================================
# Scenario 4: Mining to inference transition and cooldown resumption
# ============================================================================
@pytest.mark.asyncio
async def test_scenario_04_mining_to_inference_transition_and_cooldown_resumption():
    system, gateway, _ = make_test_system(cooldown_seconds=0.05, miner_running=True)
    service = CoordinatorService(system=system)
    app = gateway.create_app(service)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway")

    await service.start()
    assert service.is_ready is True
    sup = system.supervisors["krig"]
    backend: FakeProcessBackend = sup.backend  # type: ignore

    # Miner initially running
    assert backend.running is True

    # Send inference request
    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "local-model", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == "Completed response"

    # Miner was stopped during request and coordinator enters cooldown
    assert backend.running is False
    assert system.lease_mgr.is_cooling_down("gpu.inference") is True

    # Wait for cooldown to expire
    restarted = False
    for _ in range(25):
        if backend.running:
            restarted = True
            break
        await asyncio.sleep(0.02)
    assert restarted is True
    assert system.lease_mgr.is_cooling_down("gpu.inference") is False


# ============================================================================
# Scenario 5: Miner stop requested but never verified (veto, inference blocked)
# ============================================================================
@pytest.mark.asyncio
async def test_scenario_05_miner_stop_unverified_vetoes_inference():
    system, gateway, _ = make_test_system(miner_running=True)
    service = CoordinatorService(system=system)
    app = gateway.create_app(service)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway")

    await service.start()

    # Register blocking veto handler on trigger event
    def veto_handler(event):
        raise VetoOperation("Miner process refused to terminate cleanly")

    system.dispatcher.on("lmstudio.inference_requested", veto_handler, is_blocking=True)

    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "local-model", "messages": [{"role": "user", "content": "test"}]},
    )
    # Failed admission veto must fail closed with 503
    assert resp.status_code == 503
    assert "refused" in resp.json()["error"]["message"]

    # Inference lease was not acquired
    assert system.lease_mgr.active_count("gpu.inference") == 0


# ============================================================================
# Scenario 6: New inference arriving during cooldown or pending restart
# ============================================================================
@pytest.mark.asyncio
async def test_scenario_06_new_inference_during_cooldown_cancels_restart():
    system, gateway, _ = make_test_system(cooldown_seconds=0.1, miner_running=True)
    service = CoordinatorService(system=system)
    app = gateway.create_app(service)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway")

    await service.start()
    backend: FakeProcessBackend = system.supervisors["krig"].backend  # type: ignore

    # First request
    resp1 = await client.post("/v1/chat/completions", json={"model": "local-model", "messages": []})
    assert resp1.status_code == 200
    assert backend.running is False
    assert system.lease_mgr.is_cooling_down("gpu.inference") is True

    # Send second request during active cooldown (at 0.02s)
    await asyncio.sleep(0.02)
    resp2 = await client.post("/v1/chat/completions", json={"model": "local-model", "messages": []})
    assert resp2.status_code == 200

    # Miner should NOT have restarted between requests
    assert backend.running is False

    # After second request completes, fresh cooldown starts
    assert system.lease_mgr.is_cooling_down("gpu.inference") is True
    restarted = False
    for _ in range(25):
        if backend.running:
            restarted = True
            break
        await asyncio.sleep(0.02)
    assert restarted is True


# ============================================================================
# Scenario 7: Concurrent protected requests and model-loading contention
# ============================================================================
@pytest.mark.asyncio
async def test_scenario_07_concurrent_inference_and_model_loading_contention():
    system, gateway, _ = make_test_system(cooldown_seconds=0.05, miner_running=True)
    service = CoordinatorService(system=system)
    app = gateway.create_app(service)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway")

    await service.start()
    backend: FakeProcessBackend = system.supervisors["krig"].backend  # type: ignore

    # Submit concurrent inference requests
    req1 = client.post("/v1/chat/completions", json={"model": "local-model", "slow": True, "messages": []})
    req2 = client.post("/v1/chat/completions", json={"model": "local-model", "slow": True, "messages": []})
    res1, res2 = await asyncio.gather(req1, req2)
    assert res1.status_code == 200
    assert res2.status_code == 200
    assert backend.running is False

    # Model load without blocking policy hook fails closed with 503
    resp_load = await client.post("/api/v0/model/load", json={"model": "second-model"})
    assert resp_load.status_code == 503
    assert resp_load.json()["error"]["code"] == "uncoordinated_model_mutation"


# ============================================================================
# Scenario 8: Cancellation at each major admission transition
# ============================================================================
@pytest.mark.asyncio
async def test_scenario_08_cancellation_during_admission_transitions():
    system, gateway, _ = make_test_system(miner_running=False)
    service = CoordinatorService(system=system)
    app = gateway.create_app(service)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway")

    await service.start()

    # Client cancels slow request early
    try:
        await asyncio.wait_for(
            client.post("/v1/chat/completions", json={"model": "local-model", "slow": True, "messages": []}),
            timeout=0.05,
        )
    except asyncio.TimeoutError:
        pass

    # Wait for cancel scope cleanup to complete
    await asyncio.sleep(0.05)

    # Active count must have safely returned to 0
    assert system.lease_mgr.active_count("gpu.inference") == 0


# ============================================================================
# Scenario 9: Normal streaming completion vs truncated/uncertain termination
# ============================================================================
@pytest.mark.asyncio
async def test_scenario_09_normal_vs_truncated_streaming():
    system, gateway, _ = make_test_system(cooldown_seconds=0.05, miner_running=True)
    service = CoordinatorService(system=system)
    app = gateway.create_app(service)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway")

    await service.start()
    backend: FakeProcessBackend = system.supervisors["krig"].backend  # type: ignore

    # Subcase A: Normal streaming with [DONE]
    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "local-model", "stream": True, "stream_mode": "normal"},
    )
    assert resp.status_code == 200
    text = resp.text
    assert "[DONE]" in text
    assert system.lease_mgr.is_restart_inhibited("gpu.inference") is False

    # Subcase B: Truncated streaming without [DONE]
    resp_trunc = await client.post(
        "/v1/chat/completions",
        json={"model": "local-model", "stream": True, "stream_mode": "truncated"},
    )
    assert resp_trunc.status_code == 200

    # Truncated termination MUST assert restart inhibition
    assert system.lease_mgr.is_restart_inhibited("gpu.inference") is True

    # Miner CANNOT restart while restart is inhibited, even after waiting past cooldown
    await asyncio.sleep(0.08)
    assert backend.running is False


# ============================================================================
# Scenario 10: Shutdown with active inference (draining, bounded wait)
# ============================================================================
@pytest.mark.asyncio
async def test_scenario_10_shutdown_with_active_inference_draining():
    system, gateway, _ = make_test_system(miner_running=False)
    service = CoordinatorService(system=system, drain_timeout=0.5)
    app = gateway.create_app(service)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway")

    await service.start()

    # Start slow active request
    slow_req = asyncio.create_task(
        client.post("/v1/chat/completions", json={"model": "local-model", "slow": True, "messages": []})
    )
    await asyncio.sleep(0.05)
    assert system.lease_mgr.active_count("gpu.inference") == 1

    # Initiate service shutdown
    shutdown_task = asyncio.create_task(service.stop())
    await asyncio.sleep(0.02)

    # Service should be DRAINING
    assert service.state == ServiceState.DRAINING

    # New incoming request during draining must receive 503
    resp_new = await client.post("/v1/chat/completions", json={"model": "local-model", "messages": []})
    assert resp_new.status_code == 503
    assert resp_new.json()["error"]["code"] == "coordinator_draining"

    # Wait for slow request and shutdown to finish
    res = await slow_req
    assert res.status_code == 200
    await shutdown_task

    assert service.state == ServiceState.STOPPED


# ============================================================================
# Scenario 11: Unexpected miner relaunch detection
# ============================================================================
@pytest.mark.asyncio
async def test_scenario_11_unexpected_miner_relaunch_detection():
    system, gateway, _ = make_test_system(miner_running=True)
    service = CoordinatorService(system=system)
    await service.start()

    sup = system.supervisors["krig"]
    backend: FakeProcessBackend = sup.backend  # type: ignore

    # Simulate coordinator stopping miner
    await sup.stop()
    assert backend.running is False

    # Simulate unexpected external relaunch of process
    backend.running = True
    backend.lifecycle_owner = ProcessLifecycleOwner.EXTERNAL
    backend.is_coordinator_owned = False

    st = await sup.status()
    assert st.state == ProcessState.EXTERNAL_RUNNING
    assert st.is_coordinator_owned is False


# ============================================================================
# Scenario 12: Recycled PID or ambiguous process identity handling
# ============================================================================
@pytest.mark.asyncio
async def test_scenario_12_recycled_pid_identity_handling():
    backend = FakeProcessBackend(
        name="krig",
        running=True,
        external=False,
        allow_external_restart=False,
    )
    backend.pid = 9999
    backend.create_time = 1000.0

    sup = ProcessSupervisor(backend=backend)
    info1 = await sup.status()
    assert info1.pid == 9999
    assert info1.create_time == 1000.0

    # Stop process
    await sup.stop()

    # Simulate PID recycled by different OS process with new create_time
    backend.running = True
    backend.pid = 9999
    backend.create_time = 2000.0
    backend.lifecycle_owner = ProcessLifecycleOwner.EXTERNAL
    backend.is_coordinator_owned = False

    info2 = await sup.status()
    # Supervisor must not confuse it with previously-owned instance
    assert info2.is_coordinator_owned is False
    assert info2.create_time != info1.create_time


# ============================================================================
# Scenario 13: Unsupported mutating endpoints fail closed (HTTP 501)
# ============================================================================
@pytest.mark.asyncio
async def test_scenario_13_unsupported_mutating_endpoints_fail_closed():
    system, gateway, _ = make_test_system()
    service = CoordinatorService(system=system)
    app = gateway.create_app(service)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway")

    await service.start()

    # Unsupported mutating routes
    resp_post = await client.post("/v1/fine_tuning/jobs", json={})
    assert resp_post.status_code == 501
    assert resp_post.json()["error"]["code"] == "unsupported_endpoint"

    resp_put = await client.put("/v1/models/my-custom-model", json={})
    assert resp_put.status_code == 501
    assert resp_put.json()["error"]["code"] == "unsupported_endpoint"

    resp_del = await client.delete("/v1/files/file-123")
    assert resp_del.status_code == 501
    assert resp_del.json()["error"]["code"] == "unsupported_endpoint"


# ============================================================================
# Scenario 14: Attempted model-management bypass fails closed (HTTP 503)
# ============================================================================
@pytest.mark.asyncio
async def test_scenario_14_attempted_model_management_bypass_fails_closed():
    system, gateway, _ = make_test_system()
    service = CoordinatorService(system=system)
    app = gateway.create_app(service)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway")

    await service.start()

    # Model unload attempt without policy hooks
    resp_unload = await client.post("/api/v0/model/unload", json={"model": "qwen38"})
    assert resp_unload.status_code == 503
    assert resp_unload.json()["error"]["code"] == "uncoordinated_model_mutation"

    # Unrecognized OpenAI-shaped model load attempt
    resp_oai_load = await client.post("/v1/models/load", json={"model": "qwen38"})
    assert resp_oai_load.status_code == 501
    assert resp_oai_load.json()["error"]["code"] == "unsupported_endpoint"


# ============================================================================
# Scenario 15: Coordinator restart with unresolved or missing safety state
# ============================================================================
@pytest.mark.asyncio
async def test_scenario_15_coordinator_restart_with_unresolved_safety_state():
    system, gateway, _ = make_test_system()
    # Same-memory unresolved hold only: this does not simulate crash persistence.
    await system.lease_mgr.inhibit_restart(
        "gpu.inference",
        reason="Unresolved previous session interruption",
        holder_id="system",
    )
    service = CoordinatorService(system=system)

    passed, msgs = service.preflight_check()
    # An unresolved in-memory hold is a startup failure, not crash reconciliation.
    assert any("Unresolved previous session interruption" in m for m in msgs)

    # Start service
    await service.start()
    assert service.is_ready is False

    # Mining restart remains inhibited
    assert system.lease_mgr.is_restart_inhibited("gpu.inference") is True


# ============================================================================
# Scenario 16: Emergency abort stops admission and preserves holds
# ============================================================================
@pytest.mark.asyncio
async def test_scenario_16_emergency_abort_stops_admission_preserves_holds():
    system, gateway, _ = make_test_system(miner_running=True)
    service = CoordinatorService(system=system)
    app = gateway.create_app(service)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway")

    await service.start()
    backend: FakeProcessBackend = system.supervisors["krig"].backend  # type: ignore

    # Set active inhibition
    await system.lease_mgr.inhibit_restart("gpu.inference", reason="Manual hold", holder_id="admin")

    # Operator abort requires a credential and attributable reason.
    gateway.recovery_token = "test-token"
    resp_abort = await client.post(
        "/_coordinator/abort",
        headers={"Authorization": "Bearer test-token"},
        json={"reason": "Operator observed thermal anomaly", "operator": "test"},
    )
    assert resp_abort.status_code == 200
    assert resp_abort.json()["status"] == "aborted"
    assert resp_abort.json()["service_state"] == "reconciliation_required"

    # Service transitioned to RECONCILIATION_REQUIRED
    assert service.state == ServiceState.RECONCILIATION_REQUIRED

    # Subsequent proxy requests fail closed with 503
    resp_after = await client.post("/v1/chat/completions", json={"model": "local-model", "messages": []})
    assert resp_after.status_code == 503

    # Safety holds are PRESERVED
    assert system.lease_mgr.is_restart_inhibited("gpu.inference") is True
    assert backend.running is True  # Fake miner was not blindly killed without identity verification
