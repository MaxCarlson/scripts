import asyncio
import pytest

from resource_coordinator.core.conditions import (
    AllCondition,
    AnyCondition,
    CallableCondition,
    LeaseHeldCondition,
    MetricThresholdCondition,
    NotCondition,
    ProcessRunningCondition,
)
from resource_coordinator.core.leases import LeaseManager
from resource_coordinator.core.processes import FakeProcessBackend, ProcessSupervisor


@pytest.mark.asyncio
async def test_composite_conditions():
    c_true = CallableCondition(lambda ctx: True)
    c_false = CallableCondition(lambda ctx: False)

    # All
    assert await AllCondition([c_true, c_true]).evaluate() is True
    assert await AllCondition([c_true, c_false]).evaluate() is False

    # Any
    assert await AnyCondition([c_false, c_true]).evaluate() is True
    assert await AnyCondition([c_false, c_false]).evaluate() is False

    # Not
    assert await NotCondition(c_true).evaluate() is False
    assert await NotCondition(c_false).evaluate() is True


@pytest.mark.asyncio
async def test_process_and_lease_conditions():
    backend = FakeProcessBackend(name="krig", running=True)
    supervisor = ProcessSupervisor(backend=backend)
    proc_cond = ProcessRunningCondition(supervisor)
    assert await proc_cond.evaluate() is True

    backend.running = False
    assert await proc_cond.evaluate() is False

    lease_mgr = LeaseManager(default_cooldown_seconds=10.0)
    lease_cond = LeaseHeldCondition(lease_mgr, "gpu.inference")
    assert await lease_cond.evaluate() is False

    async with lease_mgr.acquire("gpu.inference"):
        assert await lease_cond.evaluate() is True

    assert await lease_cond.evaluate() is False


@pytest.mark.asyncio
async def test_metric_threshold_hold_duration():
    value = 50.0

    cond = MetricThresholdCondition(
        metric_getter=lambda: value,
        operator="gt",
        threshold=80.0,
        hold_seconds=0.1,
    )

    assert await cond.evaluate() is False

    value = 90.0
    # True immediately, but hold_seconds requires 0.1s
    assert await cond.evaluate() is False

    await asyncio.sleep(0.12)
    assert await cond.evaluate() is True

    # Drop below threshold resets hold
    value = 70.0
    assert await cond.evaluate() is False

    value = 95.0
    assert await cond.evaluate() is False
    await asyncio.sleep(0.12)
    assert await cond.evaluate() is True
