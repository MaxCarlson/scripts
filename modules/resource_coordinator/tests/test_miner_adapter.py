import pytest

from resource_coordinator.adapters.miners.adapter import MinerAdapter
from resource_coordinator.core.events import EventDispatcher
from resource_coordinator.core.processes import FakeProcessBackend, ProcessState, ProcessSupervisor


@pytest.mark.asyncio
async def test_miner_adapter_lifecycle_and_events():
    dispatcher = EventDispatcher()
    mining_events = []
    dispatcher.on("mining.*", lambda e: mining_events.append((e.name, e.data.get("name"))))

    backend = FakeProcessBackend(name="krig", running=True)
    supervisor = ProcessSupervisor(backend=backend, event_dispatcher=dispatcher)
    adapter = MinerAdapter(supervisor=supervisor, event_dispatcher=dispatcher)

    st = await adapter.status()
    assert st.state == ProcessState.RUNNING

    # Pause miner
    paused = await adapter.pause(timeout=2.0)
    assert paused is True
    assert adapter.supervisor.was_stopped_by_coordinator is True

    assert ("mining.stop_requested", "krig") in mining_events
    assert ("mining.stopped", "krig") in mining_events

    # Resume miner
    resumed = await adapter.resume()
    assert resumed is True
    assert adapter.supervisor.was_stopped_by_coordinator is False
    assert ("mining.started", "krig") in mining_events


@pytest.mark.asyncio
async def test_miner_adapter_manual_override():
    backend = FakeProcessBackend(name="krig", running=True)
    supervisor = ProcessSupervisor(backend=backend)
    adapter = MinerAdapter(supervisor=supervisor)

    adapter.set_manual_override(True)
    assert adapter.is_manual_override is True

    await adapter.pause()

    # Automatic resume should fail due to manual override
    res = await adapter.resume()
    assert res is False
