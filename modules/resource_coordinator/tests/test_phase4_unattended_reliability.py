"""
Phase 4 Tests: Unattended Reliability, Crash Recovery, and Durable State Journaling.

Covers:
- Exclusive single-instance lock preventing dual ownership / duplicate coordinators
- Replay of unresolved requests (reserved, possibly_forwarded, uncertain) into restart inhibitions
- Clean startup recovery after terminal_verified requests
- Fail-closed handling on corrupt journal
- Refusal to adopt or kill recycled PIDs
- Pre-forward journal persistence before upstream dispatch
- Durable recording of uncertain streams and restart inhibitions
- Miner unexpected exit backoff and crash loop exhaustion
- Operator recovery clearing durable journal holds
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional
import pytest
from starlette.requests import Request
from starlette.responses import Response

from resource_coordinator.adapters.lmstudio.gateway import LMStudioGateway
from resource_coordinator.config import (
    CoordinatorConfig,
    PolicyConfig,
    ProcessConfig,
    ServiceConfig,
    build_system,
)
from resource_coordinator.core.durable_state import (
    CoordinatorState,
    PersistedProcess,
    PersistedRequest,
    ReconciliationOutcome,
    RequestPhase,
    StateCodec,
    reconcile_pid,
    reconcile_startup_state,
)
from resource_coordinator.core.leases import LeaseManager, LeaseType
from resource_coordinator.core.lock import SingleInstanceLock, SingleInstanceLockError
from resource_coordinator.core.processes import FakeProcessBackend, ProcessState, ProcessSupervisor
from resource_coordinator.core.service import CoordinatorService, ServiceState


def _make_config(state_file: Path) -> CoordinatorConfig:
    if not state_file.exists():
        StateCodec.initialize(state_file)
    return CoordinatorConfig(
        service=ServiceConfig(state_persistence_path=str(state_file)),
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


@pytest.mark.asyncio
async def test_single_instance_lock_prevents_duplicate_coordinator(tmp_path: Path):
    """
    Test 1: Only one coordinator instance may run at a time.
    A second coordinator fails to acquire the lock and transitions to FAILED.
    When the first stops, the second can acquire the lock and start.
    """
    state_file = tmp_path / "coordinator_state.json"
    lock_file = tmp_path / "coordinator_state.lock"

    cfg1 = _make_config(state_file)
    system1 = build_system(cfg1, use_fake_processes=True)
    service1 = CoordinatorService(system1, lock_path=lock_file)

    cfg2 = _make_config(state_file)
    system2 = build_system(cfg2, use_fake_processes=True)
    service2 = CoordinatorService(system2, lock_path=lock_file)

    # First coordinator starts successfully
    assert await service1.start() is True
    assert service1.state == ServiceState.READY

    # Second coordinator attempting to start on the same lock path fails closed
    assert await service2.start() is False
    assert service2.state == ServiceState.FAILED
    assert "already held" in (service2.failure_reason or "")

    # When first coordinator stops, lock is released
    await service1.stop()
    assert service1.state == ServiceState.STOPPED

    # Create fresh system3 to attempt clean start after release
    cfg3 = _make_config(state_file)
    system3 = build_system(cfg3, use_fake_processes=True)
    service3 = CoordinatorService(system3, lock_path=lock_file)
    assert await service3.start() is True
    assert service3.state == ServiceState.READY
    await service3.stop()


@pytest.mark.asyncio
async def test_reconcile_replays_reserved_request_into_inhibition(tmp_path: Path):
    """
    Test 2: A request left in RESERVED phase at crash is replayed as a restart inhibition.
    """
    state_file = tmp_path / "journal.json"
    state = CoordinatorState(
        requests={
            "req-crashed-1": PersistedRequest(
                request_id="req-crashed-1",
                resource="gpu.inference",
                phase=RequestPhase.RESERVED.value,
                model="qwen32b",
                path="/v1/chat/completions",
            )
        }
    )
    StateCodec.save_atomic(state, state_file)

    cfg = _make_config(state_file)
    system = build_system(cfg, use_fake_processes=True)
    service = CoordinatorService(system)

    assert await service.start() is True
    assert system.lease_mgr.is_restart_inhibited("gpu.inference") is True
    inh = system.lease_mgr.get_inhibition("gpu.inference")
    assert inh is not None
    assert "unresolved_request:reserved" in inh.reason
    assert "req-crashed-1" in inh.holder_id
    await service.stop()


@pytest.mark.asyncio
async def test_reconcile_replays_possibly_forwarded_request_into_inhibition(tmp_path: Path):
    """
    Test 3: A request left in POSSIBLY_FORWARDED phase at crash is replayed as a restart inhibition.
    """
    state_file = tmp_path / "journal.json"
    state = CoordinatorState(
        requests={
            "req-fwd-99": PersistedRequest(
                request_id="req-fwd-99",
                resource="gpu.inference",
                phase=RequestPhase.POSSIBLY_FORWARDED.value,
                model="qwen32b",
                path="/v1/chat/completions",
            )
        }
    )
    StateCodec.save_atomic(state, state_file)

    cfg = _make_config(state_file)
    system = build_system(cfg, use_fake_processes=True)
    service = CoordinatorService(system)

    assert await service.start() is True
    assert system.lease_mgr.is_restart_inhibited("gpu.inference") is True
    inh = system.lease_mgr.get_inhibition("gpu.inference")
    assert inh is not None
    assert "unresolved_request:possibly_forwarded" in inh.reason
    await service.stop()


@pytest.mark.asyncio
async def test_reconcile_clean_after_terminal_verified(tmp_path: Path):
    """
    Test 4: Requests that completed normally (TERMINAL_VERIFIED) do not inhibit restarts on startup.
    """
    state_file = tmp_path / "journal.json"
    state = CoordinatorState(
        requests={
            "req-completed-1": PersistedRequest(
                request_id="req-completed-1",
                resource="gpu.inference",
                phase=RequestPhase.TERMINAL_VERIFIED.value,
                model="qwen32b",
                path="/v1/chat/completions",
            )
        }
    )
    StateCodec.save_atomic(state, state_file)

    cfg = _make_config(state_file)
    system = build_system(cfg, use_fake_processes=True)
    service = CoordinatorService(system)

    assert await service.start() is True
    assert system.lease_mgr.is_restart_inhibited("gpu.inference") is False
    await service.stop()


@pytest.mark.asyncio
async def test_corrupt_journal_fails_closed(tmp_path: Path):
    """
    Test 5: Corrupt journal file fails closed during coordinator startup.
    """
    state_file = tmp_path / "corrupt_journal.json"
    state_file.write_text("{ corrupt json data !!!", encoding="utf-8")

    cfg = _make_config(state_file)
    system = build_system(cfg, use_fake_processes=True)
    service = CoordinatorService(system)

    assert await service.start() is False
    assert service.state == ServiceState.FAILED
    assert "Corrupted or invalid durable state journal" in (service.failure_reason or "")


def test_reconcile_pid_recycled_refuses_adoption():
    """
    Test 6: PID recycling hazard detection.
    Persisted PID 4567 had creation time 100.0. Live process has creation time 350.0.
    Must return PID_RECYCLED to refuse adoption or destructive termination.
    """
    outcome = reconcile_pid(
        persisted_pid=4567,
        persisted_create_time=100.0,
        query_fn=lambda pid: 350.0 if pid == 4567 else None,
        create_time_tolerance_seconds=0.0,
    )
    assert outcome == ReconciliationOutcome.PID_RECYCLED


@pytest.mark.asyncio
async def test_gateway_persists_lifecycle_in_journal(tmp_path: Path):
    """
    Test 7: Gateway records request phases (reserved -> possibly_forwarded -> terminal_verified)
    in the durable state file.
    """
    state_file = tmp_path / "gateway_journal.json"
    lease_mgr = LeaseManager()
    gateway = LMStudioGateway(lease_manager=lease_mgr, state_persistence_path=str(state_file), standalone=True)

    # Mock upstream client returning completed non-streaming response
    import httpx

    async def mock_send(request: httpx.Request, *args, **kwargs) -> httpx.Response:
        # Check that POSSIBLY_FORWARDED was committed BEFORE sending upstream!
        current_state = StateCodec.load(state_file)
        assert len(current_state.requests) == 1
        req = list(current_state.requests.values())[0]
        assert req.phase == RequestPhase.POSSIBLY_FORWARDED.value
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "stop", "message": {"content": "ok"}}]},
            headers={"content-type": "application/json"},
        )

    client = httpx.AsyncClient(base_url="http://127.0.0.1:1234", transport=httpx.MockTransport(mock_send))
    gateway._http_client = client

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway.create_app()), base_url="http://coordinator"
    ) as coord_client:
        response = await coord_client.post(
            "/v1/chat/completions",
            json={"model": "test-model", "messages": []},
        )
        assert response.status_code == 200

    # Verify final journal state is terminal_verified
    final_state = StateCodec.load(state_file)
    assert len(final_state.requests) == 1
    req = list(final_state.requests.values())[0]
    assert req.phase == RequestPhase.TERMINAL_VERIFIED.value
    assert req.model == "test-model"
    await gateway.close()


@pytest.mark.asyncio
async def test_gateway_persists_uncertain_on_truncated_stream(tmp_path: Path):
    """
    Test 8: On truncated stream without [DONE], gateway persists UNCERTAIN and inhibits restart.
    """
    state_file = tmp_path / "stream_journal.json"
    lease_mgr = LeaseManager()
    gateway = LMStudioGateway(lease_manager=lease_mgr, state_persistence_path=str(state_file), standalone=True)

    import httpx

    # Simulate an SSE stream that terminates abruptly without [DONE]
    async def truncated_stream():
        yield b'data: {"choices": [{"delta": {"content": "hello"}}]}\n\n'

    mock_resp = httpx.Response(
        200,
        content=truncated_stream(),
        headers={"content-type": "text/event-stream"},
    )

    async def mock_send(request: httpx.Request, *args, **kwargs) -> httpx.Response:
        return mock_resp

    client = httpx.AsyncClient(base_url="http://127.0.0.1:1234", transport=httpx.MockTransport(mock_send))
    gateway._http_client = client

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway.create_app()), base_url="http://coordinator"
    ) as coord_client:
        response = await coord_client.post(
            "/v1/chat/completions",
            json={"model": "stream-model", "stream": True},
        )
        assert response.status_code == 200
        # Read the truncated response body
        text = response.text
        assert "hello" in text

    # Lease manager must have restart inhibited
    assert lease_mgr.is_restart_inhibited("gpu.inference") is True

    # Durable state must have persisted UNCERTAIN phase
    final_state = StateCodec.load(state_file)
    assert len(final_state.requests) == 1
    req = list(final_state.requests.values())[0]
    assert req.phase == RequestPhase.UNCERTAIN.value
    assert req.model == "stream-model"
    await gateway.close()


@pytest.mark.asyncio
async def test_watchdog_unexpected_miner_exit_bounded_backoff_and_exhaustion():
    """
    Test 9: ProcessSupervisor handles unexpected miner exits during safe idle:
    - First 3 unexpected exits trigger backoff restart.
    - 4th unexpected exit exceeds max retries and imposes restart inhibition.
    """
    backend = FakeProcessBackend(name="krig", running=False)
    supervisor = ProcessSupervisor(backend=backend)
    lease_mgr = LeaseManager()

    # Process is stopped, safe idle (0 active, 0 pending, not inhibited), was NOT stopped by coordinator
    assert supervisor.was_stopped_by_coordinator is False
    assert lease_mgr.is_restart_inhibited("gpu.inference") is False

    # Attempt 1: restarts with 0.01s base backoff
    restarted1 = await supervisor.handle_unexpected_exit_backoff(
        lease_manager=lease_mgr,
        max_retries=3,
        base_backoff_seconds=0.01,
    )
    assert restarted1 is True
    assert supervisor.consecutive_unexpected_exits == 1
    assert backend.running is True

    # Simulate another crash
    backend.running = False
    restarted2 = await supervisor.handle_unexpected_exit_backoff(
        lease_manager=lease_mgr,
        max_retries=3,
        base_backoff_seconds=0.01,
    )
    assert restarted2 is True
    assert supervisor.consecutive_unexpected_exits == 2

    # Simulate 3rd crash
    backend.running = False
    restarted3 = await supervisor.handle_unexpected_exit_backoff(
        lease_manager=lease_mgr,
        max_retries=3,
        base_backoff_seconds=0.01,
    )
    assert restarted3 is True
    assert supervisor.consecutive_unexpected_exits == 3

    # Simulate 4th crash: exceeds max_retries (3)!
    backend.running = False
    restarted4 = await supervisor.handle_unexpected_exit_backoff(
        lease_manager=lease_mgr,
        max_retries=3,
        base_backoff_seconds=0.01,
    )
    assert restarted4 is False
    assert supervisor.consecutive_unexpected_exits == 4
    # Restart must now be inhibited!
    assert lease_mgr.is_restart_inhibited("gpu.inference") is True
    inh = lease_mgr.get_inhibition("gpu.inference")
    assert inh is not None
    assert "process_crash_loop_exhausted:krig" in inh.reason


@pytest.mark.asyncio
async def test_operator_recover_clears_inhibition_in_journal(tmp_path: Path):
    """
    Test 10: Authenticated operator recovery clears the hold in both memory and the durable state file.
    """
    state_file = tmp_path / "recovery_journal.json"
    lease_mgr = LeaseManager()
    await lease_mgr.inhibit_restart("gpu.inference", "manual_test_hold", "op1")
    StateCodec.record_inhibition(state_file, "gpu.inference", "manual_test_hold", "op1")

    # Verify persisted inhibition is in file
    initial_state = StateCodec.load(state_file)
    assert "gpu.inference" in initial_state.inhibitions

    gateway = LMStudioGateway(
        lease_manager=lease_mgr,
        state_persistence_path=str(state_file),
        recovery_token="secret-token-123",
    )

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/coordinator/recover",
        "headers": [
            (b"authorization", b"Bearer secret-token-123"),
            (b"content-type", b"application/json"),
        ],
        "path_params": {},
        "query_string": b"resource=gpu.inference",
    }

    async def receive():
        return {
            "type": "http.request",
            "body": json.dumps({"override": True, "operator": "ops-admin", "reason": "verified safe"}).encode("utf-8"),
            "more_body": False,
        }

    request = Request(scope, receive)
    response = await gateway.handle_coordinator_recover(request)
    assert response.status_code == 200

    # Memory inhibition cleared
    assert lease_mgr.is_restart_inhibited("gpu.inference") is False

    # Journal inhibition cleared
    updated_state = StateCodec.load(state_file)
    assert "gpu.inference" not in updated_state.inhibitions
    await gateway.close()
