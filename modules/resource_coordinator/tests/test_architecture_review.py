import asyncio
from unittest.mock import Mock

import httpx
import psutil
import pytest

from resource_coordinator.adapters.lmstudio.gateway import LMStudioGateway, StreamCompletionDetector
from resource_coordinator.config import CoordinatorConfig
from resource_coordinator.core.events import EventDispatcher
from resource_coordinator.core.leases import LeaseManager, LeaseType
from resource_coordinator.core.processes import WindowsProcessBackend, ProcessInfo, ProcessState


@pytest.mark.asyncio
@pytest.mark.parametrize("event_name", ["resource.lease_requested", "resource.acquired"])
async def test_cancel_during_lease_notification_unwinds_claim(event_name):
    dispatcher = EventDispatcher()
    manager = LeaseManager(event_dispatcher=dispatcher)
    entered = asyncio.Event()

    async def block(event):
        entered.set()
        await asyncio.Event().wait()

    dispatcher.on(event_name, block)

    async def acquire():
        async with manager.acquire("gpu"):
            pass

    task = asyncio.create_task(acquire())
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert manager.pending_count("gpu") == 0
    assert manager.active_count("gpu") == 0


@pytest.mark.asyncio
async def test_release_callback_can_acquire_another_resource():
    dispatcher = EventDispatcher()
    manager = LeaseManager(event_dispatcher=dispatcher)

    async def callback(event):
        async with manager.acquire("other"):
            pass

    dispatcher.on("resource.released", callback)

    # Avoid recursion from the other resource's release.
    async def filtered(event):
        if event.data["lease"]["resource"] == "gpu":
            await callback(event)

    dispatcher.off("resource.released", callback)
    dispatcher.on("resource.released", filtered)

    async def run():
        async with manager.acquire("gpu"):
            pass

    await asyncio.wait_for(run(), 0.2)


@pytest.mark.asyncio
async def test_success_does_not_clear_earlier_uncertainty():
    gateway = LMStudioGateway(
        standalone=True,
    )
    await gateway.lease_mgr.inhibit_restart("gpu.inference", "A may still run", "A")
    gateway._http_client = httpx.AsyncClient(
        base_url="http://upstream",
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "ok"}}]})
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway.create_app()), base_url="http://gateway"
    ) as client:
        response = await client.post("/v1/chat/completions", json={})
        assert response.status_code == 200
    assert gateway.lease_mgr.is_restart_inhibited("gpu.inference")
    assert gateway.lease_mgr.get_inhibition("gpu.inference").holder_id == "A"
    await gateway.close()


@pytest.mark.parametrize(
    "payload",
    [
        b'data: {"choices":[{"finish_reason":"stop"},{"finish_reason":null}]}\n\n',
        b'data: {"choices":[{"finish_reason":"tool_calls"}]}\n\n',
        b"event: finish\n\n",
    ],
)
def test_partial_or_tool_completion_is_not_request_completion(payload):
    detector = StreamCompletionDetector()
    detector.feed(payload)
    assert not detector.finalize()


@pytest.mark.parametrize("body", [b"{}", b'{"choices":[]}', b'{"status":"in_progress"}'])
def test_nonterminal_json_does_not_prove_completion(body):
    assert not StreamCompletionDetector.check_non_streaming(200, body)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["hook", "send", "read"])
async def test_cancelled_gateway_request_cleans_claim_and_inhibits_if_forwarded(phase):
    gateway = LMStudioGateway(
        standalone=True,
    )
    entered = asyncio.Event()

    async def block(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            await block()
            yield b""

    async def transport(req):
        if phase == "send":
            await block()
        return httpx.Response(200, headers={"content-type": "application/json"}, stream=SlowStream())

    if phase == "hook":
        gateway.dispatcher.on("lmstudio.inference_requested", block, is_blocking=True)
    gateway._http_client = httpx.AsyncClient(base_url="http://upstream", transport=httpx.MockTransport(transport))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway.create_app()), base_url="http://gateway"
    ) as client:
        task = asyncio.create_task(client.post("/v1/chat/completions", json={}))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert gateway.lease_mgr.pending_count("gpu.inference") == 0
    assert gateway.lease_mgr.active_count("gpu.inference") == 0
    assert gateway.lease_mgr.is_restart_inhibited("gpu.inference") == (phase != "hook")
    await gateway.close()


@pytest.mark.asyncio
async def test_recovery_disabled_without_explicit_auth_configuration():
    gateway = LMStudioGateway(
        standalone=True,
    )
    await gateway.lease_mgr.inhibit_restart("gpu.inference", "unknown", "A")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway.create_app()), base_url="http://gateway"
    ) as client:
        response = await client.post("/_coordinator/recover")
    assert response.status_code in (403, 503)
    assert gateway.lease_mgr.is_restart_inhibited("gpu.inference")


@pytest.mark.asyncio
async def test_access_denied_is_not_successful_stop(monkeypatch):
    backend = WindowsProcessBackend(
        "miner", r"C:/Mining/miner.exe", allow_external_stop=True, allow_force_termination=True
    )

    async def status():
        return ProcessInfo("miner", ProcessState.EXTERNAL_RUNNING, pid=123, create_time=1.0)

    monkeypatch.setattr(backend, "status", status)
    process = Mock()
    process.pid = 123
    process.create_time.return_value = 1.0
    process.children.return_value = []
    process.terminate.side_effect = psutil.AccessDenied(123)
    monkeypatch.setattr(backend, "_find_owned_process", lambda: None)
    monkeypatch.setattr(backend, "_find_external_process", lambda: process)
    # All OS boundary calls are doubles; no process receives a signal.
    import ctypes

    monkeypatch.setattr(ctypes.windll.kernel32, "GenerateConsoleCtrlEvent", lambda *args: 0)
    assert await backend.stop() is False


@pytest.mark.asyncio
async def test_external_running_process_never_launches_duplicate(monkeypatch):
    backend = WindowsProcessBackend("miner", r"C:/Mining/miner.exe", allow_external_restart=True)

    async def status():
        return ProcessInfo("miner", ProcessState.EXTERNAL_RUNNING, pid=123, create_time=1.0)

    monkeypatch.setattr(backend, "status", status)

    def forbidden(*args, **kwargs):
        pytest.fail("attempted duplicate launch")

    monkeypatch.setattr("subprocess.Popen", forbidden)
    assert await backend.start()


@pytest.mark.parametrize(
    "data",
    [
        {"version": "999"},
        {"processes": {"m": {"backend": "typo"}}},
        {"policies": [{"target_process": "missing"}]},
        {"processes": {"m": {"allow_external_stop": "false"}}},
        {"policies": [{"cooldown_seconds": -1}]},
    ],
)
def test_invalid_config_is_rejected(data):
    with pytest.raises((ValueError, TypeError)):
        CoordinatorConfig.from_dict(data)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload,status",
    [
        ({}, 409),
        ({"override": True}, 400),
        ({"override": True, "operator": "test", "reason": "verified manually"}, 200),
    ],
)
async def test_recovery_requires_attributed_override(payload, status):
    gateway = LMStudioGateway(standalone=True, recovery_token="test-token")
    await gateway.lease_mgr.inhibit_restart("gpu.inference", "unknown", "A")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway.create_app()), base_url="http://gateway"
    ) as client:
        denied = await client.post("/_coordinator/recover", json=payload)
        assert denied.status_code == 403
        response = await client.post(
            "/_coordinator/recover", json=payload, headers={"Authorization": "Bearer test-token"}
        )
        assert response.status_code == status
    assert gateway.lease_mgr.is_restart_inhibited("gpu.inference") == (status != 200)


@pytest.mark.asyncio
async def test_operator_cannot_override_active_or_pending_requests():
    gateway = LMStudioGateway(standalone=True, recovery_token="test-token")
    await gateway.lease_mgr.inhibit_restart("gpu.inference", "unknown", "A")
    async with gateway.lease_mgr.reserve("gpu.inference") as reservation:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=gateway.create_app()), base_url="http://gateway"
        ) as client:
            for active in (False, True):
                if active:
                    await reservation.activate()
                response = await client.post(
                    "/_coordinator/recover",
                    headers={"Authorization": "Bearer test-token"},
                    json={"override": True, "operator": "test", "reason": "override"},
                )
                assert response.status_code == 409
                assert gateway.lease_mgr.is_restart_inhibited("gpu.inference")


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["start", "body", "upstream_error"])
async def test_stream_send_failure_or_upstream_error_never_restarts(phase):
    gateway = LMStudioGateway(
        standalone=True,
    )
    closed = False

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"finish_reason":"stop"}]}\n\n'
            if phase == "upstream_error":
                raise httpx.ReadError("truncated")
            yield b"data: [DONE]\n\n"

        async def aclose(self):
            nonlocal closed
            closed = True

    gateway._http_client = httpx.AsyncClient(
        base_url="http://upstream",
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Stream())
        ),
    )
    from starlette.requests import Request, ClientDisconnect

    request = Request(
        {"type": "http", "method": "POST", "path": "/v1/chat/completions", "headers": [], "query_string": b""}
    )
    response = await gateway._proxy_with_coordination(
        request,
        "/v1/chat/completions",
        b"{}",
        "A",
        "gpu.inference",
        LeaseType.SHARED,
        "lmstudio.inference_requested",
        "lmstudio.inference_finished",
        "test",
    )

    async def receive():
        await asyncio.Event().wait()

    async def send(message):
        if phase == "start" or (phase == "body" and message["type"] == "http.response.body"):
            raise OSError("downstream disconnected")

    scope = {"type": "http", "asgi": {"spec_version": "2.4"}}
    with pytest.raises((OSError, httpx.ReadError, ClientDisconnect)):
        await response(scope, receive, send)
    assert closed
    assert gateway.lease_mgr.active_count("gpu.inference") == 0
    assert gateway.lease_mgr.pending_count("gpu.inference") == 0
    assert gateway.lease_mgr.is_restart_inhibited("gpu.inference")
    await gateway.close()


@pytest.mark.asyncio
async def test_close_reservation_while_waiting_cannot_activate_later():
    manager = LeaseManager()
    from resource_coordinator.core.leases import LeaseType

    async with manager.acquire("gpu", LeaseType.EXCLUSIVE):
        async with manager.reserve("gpu") as reservation:
            task = asyncio.create_task(reservation.activate())
            await asyncio.sleep(0)
            await reservation.close()
        # Release of the exclusive lease must not awaken an abandoned claim.
    with pytest.raises(RuntimeError):
        await asyncio.wait_for(task, 0.2)
    assert manager.active_count("gpu") == 0
    assert manager.pending_count("gpu") == 0


@pytest.mark.asyncio
async def test_same_reservation_concurrent_activation_is_idempotent():
    dispatcher = EventDispatcher()
    manager = LeaseManager(event_dispatcher=dispatcher)
    entered = asyncio.Event()
    unblock = asyncio.Event()

    async def acquired(event):
        entered.set()
        await unblock.wait()

    dispatcher.on("resource.acquired", acquired)
    async with manager.reserve("gpu") as reservation:
        a = asyncio.create_task(reservation.activate())
        await entered.wait()
        b = asyncio.create_task(reservation.activate())
        await asyncio.sleep(0)
        unblock.set()
        results = await asyncio.gather(a, b)
        assert results[0] == results[1]
        assert manager.active_count("gpu") == 1
    assert manager.active_count("gpu") == 0


@pytest.mark.asyncio
async def test_zero_cooldown_is_cancelled_before_idle_dispatch():
    dispatcher = EventDispatcher()
    manager = LeaseManager(default_cooldown_seconds=0, event_dispatcher=dispatcher)
    idle = []
    dispatcher.on("resource.idle", lambda event: idle.append(event))
    async with manager.acquire("gpu"):
        pass
    async with manager.reserve("gpu"):
        await asyncio.sleep(0.01)
        assert not idle


@pytest.mark.asyncio
async def test_timeout_command_does_not_leave_child_running(monkeypatch):
    from resource_coordinator.core.actions import CommandAction

    class Process:
        returncode = None
        killed = False

        async def communicate(self):
            await asyncio.Event().wait()

        def kill(self):
            self.killed = True

        async def wait(self):
            self.returncode = -1

    proc = Process()

    async def spawn(*args, **kwargs):
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    result = await CommandAction(["offline-double"], timeout_seconds=0.01).execute()
    assert not result.is_ok
    assert proc.killed
    assert proc.returncode == -1


@pytest.mark.parametrize(
    "payload",
    [
        b'event: chat.end\ndata: {"type":"chat.end","result":{"model_instance_id":"qwen","output":[],"stats":{}}}\n\n',
        b'data: {"type":"response.completed","response":{"status":"completed","output":[]}}\n\n',
        b"data: [DONE]\n\n",
    ],
)
def test_complete_native_or_compatible_sse_split_across_chunks(payload):
    detector = StreamCompletionDetector()
    for byte in payload:
        detector.feed(bytes([byte]))
    assert detector.finalize()


@pytest.mark.asyncio
async def test_recovery_rejects_activity_on_other_gpu_resource():
    gateway = LMStudioGateway(standalone=True, recovery_token="test-token")
    await gateway.lease_mgr.inhibit_restart("gpu.inference", "unknown", "A")
    async with gateway.lease_mgr.acquire("gpu.model_loading"):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=gateway.create_app()), base_url="http://gateway"
        ) as client:
            response = await client.post(
                "/_coordinator/recover",
                headers={"Authorization": "Bearer test-token"},
                json={"override": True, "operator": "test", "reason": "override"},
            )
            assert response.status_code == 409
    assert gateway.lease_mgr.is_restart_inhibited("gpu.inference")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["pause", "resume"])
async def test_standalone_miner_mutation_refused_without_daemon_state(operation, monkeypatch):
    from resource_coordinator import cli

    def forbidden(*args, **kwargs):
        pytest.fail("must not construct independent process controls")

    monkeypatch.setattr(cli, "build_system", forbidden)
    if operation == "pause":
        assert await cli._async_miner_pause(None, 1) == 1
    else:
        assert await cli._async_miner_resume(None) == 1


@pytest.mark.asyncio
async def test_idle_restart_holds_arbitration_boundary_before_new_reservation():
    from resource_coordinator.core.actions import StartProcessAction
    from resource_coordinator.core.policies import Policy, PolicyEngine
    from resource_coordinator.core.processes import FakeProcessBackend, ProcessSupervisor

    dispatcher = EventDispatcher()
    manager = LeaseManager(default_cooldown_seconds=0, event_dispatcher=dispatcher)
    backend = FakeProcessBackend(start_delay=0.1)
    supervisor = ProcessSupervisor(backend, dispatcher)
    supervisor.was_stopped_by_coordinator = True
    entered = asyncio.Event()

    async def starting(event):
        entered.set()

    dispatcher.on("process.start_requested", starting)
    engine = PolicyEngine(dispatcher, manager)
    engine.register_policy(
        Policy("p", "request", resource="gpu", after_release_actions=[StartProcessAction(supervisor)])
    )
    async with manager.acquire("gpu"):
        pass
    await asyncio.wait_for(entered.wait(), 1)
    async with manager.reserve("gpu"):
        await asyncio.sleep(0.15)
        # The idle action won the arbitration lock before this reservation could
        # register. The request is admitted only after the start action settles.
        assert backend.running


@pytest.mark.asyncio
async def test_windows_unknown_state_cannot_authorize_inference(monkeypatch):
    from resource_coordinator.config import build_system, load_config

    system = build_system(load_config(), use_fake_processes=True)
    backend = system.supervisors["krig"].backend

    async def unknown():
        return ProcessInfo("krig", ProcessState.UNKNOWN)

    async def no_stop(*args, **kwargs):
        return False

    monkeypatch.setattr(backend, "status", unknown)
    monkeypatch.setattr(backend, "stop", no_stop)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=system.gateway.create_app()), base_url="http://gateway"
    ) as client:
        response = await client.post("/v1/chat/completions", json={})
    assert response.status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize("recycled", [True, False])
async def test_windows_stop_requires_exact_identity_and_opt_in_force(recycled, monkeypatch):
    backend = WindowsProcessBackend("miner", r"C:/Mining/miner.exe", allow_external_stop=True)

    async def status():
        return ProcessInfo("miner", ProcessState.EXTERNAL_RUNNING, pid=123, create_time=1.0)

    monkeypatch.setattr(backend, "status", status)
    process = Mock()
    process.pid = 123
    process.create_time.return_value = 2.0 if recycled else 1.0
    process.children.return_value = []

    def forbidden(*args, **kwargs):
        pytest.fail("must not terminate wrong PID identity or use implicit force")

    process.terminate = forbidden
    process.kill = forbidden
    monkeypatch.setattr(backend, "_find_owned_process", lambda: None)
    monkeypatch.setattr(backend, "_find_external_process", lambda: process)
    assert not await backend.stop()


@pytest.mark.asyncio
async def test_external_restart_permission_survives_loss_of_backend_owner():
    from resource_coordinator.core.processes import FakeProcessBackend, ProcessSupervisor, ProcessLifecycleOwner

    class ForgetfulBackend(FakeProcessBackend):
        async def stop(self, timeout=10):
            stopped = await super().stop(timeout)
            self.lifecycle_owner = ProcessLifecycleOwner.UNMANAGED
            return stopped

    backend = ForgetfulBackend(running=True, external=True, allow_external_stop=True)
    supervisor = ProcessSupervisor(backend)
    assert await supervisor.stop()
    assert not await supervisor.start()
    assert not backend.running


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/v0/completions", "/api/v0/embeddings", "/v1/messages", "/v1/future-inference"])
async def test_mutating_routes_cannot_bypass_coordination(path):
    from resource_coordinator.core.events import VetoOperation

    gateway = LMStudioGateway(
        standalone=True,
    )

    async def veto(event):
        raise VetoOperation("offline veto")

    gateway.dispatcher.on("lmstudio.inference_requested", veto, is_blocking=True)

    def forbidden(req):
        pytest.fail("uncoordinated request reached upstream")

    gateway._http_client = httpx.AsyncClient(base_url="http://upstream", transport=httpx.MockTransport(forbidden))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway.create_app()), base_url="http://gateway"
    ) as client:
        response = await client.post(path, json={})
    assert response.status_code in (503, 501)
    await gateway.close()


@pytest.mark.parametrize("payload", [b"data: [DONE]\n", b'data: [DONE]\n\ndata: {"error":"still failed"}\n\n'])
def test_unframed_terminal_or_error_after_marker_is_uncertain(payload):
    detector = StreamCompletionDetector()
    detector.feed(payload)
    assert not detector.finalize()


def test_terminal_marker_followed_by_truncated_frame_is_uncertain():
    detector = StreamCompletionDetector()
    detector.feed(b'data: [DONE]\n\ndata: {"error":"truncated')
    assert not detector.finalize()


@pytest.mark.asyncio
async def test_parent_exit_race_does_not_hide_known_running_child(monkeypatch):
    backend = WindowsProcessBackend(
        "miner", r"C:/Mining/miner.exe", allow_external_stop=True, allow_force_termination=True
    )

    async def status():
        return ProcessInfo("miner", ProcessState.EXTERNAL_RUNNING, pid=123, create_time=1.0)

    async def absent(*args, **kwargs):
        return True

    parent = Mock()
    parent.pid = 123
    parent.create_time.return_value = 1.0
    child = Mock()
    child.is_running.return_value = True
    parent.children.return_value = [child]
    parent.terminate.side_effect = psutil.NoSuchProcess(123)
    monkeypatch.setattr(backend, "status", status)
    monkeypatch.setattr(backend, "wait_stopped", absent)
    monkeypatch.setattr(backend, "_find_owned_process", lambda: None)
    monkeypatch.setattr(backend, "_find_external_process", lambda: parent)
    assert not await backend.stop()
