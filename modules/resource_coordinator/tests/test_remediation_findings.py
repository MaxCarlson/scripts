"""
Regression tests for independent review remediation findings.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import time
import pytest

from resource_coordinator.config import (
    CoordinatorConfig,
    PolicyConfig,
    ProcessConfig,
    ServiceConfig,
    build_system,
)
from resource_coordinator.core.durable_state import RequestPhase, StateCodec
from resource_coordinator.core.events import EventDispatcher
from resource_coordinator.core.leases import LeaseManager, LeaseType
from resource_coordinator.core.processes import FakeProcessBackend, ProcessState, ProcessSupervisor
from resource_coordinator.core.service import CoordinatorService, ServiceState


@pytest.mark.asyncio
async def test_backoff_aborted_by_reservation_arrival():
    """
    If a new inference reservation arrives while a crashed process is in backoff sleep,
    the watchdog restart must immediately abort and NOT start the process.
    """
    dispatcher = EventDispatcher()
    backend = FakeProcessBackend(name="krig")
    supervisor = ProcessSupervisor(backend=backend, event_dispatcher=dispatcher)
    lease_mgr = LeaseManager(event_dispatcher=dispatcher)

    # Initially started and running
    await supervisor.start(only_if_stopped_by_coordinator=False)
    assert (await supervisor.status()).state == ProcessState.RUNNING

    # Process crashes unexpectedly (not stopped by coordinator)
    backend.running = False
    assert not supervisor.was_stopped_by_coordinator

    # Start backoff with 0.3s sleep in a background task
    backoff_task = asyncio.create_task(
        supervisor.handle_unexpected_exit_backoff(
            lease_manager=lease_mgr,
            resource="gpu.inference",
            base_backoff_seconds=0.3,
        )
    )

    # Wait 0.05s, then simulate incoming inference reservation
    await asyncio.sleep(0.05)
    async with lease_mgr.reserve("gpu.inference", LeaseType.SHARED, "req-arrived-during-backoff"):
        # Wait for backoff to complete
        restarted = await backoff_task
        assert restarted is False
        # Process must NOT be running
        assert (await supervisor.status()).state == ProcessState.STOPPED


@pytest.mark.asyncio
async def test_continuous_supervision_loop_recovers_crashed_process():
    """
    CoordinatorService runs a continuous background supervision loop that detects
    unexpectedly stopped processes while safe idle and triggers restart.
    """
    dispatcher = EventDispatcher()
    cfg = CoordinatorConfig(
        service=ServiceConfig(),
        processes={"krig": ProcessConfig(name="krig", backend="fake")},
        policies=[
            PolicyConfig(
                name="stop-krig-for-inference",
                trigger_event="lmstudio.inference_requested",
                target_process="krig",
                stop_process=True,
                restart_process=True,
                resource="gpu.inference",
                lease_type="shared",
                cooldown_seconds=10.0,
                only_if_stopped_by_coordinator=True,
            )
        ],
    )
    system = build_system(cfg, use_fake_processes=True)
    service = CoordinatorService(system, supervision_poll_interval=0.05)
    await service.start()
    assert service.is_ready

    supervisor = system.supervisors["krig"]
    await supervisor.start(only_if_stopped_by_coordinator=False)
    assert (await supervisor.status()).state == ProcessState.RUNNING

    # Crash the process unexpectedly
    backend: FakeProcessBackend = supervisor.backend  # type: ignore
    backend.running = False
    supervisor.was_stopped_by_coordinator = False

    # Wait up to 1.0s for supervision loop to detect crash and restart with base_backoff_seconds
    for _ in range(20):
        await asyncio.sleep(0.05)
        if (await supervisor.status()).state == ProcessState.RUNNING:
            break

    assert (await supervisor.status()).state == ProcessState.RUNNING

    await service.stop()


def test_manifest_preview_failure_raises_explicit_error(tmp_path: Path):
    """
    If start-prl.ps1 -Preview fails or exits non-zero, resolve_from_mining_repo must
    raise RuntimeError explicitly rather than silently falling back to diverged flags.
    """
    from resource_coordinator.adapters.miners.manifest import MinerManifest

    # Create a dummy script that exits with non-zero
    fake_script = tmp_path / "start-prl.ps1"
    fake_script.write_text("throw 'Simulated preview failure in script'")

    with pytest.raises(RuntimeError, match="Failed running start-prl.ps1 -Preview"):
        MinerManifest.resolve_from_mining_repo(
            mining_repo=tmp_path,
            miner_type="krig",
            use_preview_invocation=True,
        )


def test_acceptance_harness_live_mode_requires_explicit_authorization():
    """
    AcceptanceHarness in 'live' mode must reject execution unless both
    allow_live_lmstudio and allow_real_miner are explicitly True.
    """
    from resource_coordinator.acceptance_harness import AcceptanceHarness

    with pytest.raises(ValueError, match="Live acceptance mode requires both allow_live_lmstudio=True and allow_real_miner=True"):
        AcceptanceHarness(mode="live", allow_live_lmstudio=False, allow_real_miner=False)

    with pytest.raises(ValueError, match="Live acceptance mode requires both allow_live_lmstudio=True and allow_real_miner=True"):
        AcceptanceHarness(mode="live", allow_live_lmstudio=True, allow_real_miner=False)

    harness = AcceptanceHarness(mode="live", allow_live_lmstudio=True, allow_real_miner=True)
    assert harness.report.verification_level == "pending_live_verification"
    assert harness.report.process_backend == "windows_miner"
    assert harness.report.upstream_type == "live_lmstudio"


def test_acceptance_report_metadata():
    """
    AcceptanceReport must record process_backend, upstream_type, and verification_level.
    """
    from resource_coordinator.acceptance_harness import AcceptanceHarness

    sim_harness = AcceptanceHarness(mode="simulated")
    report = sim_harness.report
    assert report.process_backend == "fake"
    assert report.upstream_type == "mock"
    assert report.verification_level == "unit_simulation"
    d = report.to_dict()
    assert d["process_backend"] == "fake"
    assert d["upstream_type"] == "mock"
    assert d["verification_level"] == "unit_simulation"


@pytest.mark.asyncio
async def test_missing_state_journal_refuses_startup_unless_first_boot(tmp_path: Path):
    """
    On normal startup with a missing durable state journal, CoordinatorService
    fails closed to prevent unrecorded crash recovery unless first_boot=True.
    """
    state_file = tmp_path / "nonexistent_journal.json"
    cfg = CoordinatorConfig(
        service=ServiceConfig(state_persistence_path=str(state_file)),
        processes={"krig": ProcessConfig(name="krig", backend="fake")},
        policies=[
            PolicyConfig(
                name="stop-krig",
                trigger_event="lmstudio.inference_requested",
                target_process="krig",
                stop_process=True,
                resource="gpu.inference",
            )
        ],
    )
    system_normal = build_system(cfg, use_fake_processes=True)
    service_normal = CoordinatorService(system_normal, first_boot=False)
    assert await service_normal.start() is False
    assert service_normal.state == ServiceState.FAILED
    assert "Missing required durable state journal" in (service_normal.failure_reason or "")
    assert not state_file.exists()

    system_first_boot = build_system(cfg, use_fake_processes=True)
    service_first_boot = CoordinatorService(system_first_boot, first_boot=True)
    assert await service_first_boot.start() is True
    assert service_first_boot.state == ServiceState.READY
    assert state_file.exists()
    await service_first_boot.stop()


@pytest.mark.asyncio
async def test_reservation_cleanup_on_journal_write_failure(tmp_path: Path, monkeypatch):
    """
    If persisting the initial RESERVED phase fails (e.g. disk error),
    the in-memory reservation must be cleaned up so pending_count returns to 0.
    """
    import httpx
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from resource_coordinator.adapters.lmstudio.gateway import LMStudioGateway

    state_file = tmp_path / "journal.json"
    StateCodec.initialize(state_file)

    dispatcher = EventDispatcher()
    lease_mgr = LeaseManager(event_dispatcher=dispatcher)
    backend = FakeProcessBackend(name="krig", running=False)
    supervisor = ProcessSupervisor(backend=backend, event_dispatcher=dispatcher)

    mock_lmstudio = Starlette(routes=[Route("/v1/models", lambda r: JSONResponse({"data": []}))])
    upstream_client = httpx.AsyncClient(transport=httpx.ASGITransport(app=mock_lmstudio), base_url="http://mock")

    gateway = LMStudioGateway(
        upstream_url="http://mock",
        event_dispatcher=dispatcher,
        lease_manager=lease_mgr,
        state_persistence_path=str(state_file),
    )
    gateway._http_client = upstream_client

    original_record = StateCodec.record_request_phase

    def failing_record(path, req_id, resource, phase, **kwargs):
        if phase == RequestPhase.RESERVED:
            raise OSError("Simulated disk I/O failure during journal write")
        return original_record(path, req_id, resource, phase, **kwargs)

    monkeypatch.setattr(StateCodec, "record_request_phase", failing_record)

    app = gateway.create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway") as client:
        resp = await client.post("/v1/chat/completions", json={"model": "test", "messages": []})
        assert resp.status_code in (500, 503)

    # Crucial safety assertion: lease_mgr pending and active counts MUST be 0!
    assert lease_mgr.pending_count("gpu.inference") == 0
    assert lease_mgr.active_count("gpu.inference") == 0


@pytest.mark.asyncio
async def test_recovery_resolves_persistent_unresolved_requests(tmp_path: Path):
    """
    Calling /_coordinator/recover resolves persisted POSSIBLY_FORWARDED/RESERVED
    records into TERMINAL_VERIFIED, so subsequent restarts are clean.
    """
    import httpx
    state_file = tmp_path / "journal.json"
    StateCodec.initialize(state_file)
    StateCodec.record_request_phase(
        state_file,
        "req-persisted-crash",
        "gpu.inference",
        RequestPhase.POSSIBLY_FORWARDED,
        model="qwen",
    )

    # First boot after crash: reconcile loads the hold
    cfg = CoordinatorConfig(
        service=ServiceConfig(state_persistence_path=str(state_file)),
        processes={"krig": ProcessConfig(name="krig", backend="fake")},
        policies=[
            PolicyConfig(
                name="stop-krig",
                trigger_event="lmstudio.inference_requested",
                target_process="krig",
                stop_process=True,
                restart_process=True,
                resource="gpu.inference",
                lease_type="shared",
                cooldown_seconds=10.0,
                only_if_stopped_by_coordinator=True,
            )
        ],
    )
    system1 = build_system(cfg, use_fake_processes=True)
    system1.gateway.recovery_token = "rec-token"
    service1 = CoordinatorService(system1)
    assert await service1.start() is True
    assert system1.lease_mgr.is_restart_inhibited("gpu.inference") is True

    # Operator performs recovery
    app1 = system1.gateway.create_app(service1)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app1), base_url="http://gw") as client:
        resp = await client.post(
            "/_coordinator/recover",
            headers={"Authorization": "Bearer rec-token"},
            json={"override": True, "operator": "lead_operator", "reason": "LM Studio checked idle"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "req-persisted-crash" in data["resolved_request_ids"]

    await service1.stop()

    # Verify journal on disk has resolved the request as OPERATOR_RESOLVED
    loaded = StateCodec.load(state_file)
    req = loaded.requests["req-persisted-crash"]
    assert req.phase == RequestPhase.OPERATOR_RESOLVED
    assert req.details.get("previous_phase") == RequestPhase.POSSIBLY_FORWARDED.value
    assert "lead_operator" in req.details.get("resolved_by", "")

    # Second boot: journal has NO unresolved requests, so no restart inhibition is placed!
    system2 = build_system(cfg, use_fake_processes=True)
    service2 = CoordinatorService(system2)
    assert await service2.start() is True
    assert system2.lease_mgr.is_restart_inhibited("gpu.inference") is False
    await service2.stop()


def test_multiprocess_lock_contention(tmp_path: Path):
    """
    SingleInstanceLock acquired exclusively returns False on contention
    and releases without unlinking or corrupting the lock file on disk.
    """
    from resource_coordinator.core.lock import SingleInstanceLock

    lock_file = tmp_path / "coordinator.lock"
    lock1 = SingleInstanceLock(lock_file)
    lock2 = SingleInstanceLock(lock_file)

    assert lock1.acquire() is True
    assert lock2.acquire() is False

    lock1.release()

    # Lock file must still exist stably on disk (not unlinked)
    assert lock_file.exists()

    # Second lock can now acquire cleanly
    assert lock2.acquire() is True
    lock2.release()



