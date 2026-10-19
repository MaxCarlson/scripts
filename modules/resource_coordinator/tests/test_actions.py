import sys
import pytest

from resource_coordinator.core.actions import (
    ActionOutcome,
    CallableAction,
    CommandAction,
)


@pytest.mark.asyncio
async def test_callable_action_success():
    action = CallableAction(lambda ctx: ctx.get("val", 0) * 2, name="double")
    res = await action.execute({"val": 21})
    assert res.outcome == ActionOutcome.SUCCESS
    assert res.data["result"] == 42


@pytest.mark.asyncio
async def test_callable_action_failure():
    def broken(ctx):
        raise ValueError("Intentional error")

    action = CallableAction(broken, name="broken")
    res = await action.execute()
    assert res.outcome == ActionOutcome.FAILURE
    assert "Intentional error" in res.message


@pytest.mark.asyncio
async def test_command_action():
    # Run python -c "print('hello')" safely
    action = CommandAction([sys.executable, "-c", "print('hello')"], name="py_hello")
    res = await action.execute()
    assert res.outcome == ActionOutcome.SUCCESS
    assert "hello" in res.data["stdout"]
