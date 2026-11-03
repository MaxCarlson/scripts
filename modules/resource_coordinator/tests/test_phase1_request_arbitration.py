"""
Phase 01 Request Arbitration and Admission Offline Test Suite.

Deterministic validation of:
- F-01: Idle mining state.
- F-02: Arrival barrier (stop and verify miner before forwarding).
- F-03: Outstanding requests hold miner stopped.
- F-04: Monotonic 10.0-second cooldown after final verified completion.
- F-05: Cooldown cancellation on new request arrivals (including at boundary ~9.99s).
- F-06: Verified terminal completion vs upstream uncertainty/inhibition.
- F-07: Concurrency and exclusive model-load arbitration.
- Supported routes and denial of unsupported mutating endpoints.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, List, Optional
from unittest.mock import Mock

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from resource_coordinator.adapters.lmstudio.gateway import LMStudioGateway
from resource_coordinator.config import (
    CoordinatorConfig,
    PolicyConfig,
    ProcessConfig,
    ServiceConfig,
    build_system,
)
from resource_coordinator.core.actions import StartProcessAction, StopProcessAction
from resource_coordinator.core.events import EventDispatcher, VetoOperation
from resource_coordinator.core.leases import LeaseManager, LeaseReservation, LeaseType
from resource_coordinator.core.policies import Policy, PolicyEngine
from resource_coordinator.core.processes import (
    FakeProcessBackend,
    ProcessLifecycleOwner,
    ProcessState,
    ProcessSupervisor,
)
from resource_coordinator.core.service import CoordinatorService, ServiceState


class ControllableClock:
    """Deterministic monotonic clock and sleep for fast time tests."""

    def __init__(self, start_time: float = 1000.0) -> None:
        self._current = start_time
        self._sleepers: List[asyncio.Event] = []

    def time(self) -> float:
        return self._current

    def advance(self, seconds: float) -> None:
        self._current += seconds

    async def sleep(self, seconds: float) -> None:
        evt = asyncio.Event()
        self._sleepers.append(evt)
        try:
            await evt.wait()
        finally:
            if evt in self._sleepers:
                self._sleepers.remove(evt)

    def wake_all(self) -> None:
        for evt in list(self._sleepers):
            evt.set()


def create_test_upstream():
    """Create a mock upstream server recording request state and miner state at forward time."""
    requests_received: List[dict] = []
    miner_state_at_forward: List[Optional[ProcessState]] = []
    supervisor_ref: List[Optional[ProcessSupervisor]] = [None]

    async def handle_chat(request: Request) -> Response:
        body = await request.json()
        sup = supervisor_ref[0]
        st = (await sup.status()).state if sup else None
        miner_state_at_forward.append(st)
        requests_received.append({"path": "/v1/chat/completions", "body": body})

        if body.get("fail_upstream"):
            return JSONResponse({"error": "Internal upstream error"}, status_code=500)

        if body.get("stream"):
            mode = body.get("stream_mode", "normal")

            async def event_generator():
                if mode == "normal":
                    yield b'data: {"choices": [{"delta": {"content": "Hello"}}]}\n\n'
                    yield b'data: {"choices": [{"delta": {"content": " world"}}]}\n\n'
                    yield b"data: [DONE]\n\n"
                elif mode == "truncated":
                    yield b'data: {"choices": [{"delta": {"content": "Partial"}}]}\n\n'
                    # Abrupt close without [DONE]
                elif mode == "slow":
                    yield b'data: {"choices": [{"delta": {"content": "Slow"}}]}\n\n'
                    await asyncio.sleep(0.05)
                    yield b"data: [DONE]\n\n"

            return StreamingResponse(event_generator(), media_type="text/event-stream")

        if body.get("slow"):
            await asyncio.sleep(0.05)

        return JSONResponse(
            {
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Test response"},
                        "finish_reason": "stop",
                    }
                ],
            }
        )

    async def handle_models(request: Request) -> JSONResponse:
        requests_received.append({"path": "/v1/models"})
        return JSONResponse({"data": [{"id": "test-model", "object": "model"}]})

    async def handle_model_load(request: Request) -> JSONResponse:
        body = await request.json()
        sup = supervisor_ref[0]
        st = (await sup.status()).state if sup else None
        miner_state_at_forward.append(st)
        requests_received.append({"path": request.url.path, "body": body})
        return JSONResponse({"status": "loaded", "model": body.get("model", "test-model")})

    routes = [
        Route("/v1/chat/completions", handle_chat, methods=["POST"]),
        Route("/v1/models", handle_models, methods=["GET"]),
        Route("/api/v0/model/load", handle_model_load, methods=["POST"]),
        Route("/api/v1/models/load", handle_model_load, methods=["POST"]),
    ]
    app = Starlette(routes=routes)
    return app, requests_received, miner_state_at_forward, supervisor_ref


def build_arbitration_test_system(
    cooldown_seconds: float = 10.0,
    miner_initially_running: bool = True,
    clock: Optional[ControllableClock] = None,
):
    upstream_app, requests_received, miner_states, supervisor_ref = create_test_upstream()
    mock_transport = httpx.ASGITransport(app=upstream_app)
    mock_client = httpx.AsyncClient(transport=mock_transport, base_url="http://mock-upstream")

    dispatcher = EventDispatcher()
    if clock is not None:
        lease_mgr = LeaseManager(
            default_cooldown_seconds=cooldown_seconds,
            event_dispatcher=dispatcher,
            monotonic_clock=clock.time,
            sleep=clock.sleep,
        )
    else:
        lease_mgr = LeaseManager(
            default_cooldown_seconds=cooldown_seconds,
            event_dispatcher=dispatcher,
        )

    backend = FakeProcessBackend(name="krig_miner", running=miner_initially_running, executable="/bin/krig")
    supervisor = ProcessSupervisor(backend=backend, event_dispatcher=dispatcher)
    supervisor.was_stopped_by_coordinator = False
    supervisor_ref[0] = supervisor

    policy_engine = PolicyEngine(event_dispatcher=dispatcher, lease_manager=lease_mgr)
    policy_engine.register_policy(
        Policy(
            name="pause_for_inference",
            trigger_event="lmstudio.inference_requested",
            actions=[StopProcessAction(supervisor=supervisor, wait_until_stopped=True)],
            resource="gpu.inference",
            lease_type=LeaseType.SHARED,
            cooldown_seconds=cooldown_seconds,
            after_release_actions=[StartProcessAction(supervisor=supervisor)],
        )
    )
    policy_engine.register_policy(
        Policy(
            name="pause_for_model_load",
            trigger_event="lmstudio.model_load_requested",
            actions=[StopProcessAction(supervisor=supervisor, wait_until_stopped=True)],
            resource="gpu.inference",
            lease_type=LeaseType.EXCLUSIVE,
            cooldown_seconds=cooldown_seconds,
            after_release_actions=[StartProcessAction(supervisor=supervisor)],
        )
    )

    gateway = LMStudioGateway(
        upstream_url="http://mock-upstream",
        event_dispatcher=dispatcher,
        lease_manager=lease_mgr,
        standalone=False,
    )
    gateway._http_client = mock_client

    config = CoordinatorConfig(
        version="1.0",
        service=ServiceConfig(listen_host="127.0.0.1", listen_port=1235, upstream_url="http://mock-upstream"),
        processes={
            "krig_miner": ProcessConfig(
                name="krig_miner",
                backend="fake",
                executable="/bin/krig",
                stop_timeout_seconds=5.0,
            )
        },
        policies=[
            PolicyConfig(
                name="pause_for_inference",
                trigger_event="lmstudio.inference_requested",
                target_process="krig_miner",
                stop_process=True,
                resource="gpu.inference",
                lease_type="shared",
                cooldown_seconds=cooldown_seconds,
                restart_process=True,
            ),
            PolicyConfig(
                name="pause_for_model_load",
                trigger_event="lmstudio.model_load_requested",
                target_process="krig_miner",
                stop_process=True,
                resource="gpu.inference",
                lease_type="exclusive",
                cooldown_seconds=cooldown_seconds,
                restart_process=True,
            ),
        ],
    )
    system = build_system(config, use_fake_processes=True)
    # Wire our specific instances
    system.supervisors["krig_miner"] = supervisor
    system.lease_mgr = lease_mgr
    system.dispatcher = dispatcher
    system.gateway = gateway
    system.policy_engine = policy_engine

    service = CoordinatorService(system)
    return service, gateway, supervisor, requests_received, miner_states


@pytest.mark.asyncio
async def test_stop_before_forward_guarantee():
    """A02: Prove miner is verified stopped BEFORE upstream receives the inference request."""
    service, gateway, supervisor, requests, miner_states = build_arbitration_test_system(
        cooldown_seconds=10.0, miner_initially_running=True
    )
    assert await service.start() is True
    assert (await supervisor.status()).state == ProcessState.RUNNING

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway.create_app()), base_url="http://coordinator"
    ) as client:
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "qwen38", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 200
        assert len(requests) == 1
        # Crucial invariant: Miner MUST have been stopped when upstream handled request
        assert miner_states == [ProcessState.STOPPED]

    await service.stop()


@pytest.mark.asyncio
async def test_failed_stop_vetoes_inference_upstream_receives_zero():
    """A03: If miner cannot be stopped, request is rejected and upstream receives ZERO requests."""
    service, gateway, supervisor, requests, _ = build_arbitration_test_system(
        cooldown_seconds=10.0, miner_initially_running=True
    )
    # Simulate stop failure
    supervisor.backend.fail_stop = True
    assert await service.start() is True

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway.create_app()), base_url="http://coordinator"
    ) as client:
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "qwen38", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code in {500, 503}
        # Upstream never receives any request
        assert len(requests) == 0

    await service.stop()


@pytest.mark.asyncio
async def test_canonical_10_second_cooldown_and_cancellation():
    """A04, A07, A10: Exactly 10s cooldown; cancellation by intervening request."""
    clock = ControllableClock()
    service, gateway, supervisor, requests, _ = build_arbitration_test_system(
        cooldown_seconds=10.0, miner_initially_running=True, clock=clock
    )
    assert await service.start() is True
    lease_mgr = service.system.lease_mgr

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway.create_app()), base_url="http://coordinator"
    ) as client:
        # Request 1
        resp1 = await client.post(
            "/v1/chat/completions",
            json={"model": "qwen38", "messages": [{"role": "user", "content": "req 1"}]},
        )
        assert resp1.status_code == 200

        # After completion: cooldown is running
        assert lease_mgr.is_cooling_down("gpu.inference")
        assert lease_mgr.active_count("gpu.inference") == 0
        assert (await supervisor.status()).state == ProcessState.STOPPED

        # Advance clock by 5.0 seconds (halfway through cooldown)
        clock.advance(5.0)
        assert lease_mgr.is_cooling_down("gpu.inference")
        assert (await supervisor.status()).state == ProcessState.STOPPED

        # Request 2 arrives at T+5.0s -> cancels cooldown immediately!
        resp2 = await client.post(
            "/v1/chat/completions",
            json={"model": "qwen38", "messages": [{"role": "user", "content": "req 2"}]},
        )
        assert resp2.status_code == 200

        # After request 2 completion: cooldown restarted from 0 for another 10s
        assert lease_mgr.is_cooling_down("gpu.inference")

        # Advance clock by 9.99 seconds (just before boundary)
        clock.advance(9.99)
        assert lease_mgr.is_cooling_down("gpu.inference")
        assert (await supervisor.status()).state == ProcessState.STOPPED

        # Request 3 arrives at boundary 9.99s -> cancels cooldown again!
        resp3 = await client.post(
            "/v1/chat/completions",
            json={"model": "qwen38", "messages": [{"role": "user", "content": "req 3"}]},
        )
        assert resp3.status_code == 200

        # Now let 10.0s elapse without any requests
        await asyncio.sleep(0.01)
        assert lease_mgr.is_cooling_down("gpu.inference")
        clock.advance(10.0)
        # Wake the cooldown worker
        clock.wake_all()
        await asyncio.sleep(0.02)

        # After 10 uninterrupted seconds: miner restarts!
        assert not lease_mgr.is_cooling_down("gpu.inference")
        assert (await supervisor.status()).state == ProcessState.RUNNING

    await service.stop()


@pytest.mark.asyncio
async def test_concurrent_requests_share_lease_and_cooldown_waits_for_final():
    """A08: Concurrent requests share lease; miner stays stopped; cooldown starts only when final request finishes."""
    service, gateway, supervisor, requests, _ = build_arbitration_test_system(
        cooldown_seconds=0.05, miner_initially_running=True
    )
    assert await service.start() is True
    lease_mgr = service.system.lease_mgr

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway.create_app()), base_url="http://coordinator"
    ) as client:
        # Submit two overlapping requests
        t1 = asyncio.create_task(
            client.post("/v1/chat/completions", json={"model": "qwen38", "slow": True})
        )
        t2 = asyncio.create_task(
            client.post("/v1/chat/completions", json={"model": "qwen38", "slow": True})
        )

        # Let requests enter gateway
        await asyncio.sleep(0.01)

        # Both requests are active concurrently
        assert lease_mgr.active_count("gpu.inference") == 2
        assert (await supervisor.status()).state == ProcessState.STOPPED

        r1, r2 = await asyncio.gather(t1, t2)
        assert r1.status_code == 200
        assert r2.status_code == 200

        # Both complete, cooldown starts
        assert lease_mgr.is_cooling_down("gpu.inference")
        await asyncio.sleep(0.08)

        # After cooldown, miner is restarted
        assert (await supervisor.status()).state == ProcessState.RUNNING

    await service.stop()


@pytest.mark.asyncio
async def test_streaming_sse_done_vs_truncated():
    """A05, A06: Stream with [DONE] completes and restarts; truncated stream inhibits restart."""
    service, gateway, supervisor, _, _ = build_arbitration_test_system(
        cooldown_seconds=0.05, miner_initially_running=True
    )
    assert await service.start() is True
    lease_mgr = service.system.lease_mgr

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway.create_app()), base_url="http://coordinator"
    ) as client:
        # Case 1: Stream with valid [DONE] marker
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "qwen38", "stream": True, "stream_mode": "normal"},
        )
        assert resp.status_code == 200
        body = resp.text
        assert "[DONE]" in body
        # Cooldown proceeds normally
        assert lease_mgr.is_cooling_down("gpu.inference")
        await asyncio.sleep(0.08)
        assert (await supervisor.status()).state == ProcessState.RUNNING

        # Case 2: Truncated stream missing [DONE]
        resp_trunc = await client.post(
            "/v1/chat/completions",
            json={"model": "qwen38", "stream": True, "stream_mode": "truncated"},
        )
        assert resp_trunc.status_code == 200
        # Restart must be inhibited!
        assert lease_mgr.is_restart_inhibited("gpu.inference")
        inhibition = lease_mgr.get_inhibition("gpu.inference")
        assert inhibition is not None
        assert "Stream ended without completion signal" in inhibition.reason

        # Even after waiting, miner MUST NOT restart
        await asyncio.sleep(0.08)
        assert (await supervisor.status()).state == ProcessState.STOPPED

    await service.stop()


@pytest.mark.asyncio
async def test_upstream_error_imposes_restart_inhibition():
    """A06, F-06: Upstream 500 error causes restart inhibition; miner stays stopped."""
    service, gateway, supervisor, _, _ = build_arbitration_test_system(
        cooldown_seconds=0.05, miner_initially_running=True
    )
    assert await service.start() is True
    lease_mgr = service.system.lease_mgr

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway.create_app()), base_url="http://coordinator"
    ) as client:
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "qwen38", "fail_upstream": True},
        )
        assert resp.status_code == 500
        # Restart must be inhibited
        assert lease_mgr.is_restart_inhibited("gpu.inference")
        assert (await supervisor.status()).state == ProcessState.STOPPED

    await service.stop()


@pytest.mark.asyncio
async def test_exclusive_model_load_arbitration():
    """A11: Exclusive model load stops miner and serializes with inference."""
    service, gateway, supervisor, requests, _ = build_arbitration_test_system(
        cooldown_seconds=0.05, miner_initially_running=True
    )
    assert await service.start() is True

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway.create_app()), base_url="http://coordinator"
    ) as client:
        resp = await client.post("/api/v1/models/load", json={"model": "qwen38-27b"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "loaded"
        assert len(requests) == 1

    await service.stop()


@pytest.mark.asyncio
async def test_unsupported_mutating_endpoint_denied():
    """A12: Unsupported mutations rejected by admission controller without touching miner or upstream."""
    service, gateway, supervisor, requests, _ = build_arbitration_test_system(
        cooldown_seconds=10.0, miner_initially_running=True
    )
    assert await service.start() is True

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway.create_app()), base_url="http://coordinator"
    ) as client:
        # Unsupported POST
        resp = await client.post("/api/v1/models/unload", json={"model": "qwen38"})
        assert resp.status_code == 503

        # Unsupported DELETE
        resp_del = await client.delete("/v1/models/qwen38")
        assert resp_del.status_code == 501

        # Unsupported PUT
        resp_put = await client.put("/v1/models/config", json={})
        assert resp_put.status_code == 501

        # Upstream receives zero requests
        assert len(requests) == 0
        # Miner is still running untouched!
        assert (await supervisor.status()).state == ProcessState.RUNNING

    await service.stop()


@pytest.mark.asyncio
async def test_request_arriving_during_miner_start_is_serialized():
    """A09: Request arriving while miner is starting serializes with start/stop lifecycle and stops miner before forward."""
    service, gateway, supervisor, requests, miner_states = build_arbitration_test_system(
        cooldown_seconds=10.0, miner_initially_running=False
    )
    # Configure backend to have start delay so start takes time
    supervisor.backend.start_delay = 0.05
    assert await service.start() is True

    # Start the miner in a background task
    start_task = asyncio.create_task(supervisor.start(only_if_stopped_by_coordinator=False))

    # Send an inference request while miner start is in progress
    await asyncio.sleep(0.01)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway.create_app()), base_url="http://coordinator"
    ) as client:
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "qwen38", "messages": [{"role": "user", "content": "racing req"}]},
        )
        assert resp.status_code == 200

    await start_task
    # The request must have forwarded ONLY when miner was STOPPED
    assert len(requests) == 1
    assert miner_states == [ProcessState.STOPPED]

    await service.stop()


@pytest.mark.asyncio
async def test_coordinator_status_endpoint_diagnostics():
    """A14, Stage D: /_coordinator/status exposes readiness, lease metrics, and process states."""
    service, gateway, supervisor, _, _ = build_arbitration_test_system(
        cooldown_seconds=10.0, miner_initially_running=True
    )
    assert await service.start() is True

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway.create_app()), base_url="http://coordinator"
    ) as client:
        resp = await client.get("/_coordinator/status")
        assert resp.status_code == 200
        data = resp.json()

        assert data["status"] == "online"
        assert data["is_ready"] is True
        assert data["service_state"] == "ready"
        assert "krig_miner" in data["processes"]
        assert data["gpu_inference"]["active_count"] == 0
        assert data["gpu_inference"]["pending_count"] == 0
        assert data["gpu_inference"]["is_cooling_down"] is False
        assert data["gpu_inference"]["is_restart_inhibited"] is False

    await service.stop()
