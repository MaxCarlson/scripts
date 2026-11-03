"""
Phase 01 Proxy Chain Integration Test Suite.

End-to-end chained routing:
Client -> LLM Monitor gateway -> Resource Coordinator -> Mock LM Studio

Verifies:
- A13: Chained proxy forwarding works seamlessly for streaming and non-streaming.
- A14: Monitor recording unhealthy fail-closed contract is preserved.
- A15: Downstream client disconnect / incomplete stream causes Coordinator to inhibit restart.
- Coordinator lease management and 10s debounce remain authoritative throughout the chain.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import List, Optional

import httpx
import pytest
from fastapi import FastAPI
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

# Ensure llm_monitor is importable from scripts repo
scripts_root = Path(__file__).resolve().parent.parent.parent.parent
llm_monitor_path = scripts_root / "modules" / "llm_monitor"
if str(llm_monitor_path) not in sys.path:
    sys.path.insert(0, str(llm_monitor_path))

from llm_monitor.gateway import OpenAIInferenceGateway, RequestEventHub
from llm_monitor.live_store import LiveInferenceStore
from resource_coordinator.adapters.lmstudio.gateway import LMStudioGateway
from resource_coordinator.config import (
    CoordinatorConfig,
    PolicyConfig,
    ProcessConfig,
    ServiceConfig,
    build_system,
)
from resource_coordinator.core.actions import StartProcessAction, StopProcessAction
from resource_coordinator.core.events import EventDispatcher
from resource_coordinator.core.leases import LeaseManager, LeaseType
from resource_coordinator.core.policies import Policy, PolicyEngine
from resource_coordinator.core.processes import (
    FakeProcessBackend,
    ProcessState,
    ProcessSupervisor,
)
from resource_coordinator.core.service import CoordinatorService


def create_mock_lmstudio_upstream():
    upstream_calls = []

    async def handle_chat(request: Request) -> Response:
        body = await request.json()
        upstream_calls.append(body)

        if body.get("stream"):

            async def event_generator():
                yield b'data: {"choices": [{"delta": {"content": "Hello"}}]}\n\n'
                if not body.get("truncate"):
                    yield b'data: {"choices": [{"delta": {"content": " world"}}]}\n\n'
                    yield b"data: [DONE]\n\n"

            return StreamingResponse(event_generator(), media_type="text/event-stream")

        return JSONResponse(
            {
                "id": "chatcmpl-chained-test",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Chained proxy response"},
                        "finish_reason": "stop",
                    }
                ],
            }
        )

    app = Starlette(routes=[Route("/v1/chat/completions", handle_chat, methods=["POST"])])
    return app, upstream_calls


def setup_proxy_chain(
    cooldown_seconds: float = 0.05,
    miner_running: bool = True,
    capture_enabled: bool = True,
    recorder: Optional[Any] = None,
):
    """
    Sets up:
    Mock LM Studio (App)
    ^
    Coordinator Gateway (App, using ASGITransport to Mock LM Studio)
    ^
    LLM Monitor Gateway (App, using ASGITransport to Coordinator Gateway)
    """
    upstream_app, upstream_calls = create_mock_lmstudio_upstream()
    upstream_transport = httpx.ASGITransport(app=upstream_app)
    upstream_client = httpx.AsyncClient(transport=upstream_transport, base_url="http://127.0.0.1:1234")

    dispatcher = EventDispatcher()
    lease_mgr = LeaseManager(default_cooldown_seconds=cooldown_seconds, event_dispatcher=dispatcher)
    backend = FakeProcessBackend(name="krig_miner", running=miner_running, executable="/bin/krig")
    supervisor = ProcessSupervisor(backend=backend, event_dispatcher=dispatcher)

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

    coordinator_gateway = LMStudioGateway(
        upstream_url="http://127.0.0.1:1234",
        event_dispatcher=dispatcher,
        lease_manager=lease_mgr,
        standalone=False,
    )
    coordinator_gateway._http_client = upstream_client

    config = CoordinatorConfig(
        version="1.0",
        service=ServiceConfig(listen_host="127.0.0.1", listen_port=1235, upstream_url="http://127.0.0.1:1234"),
        processes={
            "krig_miner": ProcessConfig(
                name="krig_miner", backend="fake", executable="/bin/krig", stop_timeout_seconds=5.0
            )
        },
        policies=[
            PolicyConfig(
                name="pause_for_inference",
                trigger_event="lmstudio.inference_requested",
                target_process="krig_miner",
                stop_process=True,
                resource="gpu.inference",
                cooldown_seconds=cooldown_seconds,
                restart_process=True,
            )
        ],
    )
    system = build_system(config, use_fake_processes=True)
    system.supervisors["krig_miner"] = supervisor
    system.lease_mgr = lease_mgr
    system.dispatcher = dispatcher
    system.gateway = coordinator_gateway
    system.policy_engine = policy_engine

    coordinator_service = CoordinatorService(system)
    coordinator_app = coordinator_gateway.create_app()

    # LLM Monitor Gateway pointing to Coordinator
    coordinator_transport = httpx.ASGITransport(app=coordinator_app)
    monitor_to_coord_client = httpx.AsyncClient(
        transport=coordinator_transport, base_url="http://127.0.0.1:1235"
    )

    monitor_store = LiveInferenceStore()
    monitor_events = RequestEventHub()
    monitor_gateway = OpenAIInferenceGateway(
        upstream="http://127.0.0.1:1235",
        store=monitor_store,
        events=monitor_events,
        client=monitor_to_coord_client,
        capture_enabled=capture_enabled,
        recorder=recorder,
    )

    monitor_app = FastAPI()
    monitor_app.include_router(monitor_gateway.router())

    return (
        monitor_app,
        coordinator_service,
        supervisor,
        lease_mgr,
        upstream_calls,
        monitor_store,
    )


@pytest.mark.asyncio
async def test_chained_non_streaming_inference():
    """A13: Client -> Monitor -> Coordinator -> LM Studio non-streaming request."""
    (
        monitor_app,
        coord_service,
        supervisor,
        lease_mgr,
        upstream_calls,
        monitor_store,
    ) = setup_proxy_chain(cooldown_seconds=0.05, miner_running=True)

    assert await coord_service.start() is True
    assert (await supervisor.status()).state == ProcessState.RUNNING

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=monitor_app), base_url="http://llm-monitor"
    ) as client:
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "qwen38", "messages": [{"role": "user", "content": "hello chain"}]},
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["choices"][0]["message"]["content"] == "Chained proxy response"

        # Upstream received the request
        assert len(upstream_calls) == 1

        # Monitor recorded the request
        records = monitor_store.requests()
        assert len(records) >= 1
        assert records[0].model_name == "qwen38"

        # Coordinator cooldown started and miner resumes after cooldown
        assert lease_mgr.is_cooling_down("gpu.inference")
        for _ in range(15):
            await asyncio.sleep(0.02)
            if (await supervisor.status()).state == ProcessState.RUNNING:
                break
        assert (await supervisor.status()).state == ProcessState.RUNNING

    await coord_service.stop()


@pytest.mark.asyncio
async def test_chained_streaming_inference():
    """A13: Client -> Monitor -> Coordinator -> LM Studio streaming request with [DONE]."""
    (
        monitor_app,
        coord_service,
        supervisor,
        lease_mgr,
        upstream_calls,
        monitor_store,
    ) = setup_proxy_chain(cooldown_seconds=0.05, miner_running=True)

    assert await coord_service.start() is True

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=monitor_app), base_url="http://llm-monitor"
    ) as client:
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "qwen38",
                "stream": True,
                "messages": [{"role": "user", "content": "stream chain"}],
            },
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 200
        content = resp.text
        assert "[DONE]" in content
        assert "Hello" in content
        assert "world" in content

        # Upstream received request
        assert len(upstream_calls) == 1

        # Coordinator cooldown completed and miner resumes
        for _ in range(15):
            await asyncio.sleep(0.02)
            if (await supervisor.status()).state == ProcessState.RUNNING:
                break
        assert (await supervisor.status()).state == ProcessState.RUNNING

    await coord_service.stop()


@pytest.mark.asyncio
async def test_chained_truncated_stream_causes_coordinator_inhibition():
    """A15: If stream terminates prematurely without [DONE], coordinator inhibits miner restart."""
    (
        monitor_app,
        coord_service,
        supervisor,
        lease_mgr,
        upstream_calls,
        _,
    ) = setup_proxy_chain(cooldown_seconds=0.05, miner_running=True)

    assert await coord_service.start() is True

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=monitor_app), base_url="http://llm-monitor"
    ) as client:
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "qwen38",
                "stream": True,
                "truncate": True,
                "messages": [{"role": "user", "content": "truncated"}],
            },
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 200

        # Coordinator MUST detect missing [DONE] and inhibit restart!
        assert lease_mgr.is_restart_inhibited("gpu.inference")
        # Even after waiting past cooldown, miner MUST NOT restart
        await asyncio.sleep(0.08)
        assert (await supervisor.status()).state == ProcessState.STOPPED

    await coord_service.stop()


@pytest.mark.asyncio
async def test_chained_unhealthy_recorder_fails_closed():
    """A14: When monitor recorder is unhealthy, dispatch is blocked before reaching coordinator."""
    class FakeUnhealthyRecorder:
        is_healthy = False

    (
        monitor_app,
        coord_service,
        supervisor,
        lease_mgr,
        upstream_calls,
        _,
    ) = setup_proxy_chain(
        cooldown_seconds=0.05,
        miner_running=True,
        capture_enabled=True,
        recorder=FakeUnhealthyRecorder(),
    )

    assert await coord_service.start() is True

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=monitor_app), base_url="http://llm-monitor"
    ) as client:
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "qwen38", "messages": [{"role": "user", "content": "test"}]},
            headers={"content-type": "application/json"},
        )
        # Monitor rejects with 503
        assert resp.status_code == 503
        assert "Inference recording is unhealthy" in resp.json()["detail"]

        # Coordinator and upstream are never called
        assert len(upstream_calls) == 0
        assert lease_mgr.active_count("gpu.inference") == 0
        # Miner is still running untouched!
        assert (await supervisor.status()).state == ProcessState.RUNNING

    await coord_service.stop()
