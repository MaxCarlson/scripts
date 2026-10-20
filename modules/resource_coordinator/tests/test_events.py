import pytest

from resource_coordinator.core.events import Event, EventDispatcher, VetoOperation


@pytest.mark.asyncio
async def test_event_dispatcher_observational():
    dispatcher = EventDispatcher()
    received = []

    def sync_listener(event: Event):
        received.append(("sync", event.name, event.data))

    async def async_listener(event: Event):
        received.append(("async", event.name, event.data))

    dispatcher.on("test.event", sync_listener)
    dispatcher.on("test.*", async_listener)

    await dispatcher.emit("test.event", {"key": "value"})

    assert len(received) == 2
    assert ("sync", "test.event", {"key": "value"}) in received
    assert ("async", "test.event", {"key": "value"}) in received


@pytest.mark.asyncio
async def test_event_dispatcher_unregistered():
    dispatcher = EventDispatcher()
    received = []

    def listener(event: Event):
        received.append(event.name)

    dispatcher.on("test.event", listener)
    assert dispatcher.off("test.event", listener) is True
    assert dispatcher.off("test.event", listener) is False

    await dispatcher.emit("test.event")
    assert received == []


@pytest.mark.asyncio
async def test_event_dispatcher_blocking_hook_veto():
    dispatcher = EventDispatcher()

    async def blocking_hook(event: Event):
        if event.data.get("reject"):
            raise VetoOperation("Rejected by test hook")

    dispatcher.on("operation.start", blocking_hook, is_blocking=True)

    # Allowed
    event = await dispatcher.emit_blocking("operation.start", {"reject": False})
    assert event.name == "operation.start"

    # Vetoed
    with pytest.raises(VetoOperation) as exc_info:
        await dispatcher.emit_blocking("operation.start", {"reject": True})
    assert "Rejected by test hook" in str(exc_info.value)


@pytest.mark.asyncio
async def test_event_dispatcher_error_isolation():
    dispatcher = EventDispatcher()
    called = []

    def failing_listener(event: Event):
        raise RuntimeError("Boom in listener")

    def working_listener(event: Event):
        called.append(event.name)

    dispatcher.on("test.event", failing_listener)
    dispatcher.on("test.event", working_listener)

    # emit should not crash the caller when observational listener fails
    await dispatcher.emit("test.event")
    assert called == ["test.event"]
