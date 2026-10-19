import asyncio
import pytest

from resource_coordinator.core.events import EventDispatcher
from resource_coordinator.core.leases import LeaseManager, LeaseType


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.waiters = []

    def monotonic(self):
        return self.now

    async def sleep(self, delay):
        future = asyncio.get_running_loop().create_future()
        waiter = (self.now + delay, future)
        self.waiters.append(waiter)
        await future

    def advance(self, seconds):
        self.now += seconds
        for deadline, future in list(self.waiters):
            if deadline <= self.now and not future.done():
                future.set_result(None)


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
async def test_pending_exclusive_lease_blocks_later_shared_requests():
    mgr = LeaseManager(default_cooldown_seconds=0)
    order = []

    async def acquire(lease_type, label):
        async with mgr.acquire("gpu.inference", lease_type=lease_type, holder_id=label):
            order.append(label)

    async with mgr.acquire("gpu.inference", lease_type=LeaseType.SHARED, holder_id="first"):
        exclusive = asyncio.create_task(acquire(LeaseType.EXCLUSIVE, "load"))
        while mgr.pending_count("gpu.inference") < 1:
            await asyncio.sleep(0)
        later_shared = asyncio.create_task(acquire(LeaseType.SHARED, "later-inference"))
        await asyncio.sleep(0)
        assert order == []

    await asyncio.gather(exclusive, later_shared)
    assert order == ["load", "later-inference"]


@pytest.mark.asyncio
async def test_idle_action_and_new_reservation_share_one_arbitration_boundary():
    mgr = LeaseManager(default_cooldown_seconds=0)
    action_entered = asyncio.Event()
    allow_action_to_finish = asyncio.Event()
    order = []

    async def idle_action():
        action_entered.set()
        await allow_action_to_finish.wait()
        order.append("idle-action")

    async def request():
        async with mgr.acquire("gpu.inference", holder_id="new-request"):
            order.append("request")

    idle = asyncio.create_task(mgr.run_if_idle("gpu.inference", idle_action))
    await action_entered.wait()
    incoming = asyncio.create_task(request())
    await asyncio.sleep(0)
    assert mgr.pending_count("gpu.inference") == 0
    allow_action_to_finish.set()
    assert await idle is True
    await incoming
    assert order == ["idle-action", "request"]


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


@pytest.mark.asyncio
async def test_cooldown_uses_monotonic_clock_and_resets_deterministically():
    from resource_coordinator.core.actions import StartProcessAction
    from resource_coordinator.core.policies import Policy, PolicyEngine
    from resource_coordinator.core.processes import FakeProcessBackend, ProcessSupervisor

    clock = FakeClock()
    dispatcher = EventDispatcher()
    idle_events = []
    dispatcher.on("resource.idle", lambda e: idle_events.append(e.data))
    mgr = LeaseManager(
        default_cooldown_seconds=5,
        event_dispatcher=dispatcher,
        monotonic_clock=clock.monotonic,
        sleep=clock.sleep,
    )
    backend = FakeProcessBackend(name="worker", running=False)
    supervisor = ProcessSupervisor(backend, dispatcher)
    supervisor.was_stopped_by_coordinator = True
    policy_engine = PolicyEngine(dispatcher, mgr)
    policy_engine.register_policy(
        Policy(
            name="restart-after-idle",
            trigger_event="lmstudio.inference_requested",
            resource="gpu.inference",
            cooldown_seconds=5,
            after_release_actions=[StartProcessAction(supervisor)],
        )
    )

    async with mgr.acquire("gpu.inference", holder_id="first"):
        pass
    await asyncio.sleep(0)
    clock.advance(4)
    assert mgr.cooldown_remaining("gpu.inference") == 1

    async with mgr.acquire("gpu.inference", holder_id="second"):
        assert not mgr.is_cooling_down("gpu.inference")
    await asyncio.sleep(0)
    clock.advance(4)
    await asyncio.sleep(0)
    assert idle_events == []
    clock.advance(1)
    for _ in range(5):
        await asyncio.sleep(0)
    assert len(idle_events) == 1
    assert mgr.is_cooling_down("gpu.inference") is False
    assert backend.running is True
