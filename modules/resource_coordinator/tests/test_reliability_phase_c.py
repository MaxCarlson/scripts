"""
Extended offline reliability tests for Phase C preparation.

Covers:
1. External supervisor auto-relaunch and PID verification
2. High-concurrency resource contention and cooldown interleavings
3. Termination uncertainty and non-clearing inhibition guarantees
4. Configuration safety boundaries and template validation
"""

import asyncio

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from resource_coordinator.config import CoordinatorConfig, load_config
from resource_coordinator.core.actions import (
    ActionOutcome,
    StartProcessAction,
    StopProcessAction,
)
from resource_coordinator.core.events import EventDispatcher
from resource_coordinator.core.leases import LeaseManager
from resource_coordinator.core.processes import (
    FakeProcessBackend,
    ProcessState,
    ProcessSupervisor,
)


def create_controllable_upstream_app():
    """Mock upstream LM Studio service with precise stream control."""

    async def handle_chat(request):
        body = await request.json()
        mode = body.get("mode", "normal")

        if body.get("stream"):

            async def event_generator():
                if mode == "normal_done":
                    yield b'data: {"choices": [{"delta": {"content": "Hi"}}]}\n\n'
                    yield b'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n\n'
                    yield b"data: [DONE]\n\n"
                elif mode == "slow_abort":
                    yield b'data: {"choices": [{"delta": {"content": "Chunk1"}}]}\n\n'
                    await asyncio.sleep(0.5)
                    # Client expected to disconnect here
                    yield b"data: [DONE]\n\n"
                elif mode == "incomplete":
                    yield b'data: {"choices": [{"delta": {"content": "Chunk1"}}]}\n\n'
                    # Abrupt close without DONE

            return StreamingResponse(event_generator(), media_type="text/event-stream")

        return JSONResponse(
            {"choices": [{"message": {"content": "Done"}, "finish_reason": "stop"}]}
        )

    return Starlette(
        routes=[Route("/v1/chat/completions", handle_chat, methods=["POST"])]
    )


# ===========================================================================
# 1. External Supervision & PID Verification Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_external_supervisor_immediate_relaunch() -> None:
    """When a supervisor automatically relaunches a stopped miner, supervisor status detects relaunch."""
    dispatcher = EventDispatcher()
    backend = FakeProcessBackend(
        name="krig",
        running=True,
        external=True,
        allow_external_stop=True,
        relaunch_delay=0.01,  # Supervisor relaunches in 10ms
    )
    supervisor = ProcessSupervisor(backend=backend, event_dispatcher=dispatcher)

    # Initial state is external running
    info = await supervisor.status()
    assert info.state == ProcessState.EXTERNAL_RUNNING
    assert info.pid == 12345

    # Attempt to stop with verification
    action = StopProcessAction(
        supervisor=supervisor, wait_until_stopped=True, timeout_seconds=0.1
    )
    result = await action.execute()
    assert result.outcome == ActionOutcome.SUCCESS

    # Give supervisor's background relaunch task time to trigger
    await asyncio.sleep(0.03)

    # Because external supervisor automatically relaunched, the process is running again with new PID!
    current_info = await supervisor.status()
    assert current_info.state == ProcessState.EXTERNAL_RUNNING
    assert current_info.pid == 12346


@pytest.mark.asyncio
async def test_stop_succeeds_but_process_remains_active() -> None:
    """Process ignores termination signals (fail_stop=True); stop action fails."""
    dispatcher = EventDispatcher()
    backend = FakeProcessBackend(
        name="uncooperative_miner",
        running=True,
        fail_stop=True,
    )
    supervisor = ProcessSupervisor(backend=backend, event_dispatcher=dispatcher)

    action = StopProcessAction(
        supervisor=supervisor, wait_until_stopped=True, timeout_seconds=0.05
    )
    result = await action.execute()
    assert result.outcome == ActionOutcome.FAILURE
    assert not result.is_ok

    info = await supervisor.status()
    assert info.state == ProcessState.RUNNING


@pytest.mark.asyncio
async def test_miner_already_manually_stopped_not_restarted() -> None:
    """If miner was already stopped before inference, coordinator does not restart it."""
    dispatcher = EventDispatcher()
    backend = FakeProcessBackend(
        name="krig",
        running=False,  # Manually stopped prior to start
    )
    supervisor = ProcessSupervisor(backend=backend, event_dispatcher=dispatcher)

    stop_action = StopProcessAction(supervisor=supervisor, wait_until_stopped=True)
    res_stop = await stop_action.execute()
    assert res_stop.outcome == ActionOutcome.SKIPPED
    # Crucial guarantee: coordinator did NOT stop it
    assert supervisor.was_stopped_by_coordinator is False

    # After inference completes, restart action with only_if_stopped_by_coordinator=True is a no-op
    restart_action = StartProcessAction(
        supervisor=supervisor, only_if_stopped_by_coordinator=True
    )
    res_start = await restart_action.execute()
    assert res_start.outcome == ActionOutcome.SKIPPED

    info = await supervisor.status()
    assert info.state == ProcessState.STOPPED


@pytest.mark.asyncio
async def test_restart_requested_without_external_restart_permission() -> None:
    """External process adopted without restart permission is not restarted."""
    dispatcher = EventDispatcher()
    backend = FakeProcessBackend(
        name="krig",
        running=True,
        external=True,
        allow_external_stop=True,
        allow_external_restart=False,  # Denied restart
    )
    supervisor = ProcessSupervisor(backend=backend, event_dispatcher=dispatcher)

    await supervisor.stop()
    assert supervisor.was_stopped_by_coordinator is True

    # Attempt restart
    restart_action = StartProcessAction(
        supervisor=supervisor, only_if_stopped_by_coordinator=True
    )
    res_start = await restart_action.execute()
    assert res_start.outcome == ActionOutcome.FAILURE

    info = await supervisor.status()
    assert info.state == ProcessState.STOPPED


# ===========================================================================
# 2. Resource Contention & Concurrency Interleaving Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_multiple_inferences_arrive_during_miner_shutdown() -> None:
    """Multiple requests arriving while miner shutdown is in progress all reserve atomically."""
    dispatcher = EventDispatcher()
    lease_mgr = LeaseManager(default_cooldown_seconds=60.0, event_dispatcher=dispatcher)

    # Reservation 1 starts
    async with lease_mgr.reserve("gpu.inference", holder_id="c1") as res1:
        assert lease_mgr.pending_count("gpu.inference") == 1

        # Reservation 2 arrives while res1 is pending
        async with lease_mgr.reserve("gpu.inference", holder_id="c2") as res2:
            assert lease_mgr.pending_count("gpu.inference") == 2

            # Activate both
            await res1.activate()
            await res2.activate()

            assert lease_mgr.active_count("gpu.inference") == 2
            assert lease_mgr.pending_count("gpu.inference") == 0

        # res2 exited and released
        assert lease_mgr.active_count("gpu.inference") == 1
        assert lease_mgr.is_cooling_down("gpu.inference") is False

    # res1 exited and released; cooldown starts
    assert lease_mgr.active_count("gpu.inference") == 0
    assert lease_mgr.is_cooling_down("gpu.inference") is True


@pytest.mark.asyncio
async def test_new_operation_arrives_during_cooldown_cancels_restart() -> None:
    """New inference during cooldown immediately cancels pending miner restart."""
    dispatcher = EventDispatcher()
    lease_mgr = LeaseManager(default_cooldown_seconds=60.0, event_dispatcher=dispatcher)

    # Request 1 enters and leaves
    async with lease_mgr.reserve("gpu.inference", holder_id="c1") as res1:
        await res1.activate()

    assert lease_mgr.is_cooling_down("gpu.inference") is True

    # Request 2 arrives during cooldown
    async with lease_mgr.reserve("gpu.inference", holder_id="c2") as res2:
        # Immediate cooldown cancellation upon reservation!
        assert lease_mgr.is_cooling_down("gpu.inference") is False
        assert lease_mgr.pending_count("gpu.inference") == 1

        await res2.activate()
        assert lease_mgr.active_count("gpu.inference") == 1

    assert lease_mgr.active_count("gpu.inference") == 0
    assert lease_mgr.is_cooling_down("gpu.inference") is True


@pytest.mark.asyncio
async def test_resource_claims_released_in_different_orders() -> None:
    """Multiple concurrent claims releasing out-of-order maintain correct lease counters."""
    lease_mgr = LeaseManager(default_cooldown_seconds=30.0)

    async with (
        lease_mgr.reserve("gpu.inference", holder_id="A") as res_a,
        lease_mgr.reserve("gpu.inference", holder_id="B") as res_b,
        lease_mgr.reserve("gpu.inference", holder_id="C") as res_c,
    ):
        l_a = await res_a.activate()
        l_b = await res_b.activate()
        l_c = await res_c.activate()
        assert lease_mgr.active_count("gpu.inference") == 3

        # Release B first
        await lease_mgr.release(l_b)
        assert lease_mgr.active_count("gpu.inference") == 2
        assert lease_mgr.is_cooling_down("gpu.inference") is False

        # Release A second
        await lease_mgr.release(l_a)
        assert lease_mgr.active_count("gpu.inference") == 1
        assert lease_mgr.is_cooling_down("gpu.inference") is False

        # Release C last
        await lease_mgr.release(l_c)
        assert lease_mgr.active_count("gpu.inference") == 0
        assert lease_mgr.is_cooling_down("gpu.inference") is True


# ===========================================================================
# 3. Termination Uncertainty & Non-Clearing Inhibition Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_later_successful_request_does_not_clear_prior_inhibition() -> None:
    """A subsequent successful request must never clear an unresolved earlier restart inhibition."""
    dispatcher = EventDispatcher()
    lease_mgr = LeaseManager(default_cooldown_seconds=30.0, event_dispatcher=dispatcher)

    # Simulate an earlier request that terminated uncertainly
    await lease_mgr.inhibit_restart(
        "gpu.inference", reason="client_disconnect", holder_id="req-1"
    )
    assert lease_mgr.is_restart_inhibited("gpu.inference") is True

    # A second request arrives and completes normally
    async with lease_mgr.acquire("gpu.inference", holder_id="req-2"):
        pass

    # Restart MUST remain inhibited!
    assert lease_mgr.is_restart_inhibited("gpu.inference") is True
    inh = lease_mgr.get_inhibition("gpu.inference")
    assert inh is not None
    assert inh.holder_id == "req-1"


@pytest.mark.asyncio
async def test_administrative_recovery_with_active_leases() -> None:
    """Administrative recovery rejects clearing if active leases exist."""
    dispatcher = EventDispatcher()
    lease_mgr = LeaseManager(default_cooldown_seconds=30.0, event_dispatcher=dispatcher)

    # Inhibit restart
    await lease_mgr.inhibit_restart(
        "gpu.inference", reason="uncertain_error", holder_id="err-1"
    )

    # Another lease is active
    async with lease_mgr.acquire("gpu.inference", holder_id="active-job"):
        # Attempt recovery while lease is active - must raise RuntimeError!
        with pytest.raises(
            RuntimeError,
            match="Cannot recover a resource with active or pending requests",
        ):
            await lease_mgr.clear_inhibition("gpu.inference")
        assert lease_mgr.is_restart_inhibited("gpu.inference") is True

    # Now that the active lease is released, administrative recovery succeeds
    cleared = await lease_mgr.clear_inhibition("gpu.inference")
    assert cleared is not None
    assert lease_mgr.is_restart_inhibited("gpu.inference") is False
    assert lease_mgr.is_cooling_down("gpu.inference") is True


# ===========================================================================
# 4. Configuration Safety Tests
# ===========================================================================


def test_config_validation_invalid_backend() -> None:
    """Reject unknown process backend."""
    raw = {
        "version": "1.0",
        "processes": {
            "p1": {"backend": "solaris", "executable": "C:\\bin\\proc.exe"},
        },
    }
    with pytest.raises(ValueError, match="Unknown backend"):
        CoordinatorConfig.from_dict(raw)


def test_config_validation_relative_windows_path() -> None:
    """Reject relative executable paths on Windows backend."""
    raw = {
        "version": "1.0",
        "processes": {
            "p1": {"backend": "windows", "executable": "relative\\path.exe"},
        },
    }
    with pytest.raises(ValueError, match="must be an absolute path"):
        CoordinatorConfig.from_dict(raw)


def test_config_validation_missing_target_process() -> None:
    """Reject policy targeting an undefined process."""
    raw = {
        "version": "1.0",
        "processes": {
            "miner": {"backend": "fake"},
        },
        "policies": [
            {
                "name": "p1",
                "trigger_event": "e1",
                "target_process": "non_existent_process",
            },
        ],
    }
    with pytest.raises(ValueError, match="Unknown target process"):
        CoordinatorConfig.from_dict(raw)


def test_config_validation_negative_cooldown() -> None:
    """Reject negative cooldown durations."""
    raw = {
        "version": "1.0",
        "policies": [
            {"name": "p1", "trigger_event": "e1", "cooldown_seconds": -5.0},
        ],
    }
    with pytest.raises(ValueError, match="Durations must be finite and nonnegative"):
        CoordinatorConfig.from_dict(raw)


def test_config_supervised_template_file() -> None:
    """Validate that the shipped supervised acceptance template parses cleanly."""
    from pathlib import Path

    template_path = (
        Path(__file__).resolve().parent.parent / "config.supervised-template.yaml"
    )
    cfg = load_config(template_path)
    assert cfg.version == "1.0"
    assert "krig_miner" in cfg.processes
    miner = cfg.processes["krig_miner"]
    assert miner.backend == "windows"
    assert miner.allow_force_termination is False
    assert miner.allow_external_stop is True
    assert miner.allow_external_restart is True
    assert miner.adopt_external is False
    assert len(cfg.policies) == 1
    pol = cfg.policies[0]
    assert pol.only_if_stopped_by_coordinator is True
