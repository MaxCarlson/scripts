"""
Unit tests for CoordinatorService lifecycle, readiness state machine, preflight, and abort.
"""

import asyncio
import pytest

from resource_coordinator.config import CoordinatorConfig, build_system
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
