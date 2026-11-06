"""
Unit tests for CoordinatorService lifecycle, readiness state machine, preflight, and abort.
"""

import asyncio
import httpx
import pytest

from resource_coordinator.config import CoordinatorConfig, ProcessConfig, PolicyConfig, ServiceConfig, build_system
from resource_coordinator.core.service import CoordinatorService, ServiceState


@pytest.fixture
def minimal_system():
    config = CoordinatorConfig()
    return build_system(config, use_fake_processes=True)


@pytest.mark.asyncio
async def test_service_initial_state_created(minimal_system):
    service = CoordinatorService(minimal_system)
    assert service.state == ServiceState.CREATED
    assert service.is_ready is False
    assert len(service.runtime_identity["revision"]) == 64
    assert service.runtime_identity["source_path"].endswith("__init__.py")


def test_service_keeps_startup_runtime_identity_after_source_changes(minimal_system, monkeypatch):
    import resource_coordinator.core.service as service_module

    captured = {"version": "0.10.0", "source_path": "C:/source/__init__.py", "revision": "startup-revision"}
    monkeypatch.setattr(service_module, "build_runtime_identity", lambda: dict(captured))
    service = CoordinatorService(minimal_system)
    monkeypatch.setattr(service_module, "build_runtime_identity",
                        lambda: {**captured, "revision": "new-checkout-revision"})

    assert service.runtime_identity["revision"] == "startup-revision"


@pytest.mark.asyncio
async def test_service_startup_to_ready(minimal_system):
    service = CoordinatorService(minimal_system)
    started = await service.start()
    assert started is True
    assert service.state == ServiceState.READY
    assert service.is_ready is True
    assert service.failure_reason is None


@pytest.mark.asyncio
async def test_manual_miner_pause_persists_deadline_and_resumes_safely(tmp_path):
    from resource_coordinator.core.durable_state import StateCodec
    from resource_coordinator.core.processes import ProcessState

    state_path = tmp_path / "coordinator.json"
    config = CoordinatorConfig(
        service=ServiceConfig(state_persistence_path=str(state_path)),
        processes={"krig": ProcessConfig(name="krig", backend="fake")},
        policies=[PolicyConfig(
            name="stop", trigger_event="lmstudio.inference_requested", target_process="krig",
            resource="gpu.inference", cooldown_seconds=0.01,
        )],
    )
    system = build_system(config, use_fake_processes=True)
    system.lease_mgr.set_resource_cooldown("gpu.model_loading", 0)
    service = CoordinatorService(system, start_miner_on_ready=True, first_boot=True,
                                 supervision_poll_interval=0.01)
    assert await service.start()
    result = await service.manual_miner_control("pause", duration_seconds=0.05)
    assert result["status"] == "paused"
    supervisor = system.supervisors["krig"]
    assert supervisor.is_manual_override
    assert supervisor.manual_override_until is not None
    assert StateCodec.load(state_path).processes["krig"].manual_override_until == supervisor.manual_override_until
    await asyncio.sleep(0.15)
    assert not supervisor.is_manual_override
    assert (await supervisor.status()).state == ProcessState.RUNNING
    await service.stop()


@pytest.mark.asyncio
async def test_manual_miner_http_control_requires_operator_token(tmp_path, monkeypatch):
    from resource_coordinator.core.durable_state import StateCodec
    from resource_coordinator.core.processes import ProcessState

    state_path = tmp_path / "coordinator.json"
    config = CoordinatorConfig(
        service=ServiceConfig(state_persistence_path=str(state_path)),
        processes={"krig": ProcessConfig(name="krig", backend="fake")},
        policies=[PolicyConfig(name="stop", trigger_event="lmstudio.inference_requested",
                               target_process="krig", resource="gpu.inference", cooldown_seconds=0)],
    )
    system = build_system(config, use_fake_processes=True)
    service = CoordinatorService(system, start_miner_on_ready=True, first_boot=True)
    assert await service.start()
    app = system.gateway.create_app(service)
    monkeypatch.setenv("RESOURCE_COORDINATOR_OPERATOR_TOKEN", "test-token")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        body = {"operator": "test", "reason": "pause for maintenance", "duration_seconds": 600}
        denied = await client.post("/_coordinator/miner/pause", json=body)
        assert denied.status_code == 403
        assert (await system.miner_adapter.status()).state == ProcessState.RUNNING
        accepted = await client.post("/_coordinator/miner/pause", headers={"Authorization": "Bearer test-token"},
                                     json=body)
        assert accepted.status_code == 200
        assert accepted.json()["status"] == "paused"
        persisted = StateCodec.load(state_path).processes["krig"]
        assert persisted.is_manual_override and persisted.manual_override_until is not None
    await service.stop()


@pytest.mark.asyncio
async def test_manual_miner_http_controls_start_stop_pause_resume_and_status(tmp_path, monkeypatch):
    from resource_coordinator.core.durable_state import StateCodec
    from resource_coordinator.core.processes import ProcessState

    state_path = tmp_path / "coordinator.json"
    config = CoordinatorConfig(
        service=ServiceConfig(state_persistence_path=str(state_path)),
        processes={"krig": ProcessConfig(name="krig", backend="fake")},
        policies=[PolicyConfig(
            name="stop", trigger_event="lmstudio.inference_requested", target_process="krig",
            resource="gpu.inference", cooldown_seconds=0.05,
        )],
    )
    system = build_system(config, use_fake_processes=True)
    system.lease_mgr.set_resource_cooldown("gpu.model_loading", 0)
    system.lease_mgr.set_resource_cooldown("gpu.inference", 0.05)
    service = CoordinatorService(system, start_miner_on_ready=True, first_boot=True)
    assert await service.start()
    monkeypatch.setenv("RESOURCE_COORDINATOR_OPERATOR_TOKEN", "test-token")
    app = system.gateway.create_app(service)
    headers = {"Authorization": "Bearer test-token"}

    async def wait_for_inference_cooldown():
        deadline = asyncio.get_running_loop().time() + 1.0
        while system.lease_mgr.is_cooling_down("gpu.inference") and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.005)
        assert not system.lease_mgr.is_cooling_down("gpu.inference")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        async with system.lease_mgr.acquire("gpu.inference", holder_id="inference-in-flight"):
            blocked = await client.post(
                "/_coordinator/miner/stop", headers=headers,
                json={"operator": "test", "reason": "must respect inference"},
            )
            assert blocked.status_code == 409
            assert blocked.json()["status"] == "blocked"
            assert blocked.json()["reason"] == "GPU claims, cooldown, inhibition, or safety gate is active"
            assert blocked.json()["operator_reason"] == "must respect inference"
            assert (await system.miner_adapter.status()).state == ProcessState.RUNNING
            gaming = await client.post(
                "/_coordinator/gaming/start", headers=headers,
                json={"operator": "test", "reason": "must respect inference"},
            )
            assert gaming.status_code == 409
            assert gaming.json()["reason"] == "GPU claims, cooldown, inhibition, or safety gate is active"
            assert gaming.json()["operator_reason"] == "must respect inference"

        cooling_down = await client.post(
            "/_coordinator/miner/stop", headers=headers,
            json={"operator": "test", "reason": "must respect cooldown"},
        )
        assert cooling_down.status_code == 409
        assert cooling_down.json()["status"] == "blocked"
        assert cooling_down.json()["operator_reason"] == "must respect cooldown"
        assert cooling_down.json()["reason"] == "GPU claims, cooldown, inhibition, or safety gate is active"
        assert (await system.miner_adapter.status()).state == ProcessState.RUNNING
        await wait_for_inference_cooldown()

        stopped = await client.post(
            "/_coordinator/miner/stop", headers=headers,
            json={"operator": "test", "reason": "manual stop"},
        )
        assert stopped.status_code == 200 and stopped.json()["status"] == "stopped", stopped.text
        persisted = StateCodec.load(state_path).processes["krig"]
        assert persisted.is_manual_override and persisted.was_stopped_by_coordinator
        await wait_for_inference_cooldown()

        started = await client.post(
            "/_coordinator/miner/start", headers=headers,
            json={"operator": "test", "reason": "manual start"},
        )
        assert started.status_code == 200 and started.json()["status"] == "running"
        await wait_for_inference_cooldown()

        paused = await client.post(
            "/_coordinator/miner/pause", headers=headers,
            json={"operator": "test", "reason": "timed pause", "duration_seconds": 60},
        )
        assert paused.status_code == 200 and paused.json()["status"] == "paused"
        await wait_for_inference_cooldown()

        resumed = await client.post(
            "/_coordinator/miner/resume", headers=headers,
            json={"operator": "test", "reason": "manual resume"},
        )
        assert resumed.status_code == 200 and resumed.json()["status"] == "running"

        status = await client.get("/_coordinator/miner/status")
        assert status.status_code == 200
        assert status.json()["process"]["state"] == "running"
        assert status.json()["process"]["is_coordinator_owned"] is True
    await service.stop()


@pytest.mark.asyncio
async def test_gaming_mode_unloads_models_then_restores_model_and_owned_miner(tmp_path):
    import json
    from resource_coordinator.core.durable_state import StateCodec
    from resource_coordinator.core.processes import ProcessState

    state_path = tmp_path / "coordinator.json"
    config = CoordinatorConfig(
        service=ServiceConfig(state_persistence_path=str(state_path), upstream_url="http://lmstudio:1234"),
        processes={"krig": ProcessConfig(name="krig", backend="fake")},
        policies=[PolicyConfig(name="stop", trigger_event="lmstudio.inference_requested",
                               target_process="krig", resource="gpu.inference", cooldown_seconds=0)],
    )
    loaded = [{"type": "llm", "key": "publisher/model", "loaded_instances": [
        {"id": "instance-1", "config": {"context_length": 4096}}
    ]}]

    async def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"models": loaded})
        body = json.loads(request.content or b"{}")
        if request.url.path.endswith("/unload"):
            loaded[0]["loaded_instances"] = []
            return httpx.Response(200, json={"instance_id": body["instance_id"]})
        loaded[0]["loaded_instances"] = [{"id": "instance-restored", "config": body}]
        return httpx.Response(200, json={"status": "loaded"})

    def client_factory(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    system = build_system(config, use_fake_processes=True)
    system.lease_mgr.set_resource_cooldown("gpu.model_loading", 0)
    service = CoordinatorService(system, start_miner_on_ready=True, first_boot=True,
                                 lmstudio_client_factory=client_factory)
    assert await service.start()
    gaming_result = await service.gaming_control("start")
    assert gaming_result["status"] == "active", gaming_result
    assert loaded[0]["loaded_instances"] == []
    assert (await system.miner_adapter.status()).state == ProcessState.STOPPED
    assert StateCodec.load(state_path).gaming_mode["state"] == "active"
    await service.stop()

    restored_system = build_system(config, use_fake_processes=True)
    restored_system.lease_mgr.set_resource_cooldown("gpu.model_loading", 0)
    restored_service = CoordinatorService(restored_system, start_miner_on_ready=True,
                                         lmstudio_client_factory=client_factory)
    assert await restored_service.start()
    assert restored_system.miner_adapter.is_manual_override
    assert (await restored_service.gaming_control("status"))["state"] == "active"
    stop_result = await restored_service.gaming_control("stop")
    assert stop_result["status"] == "inactive", stop_result
    assert loaded[0]["loaded_instances"][0]["config"]["context_length"] == 4096
    assert (await restored_system.miner_adapter.status()).state == ProcessState.RUNNING
    assert StateCodec.load(state_path).gaming_mode["state"] == "inactive"
    await restored_service.stop()


@pytest.mark.asyncio
async def test_gpu_idle_pause_persists_across_restart_and_resumes_after_complete_window(tmp_path):
    from resource_coordinator.monitors.gpu import GpuDeviceMetrics
    from resource_coordinator.core.durable_state import StateCodec
    from resource_coordinator.core.processes import ProcessState

    state_path = tmp_path / "coordinator.json"
    config = CoordinatorConfig(
        service=ServiceConfig(state_persistence_path=str(state_path)),
        processes={"krig": ProcessConfig(name="krig", backend="fake")},
        policies=[PolicyConfig(name="stop", trigger_event="lmstudio.inference_requested",
                               target_process="krig", resource="gpu.inference", cooldown_seconds=0)],
    )

    class IdleGpu:
        async def get_metrics(self):
            return [GpuDeviceMetrics("gpu-0", 5.0)]

    system = build_system(config, use_fake_processes=True)
    system.lease_mgr.set_resource_cooldown("gpu.model_loading", 0)
    service = CoordinatorService(system, start_miner_on_ready=True, first_boot=True,
                                 supervision_poll_interval=0.01, gpu_monitor=IdleGpu())
    assert await service.start()
    result = await service.manual_miner_control("pause", threshold_pct=20, window_seconds=0.06)
    assert result["status"] == "paused"
    persisted = StateCodec.load(state_path).gpu_idle_condition
    assert persisted["threshold_pct"] == 20 and persisted["window_seconds"] == 0.06
    await service.stop()

    restarted_system = build_system(config, use_fake_processes=True)
    restarted_system.lease_mgr.set_resource_cooldown("gpu.model_loading", 0)
    restarted = CoordinatorService(restarted_system, start_miner_on_ready=True,
                                  supervision_poll_interval=0.01, gpu_monitor=IdleGpu())
    assert await restarted.start()
    deadline = asyncio.get_running_loop().time() + 1.0
    while asyncio.get_running_loop().time() < deadline:
        if (await restarted_system.miner_adapter.status()).state == ProcessState.RUNNING:
            break
        await asyncio.sleep(0.01)
    assert (await restarted_system.miner_adapter.status()).state == ProcessState.RUNNING
    assert StateCodec.load(state_path).gpu_idle_condition == {}
    await restarted.stop()


@pytest.mark.asyncio
async def test_gpu_idle_pause_keeps_miner_stopped_when_telemetry_is_missing(tmp_path):
    from resource_coordinator.core.durable_state import StateCodec
    from resource_coordinator.core.processes import ProcessState

    state_path = tmp_path / "coordinator.json"
    config = CoordinatorConfig(
        service=ServiceConfig(state_persistence_path=str(state_path)),
        processes={"krig": ProcessConfig(name="krig", backend="fake")},
        policies=[PolicyConfig(name="stop", trigger_event="lmstudio.inference_requested",
                               target_process="krig", resource="gpu.inference", cooldown_seconds=0)],
    )

    class MissingGpu:
        async def get_metrics(self):
            return []

    system = build_system(config, use_fake_processes=True)
    service = CoordinatorService(system, start_miner_on_ready=True, first_boot=True,
                                 supervision_poll_interval=0.01, gpu_monitor=MissingGpu())
    assert await service.start()
    result = await service.manual_miner_control("pause", threshold_pct=20, window_seconds=0.03)
    assert result["status"] == "paused"
    await asyncio.sleep(0.1)
    assert (await system.miner_adapter.status()).state == ProcessState.STOPPED
    assert system.miner_adapter.is_manual_override
    assert StateCodec.load(state_path).gpu_idle_condition["samples"] == []
    await service.stop()


@pytest.mark.asyncio
async def test_clean_restart_does_not_persist_temporary_shutdown_override(tmp_path):
    from resource_coordinator.core.durable_state import StateCodec
    from resource_coordinator.core.processes import ProcessState

    state_path = tmp_path / "coordinator.json"
    config = CoordinatorConfig(
        service=ServiceConfig(state_persistence_path=str(state_path)),
        processes={"krig": ProcessConfig(name="krig", backend="fake")},
        policies=[PolicyConfig(name="stop", trigger_event="lmstudio.inference_requested",
                               target_process="krig", resource="gpu.inference", cooldown_seconds=0)],
    )
    system = build_system(config, use_fake_processes=True)
    service = CoordinatorService(system, start_miner_on_ready=True, stop_miner_on_shutdown=True, first_boot=True)
    assert await service.start()
    assert (await system.miner_adapter.status()).state == ProcessState.RUNNING
    await service.stop()
    assert StateCodec.load(state_path).processes["krig"].is_manual_override is False

    restarted_system = build_system(config, use_fake_processes=True)
    restarted = CoordinatorService(restarted_system, start_miner_on_ready=True, stop_miner_on_shutdown=True)
    assert await restarted.start()
    assert (await restarted_system.miner_adapter.status()).state == ProcessState.RUNNING
    await restarted.stop()


@pytest.mark.asyncio
async def test_gaming_unload_failure_keeps_miner_held_and_records_reconciliation_state(tmp_path):
    from resource_coordinator.core.durable_state import StateCodec
    from resource_coordinator.core.processes import ProcessState

    state_path = tmp_path / "coordinator.json"
    config = CoordinatorConfig(
        service=ServiceConfig(state_persistence_path=str(state_path), upstream_url="http://lmstudio:1234"),
        processes={"krig": ProcessConfig(name="krig", backend="fake")},
        policies=[PolicyConfig(name="stop", trigger_event="lmstudio.inference_requested",
                               target_process="krig", resource="gpu.inference", cooldown_seconds=0)],
    )

    async def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"models": [{"type": "llm", "key": "model",
                "loaded_instances": [{"id": "instance", "config": {"context_length": 2048}}]}]})
        return httpx.Response(500, json={"error": "injected unload failure"})

    system = build_system(config, use_fake_processes=True)
    service = CoordinatorService(system, start_miner_on_ready=True, first_boot=True,
        lmstudio_client_factory=lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs))
    assert await service.start()
    result = await service.gaming_control("start")
    assert result["status"] == "failed"
    assert (await system.miner_adapter.status()).state == ProcessState.STOPPED
    assert system.miner_adapter.is_manual_override
    assert StateCodec.load(state_path).gaming_mode["state"] == "failed"
    await service.stop()


@pytest.mark.asyncio
async def test_service_can_explicitly_start_generic_configured_process():
    from resource_coordinator.config import CoordinatorConfig

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
                }
            ],
        }
    )
    system = build_system(config, use_fake_processes=True)
    service = CoordinatorService(system, start_process_on_ready="worker")

    assert await service.start() is True
    info = await system.supervisors["worker"].status()
    assert info.state.value == "running"
    assert info.is_coordinator_owned


@pytest.mark.asyncio
async def test_shutdown_uses_configured_process_stop_timeout():
    from resource_coordinator.core.processes import ProcessLifecycleOwner

    config = CoordinatorConfig.from_dict(
        {
            "version": "1.0",
            "processes": {
                "worker": {"backend": "fake", "stop_timeout_seconds": 13.5},
            },
            "policies": [
                {
                    "name": "stop-for-inference",
                    "trigger_event": "lmstudio.inference_requested",
                    "target_process": "worker",
                    "resource": "gpu.inference",
                    "lease_type": "shared",
                }
            ],
        }
    )
    system = build_system(config, use_fake_processes=True)
    backend = system.supervisors["worker"].backend
    backend.running = True
    backend.lifecycle_owner = ProcessLifecycleOwner.COORDINATOR
    backend.is_coordinator_owned = True
    observed_timeouts: list[float] = []
    original_stop = backend.stop

    async def record_stop(timeout: float = 10.0) -> bool:
        observed_timeouts.append(timeout)
        return await original_stop(timeout)

    backend.stop = record_stop  # type: ignore[method-assign]
    service = CoordinatorService(system, stop_process_on_shutdown="worker")
    assert await service.start() is True

    await service.stop()

    assert observed_timeouts == [13.5]
    assert service.state == ServiceState.STOPPED


@pytest.mark.asyncio
async def test_service_preflight_fails_on_broken_policy():
    config = CoordinatorConfig.from_dict(
        {
            "version": "1.0",
            "processes": {"p1": {"backend": "fake"}},
        }
    )
    system = build_system(config, use_fake_processes=True)
    # Tamper with policy to target missing process
    from resource_coordinator.config import PolicyConfig

    system.config.policies.append(PolicyConfig(name="broken", trigger_event="e", target_process="missing"))

    service = CoordinatorService(system)
    passed, msgs = service.preflight_check()
    assert passed is False
    assert any("targets unknown process" in m for m in msgs)

    started = await service.start()
    assert started is False
    assert service.state == ServiceState.FAILED
    assert service.is_ready is False
    assert "Preflight checks failed" in service.failure_reason


def test_service_preflight_rejects_restart_without_coordinator_stop_ownership():
    from resource_coordinator.config import PolicyConfig, ProcessConfig

    config = CoordinatorConfig(
        processes={"worker": ProcessConfig(name="worker", backend="fake")},
        policies=[
            PolicyConfig(
                name="unsafe-restart",
                trigger_event="lmstudio.inference_requested",
                target_process="worker",
                resource="gpu.inference",
                only_if_stopped_by_coordinator=False,
            )
        ],
    )
    service = CoordinatorService(build_system(config, use_fake_processes=True))

    passed, messages = service.preflight_check()

    assert passed is False
    assert any("coordinator-owned stop" in message for message in messages)


@pytest.mark.asyncio
async def test_service_graceful_shutdown(minimal_system):
    service = CoordinatorService(minimal_system, drain_timeout_seconds=0.5)
    await service.start()
    assert service.state == ServiceState.READY

    await service.stop()
    assert service.state == ServiceState.STOPPED
    assert service.is_ready is False


@pytest.mark.asyncio
async def test_service_drain_with_active_leases(minimal_system):
    service = CoordinatorService(minimal_system, drain_timeout_seconds=0.2)
    await service.start()

    # Acquire an inference lease
    async with minimal_system.lease_mgr.acquire("gpu.inference", holder_id="in-flight"):
        # Trigger stop while lease is active
        stop_task = asyncio.create_task(service.stop())
        await asyncio.sleep(0.05)
        # Service should be in DRAINING
        assert service.state == ServiceState.DRAINING
        # Drain timeout (0.2s) will expire while lease is held
        await stop_task

    assert service.state == ServiceState.RECONCILIATION_REQUIRED
    # Because lease was still active when drain timed out, restart MUST be inhibited!
    assert minimal_system.lease_mgr.is_restart_inhibited("gpu.inference") is True
    inh = minimal_system.lease_mgr.get_inhibition("gpu.inference")
    assert inh is not None
    assert "shutdown:" in inh.reason


@pytest.mark.asyncio
async def test_shutdown_timeout_keeps_gateway_and_instance_lock_open(minimal_system, tmp_path):
    service = CoordinatorService(
        minimal_system,
        drain_timeout_seconds=0.05,
        lock_path=tmp_path / "coordinator.lock",
    )
    assert await service.start() is True
    lock = service._instance_lock
    assert lock is not None and lock.is_acquired

    async with minimal_system.lease_mgr.acquire("gpu.inference", holder_id="uncertain"):
        await service.stop()

        assert service.state == ServiceState.RECONCILIATION_REQUIRED
        assert minimal_system.gateway._http_client is None
        assert lock.is_acquired is True

    await service.stop()
    assert service.state == ServiceState.STOPPED
    assert lock.is_acquired is False


@pytest.mark.asyncio
async def test_service_emergency_abort(minimal_system):
    service = CoordinatorService(minimal_system)
    await service.start()

    result = await service.emergency_abort(reason="manual_operator_trip")
    assert service.state == ServiceState.RECONCILIATION_REQUIRED
    assert service.is_ready is False
    assert "manual_operator_trip" in service.failure_reason

    # Both inference and model loading must be inhibited
    assert minimal_system.lease_mgr.is_restart_inhibited("gpu.inference") is True
    assert minimal_system.lease_mgr.is_restart_inhibited("gpu.model_loading") is True

    assert result["service_state"] == ServiceState.RECONCILIATION_REQUIRED.value
    assert "gpu.inference" in result["inhibited_resources"]
