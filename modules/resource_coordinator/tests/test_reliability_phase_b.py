import asyncio
import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from resource_coordinator.adapters.lmstudio.gateway import LMStudioGateway
from resource_coordinator.core.actions import StartProcessAction, StopProcessAction
from resource_coordinator.core.conditions import ProcessRunningCondition
from resource_coordinator.core.events import EventDispatcher, VetoOperation
from resource_coordinator.core.leases import LeaseManager
from resource_coordinator.core.policies import Policy, PolicyEngine
from resource_coordinator.core.processes import (
    FakeProcessBackend,
    ProcessLifecycleOwner,
    ProcessState,
    ProcessSupervisor,
)


# ---------------------------------------------------------------------------
# Helpers for mock upstream
# ---------------------------------------------------------------------------


def create_phase_b_upstream_app():
    """Create a mock upstream LM Studio app with controllable stream completion signals."""

    async def handle_chat(request):
        body = await request.json()
        mode = body.get("mode", "normal")

        if body.get("stream"):

            async def event_generator():
                if mode == "normal_done":
                    yield b'data: {"choices": [{"delta": {"content": "Hello"}}]}\n\n'
                    yield b'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n\n'
                    yield b"data: [DONE]\n\n"
                elif mode == "incomplete_no_done":
                    # Stream ends without DONE or finish_reason
                    yield b'data: {"choices": [{"delta": {"content": "Hello"}}]}\n\n'
                    # Abrupt close without [DONE]
                elif mode == "slow_with_done":
                    yield b'data: {"choices": [{"delta": {"content": "Chunk1"}}]}\n\n'
                    await asyncio.sleep(0.05)
                    yield b'data: {"choices": [{"delta": {"content": "Chunk2"}}]}\n\n'
                    await asyncio.sleep(0.05)
                    yield b"data: [DONE]\n\n"
                elif mode == "error_mid_stream":
                    yield b'data: {"choices": [{"delta": {"content": "Start"}}]}\n\n'
                    raise RuntimeError("Upstream connection abruptly lost")
                elif mode == "native_event_done":
                    yield b'event: message\ndata: {"content": "Hello"}\n\n'
                    yield b"event: done\ndata: {}\n\n"

            return StreamingResponse(event_generator(), media_type="text/event-stream")

        if mode == "server_error":
            return JSONResponse({"error": "CUDA out of memory"}, status_code=500)

        return JSONResponse({"id": "chat-1", "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}]})

    routes = [
        Route("/v1/chat/completions", handle_chat, methods=["POST"]),
    ]
    return Starlette(routes=routes)


# ---------------------------------------------------------------------------
# Test Suite: Atomic Request Registration and Concurrency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_atomic_registration_cancels_cooldown_before_hooks():
    """
    Ensure incoming request immediately cancels idle cooldown and increments pending_count
    BEFORE blocking pre-inference hooks (e.g. miner shutdown) complete.
    """
    dispatcher = EventDispatcher()
    lease_mgr = LeaseManager(default_cooldown_seconds=10.0, event_dispatcher=dispatcher)

    # Put gpu.inference into active cooldown
    lease_mgr.set_resource_cooldown("gpu.inference", 10.0)
    async with lease_mgr.acquire("gpu.inference"):
        pass

    assert lease_mgr.is_cooling_down("gpu.inference") is True
    assert lease_mgr.active_count("gpu.inference") == 0
    assert lease_mgr.pending_count("gpu.inference") == 0

    gateway = LMStudioGateway(
        upstream_url="http://mock-lmstudio",
        event_dispatcher=dispatcher,
        lease_manager=lease_mgr,
    )
    upstream_app = create_phase_b_upstream_app()
    gateway._http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=upstream_app),
        base_url="http://mock-lmstudio",
    )

    hook_entered = asyncio.Event()
    hook_unblock = asyncio.Event()
    cooldown_cancelled_during_hook = False
    pending_during_hook = 0

    async def blocking_hook(event):
        nonlocal cooldown_cancelled_during_hook, pending_during_hook
        cooldown_cancelled_during_hook = not lease_mgr.is_cooling_down("gpu.inference")
        pending_during_hook = lease_mgr.pending_count("gpu.inference")
        hook_entered.set()
        await hook_unblock.wait()

    dispatcher.on("lmstudio.inference_requested", blocking_hook, is_blocking=True)

    app = gateway.create_app()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway")

    # Launch request in background task
    req_task = asyncio.create_task(
        client.post("/v1/chat/completions", json={"model": "m", "messages": [], "mode": "normal"})
    )

    await hook_entered.wait()
    # At this exact moment: hook is blocked, request is pending
    assert cooldown_cancelled_during_hook is True, "Cooldown was NOT cancelled before blocking hook!"
    assert pending_during_hook == 1, "Pending count was NOT recorded before blocking hook!"
    assert lease_mgr.active_count("gpu.inference") == 0

    # Unblock hook and allow request to finish
    hook_unblock.set()
    resp = await req_task
    assert resp.status_code == 200

    # Clean up
    await client.aclose()
    await gateway.close()


@pytest.mark.asyncio
async def test_concurrent_inference_during_miner_shutdown():
    """
    Test multiple requests arriving concurrently while miner shutdown is in progress.
    Ensure stop is shared, all requests record pending, and all succeed.
    """
    dispatcher = EventDispatcher()
    lease_mgr = LeaseManager(default_cooldown_seconds=0.1, event_dispatcher=dispatcher)
    fake_miner = FakeProcessBackend(name="krig", running=True, stop_delay=0.08)
    supervisor = ProcessSupervisor(backend=fake_miner, event_dispatcher=dispatcher)

    policy_engine = PolicyEngine(event_dispatcher=dispatcher, lease_manager=lease_mgr)
    policy = Policy(
        name="stop-miner",
        trigger_event="lmstudio.inference_requested",
        condition=ProcessRunningCondition(supervisor),
        actions=[StopProcessAction(supervisor=supervisor, wait_until_stopped=True)],
        resource="gpu.inference",
        cooldown_seconds=0.1,
        after_release_actions=[StartProcessAction(supervisor=supervisor)],
    )
    policy_engine.register_policy(policy)

    gateway = LMStudioGateway(
        upstream_url="http://mock-lmstudio",
        event_dispatcher=dispatcher,
        lease_manager=lease_mgr,
    )
    upstream_app = create_phase_b_upstream_app()
    gateway._http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=upstream_app),
        base_url="http://mock-lmstudio",
    )

    app = gateway.create_app()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway")

    # Send 3 concurrent requests
    async def send_req(idx):
        return await client.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": [{"role": "user", "content": f"msg {idx}"}], "mode": "normal"},
        )

    results = await asyncio.gather(send_req(1), send_req(2), send_req(3))
    for r in results:
        assert r.status_code == 200

    # After completion and cooldown, miner should have restarted
    await asyncio.sleep(0.2)
    st = await supervisor.status()
    assert st.state == ProcessState.RUNNING

    await client.aclose()
    await gateway.close()


@pytest.mark.asyncio
async def test_miner_initially_stopped_skips_stop_and_avoids_unwanted_restart():
    """
    When miner is initially stopped:
    1. Inference request increments pending count.
    2. ProcessRunningCondition is False -> stop action skipped.
    3. Inference completes.
    4. Miner is NOT started (since coordinator did not stop it).
    """
    dispatcher = EventDispatcher()
    lease_mgr = LeaseManager(default_cooldown_seconds=0.05, event_dispatcher=dispatcher)
    fake_miner = FakeProcessBackend(name="krig", running=False)
    supervisor = ProcessSupervisor(backend=fake_miner, event_dispatcher=dispatcher)

    policy_engine = PolicyEngine(event_dispatcher=dispatcher, lease_manager=lease_mgr)
    policy = Policy(
        name="stop-miner",
        trigger_event="lmstudio.inference_requested",
        condition=ProcessRunningCondition(supervisor),
        actions=[StopProcessAction(supervisor=supervisor)],
        resource="gpu.inference",
        cooldown_seconds=0.05,
        after_release_actions=[StartProcessAction(supervisor=supervisor, only_if_stopped_by_coordinator=True)],
    )
    policy_engine.register_policy(policy)

    gateway = LMStudioGateway(
        upstream_url="http://mock-lmstudio",
        event_dispatcher=dispatcher,
        lease_manager=lease_mgr,
    )
    upstream_app = create_phase_b_upstream_app()
    gateway._http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=upstream_app),
        base_url="http://mock-lmstudio",
    )

    app = gateway.create_app()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway")

    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "m", "messages": [], "mode": "normal"},
    )
    assert resp.status_code == 200

    # Wait for cooldown to expire
    await asyncio.sleep(0.1)

    # Miner must remain STOPPED
    st = await supervisor.status()
    assert st.state == ProcessState.STOPPED
    assert supervisor.was_stopped_by_coordinator is False

    await client.aclose()
    await gateway.close()


# ---------------------------------------------------------------------------
# Test Suite: Uncertain Inference Termination & Restart Prevention
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_without_done_marker_inhibits_restart():
    """
    If a stream completes without [DONE] or a finish_reason, the termination is uncertain.
    The coordinator must impose a protective RestartInhibition and prevent mining restart.
    """
    dispatcher = EventDispatcher()
    lease_mgr = LeaseManager(default_cooldown_seconds=0.05, event_dispatcher=dispatcher)
    fake_miner = FakeProcessBackend(name="krig", running=True)
    supervisor = ProcessSupervisor(backend=fake_miner, event_dispatcher=dispatcher)

    # Wire policy with restart action on idle
    policy_engine = PolicyEngine(event_dispatcher=dispatcher, lease_manager=lease_mgr)
    policy = Policy(
        name="manage-miner",
        trigger_event="lmstudio.inference_requested",
        condition=ProcessRunningCondition(supervisor),
        actions=[StopProcessAction(supervisor=supervisor)],
        resource="gpu.inference",
        cooldown_seconds=0.05,
        after_release_actions=[StartProcessAction(supervisor=supervisor)],
    )
    policy_engine.register_policy(policy)

    gateway = LMStudioGateway(
        upstream_url="http://mock-lmstudio",
        event_dispatcher=dispatcher,
        lease_manager=lease_mgr,
    )
    upstream_app = create_phase_b_upstream_app()
    gateway._http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=upstream_app),
        base_url="http://mock-lmstudio",
    )

    app = gateway.create_app()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway")

    # Request stream with mode 'incomplete_no_done'
    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "m", "stream": True, "mode": "incomplete_no_done"},
    )
    assert resp.status_code == 200
    chunks = []
    async for chunk in resp.aiter_bytes():
        chunks.append(chunk)

    assert len(chunks) > 0
    # Stream completed on HTTP, but without [DONE]
    assert lease_mgr.is_restart_inhibited("gpu.inference") is True
    inhibition = lease_mgr.get_inhibition("gpu.inference")
    assert inhibition is not None
    assert "Stream ended without completion signal" in inhibition.reason

    # Cooldown must NOT start
    assert lease_mgr.is_cooling_down("gpu.inference") is False

    # Wait past cooldown duration to verify miner is NOT restarted
    await asyncio.sleep(0.1)
    st = await supervisor.status()
    assert st.state == ProcessState.STOPPED, "Miner was restarted despite uncertain stream termination!"

    # Now verify recovery clears inhibition and allows cooldown to proceed
    cleared = await lease_mgr.clear_inhibition("gpu.inference", origin="admin_recovery")
    assert cleared is not None
    assert lease_mgr.is_restart_inhibited("gpu.inference") is False
    assert lease_mgr.is_cooling_down("gpu.inference") is True

    # After cooldown expires, miner restarts
    await asyncio.sleep(0.1)
    st = await supervisor.status()
    assert st.state == ProcessState.RUNNING

    await client.aclose()
    await gateway.close()


@pytest.mark.asyncio
async def test_stream_confirmed_done_allows_restart():
    """
    When streaming completes with confirmed [DONE], cooldown starts and miner restarts.
    """
    dispatcher = EventDispatcher()
    lease_mgr = LeaseManager(default_cooldown_seconds=0.05, event_dispatcher=dispatcher)
    fake_miner = FakeProcessBackend(name="krig", running=True)
    supervisor = ProcessSupervisor(backend=fake_miner, event_dispatcher=dispatcher)

    policy_engine = PolicyEngine(event_dispatcher=dispatcher, lease_manager=lease_mgr)
    policy = Policy(
        name="manage-miner",
        trigger_event="lmstudio.inference_requested",
        condition=ProcessRunningCondition(supervisor),
        actions=[StopProcessAction(supervisor=supervisor)],
        resource="gpu.inference",
        cooldown_seconds=0.05,
        after_release_actions=[StartProcessAction(supervisor=supervisor)],
    )
    policy_engine.register_policy(policy)

    gateway = LMStudioGateway(
        upstream_url="http://mock-lmstudio",
        event_dispatcher=dispatcher,
        lease_manager=lease_mgr,
    )
    upstream_app = create_phase_b_upstream_app()
    gateway._http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=upstream_app),
        base_url="http://mock-lmstudio",
    )

    app = gateway.create_app()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway")

    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "m", "stream": True, "mode": "normal_done"},
    )
    assert resp.status_code == 200
    chunks = [chunk async for chunk in resp.aiter_bytes()]
    assert len(chunks) > 0

    assert lease_mgr.is_restart_inhibited("gpu.inference") is False
    assert lease_mgr.is_cooling_down("gpu.inference") is True

    await asyncio.sleep(0.1)
    st = await supervisor.status()
    assert st.state == ProcessState.RUNNING

    await client.aclose()
    await gateway.close()


@pytest.mark.asyncio
async def test_upstream_error_inhibits_restart():
    """
    When upstream returns an error (500), restart must be inhibited to prevent GPU thrashing.
    """
    dispatcher = EventDispatcher()
    lease_mgr = LeaseManager(default_cooldown_seconds=0.05, event_dispatcher=dispatcher)
    gateway = LMStudioGateway(
        upstream_url="http://mock-lmstudio",
        event_dispatcher=dispatcher,
        lease_manager=lease_mgr,
    )
    upstream_app = create_phase_b_upstream_app()
    gateway._http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=upstream_app),
        base_url="http://mock-lmstudio",
    )

    app = gateway.create_app()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway")

    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "m", "mode": "server_error"},
    )
    assert resp.status_code == 500
    assert lease_mgr.is_restart_inhibited("gpu.inference") is True

    await client.aclose()
    await gateway.close()


@pytest.mark.asyncio
async def test_recovery_endpoint_via_gateway():
    """
    Test /_coordinator/recover endpoint clears active inhibition.
    """
    dispatcher = EventDispatcher()
    lease_mgr = LeaseManager(default_cooldown_seconds=10.0, event_dispatcher=dispatcher)
    await lease_mgr.inhibit_restart("gpu.inference", "Test failure", "req-1")
    assert lease_mgr.is_restart_inhibited("gpu.inference") is True

    gateway = LMStudioGateway(
        upstream_url="http://mock-lmstudio",
        event_dispatcher=dispatcher,
        lease_manager=lease_mgr,
    )
    app = gateway.create_app()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway")

    # Query status
    st_resp = await client.get("/_coordinator/status")
    assert st_resp.status_code == 200
    data = st_resp.json()
    assert data["gpu_inference"]["is_restart_inhibited"] is True
    assert data["gpu_inference"]["inhibition"]["reason"] == "Test failure"

    # Recover
    rec_resp = await client.post("/_coordinator/recover?resource=gpu.inference")
    assert rec_resp.status_code == 200
    rec_data = rec_resp.json()
    assert rec_data["status"] == "cleared"

    assert lease_mgr.is_restart_inhibited("gpu.inference") is False

    await client.aclose()
    await gateway.close()


# ---------------------------------------------------------------------------
# Test Suite: Process Adoption and Permissions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_external_process_permissions():
    """
    Verify separate permissions for stopping and restarting externally launched processes.
    """
    dispatcher = EventDispatcher()

    # Case 1: allow_external_stop=False -> stop refused
    backend1 = FakeProcessBackend(
        name="external_miner",
        running=True,
        external=True,
        allow_external_stop=False,
        allow_external_restart=False,
    )
    sup1 = ProcessSupervisor(backend=backend1, event_dispatcher=dispatcher)
    st = await sup1.status()
    assert st.state == ProcessState.EXTERNAL_RUNNING
    assert st.lifecycle_owner == ProcessLifecycleOwner.EXTERNAL

    stop_ok = await sup1.stop()
    assert stop_ok is False
    st = await sup1.status()
    assert st.state == ProcessState.EXTERNAL_RUNNING

    # Case 2: allow_external_stop=True, allow_external_restart=False -> stop works, restart refused
    backend2 = FakeProcessBackend(
        name="external_miner",
        running=True,
        external=True,
        allow_external_stop=True,
        allow_external_restart=False,
    )
    sup2 = ProcessSupervisor(backend=backend2, event_dispatcher=dispatcher)
    stop_ok = await sup2.stop()
    assert stop_ok is True
    assert sup2.was_stopped_by_coordinator is True

    # Attempt start
    start_ok = await sup2.start()
    assert start_ok is False, "External process was started without allow_external_restart!"

    # Case 3: allow_external_stop=True, allow_external_restart=True -> both allowed
    backend3 = FakeProcessBackend(
        name="external_miner",
        running=True,
        external=True,
        allow_external_stop=True,
        allow_external_restart=True,
    )
    sup3 = ProcessSupervisor(backend=backend3, event_dispatcher=dispatcher)
    assert await sup3.stop() is True
    assert await sup3.start() is True
    st3 = await sup3.status()
    assert st3.state == ProcessState.RUNNING


@pytest.mark.asyncio
async def test_external_supervisor_auto_relaunch():
    """
    Test external supervisor auto-relaunching process.
    """
    backend = FakeProcessBackend(
        name="watchdog_miner",
        running=True,
        external=True,
        allow_external_stop=True,
        relaunch_delay=0.05,
    )
    supervisor = ProcessSupervisor(backend=backend)

    # Stop process
    assert await supervisor.stop() is True
    st = await supervisor.status()
    assert st.state == ProcessState.STOPPED

    # Wait for external supervisor to auto-relaunch
    await asyncio.sleep(0.08)
    st = await supervisor.status()
    assert st.state == ProcessState.EXTERNAL_RUNNING
    assert st.lifecycle_owner == ProcessLifecycleOwner.EXTERNAL


# ---------------------------------------------------------------------------
# Test Suite: Veto and Cleanup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_action_veto_unwinds_reservation():
    """
    When a pre-inference hook raises VetoOperation, pending claims must be
    unwound completely with zero active or pending leases remaining.
    """
    dispatcher = EventDispatcher()
    lease_mgr = LeaseManager(default_cooldown_seconds=1.0, event_dispatcher=dispatcher)

    async def veto_hook(event):
        raise VetoOperation("Emergency maintenance mode")

    dispatcher.on("lmstudio.inference_requested", veto_hook, is_blocking=True)

    gateway = LMStudioGateway(
        upstream_url="http://mock-lmstudio",
        event_dispatcher=dispatcher,
        lease_manager=lease_mgr,
    )
    app = gateway.create_app()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway")

    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "m", "messages": []},
    )
    assert resp.status_code == 503
    assert resp.json()["error"]["type"] == "coordinator_veto"

    # Pending and active counts must be 0
    assert lease_mgr.pending_count("gpu.inference") == 0
    assert lease_mgr.active_count("gpu.inference") == 0

    await client.aclose()
    await gateway.close()
