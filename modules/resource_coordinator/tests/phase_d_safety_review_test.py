import asyncio

import httpx
import pytest

from resource_coordinator.config import CoordinatorConfig, ProcessConfig, PolicyConfig, build_system
from resource_coordinator.core.service import CoordinatorService, ServiceState
from resource_coordinator.adapters.lmstudio.gateway import LMStudioGateway


def assembled(**kwargs):
    config = CoordinatorConfig(
        processes={"krig": ProcessConfig(name="krig", backend="fake")},
        policies=[
            PolicyConfig(
                name="stop",
                trigger_event="lmstudio.inference_requested",
                target_process="krig",
                resource="gpu.inference",
                cooldown_seconds=0.02,
            )
        ],
    )
    system = build_system(config, use_fake_processes=True)
    service = CoordinatorService(system, **kwargs)
    return system, service


@pytest.mark.asyncio
async def test_real_factory_lifespan_start_miner_actually_launches_owned_miner():
    system, service = assembled(start_miner_on_ready=True, stop_miner_on_shutdown=True)
    app = system.gateway.create_app(service)
    async with app.router.lifespan_context(app):
        assert service.is_ready
        assert system.supervisors["krig"].backend.running
        assert (await system.miner_adapter.status()).is_coordinator_owned
    assert not system.supervisors["krig"].backend.running


@pytest.mark.asyncio
async def test_ready_not_published_during_startup_and_cancel_fails_closed(monkeypatch):
    system, service = assembled(start_miner_on_ready=True)
    entered = asyncio.Event()

    async def blocked(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(system.miner_adapter, "resume", blocked)
    task = asyncio.create_task(service.start())
    await entered.wait()
    try:
        assert not service.is_ready
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert not service.is_ready
    assert system.lease_mgr.is_restart_inhibited("gpu.inference")


@pytest.mark.asyncio
async def test_abort_does_not_wait_for_startup_lock(monkeypatch):
    system, service = assembled(start_miner_on_ready=True)
    entered = asyncio.Event()

    async def blocked(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(system.miner_adapter, "resume", blocked)
    task = asyncio.create_task(service.start())
    await entered.wait()
    try:
        await asyncio.wait_for(service.emergency_abort("test"), 0.2)
        assert not service.is_ready
        assert system.lease_mgr.is_restart_inhibited("gpu.inference")
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_shutdown_cannot_restart_miner_after_cooldown_or_pending_unwind():
    system, service = assembled(stop_miner_on_shutdown=True, drain_timeout_seconds=0.1)
    await service.start()
    supervisor = system.supervisors["krig"]
    await supervisor.start(only_if_stopped_by_coordinator=False)
    await supervisor.stop()
    async with system.lease_mgr.acquire("gpu.inference"):
        pass
    await service.stop()
    await asyncio.sleep(0.05)
    assert not supervisor.backend.running
    assert system.lease_mgr.is_restart_inhibited("gpu.inference")


@pytest.mark.asyncio
async def test_pending_only_drain_deadline_retains_protection():
    system, service = assembled(drain_timeout_seconds=0.1)
    await service.start()
    async with system.lease_mgr.reserve("gpu.inference"):
        await service.stop()
        assert system.lease_mgr.is_restart_inhibited("gpu.inference")
        assert service.state == ServiceState.RECONCILIATION_REQUIRED
    await asyncio.sleep(0.04)
    assert not system.lease_mgr.is_cooling_down("gpu.inference")


@pytest.mark.asyncio
async def test_shutdown_stop_failure_is_not_success():
    system, service = assembled(stop_miner_on_shutdown=True)
    await service.start()
    supervisor = system.supervisors["krig"]
    await supervisor.start(only_if_stopped_by_coordinator=False)
    supervisor.backend.fail_stop = True
    await service.stop()
    assert service.state == ServiceState.RECONCILIATION_REQUIRED
    assert system.lease_mgr.is_restart_inhibited("gpu.inference")


@pytest.mark.asyncio
async def test_abort_endpoint_authentication_and_terminal_recovery(monkeypatch):
    monkeypatch.delenv("RESOURCE_COORDINATOR_OPERATOR_TOKEN", raising=False)
    monkeypatch.delenv("RESOURCE_COORDINATOR_RECOVERY_TOKEN", raising=False)
    system, service = assembled()
    await service.start()
    app = system.gateway.create_app(service)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway") as client:
        denied = await client.post("/_coordinator/abort", json={"reason": "test", "operator": "test"})
        assert denied.status_code == 503
        assert service.is_ready
        system.gateway.recovery_token = "test-token"
        denied = await client.post("/_coordinator/abort", json={"reason": "test", "operator": "test"})
        assert denied.status_code == 403
        response = await client.post(
            "/_coordinator/abort",
            headers={"Authorization": "Bearer test-token"},
            json={"reason": "test", "operator": "test"},
        )
        assert response.status_code == 200
        response = await client.post(
            "/_coordinator/recover",
            headers={"Authorization": "Bearer test-token"},
            json={"override": True, "operator": "test", "reason": "override"},
        )
        assert response.status_code == 409
        assert system.lease_mgr.is_restart_inhibited("gpu.inference")


@pytest.mark.asyncio
async def test_abort_while_blocking_hook_waits_prevents_later_forwarding():
    system, service = assembled()
    await service.start()
    entered, release = asyncio.Event(), asyncio.Event()

    async def hook(event):
        entered.set()
        await release.wait()

    system.dispatcher.on("lmstudio.inference_requested", hook, is_blocking=True)

    def forbidden(request):
        pytest.fail("old admission decision forwarded after abort")

    system.gateway._http_client = httpx.AsyncClient(
        base_url="http://upstream", transport=httpx.MockTransport(forbidden)
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=system.gateway.create_app(service)), base_url="http://gateway"
    ) as client:
        task = asyncio.create_task(client.post("/v1/chat/completions", json={}))
        await entered.wait()
        await service.emergency_abort("test")
        release.set()
        response = await task
        assert response.status_code == 503
    assert system.lease_mgr.active_count("gpu.inference") == 0
    await system.gateway.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/v1/models/load", "/v1/chat/completions", "/unknown", "/_coordinator/unknown"])
async def test_unknown_get_cannot_reach_uncoordinated_upstream(path):
    system, service = assembled()
    await service.start()

    def forbidden(request):
        pytest.fail("unknown GET reached upstream")

    system.gateway._http_client = httpx.AsyncClient(
        base_url="http://upstream", transport=httpx.MockTransport(forbidden)
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=system.gateway.create_app(service)), base_url="http://gateway"
    ) as client:
        response = await client.get(path)
    assert response.status_code in (404, 405, 501)
    await system.gateway.close()


@pytest.mark.asyncio
async def test_unbound_default_gateway_does_not_admit_inference():
    gateway = LMStudioGateway()

    def forbidden(request):
        pytest.fail("unbound gateway admitted protected traffic")

    gateway._http_client = httpx.AsyncClient(base_url="http://upstream", transport=httpx.MockTransport(forbidden))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway.create_app()), base_url="http://gateway"
    ) as client:
        assert (await client.post("/v1/chat/completions", json={})).status_code == 503
    await gateway.close()


@pytest.mark.asyncio
async def test_service_binding_survives_create_app_without_repeating_service():
    system, service = assembled()
    system.gateway.create_app(service)
    app_again = system.gateway.create_app()
    async with app_again.router.lifespan_context(app_again):
        assert service.is_ready
    assert not service.is_ready


@pytest.mark.asyncio
async def test_lifespan_exception_still_shuts_down():
    system, service = assembled()
    app = system.gateway.create_app(service)
    with pytest.raises(RuntimeError):
        async with app.router.lifespan_context(app):
            raise RuntimeError("test")
    assert not service.is_ready
    assert system.lease_mgr.is_restart_inhibited("gpu.inference")


@pytest.mark.asyncio
async def test_abort_during_body_upload_cannot_reuse_admission():
    system, service = assembled()
    await service.start()
    app = system.gateway.create_app(service)
    entered, release = asyncio.Event(), asyncio.Event()
    sent = []

    async def receive():
        entered.set()
        await release.wait()
        return {"type": "http.request", "body": b"{}", "more_body": False}

    async def send(message):
        sent.append(message)

    def forbidden(request):
        pytest.fail("upload reused stale admission after abort")

    system.gateway._http_client = httpx.AsyncClient(
        base_url="http://upstream", transport=httpx.MockTransport(forbidden)
    )
    task = asyncio.create_task(
        app(
            {
                "type": "http",
                "asgi": {"spec_version": "2.4"},
                "method": "POST",
                "path": "/v1/chat/completions",
                "headers": [],
                "query_string": b"",
            },
            receive,
            send,
        )
    )
    await entered.wait()
    await service.emergency_abort("during upload")
    release.set()
    await task
    assert next(m for m in sent if m["type"] == "http.response.start")["status"] == 503
    await system.gateway.close()


@pytest.mark.asyncio
async def test_abort_from_reservation_observer_does_not_run_new_stop_action():
    system, service = assembled(start_miner_on_ready=True)
    await service.start()

    async def abort(event):
        await service.emergency_abort("reservation notification")

    system.dispatcher.on("resource.lease_requested", abort)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=system.gateway.create_app(service)), base_url="http://gateway"
    ) as client:
        response = await client.post("/v1/chat/completions", json={})
    assert response.status_code == 503
    assert system.supervisors["krig"].backend.running, "abort must not schedule a new process mutation"


@pytest.mark.asyncio
async def test_requested_start_failure_is_not_ready():
    system, service = assembled(start_miner_on_ready=True)
    system.supervisors["krig"].backend.fail_start = True
    assert not await service.start()
    assert not service.is_ready
    assert system.lease_mgr.is_restart_inhibited("gpu.inference")


@pytest.mark.asyncio
async def test_shutdown_cancellation_and_client_close_error_keep_restart_latch(monkeypatch):
    system, service = assembled()
    await service.start()
    async with system.lease_mgr.reserve("gpu.inference"):
        task = asyncio.create_task(service.stop())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert service.state == ServiceState.RECONCILIATION_REQUIRED
    assert system.lease_mgr.restarts_blocked

    async def failed_close():
        raise RuntimeError("offline close failure")

    monkeypatch.setattr(system.gateway, "close", failed_close)
    await service.stop()
    assert service.state == ServiceState.RECONCILIATION_REQUIRED
    assert not service.is_ready


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/v1/chat/completions",
        "/v1/completions",
        "/v1/embeddings",
        "/v1/responses",
        "/v1/messages",
        "/api/v0/chat/completions",
        "/api/v0/completions",
        "/api/v0/embeddings",
        "/api/v1/chat",
    ],
)
async def test_protected_routes_use_real_factory_stop_and_reservation(path):
    system, service = assembled(start_miner_on_ready=True, stop_miner_on_shutdown=True)
    calls = []

    def upstream(request):
        assert not system.supervisors["krig"].backend.running
        assert system.lease_mgr.active_count("gpu.inference") == 1
        calls.append(request.url.path)
        if path.endswith("embeddings"):
            body = {"data": [{"embedding": [0.1]}]}
        elif path.endswith("responses"):
            body = {"status": "completed", "output": []}
        elif path == "/api/v1/chat":
            body = {"model_instance_id": "qwen", "output": [], "stats": {}}
        elif path == "/v1/messages":
            body = {"type": "message", "stop_reason": "end_turn", "content": []}
        else:
            body = {"choices": [{"finish_reason": "stop", "message": {"content": "ok"}}]}
        return httpx.Response(200, json=body)

    system.gateway._http_client = httpx.AsyncClient(base_url="http://upstream", transport=httpx.MockTransport(upstream))
    app = system.gateway.create_app(service)
    async with app.router.lifespan_context(app):
        resumed = asyncio.Event()
        system.dispatcher.on("process.started", lambda event: resumed.set())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway") as client:
            assert (await client.post(path, json={"model": "qwen"})).status_code == 200
            assert calls == [path]
            assert system.lease_mgr.active_count("gpu.inference") == 0
            if path != "/v1/messages":
                await asyncio.wait_for(resumed.wait(), timeout=1)
                assert system.supervisors["krig"].backend.running
            else:
                assert system.lease_mgr.is_restart_inhibited("gpu.inference")
    assert not system.supervisors["krig"].backend.running


@pytest.mark.asyncio
async def test_managed_model_mutation_stays_disabled_even_with_noop_hook():
    system, service = assembled()
    system.dispatcher.on("lmstudio.model_load_requested", lambda e: None, is_blocking=True)
    await service.start()

    def forbidden(request):
        pytest.fail("model mutation must stay disabled without cross-resource transaction")

    system.gateway._http_client = httpx.AsyncClient(
        base_url="http://upstream", transport=httpx.MockTransport(forbidden)
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=system.gateway.create_app(service)), base_url="http://gateway"
    ) as client:
        for path in ("/api/v1/models/load", "/api/v1/models/unload", "/api/v0/model/load", "/api/v0/model/unload"):
            assert (await client.post(path, json={})).status_code == 503
    await system.gateway.close()


def test_cli_serve_runs_real_factory_and_lifespan_offline(monkeypatch):
    from resource_coordinator import cli

    config = CoordinatorConfig(
        processes={"krig": ProcessConfig(name="krig", backend="fake")},
        policies=[
            PolicyConfig(
                name="stop",
                trigger_event="lmstudio.inference_requested",
                target_process="krig",
                resource="gpu.inference",
            )
        ],
    )
    monkeypatch.setattr(cli, "load_config", lambda path: config)
    observed = []

    def fake_uvicorn(app, **kwargs):
        async def run():
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://gateway"
                ) as client:
                    observed.append((await client.get("/_coordinator/status")).json()["is_ready"])

        asyncio.run(run())

    monkeypatch.setattr(cli.uvicorn, "run", fake_uvicorn)
    assert cli.cmd_serve(cli.parse_args(["serve", "--fake-miner", "--start-miner", "--stop-miner-on-shutdown"])) == 0
    assert observed == [True]


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/custom/chat/completions"),
        ("POST", "/custom/models/load"),
        ("GET", "/v1/models/qwen/reset"),
        ("GET", "/api/v0/models/qwen/unload"),
    ],
)
def test_unknown_route_shapes_fail_closed(method, path):
    from resource_coordinator.adapters.lmstudio.admission import OperationClassifier, OperationKind

    assert OperationClassifier.classify(method, path) in {
        OperationKind.UNSUPPORTED_MUTATING,
        OperationKind.UNKNOWN_READ,
    }
