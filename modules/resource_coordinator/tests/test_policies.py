import asyncio
import pytest

from resource_coordinator.core.actions import StartProcessAction, StopProcessAction
from resource_coordinator.core.conditions import ProcessRunningCondition
from resource_coordinator.core.events import EventDispatcher, VetoOperation
from resource_coordinator.core.leases import LeaseManager, LeaseType
from resource_coordinator.core.policies import Policy, PolicyEngine
from resource_coordinator.core.processes import FakeProcessBackend, ProcessSupervisor


@pytest.mark.asyncio
async def test_policy_engine_end_to_end():
    dispatcher = EventDispatcher()
    lease_mgr = LeaseManager(default_cooldown_seconds=0.1, event_dispatcher=dispatcher)
    engine = PolicyEngine(event_dispatcher=dispatcher, lease_manager=lease_mgr)

    backend = FakeProcessBackend(name="krig", running=True)
    supervisor = ProcessSupervisor(backend=backend, event_dispatcher=dispatcher)

    # Policy: On lmstudio.inference_requested, if krig is running, stop it.
    # After release + cooldown, restart krig if coordinator stopped it.
    policy = Policy(
        name="prioritize-local-inference",
        trigger_event="lmstudio.inference_requested",
        condition=ProcessRunningCondition(supervisor),
        actions=[StopProcessAction(supervisor=supervisor, wait_until_stopped=True)],
        on_failure="reject_operation",
        resource="gpu.inference",
        cooldown_seconds=0.1,
        after_release_actions=[StartProcessAction(supervisor=supervisor, only_if_stopped_by_coordinator=True)],
    )

    engine.register_policy(policy)

    # 1. Initially miner is running
    assert backend.running is True

    # 2. Trigger arrives: inference requested
    await dispatcher.emit_blocking("lmstudio.inference_requested", {"model": "qwen38"})

    # Miner should have been stopped!
    assert backend.running is False
    assert supervisor.was_stopped_by_coordinator is True

    # 3. Simulate inference lease duration
    async with lease_mgr.acquire("gpu.inference", lease_type=LeaseType.SHARED, holder_id="req-1"):
        assert lease_mgr.active_count("gpu.inference") == 1
        assert backend.running is False

    # 4. Lease released, cooldown starts
    assert lease_mgr.is_cooling_down("gpu.inference") is True
    assert backend.running is False

    # Wait for cooldown to expire
    await asyncio.sleep(0.15)

    # 5. Miner should automatically resume!
    assert backend.running is True
    assert supervisor.was_stopped_by_coordinator is False


@pytest.mark.asyncio
async def test_policy_engine_action_failure_veto():
    dispatcher = EventDispatcher()
    lease_mgr = LeaseManager(default_cooldown_seconds=0.1, event_dispatcher=dispatcher)
    engine = PolicyEngine(event_dispatcher=dispatcher, lease_manager=lease_mgr)

    backend = FakeProcessBackend(name="krig", running=True, fail_stop=True)
    supervisor = ProcessSupervisor(backend=backend, event_dispatcher=dispatcher)

    policy = Policy(
        name="prioritize-local-inference",
        trigger_event="lmstudio.inference_requested",
        actions=[StopProcessAction(supervisor=supervisor, wait_until_stopped=True)],
        on_failure="reject_operation",
    )
    engine.register_policy(policy)

    # Trigger should raise VetoOperation because miner stop failed!
    with pytest.raises(VetoOperation) as exc_info:
        await dispatcher.emit_blocking("lmstudio.inference_requested", {"model": "qwen38"})

    assert "action failed" in str(exc_info.value)
