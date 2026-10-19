import asyncio
import pytest

from resource_coordinator.core.events import EventDispatcher
from resource_coordinator.core.leases import LeaseManager, LeaseType


@pytest.mark.asyncio
async def test_lease_manager_shared_concurrency():
    mgr = LeaseManager(default_cooldown_seconds=10.0)

    assert mgr.active_count("gpu.inference") == 0

    async with mgr.acquire("gpu.inference", lease_type=LeaseType.SHARED, holder_id="h1") as l1:
        assert mgr.active_count("gpu.inference") == 1
        assert l1.holder_id == "h1"

        async with mgr.acquire("gpu.inference", lease_type=LeaseType.SHARED, holder_id="h2") as l2:
            assert mgr.active_count("gpu.inference") == 2
            assert l2.holder_id == "h2"

        assert mgr.active_count("gpu.inference") == 1

    assert mgr.active_count("gpu.inference") == 0
    assert mgr.is_cooling_down("gpu.inference") is True


@pytest.mark.asyncio
async def test_lease_manager_exclusive_blocks():
    mgr = LeaseManager(default_cooldown_seconds=0.0)
    order = []

    async def op1():
        async with mgr.acquire("gpu.model", lease_type=LeaseType.EXCLUSIVE, holder_id="load"):
            order.append("op1_start")
            await asyncio.sleep(0.05)
            order.append("op1_end")

    async def op2():
        await asyncio.sleep(0.01)
        async with mgr.acquire("gpu.model", lease_type=LeaseType.SHARED, holder_id="infer"):
            order.append("op2_start")
            order.append("op2_end")

    await asyncio.gather(op1(), op2())
    assert order == ["op1_start", "op1_end", "op2_start", "op2_end"]


@pytest.mark.asyncio
async def test_lease_manager_cooldown_and_cancellation():
    dispatcher = EventDispatcher()
    idle_events = []

    dispatcher.on("resource.idle", lambda e: idle_events.append(e.data))

    mgr = LeaseManager(default_cooldown_seconds=0.1, event_dispatcher=dispatcher)

    # Acquire and release
    async with mgr.acquire("gpu.inference", holder_id="h1"):
        pass

    assert mgr.is_cooling_down("gpu.inference") is True

    # Immediate new acquisition cancels the cooldown
    async with mgr.acquire("gpu.inference", holder_id="h2"):
        assert mgr.is_cooling_down("gpu.inference") is False
        assert len(idle_events) == 0

    # Wait for cooldown to expire this time
    assert mgr.is_cooling_down("gpu.inference") is True
    await asyncio.sleep(0.15)
    assert mgr.is_cooling_down("gpu.inference") is False
    assert len(idle_events) == 1
    assert idle_events[0]["resource"] == "gpu.inference"
