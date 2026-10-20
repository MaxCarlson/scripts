"""Factory-to-ASGI integration tests with isolated process and upstream fakes."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from resource_coordinator import config as config_module
from resource_coordinator.config import build_system, load_config
from resource_coordinator.core.leases import LeaseManager, LeaseType
from resource_coordinator.core.processes import (
    FakeProcessBackend,
    ProcessLifecycleOwner,
    ProcessState,
)
from resource_coordinator.core.service import CoordinatorService


class ControlledClock:
    """Monotonic clock whose sleepers advance only when a test requests it."""

    def __init__(self) -> None:
        self.now = 0.0
        self._sleepers: list[tuple[float, asyncio.Future[None]]] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        future = asyncio.get_running_loop().create_future()
        sleeper = (self.now + seconds, future)
        self._sleepers.append(sleeper)
        try:
            await future
        finally:
            self._sleepers.remove(sleeper)

    def advance(self, seconds: float) -> None:
        self.now += seconds
        for deadline, future in tuple(self._sleepers):
            if deadline <= self.now and not future.done():
                future.set_result(None)

    async def settle(self) -> None:
        for _ in range(8):
            await asyncio.sleep(0)


def make_isolated_config(path: Path, process_name: str, cooldown_seconds: float = 5.0) -> None:
    """Write test-only JSON configuration with no production process or endpoint references."""
    fake_executable = f"FAKE-ONLY://{process_name}"
    config = {
        "version": "1.0",
        "service": {
            "listen_host": "127.0.0.1",
            "listen_port": 18765,
            "upstream_url": "http://resource-coordinator-upstream.invalid",
        },
        "processes": {
            process_name: {
                "backend": "fake",
                "executable": fake_executable,
                "arguments": ["--fake-integration-target"],
                "working_directory": None,
                "allow_external_stop": False,
                "allow_external_restart": False,
                "adopt_external": False,
                "allow_force_termination": False,
            }
        },
        "policies": [
            {
                "name": "fake-integration-inference",
                "trigger_event": "lmstudio.inference_requested",
                "target_process": process_name,
                "stop_process": True,
                "restart_process": True,
                "only_if_stopped_by_coordinator": True,
                "resource": "gpu.inference",
                "lease_type": "shared",
                "cooldown_seconds": cooldown_seconds,
            },
            {
                "name": "fake-integration-model-load",
                "trigger_event": "lmstudio.model_load_requested",
                "target_process": process_name,
                "stop_process": True,
                "restart_process": True,
                "only_if_stopped_by_coordinator": True,
                "resource": "gpu.inference",
                "lease_type": "exclusive",
                "cooldown_seconds": cooldown_seconds,
            },
        ],
    }
    serialized = json.dumps(config)
    assert "krig" not in serialized.lower()
    assert "1234" not in serialized
    assert "1235" not in serialized
    assert "127.0.0.1:1234" not in serialized
    assert "token" not in serialized.lower()
    path.write_text(serialized, encoding="utf-8")


async def make_factory_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clock: ControlledClock,
    *,
    initially_running: bool = True,
    upstream_mode: str = "complete",
) -> tuple[Any, CoordinatorService, httpx.AsyncClient, FakeProcessBackend, list[str]]:
    process_name = f"fake_target_{uuid4().hex}"
    config_path = tmp_path / f"{process_name}.json"
    make_isolated_config(config_path, process_name)

    class ClockedLeaseManager(LeaseManager):
        def __init__(self, default_cooldown_seconds: float = 60.0, event_dispatcher: Any = None) -> None:
            super().__init__(
                default_cooldown_seconds=default_cooldown_seconds,
                event_dispatcher=event_dispatcher,
                monotonic_clock=clock.monotonic,
                sleep=clock.sleep,
            )

    monkeypatch.setattr(config_module, "LeaseManager", ClockedLeaseManager)
    config = load_config(config_path)
    assert config.processes[process_name].backend == "fake"
    assert config.service.upstream_url == "http://resource-coordinator-upstream.invalid"
    system = build_system(config, use_fake_processes=True)
    supervisor = system.supervisors[process_name]
    backend = supervisor.backend
    assert isinstance(backend, FakeProcessBackend)

    if initially_running:
        backend.running = True
        backend.lifecycle_owner = ProcessLifecycleOwner.COORDINATOR
        backend.is_coordinator_owned = True
        backend.pid = 987654
        backend.create_time = 1.0
    timeline: list[str] = []

    original_stop = backend.stop
    original_start = backend.start

    async def record_stop(timeout: float = 10.0) -> bool:
        timeline.append("process_stop_requested")
        success = await original_stop(timeout)
        if success and (await backend.status()).state == ProcessState.STOPPED:
            timeline.append("process_stopped_verified")
        return success

    async def record_start() -> bool:
        assert system.lease_mgr.active_count("gpu.inference") == 0
        assert system.lease_mgr.pending_count("gpu.inference") == 0
        assert not system.lease_mgr.is_restart_inhibited("gpu.inference")
        timeline.append("process_start_requested_when_eligible")
        success = await original_start()
        if success:
            timeline.append("process_restarted")
        return success

    backend.stop = record_stop  # type: ignore[method-assign]
    backend.start = record_start  # type: ignore[method-assign]

    async def handle_chat(request: Request) -> JSONResponse:
        timeline.append("mock_inference_forwarded")
        assert system.lease_mgr.active_count("gpu.inference") == 1
        assert (await supervisor.status()).state == ProcessState.STOPPED
        if upstream_mode == "incomplete":
            return JSONResponse({"choices": [{"finish_reason": None, "message": {"content": "partial"}}]})
        return JSONResponse({"choices": [{"finish_reason": "stop", "message": {"content": "mock result"}}]})

    async def handle_load(request: Request) -> JSONResponse:
        timeline.append("mock_model_load_forwarded")
        leases = system.lease_mgr.active_leases_for("gpu.inference")
        assert len(leases) == 1
        assert leases[0].lease_type == LeaseType.EXCLUSIVE
        assert (await supervisor.status()).state == ProcessState.STOPPED
        return JSONResponse({"status": "loaded", "model": "fake-model"})

    upstream = Starlette(
        routes=[
            Route("/v1/chat/completions", handle_chat, methods=["POST"]),
            Route("/api/v0/model/load", handle_load, methods=["POST"]),
        ]
    )
    system.gateway._http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=upstream),
        base_url=config.service.upstream_url,
    )

    admission_calls: dict[str, int] = {}
    original_evaluate = system.gateway.admission_controller.evaluate

    def record_admission(method: str, path: str):
        decision = original_evaluate(method, path)
        if decision.allowed and decision.operation_kind.value in {"inference", "model_load"}:
            count = admission_calls.get(path, 0)
            if count % 2 == 0:
                timeline.append("protected_request_admitted")
            admission_calls[path] = count + 1
        return decision

    system.gateway.admission_controller.evaluate = record_admission  # type: ignore[method-assign]

    def record_event(name: str, marker: str):
        async def handler(event: Any) -> None:
            if name == "process.stopped":
                assert (await supervisor.status()).state == ProcessState.STOPPED
            if name == "resource.idle":
                assert event.data["resource"] == "gpu.inference"
            if name == "lmstudio.inference_finished":
                if event.data["status"] == "completed":
                    timeline.append("mock_inference_confirmed_complete")
                else:
                    timeline.append("mock_inference_uncertain")
                return
            if name == "lmstudio.model_load_finished":
                if event.data["status"] == "completed":
                    timeline.append("mock_model_load_confirmed_complete")
                return
            timeline.append(marker)

        system.dispatcher.on(name, handler)

    record_event("resource.lease_requested", "resource_reservation_established")
    record_event("resource.acquired", "resource_lease_activated")
    record_event("process.stop_requested", "supervisor_stop_requested")
    record_event("process.stopped", "supervisor_stop_verified")
    record_event("resource.idle", "idle_timeout_elapsed")
    record_event("lmstudio.inference_finished", "inference_finished")
    record_event("lmstudio.model_load_finished", "model_load_finished")

    system.dispatcher.on(
        "lmstudio.inference_requested",
        lambda event: timeline.append("inference_operation_admitted"),
        is_blocking=True,
        priority=100,
    )
    system.dispatcher.on(
        "lmstudio.model_load_requested",
        lambda event: timeline.append("model_load_operation_admitted"),
        is_blocking=True,
        priority=100,
    )

    service = CoordinatorService(system)
    app = system.gateway.create_app(service)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://coordinator.test")
    return app, service, client, backend, timeline


@pytest.mark.asyncio
async def test_factory_lifespan_inference_cooldown_model_load_and_second_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = ControlledClock()
    app, service, client, backend, timeline = await make_factory_app(tmp_path, monkeypatch, clock)

    async with app.router.lifespan_context(app):
        assert service.is_ready
        first = await client.post("/v1/chat/completions", json={"model": "fake-model", "messages": []})
        assert first.status_code == 200
        assert backend.running is False
        assert service.system.lease_mgr.is_cooling_down("gpu.inference")

        required_order = [
            "protected_request_admitted",
            "resource_reservation_established",
            "supervisor_stop_requested",
            "supervisor_stop_verified",
            "resource_lease_activated",
            "mock_inference_forwarded",
            "mock_inference_confirmed_complete",
        ]
        positions = [timeline.index(marker) for marker in required_order]
        assert positions == sorted(positions)

        await clock.settle()
        clock.advance(3.0)
        await clock.settle()
        assert service.system.lease_mgr.cooldown_remaining("gpu.inference") == 2.0
        second = await client.post("/v1/chat/completions", json={"model": "fake-model", "messages": []})
        assert second.status_code == 200
        assert backend.running is False
        assert timeline.count("process_restarted") == 0
        assert service.system.lease_mgr.cooldown_remaining("gpu.inference") == 5.0

        await clock.settle()
        clock.advance(4.0)
        await clock.settle()
        assert backend.running is False
        clock.advance(1.0)
        timeline.append("idle_timeout_elapsed")
        await clock.settle()
        assert backend.running is True
        assert timeline.index("idle_timeout_elapsed") < timeline.index("process_start_requested_when_eligible")
        assert timeline.index("process_start_requested_when_eligible") < timeline.index("process_restarted")

        load = await client.post("/api/v0/model/load", json={"model": "fake-model"})
        assert load.status_code == 200
        assert backend.running is False
        assert "mock_model_load_forwarded" in timeline
        assert "mock_model_load_confirmed_complete" in timeline

        restarted_index = timeline.index("process_restarted")
        load_admitted = timeline.index("protected_request_admitted", restarted_index + 1)
        load_reserved = timeline.index("resource_reservation_established", load_admitted)
        load_stopped = timeline.index("supervisor_stop_verified", load_reserved)
        load_forward = timeline.index("mock_model_load_forwarded", load_stopped)
        load_completed = timeline.index("mock_model_load_confirmed_complete", load_forward)
        assert load_admitted < load_reserved < load_stopped < load_forward < load_completed

        await clock.settle()
        clock.advance(5.0)
        await clock.settle()
        assert backend.running is True

    await client.aclose()


@pytest.mark.asyncio
async def test_factory_does_not_restart_initially_stopped_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = ControlledClock()
    app, service, client, backend, timeline = await make_factory_app(
        tmp_path, monkeypatch, clock, initially_running=False
    )

    async with app.router.lifespan_context(app):
        response = await client.post("/v1/chat/completions", json={"model": "fake-model", "messages": []})
        assert response.status_code == 200
        await clock.settle()
        clock.advance(30.0)
        await clock.settle()
        assert backend.running is False
        assert not service.system.supervisors[backend.name].was_stopped_by_coordinator
        assert "process_restarted" not in timeline

    await client.aclose()


@pytest.mark.asyncio
async def test_factory_keeps_restart_inhibited_for_incomplete_upstream_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = ControlledClock()
    app, service, client, backend, timeline = await make_factory_app(
        tmp_path, monkeypatch, clock, upstream_mode="incomplete"
    )

    async with app.router.lifespan_context(app):
        response = await client.post("/v1/chat/completions", json={"model": "fake-model", "messages": []})
        assert response.status_code == 200
        assert service.system.lease_mgr.is_restart_inhibited("gpu.inference")
        assert timeline[-1] in {"inference_finished", "mock_inference_uncertain"}
        await clock.settle()
        clock.advance(30.0)
        await clock.settle()
        assert backend.running is False
        assert "process_restarted" not in timeline

    await client.aclose()
