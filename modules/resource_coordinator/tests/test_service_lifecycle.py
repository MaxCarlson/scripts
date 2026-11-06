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
