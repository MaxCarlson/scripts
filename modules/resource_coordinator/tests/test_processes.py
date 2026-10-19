import pytest

from resource_coordinator.core.events import EventDispatcher
from resource_coordinator.core.processes import (
    FakeProcessBackend,
    ProcessState,
    ProcessSupervisor,
)


@pytest.mark.asyncio
async def test_process_supervisor_fake_lifecycle():
    dispatcher = EventDispatcher()
    events = []
    dispatcher.on("process.*", lambda e: events.append((e.name, e.data.get("name"))))

    backend = FakeProcessBackend(name="krig", running=True)
    supervisor = ProcessSupervisor(backend=backend, event_dispatcher=dispatcher)

    st = await supervisor.status()
    assert st.state == ProcessState.RUNNING

    # Stop process
    success = await supervisor.stop(timeout=2.0)
    assert success is True
    assert supervisor.was_stopped_by_coordinator is True
    st_after = await supervisor.status()
    assert st_after.state == ProcessState.STOPPED

    assert ("process.stop_requested", "krig") in events
    assert ("process.stopped", "krig") in events

    # Start process
    start_success = await supervisor.start(origin="coordinator", only_if_stopped_by_coordinator=True)
    assert start_success is True
    assert supervisor.was_stopped_by_coordinator is False
    st_running = await supervisor.status()
    assert st_running.state == ProcessState.RUNNING

    assert ("process.start_requested", "krig") in events
    assert ("process.started", "krig") in events


@pytest.mark.asyncio
async def test_process_supervisor_manual_override():
    backend = FakeProcessBackend(name="krig", running=False)
    supervisor = ProcessSupervisor(backend=backend)
    supervisor.was_stopped_by_coordinator = True

    supervisor.set_manual_override(True)
    assert supervisor.is_manual_override is True

    # Start should be blocked by manual override
    res = await supervisor.start()
    assert res is False
    st = await supervisor.status()
    assert st.state == ProcessState.STOPPED

    # Clear manual override
    supervisor.set_manual_override(False)
    res = await supervisor.start()
    assert res is True
    st = await supervisor.status()
    assert st.state == ProcessState.RUNNING


@pytest.mark.asyncio
async def test_process_supervisor_external_ownership():
    # External process running (not coordinator-owned)
    backend = FakeProcessBackend(name="krig", running=True, external=True)
    supervisor = ProcessSupervisor(backend=backend)

    st = await supervisor.status()
    assert st.state == ProcessState.EXTERNAL_RUNNING
    assert supervisor.was_stopped_by_coordinator is False

    # Start with only_if_stopped_by_coordinator=True should skip if not stopped by coordinator
    backend.running = False
    start_res = await supervisor.start(only_if_stopped_by_coordinator=True)
    assert start_res is False
