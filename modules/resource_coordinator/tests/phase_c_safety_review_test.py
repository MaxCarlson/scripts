import asyncio
from pathlib import Path
from unittest.mock import Mock

import httpx
import psutil
import pytest

from resource_coordinator.adapters.lmstudio.gateway import LMStudioGateway
from resource_coordinator.core.durable_state import CoordinatorState, StateCodec, ReconciliationOutcome, reconcile_pid
from resource_coordinator.core.events import EventDispatcher
from resource_coordinator.core.leases import LeaseManager
from resource_coordinator.core.processes import WindowsProcessBackend, FakeProcessBackend, ProcessSupervisor
from resource_coordinator.core.policies import Policy, PolicyEngine
from resource_coordinator.core.actions import StartProcessAction
from resource_coordinator.monitors.gpu import NvidiaGpuMonitor


@pytest.mark.parametrize("delta", [0.0001, 0.01, 0.999])
def test_close_but_different_creation_time_is_never_verified(delta):
    assert reconcile_pid(123, 100.0, lambda pid: 100.0 + delta) == ReconciliationOutcome.PID_RECYCLED


@pytest.mark.parametrize("tolerance", [0.01, 1.0, float("nan")])
def test_identity_tolerance_cannot_be_relaxed(tolerance):
    with pytest.raises(ValueError):
        reconcile_pid(123, 100.0, lambda pid: 100.2, tolerance)


@pytest.mark.parametrize("pid,created", [(123, None), (True, 100.0), (123, float("nan"))])
def test_ambiguous_persisted_identity_is_not_not_running(pid, created):
    outcome = reconcile_pid(pid, created, lambda pid: 100.0)
    assert outcome.value == "unverifiable"


def test_pid_query_access_denied_does_not_mean_stopped():
    def denied(pid):
        raise psutil.AccessDenied(pid)

    assert reconcile_pid(123, 100.0, denied) == ReconciliationOutcome.ACCESS_DENIED


@pytest.mark.parametrize("created", [100.01, None])
def test_owned_process_requires_exact_known_create_time(created, monkeypatch):
    backend = WindowsProcessBackend("miner", r"C:/Mining/miner.exe")
    backend._owned_pid = 123
    backend._owned_create_time = created
    process = Mock()
    process.create_time.return_value = 100.0
    monkeypatch.setattr(psutil, "Process", lambda pid: process)
    monkeypatch.setattr(backend, "_same_executable", lambda process: True)
    assert backend._find_owned_process() is None


@pytest.mark.parametrize(
    "body", [None, "{broken", "{}", '{"version":"999","updated_at":1,"inhibitions":{},"processes":{}}']
)
def test_missing_corrupt_or_unknown_state_never_loads_clean(tmp_path, body):
    path = tmp_path / "state.json"
    if body is not None:
        path.write_text(body)
    with pytest.raises((OSError, ValueError)):
        StateCodec.load(path)


def test_persisted_string_false_cannot_grant_restart_ownership():
    raw = CoordinatorState().to_dict()
    raw["processes"] = {"miner": {"name": "miner", "was_stopped_by_coordinator": "false"}}
    with pytest.raises(ValueError):
        CoordinatorState.from_dict(raw)


@pytest.mark.asyncio
async def test_restore_validates_all_records_before_installing_any_hold():
    manager = LeaseManager()
    state = CoordinatorState(inhibitions={"gpu.inference": {"reason": "unknown", "holder_id": "A"}, "bad": []})
    with pytest.raises(ValueError):
        await StateCodec.restore_into_leases(state, manager)
    assert not manager.is_restart_inhibited("gpu.inference")


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True])
async def test_gpu_query_timeout_or_cancellation_reaps_subprocess(cancelled, monkeypatch):
    entered = asyncio.Event()

    class Process:
        returncode = None
        killed = False

        async def communicate(self):
            entered.set()
            await asyncio.Event().wait()

        def kill(self):
            self.killed = True

        async def wait(self):
            self.returncode = -1

    proc = Process()

    async def spawn(*args, **kwargs):
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monitor = NvidiaGpuMonitor(timeout_seconds=0.01 if not cancelled else 60)
    task = asyncio.create_task(monitor.get_metrics())
    await entered.wait()
    if cancelled:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        assert await task == []
    assert proc.killed and proc.returncode == -1


@pytest.mark.asyncio
async def test_missing_gpu_measurement_is_not_zero_utilization(monkeypatch):
    monitor = NvidiaGpuMonitor()

    async def empty():
        return []

    monkeypatch.setattr(monitor, "get_metrics", empty)
    with pytest.raises(RuntimeError):
        await monitor.get_max_utilization()


@pytest.mark.asyncio
async def test_unconfigured_model_load_cannot_reach_upstream():
    gateway = LMStudioGateway()

    def forbidden(req):
        pytest.fail("unconfigured model mutation reached upstream")

    gateway._http_client = httpx.AsyncClient(base_url="http://upstream", transport=httpx.MockTransport(forbidden))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway.create_app()), base_url="http://gateway"
    ) as client:
        response = await client.post("/api/v1/models/load", json={"model": "fake"})
    assert response.status_code == 503
    await gateway.close()


@pytest.mark.asyncio
async def test_idle_inference_does_not_ignore_unregistered_gpu_model_hold():
    dispatcher = EventDispatcher()
    manager = LeaseManager(default_cooldown_seconds=0, event_dispatcher=dispatcher)
    backend = FakeProcessBackend()
    supervisor = ProcessSupervisor(backend, dispatcher)
    supervisor.was_stopped_by_coordinator = True
    engine = PolicyEngine(dispatcher, manager)
    engine.register_policy(
        Policy("p", "request", resource="gpu.inference", after_release_actions=[StartProcessAction(supervisor)])
    )
    await manager.inhibit_restart("gpu.model_loading", "uncertain load", "A")
    await dispatcher.emit("resource.idle", {"resource": "gpu.inference"})
    assert not backend.running


@pytest.mark.asyncio
@pytest.mark.parametrize("row", ["0, GPU, nan, 100, 200, 30", "0, GPU, -1, 100, 200, 30", "0, GPU, 10, 100, 200, nan"])
async def test_invalid_gpu_values_are_unavailable_not_idle(row, monkeypatch):
    class Process:
        returncode = 0

        async def communicate(self):
            return row.encode(), b""

    async def spawn(*args, **kwargs):
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    assert await NvidiaGpuMonitor().get_metrics() == []


@pytest.mark.asyncio
async def test_template_launches_known_group_and_successful_signal_still_requires_absence(monkeypatch):
    import subprocess
    import ctypes
    from resource_coordinator.config import load_config, build_system

    cfg = load_config(Path(__file__).resolve().parent.parent / "config.supervised-template.yaml")
    backend = build_system(cfg).supervisors["krig_miner"].backend
    assert not backend.allow_external_stop
    assert not backend.allow_external_restart
    calls = []

    def spawn(cmd, **kwargs):
        calls.append(kwargs["creationflags"])
        return Mock(pid=123)

    process = Mock(pid=123)
    process.create_time.return_value = 100.0
    process.name.return_value = Path(cfg.processes["krig_miner"].executable).name
    process.exe.return_value = cfg.processes["krig_miner"].executable
    process.is_running.return_value = True
    process.children.return_value = []
    monkeypatch.setattr(backend, "_find_external_process", lambda: None)
    monkeypatch.setattr(subprocess, "Popen", spawn)
    monkeypatch.setattr(psutil, "Process", lambda pid: process)
    monkeypatch.setattr(ctypes.windll.kernel32, "GenerateConsoleCtrlEvent", lambda event, group: 1)

    async def still_running(*args, **kwargs):
        return False

    monkeypatch.setattr(backend, "wait_stopped", still_running)
    assert await backend.start()
    assert calls == [subprocess.CREATE_NEW_PROCESS_GROUP]
    assert not await backend.stop()


@pytest.mark.parametrize(
    "body",
    [
        '{"version":"1.0","updated_at":1,"processes":{},"inhibitions":{"gpu.inference":{"reason":"uncertain","holder_id":"A"}},"inhibitions":{}}',
        '{"version":"1.0","updated_at":1,"inhibitions":{},"processes":{"miner":{"name":"miner","was_stopped_by_coordinator":false,"was_stopped_by_coordinator":true}}}',
    ],
)
def test_duplicate_state_keys_cannot_erase_hold_or_grant_restart(body):
    with pytest.raises(ValueError):
        StateCodec.deserialize(body)


@pytest.mark.asyncio
async def test_stop_action_waits_for_serialized_start_even_if_initial_status_is_stopped():
    from resource_coordinator.core.actions import StopProcessAction

    entered, release = asyncio.Event(), asyncio.Event()

    class StartingBackend(FakeProcessBackend):
        async def start(self):
            entered.set()
            await release.wait()
            return await super().start()

    backend = StartingBackend()
    supervisor = ProcessSupervisor(backend)
    supervisor.was_stopped_by_coordinator = True
    start_task = asyncio.create_task(supervisor.start())
    await entered.wait()
    stop_task = asyncio.create_task(StopProcessAction(supervisor).execute())
    try:
        await asyncio.sleep(0)
        assert not stop_task.done(), "STOPPED snapshot must not bypass the action mutex"
    finally:
        release.set()
        await start_task
        result = await stop_task
    assert result.is_ok
    assert not backend.running
