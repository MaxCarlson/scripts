import asyncio
import json
import time
from pathlib import Path

import pytest
import httpx

from resource_coordinator.config import (
    CoordinatorConfig,
    PolicyConfig,
    ProcessConfig,
    ServiceConfig,
    build_system,
)
from resource_coordinator.core.durable_state import CoordinatorState, StateCodec
from resource_coordinator.core.leases import LeaseManager, LeaseType, MaintenanceAdmissionBlocked
from resource_coordinator.core.processes import ProcessLifecycleOwner, ProcessState
from resource_coordinator.core.service import CoordinatorService


@pytest.mark.asyncio
async def test_maintenance_fence_blocks_all_gpu_reservations_and_idle_actions():
    manager = LeaseManager(default_cooldown_seconds=0)

    assert await manager.begin_gpu_maintenance("session-1") is True
    assert manager.gpu_maintenance_owner == "session-1"

    for resource in ("gpu.inference", "gpu.model_loading", "gpu.maintenance"):
        with pytest.raises(MaintenanceAdmissionBlocked):
            async with manager.reserve(resource, LeaseType.SHARED, holder_id="late"):
                pytest.fail("protected GPU reservation crossed active maintenance fence")

    invoked = False

    async def idle_action():
        nonlocal invoked
        invoked = True

    assert await manager.run_if_idle("gpu.inference", idle_action) is False
    assert invoked is False
    await manager.end_gpu_maintenance("session-1")
    assert manager.gpu_maintenance_owner is None


@pytest.mark.asyncio
async def test_maintenance_fence_cannot_start_with_active_or_pending_gpu_claim():
    manager = LeaseManager(default_cooldown_seconds=0)

    async with manager.acquire("gpu.inference", holder_id="active"):
        assert await manager.begin_gpu_maintenance("session-active") is False

    reservation = manager.reserve("gpu.model_loading", LeaseType.EXCLUSIVE, holder_id="pending")
    async with reservation:
        assert await manager.begin_gpu_maintenance("session-pending") is False
        assert manager.gpu_maintenance_owner is None


@pytest.mark.asyncio
async def test_only_one_concurrent_maintenance_owner_can_close_admission():
    manager = LeaseManager(default_cooldown_seconds=0)
    outcomes = await asyncio.gather(
        manager.begin_gpu_maintenance("owner-a"),
        manager.begin_gpu_maintenance("owner-b"),
    )

    assert sorted(outcomes) == [False, True]
    owner = manager.gpu_maintenance_owner
    assert owner in {"owner-a", "owner-b"}
    with pytest.raises(RuntimeError, match="owner"):
        await manager.end_gpu_maintenance("stale-owner")
    await manager.end_gpu_maintenance(owner)


@pytest.mark.asyncio
async def test_maintenance_fence_rejects_existing_hold_and_cooldown():
    manager = LeaseManager(default_cooldown_seconds=30)
    await manager.inhibit_restart("gpu.model_loading", "uncertain", "req-1")
    assert await manager.begin_gpu_maintenance("blocked") is False
    assert manager.gpu_maintenance_owner is None

    await manager.clear_inhibition("gpu.model_loading")
    assert await manager.begin_gpu_maintenance("blocked-by-cooldown") is False
    assert manager.gpu_maintenance_owner is None


def test_legacy_durable_state_without_maintenance_remains_compatible():
    legacy = {
        "version": "1.0",
        "updated_at": 100.0,
        "inhibitions": {},
        "processes": {},
    }

    state = StateCodec.deserialize(json.dumps(legacy))
    assert state.maintenance == {}
    assert "maintenance" not in state.to_dict()


def test_durable_maintenance_record_round_trips_and_rejects_malformed_state():
    record = {
        "state": "active",
        "operation_id": "request-1",
        "session_id": "session-1",
        "operator": "mining_optimizer",
        "reason": "Optimization",
        "requested_at": 100.0,
        "updated_at": 101.0,
        "lease_seconds": 3600,
        "expires_at": 3701.0,
        "miner_was_running": True,
        "miner_stopped_by_coordinator": True,
        "manual_override_before": False,
        "restoration": {},
    }
    state = CoordinatorState(maintenance=record)
    decoded = StateCodec.deserialize(StateCodec.serialize(state))
    assert decoded.maintenance == record

    broken = state.to_dict()
    broken["maintenance"] = {**record, "state": "unknown"}
    with pytest.raises(ValueError, match="maintenance"):
        CoordinatorState.from_dict(broken)


def test_startup_recovery_adds_maintenance_holder_without_replacing_other_hold(tmp_path: Path):
    state_path = tmp_path / "coordinator-state.json"
    StateCodec.initialize(state_path)
    state = StateCodec.load(state_path)
    state.maintenance = {
        "state": "active",
        "operation_id": "startup-op",
        "session_id": "startup-session",
        "operator": "mining_optimizer",
        "reason": "restart test",
        "requested_at": 100.0,
        "updated_at": 101.0,
        "lease_seconds": 3600,
        "expires_at": 3701.0,
        "miner_was_running": True,
        "miner_stopped_by_coordinator": True,
        "manual_override_before": False,
        "restoration": {},
    }
    state.inhibitions["gpu.inference"] = {
        "resource": "gpu.inference", "reason": "other request uncertain", "holder_id": "other-request",
        "inhibited_at": 101.0, "details": {},
    }
    StateCodec.save_atomic(state, state_path)

    recovered = StateCodec.mark_maintenance_recovery_required(state_path)
    assert recovered.maintenance["state"] == "recovery_required"
    hold = recovered.inhibitions["gpu.inference"]
    assert hold["holder_id"] == "other-request"
    nested = hold["details"]["additional_uncertain_holders"]
    assert [entry["holder_id"] for entry in nested] == ["maintenance:startup-op"]


def make_maintenance_service(
    tmp_path: Path,
    *,
    initially_running: bool = True,
    stop_delay: float = 0.0,
    fail_stop: bool = False,
    response_wait_seconds: float = 2.0,
    restoration_verifier=None,
    start_miner_on_ready: bool = False,
):
    state_path = tmp_path / "coordinator-state.json"
    StateCodec.initialize(state_path)
    process_name = "fake_miner"
    policies = [
        PolicyConfig(
            name="test-inference",
            trigger_event="lmstudio.inference_requested",
            target_process=process_name,
            stop_process=True,
            restart_process=True,
            only_if_stopped_by_coordinator=True,
            resource="gpu.inference",
            lease_type="shared",
            cooldown_seconds=0,
        ),
        PolicyConfig(
            name="test-model-load",
            trigger_event="lmstudio.model_load_requested",
            target_process=process_name,
            stop_process=True,
            restart_process=True,
            only_if_stopped_by_coordinator=True,
            resource="gpu.inference",
            lease_type="exclusive",
            cooldown_seconds=0,
        ),
    ]
    config = CoordinatorConfig(
        service=ServiceConfig(state_persistence_path=str(state_path)),
        processes={
            process_name: ProcessConfig(
                name=process_name,
                backend="fake",
                executable="FAKE-ONLY://maintenance-test",
                stop_timeout_seconds=1.0,
            )
        },
        policies=policies,
    )
    system = build_system(config, use_fake_processes=True)
    backend = system.supervisors[process_name].backend
    backend.running = initially_running
    backend.lifecycle_owner = (
        ProcessLifecycleOwner.COORDINATOR if initially_running else ProcessLifecycleOwner.UNMANAGED
    )
    backend.is_coordinator_owned = initially_running
    backend.pid = 8123 if initially_running else None
    backend.create_time = 10.0 if initially_running else None
    backend.stop_delay = stop_delay
    backend.fail_stop = fail_stop
    system.supervisors[process_name]._has_started = initially_running
    system.lease_mgr.default_cooldown_seconds = 0
    service = CoordinatorService(
        system,
        start_miner_on_ready=start_miner_on_ready,
        maintenance_response_wait_seconds=response_wait_seconds,
        maintenance_restoration_verifier=restoration_verifier,
    )
    system.gateway.operator_token = "test-operator-secret"
    system.gateway.recovery_token = "test-operator-secret"
    return service, backend, state_path


def acquire_payload(request_id="test-operation"):
    return {
        "operator": "mining_optimizer",
        "reason": "Offline maintenance test",
        "lease_seconds": 3600,
        "inhibit_restarts": True,
        "request_id": request_id,
    }


@pytest.mark.asyncio
async def test_acquisition_persists_hold_before_stopping_and_grants_only_after_verified_stop(tmp_path: Path):
    service, backend, state_path = make_maintenance_service(tmp_path)
    manager = service.maintenance_manager
    result = await manager.acquire(acquire_payload())

    assert result["status"] == "granted"
    assert backend.running is False
    assert manager.state == "active"
    assert service.system.lease_mgr.gpu_maintenance_owner == "maintenance:test-operation"
    assert service.system.lease_mgr.is_restart_inhibited("gpu.inference")
    durable = StateCodec.load(state_path)
    assert durable.maintenance["state"] == "active"
    assert durable.maintenance["miner_stopped_by_coordinator"] is True
    assert durable.inhibitions["gpu.inference"]["holder_id"] == "maintenance:test-operation"
    assert result["token"] not in StateCodec.serialize(durable)
    assert result["token"] not in json.dumps(manager.status())
    manager._expiry_task.cancel()


@pytest.mark.asyncio
async def test_active_or_pending_inference_vetoes_maintenance_acquisition(tmp_path: Path):
    service, _, _ = make_maintenance_service(tmp_path)
    manager = service.maintenance_manager

    async with service.system.lease_mgr.acquire("gpu.inference", holder_id="active-inference"):
        result = await manager.acquire(acquire_payload())
        assert result["status"] == "conflict"
        assert service.system.lease_mgr.gpu_maintenance_owner is None

    async with service.system.lease_mgr.reserve("gpu.model_loading", LeaseType.EXCLUSIVE, "pending-load"):
        result = await manager.acquire(acquire_payload("pending-operation"))
        assert result["status"] == "conflict"
        assert manager.state == "idle"


@pytest.mark.asyncio
async def test_failed_or_external_miner_stop_never_grants_token(tmp_path: Path):
    service, backend, _ = make_maintenance_service(tmp_path, fail_stop=True)
    result = await service.maintenance_manager.acquire(acquire_payload())
    assert result["status"] == "recovery_required"
    assert "token" not in result
    assert service.maintenance_manager.state == "recovery_required"
    assert service.system.lease_mgr.gpu_maintenance_owner is not None
    assert service.system.lease_mgr.is_restart_inhibited("gpu.inference")
    assert backend.running is True

    other, external_backend, _ = make_maintenance_service(tmp_path / "other", initially_running=True)
    external_backend.lifecycle_owner = ProcessLifecycleOwner.EXTERNAL
    external_backend.is_coordinator_owned = False
    info = await other.system.miner_adapter.status()
    assert info.state == ProcessState.EXTERNAL_RUNNING
    denied = await other.maintenance_manager.acquire(acquire_payload("external-operation"))
    assert denied["status"] == "recovery_required"
    assert external_backend.running is True


@pytest.mark.asyncio
async def test_cancelled_acquisition_keeps_gpu_fence_and_restart_hold(tmp_path: Path):
    service, backend, state_path = make_maintenance_service(tmp_path, stop_delay=5.0)
    manager = service.maintenance_manager
    pending = await manager.acquire(acquire_payload("cancelled-stop"))
    assert pending["status"] == "pending"
    assert service.system.lease_mgr.gpu_maintenance_owner == "maintenance:cancelled-stop"
    assert StateCodec.load(state_path).maintenance["state"] == "acquiring"

    manager._operation_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await manager._operation_task

    assert manager.state == "recovery_required"
    assert service.system.lease_mgr.gpu_maintenance_owner == "maintenance:cancelled-stop"
    assert service.system.lease_mgr.is_restart_inhibited("gpu.inference")
    assert backend.running is True
    assert "token" not in manager.operation_status("cancelled-stop")


@pytest.mark.asyncio
async def test_cancelled_release_restores_fence_and_revokes_token(tmp_path: Path, monkeypatch):
    service, backend, state_path = make_maintenance_service(tmp_path)
    manager = service.maintenance_manager
    acquired = await manager.acquire(acquire_payload("cancelled-release"))
    entered = asyncio.Event()
    original_persist_supervisor = service._persist_supervisor_state
    calls = 0

    async def block_first_persist(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await asyncio.Future()
        await original_persist_supervisor(*args, **kwargs)

    monkeypatch.setattr(service, "_persist_supervisor_state", block_first_persist)
    task = asyncio.create_task(manager.release({
        "token": acquired["token"], "session_id": acquired["session_id"], "operator": "operator",
        "restoration_verified": True, "resume_miner": False,
        "operator_override": True, "override_reason": "Test release cancellation",
    }))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert manager.state == "recovery_required"
    assert StateCodec.load(state_path).maintenance["state"] == "recovery_required"
    assert service.system.lease_mgr.gpu_maintenance_owner == "maintenance:cancelled-release"
    assert service.system.lease_mgr.is_restart_inhibited("gpu.inference")
    assert backend.running is False
    assert (await manager.heartbeat({"token": acquired["token"], "lease_seconds": 3600}))["status"] == "stale"


@pytest.mark.asyncio
async def test_cancellation_after_release_commit_keeps_idempotent_success(tmp_path: Path, monkeypatch):
    service, _, _ = make_maintenance_service(tmp_path)
    manager = service.maintenance_manager
    acquired = await manager.acquire(acquire_payload("cancel-after-release-commit"))
    event_started = asyncio.Event()

    async def block_release_event(event_name, _payload=None, **_kwargs):
        if event_name == "resource_coordinator.maintenance_released":
            event_started.set()
            await asyncio.Future()

    monkeypatch.setattr(service.system.dispatcher, "emit", block_release_event)
    task = asyncio.create_task(manager.release({
        "token": acquired["token"], "session_id": acquired["session_id"], "operator": "operator",
        "restoration_verified": True, "resume_miner": False,
        "operator_override": True, "override_reason": "Release already committed",
    }))
    await event_started.wait()
    assert manager.state == "idle"
    assert service.system.lease_mgr.gpu_maintenance_owner is None
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    replay = await manager.release({
        "operation_id": "cancel-after-release-commit", "operator": "operator",
        "restoration_verified": True, "resume_miner": False,
    })
    assert replay["status"] == "released"
    assert replay["idempotent_replay"] is True


@pytest.mark.asyncio
async def test_manual_resume_and_gaming_transition_are_blocked_by_maintenance(tmp_path: Path):
    service, backend, state_path = make_maintenance_service(tmp_path, initially_running=False)
    assert await service.start() is True
    acquired = await service.maintenance_manager.acquire(acquire_payload("manual-gaming"))
    assert acquired["status"] == "granted"

    manual = await service.manual_miner_control("resume")
    gaming = await service.gaming_control("start")
    assert manual["status"] == "blocked"
    assert gaming["status"] == "blocked"
    assert backend.running is False
    assert StateCodec.load(state_path).gaming_mode["state"] == "inactive"
    assert service.maintenance_manager.state == "active"
    await service.stop("maintenance-manual-gaming-test")


@pytest.mark.asyncio
async def test_wrong_or_expired_fencing_cannot_renew_or_release(tmp_path: Path):
    service, _, _ = make_maintenance_service(tmp_path)
    manager = service.maintenance_manager
    acquired = await manager.acquire(acquire_payload("stale-token"))
    wrong_heartbeat = await manager.heartbeat({"token": "not-the-token", "lease_seconds": 3600})
    wrong_release = await manager.release({
        "token": "not-the-token", "session_id": acquired["session_id"], "operator": "operator",
        "restoration_verified": False, "resume_miner": False,
    })
    assert wrong_heartbeat["status"] == "stale"
    assert wrong_release["status"] == "stale"
    assert manager.state == "active"
    assert manager._expiry_task is not None
    manager._expiry_task.cancel()


@pytest.mark.asyncio
async def test_idempotent_acquire_and_heartbeat_use_server_expiration(tmp_path: Path):
    service, _, _ = make_maintenance_service(tmp_path)
    manager = service.maintenance_manager
    first = await manager.acquire(acquire_payload())
    duplicate = await manager.acquire(acquire_payload())
    assert duplicate["status"] == "granted"
    assert duplicate["session_id"] == first["session_id"]
    assert duplicate["token"] == first["token"]
    mismatched = await manager.acquire({**acquire_payload(), "reason": "Different request under reused identity"})
    assert mismatched["status"] == "conflict"
    assert "token" not in mismatched

    renewed = await manager.heartbeat({"token": first["token"], "lease_seconds": 3600})
    assert renewed["status"] == "renewed"
    assert renewed["expires_at"] > first["expires_at"]
    assert manager.status()["last_renewed_at"] is not None
    manager._expiry_task.cancel()


@pytest.mark.asyncio
async def test_fencing_token_is_absent_from_status_events_and_error_payloads(tmp_path: Path):
    service, _, _ = make_maintenance_service(tmp_path)
    events = []
    service.system.dispatcher.on("resource_coordinator.maintenance_*", lambda event: events.append(event.to_dict()))
    acquired = await service.maintenance_manager.acquire(acquire_payload("secret-redaction"))
    token = acquired["token"]
    assert token not in json.dumps(service.maintenance_manager.status())
    assert token not in json.dumps(service.maintenance_manager.operation_status("secret-redaction"))

    bad = await service.maintenance_manager.heartbeat({"token": "invalid", "lease_seconds": 3600})
    assert token not in json.dumps(bad)
    assert token not in json.dumps(events)
    assert [event["name"] for event in events] == [
        "resource_coordinator.maintenance_acquiring", "resource_coordinator.maintenance_granted"
    ]
    service.maintenance_manager._expiry_task.cancel()


@pytest.mark.asyncio
async def test_release_requires_independent_restoration_proof_or_explicit_operator_override(tmp_path: Path):
    service, backend, state_path = make_maintenance_service(tmp_path)
    manager = service.maintenance_manager
    acquired = await manager.acquire(acquire_payload())
    request = {
        "token": acquired["token"],
        "session_id": acquired["session_id"],
        "operator": "mining_optimizer",
        "restoration_verified": True,
        "resume_miner": True,
    }

    denied = await manager.release(request)
    assert denied["status"] == "recovery_required"
    assert manager.state == "active"
    assert service.system.lease_mgr.gpu_maintenance_owner is not None
    assert backend.running is False

    accepted = await manager.release({**request, "operator_override": True, "override_reason": "Operator verified reset"})
    assert accepted["status"] == "released"
    assert manager.state == "idle"
    assert service.system.lease_mgr.gpu_maintenance_owner is None
    assert not service.system.lease_mgr.is_restart_inhibited("gpu.inference")
    assert StateCodec.load(state_path).maintenance["last_disposition"]["restoration"]["operator_override"] is True
    assert "Operator verified reset" not in json.dumps(manager.status())
    replay = await manager.release(request)
    assert replay["status"] == "released" and replay["idempotent_replay"] is True
    await asyncio.sleep(0.02)
    assert backend.running is True


@pytest.mark.asyncio
async def test_independent_verifier_can_accept_evidence_and_startup_revokes_old_token(tmp_path: Path):
    service, backend, state_path = make_maintenance_service(
        tmp_path, restoration_verifier=lambda record, evidence: evidence.get("verified") is True
    )
    manager = service.maintenance_manager
    acquired = await manager.acquire(acquire_payload())
    released = await manager.release({
        "token": acquired["token"],
        "session_id": acquired["session_id"],
        "operator": "mining_optimizer",
        "restoration_verified": True,
        "restoration_evidence": {"verified": True},
        "resume_miner": False,
    })
    assert released["status"] == "released"
    assert backend.running is False

    active_service, _, _ = make_maintenance_service(tmp_path / "restart")
    active = await active_service.maintenance_manager.acquire(acquire_payload("restart-op"))
    # A new Coordinator instance uses the same durable journal but has no process-local token.
    restarted_config = active_service.system.config
    restarted_system = build_system(restarted_config, use_fake_processes=True)
    restarted = CoordinatorService(
        restarted_system, start_miner_on_ready=True, supervision_poll_interval=0.01
    )
    assert await restarted.start() is True
    assert restarted.maintenance_manager.state == "recovery_required"
    assert restarted_system.lease_mgr.gpu_maintenance_owner == "maintenance:restart-op"
    assert restarted_system.lease_mgr.is_restart_inhibited("gpu.inference")
    heartbeat = await restarted.maintenance_manager.heartbeat({"token": active["token"], "lease_seconds": 3600})
    assert heartbeat["status"] == "stale"
    assert restarted_system.supervisors["fake_miner"].is_manual_override is True
    await restarted.stop("maintenance-restart-test")
    if restarted.maintenance_manager._expiry_task:
        restarted.maintenance_manager._expiry_task.cancel()
    if manager._expiry_task:
        manager._expiry_task.cancel()


@pytest.mark.asyncio
async def test_coordinator_shutdown_during_active_session_retains_durable_recovery_hold(tmp_path: Path):
    service, backend, state_path = make_maintenance_service(tmp_path)
    assert await service.start() is True
    acquired = await service.maintenance_manager.acquire(acquire_payload("shutdown-active"))
    assert acquired["status"] == "granted"
    await service.stop("test coordinator interruption")

    assert service.maintenance_manager.state == "recovery_required"
    assert StateCodec.load(state_path).maintenance["state"] == "recovery_required"
    assert service.system.lease_mgr.gpu_maintenance_owner == "maintenance:shutdown-active"
    assert service.system.lease_mgr.is_restart_inhibited("gpu.inference")
    assert backend.running is False
    assert (await service.maintenance_manager.heartbeat({
        "token": acquired["token"], "lease_seconds": 3600,
    }))["status"] == "stale"


@pytest.mark.asyncio
async def test_restart_preserves_maintenance_hold_alongside_unrelated_inhibition(tmp_path: Path):
    service, _, state_path = make_maintenance_service(tmp_path)
    acquired = await service.maintenance_manager.acquire(acquire_payload("nested-hold-restart"))
    durable = StateCodec.load(state_path)
    durable.inhibitions["gpu.inference"] = {
        "resource": "gpu.inference",
        "reason": "separate unresolved request",
        "holder_id": "other-request",
        "inhibited_at": time.time(),
        "details": {
            "additional_uncertain_holders": [{
                "resource": "gpu.inference",
                "reason": "exclusive GPU maintenance session",
                "holder_id": "maintenance:nested-hold-restart",
                "inhibited_at": time.time(),
                "details": {"maintenance_operation_id": "nested-hold-restart"},
            }]
        },
    }
    StateCodec.save_atomic(durable, state_path)

    restarted_system = build_system(service.system.config, use_fake_processes=True)
    restarted = CoordinatorService(
        restarted_system, start_miner_on_ready=True, supervision_poll_interval=0.01
    )
    assert await restarted.start() is True
    holds = StateCodec.load(state_path).inhibitions["gpu.inference"]
    assert holds["holder_id"] == "other-request"
    assert any(item["holder_id"] == "maintenance:nested-hold-restart"
               for item in holds["details"]["additional_uncertain_holders"])
    assert restarted_system.lease_mgr.gpu_maintenance_owner == "maintenance:nested-hold-restart"

    released = await restarted.maintenance_manager.release({
        "operation_id": "nested-hold-restart",
        "session_id": acquired["session_id"],
        "operator": "operator",
        "operator_override": True,
        "override_reason": "Reconcile maintenance while preserving other hold",
        "restoration_verified": True,
        "resume_miner": False,
    })
    assert released["status"] == "released"
    remaining = StateCodec.load(state_path).inhibitions["gpu.inference"]
    assert remaining["holder_id"] == "other-request"
    assert restarted.maintenance_manager.status()["gpu_admission_permitted"] is False
    await restarted.stop("nested-maintenance-hold-test")


@pytest.mark.asyncio
async def test_restart_during_post_release_cooldown_does_not_start_miner_early(tmp_path: Path):
    service, backend, state_path = make_maintenance_service(
        tmp_path, restoration_verifier=lambda _record, _evidence: True
    )
    service.system.lease_mgr.set_resource_cooldown("gpu.inference", 0.5)
    acquired = await service.maintenance_manager.acquire(acquire_payload("release-cooldown"))
    result = await service.maintenance_manager.release({
        "token": acquired["token"],
        "session_id": acquired["session_id"],
        "operator": "mining_optimizer",
        "restoration_verified": True,
        "restoration_evidence": {"evidence_id": "mock-restoration"},
        "resume_miner": True,
    })
    assert result["status"] == "released"
    assert backend.running is False
    durable = StateCodec.load(state_path)
    assert durable.maintenance["restart_not_before"] > time.time()

    restarted_system = build_system(service.system.config, use_fake_processes=True)
    restarted = CoordinatorService(
        restarted_system, start_miner_on_ready=True, supervision_poll_interval=0.01
    )
    assert await restarted.start() is True
    assert restarted_system.lease_mgr.is_cooling_down("gpu.inference")
    assert restarted_system.supervisors["fake_miner"].backend.running is False
    assert restarted.maintenance_manager.state == "idle"
    deadline = asyncio.get_running_loop().time() + 2.0
    while asyncio.get_running_loop().time() < deadline:
        if restarted_system.supervisors["fake_miner"].backend.running:
            break
        await asyncio.sleep(0.01)
    supervisor = restarted_system.supervisors["fake_miner"]
    assert supervisor.backend.running is True, json.dumps({
        "generation": supervisor.backend.generation,
        "manual_override": supervisor.is_manual_override,
        "manual_override_until": supervisor.manual_override_until,
        "now": time.time(),
        "was_stopped_by_coordinator": supervisor.was_stopped_by_coordinator,
        "service_state": restarted.state.value,
        "cooling_down": restarted_system.lease_mgr.is_cooling_down("gpu.inference"),
        "inhibited": restarted_system.lease_mgr.is_restart_inhibited("gpu.inference"),
        "restarts_blocked": restarted_system.lease_mgr.restarts_blocked,
    })
    assert supervisor.backend.generation == 1
    await restarted.stop("release-cooldown-restart-test")
    if service.maintenance_manager._expiry_task:
        service.maintenance_manager._expiry_task.cancel()


@pytest.mark.asyncio
async def test_release_preserves_new_unrelated_inhibition(tmp_path: Path):
    service, _, state_path = make_maintenance_service(tmp_path)
    manager = service.maintenance_manager
    acquired = await manager.acquire(acquire_payload())
    await service.system.lease_mgr.inhibit_restart(
        "gpu.inference", "independent uncertainty", "unrelated-request", {"request_id": "unrelated-request"}
    )
    StateCodec.record_inhibition(
        state_path, "gpu.inference", "independent uncertainty", "unrelated-request",
        {"request_id": "unrelated-request"},
    )

    result = await manager.release({
        "token": acquired["token"],
        "session_id": acquired["session_id"],
        "operator": "mining_optimizer",
        "restoration_verified": True,
        "resume_miner": False,
        "operator_override": True,
        "override_reason": "Reconciled maintenance only",
    })
    assert result["status"] == "released"
    inhibition = service.system.lease_mgr.get_inhibition("gpu.inference")
    assert inhibition is not None
    assert inhibition.holder_id == "unrelated-request"
    assert StateCodec.load(state_path).inhibitions["gpu.inference"]["holder_id"] == "unrelated-request"
    assert manager.status()["gpu_admission_permitted"] is False
    assert service.system.lease_mgr.gpu_maintenance_owner is None
    if manager._expiry_task:
        manager._expiry_task.cancel()


@pytest.mark.asyncio
async def test_operator_can_reconcile_failed_acquisition_without_a_session_token(tmp_path: Path):
    service, backend, _ = make_maintenance_service(tmp_path, fail_stop=True)
    manager = service.maintenance_manager
    result = await manager.acquire(acquire_payload("failed-stop-operation"))
    assert result["status"] == "recovery_required"
    assert backend.running is True

    backend.fail_stop = False
    stopped = await service.system.supervisors["fake_miner"].stop(origin="manual")
    assert stopped is True
    reconciled = await manager.release({
        "operation_id": "failed-stop-operation",
        "operator": "operator",
        "operator_override": True,
        "override_reason": "Verified the fake miner is stopped",
        "restoration_verified": True,
        "resume_miner": False,
    })
    assert reconciled["status"] == "released"
    assert service.system.lease_mgr.gpu_maintenance_owner is None
    assert not service.system.lease_mgr.is_restart_inhibited("gpu.inference")


@pytest.mark.asyncio
async def test_slow_acquisition_returns_queryable_pending_and_idempotent_retry(tmp_path: Path):
    service, _, _ = make_maintenance_service(tmp_path, stop_delay=0.1, response_wait_seconds=0.005)
    manager = service.maintenance_manager
    result = await manager.acquire(acquire_payload("slow-operation"))
    assert result["status"] == "pending"
    assert manager.operation_status("slow-operation")["status"] == "pending"
    await manager._operation_task
    retry = await manager.acquire(acquire_payload("slow-operation"))
    assert retry["status"] == "granted"
    assert retry["token"]
    assert retry["session_id"] == manager.status()["session_id"]
    if manager._expiry_task:
        manager._expiry_task.cancel()


@pytest.mark.asyncio
async def test_concurrent_manager_acquisitions_create_one_session(tmp_path: Path):
    service, _, _ = make_maintenance_service(tmp_path, stop_delay=0.02)
    manager = service.maintenance_manager
    first, second = await asyncio.gather(
        manager.acquire(acquire_payload("concurrent-a")),
        manager.acquire(acquire_payload("concurrent-b")),
    )
    statuses = {first["status"], second["status"]}
    assert statuses in ({"granted", "conflict"}, {"pending", "conflict"})
    await manager._operation_task
    assert manager.state == "active"
    assert manager.status()["operation_id"] in {"concurrent-a", "concurrent-b"}
    if manager._expiry_task:
        manager._expiry_task.cancel()


@pytest.mark.asyncio
async def test_acquisition_persistence_failure_keeps_in_memory_fence_and_does_not_stop_miner(
    tmp_path: Path, monkeypatch
):
    service, backend, _ = make_maintenance_service(tmp_path)

    def fail_write(*_args, **_kwargs):
        raise OSError("simulated durable-state write failure")

    monkeypatch.setattr(StateCodec, "record_maintenance", fail_write)
    result = await service.maintenance_manager.acquire(acquire_payload("failed-persistence"))
    assert result["status"] == "persistence_failed"
    assert backend.running is True
    assert service.system.lease_mgr.gpu_maintenance_owner == "maintenance:failed-persistence"
    assert service.maintenance_manager.state == "recovery_required"
    assert not service.is_ready


@pytest.mark.asyncio
async def test_old_session_cannot_release_newer_maintenance_owner(tmp_path: Path):
    service, _, _ = make_maintenance_service(tmp_path)
    service.system.lease_mgr.set_resource_cooldown("gpu.inference", 0.0)
    manager = service.maintenance_manager
    first = await manager.acquire(acquire_payload("old-owner"))
    released = await manager.release({
        "token": first["token"], "session_id": first["session_id"], "operator": "operator",
        "restoration_verified": True, "resume_miner": False,
        "operator_override": True, "override_reason": "Test first session reconciliation",
    })
    assert released["status"] == "released", released
    cooldown_task = service.system.lease_mgr._cooldown_tasks["gpu.inference"]
    await asyncio.wait_for(cooldown_task, timeout=1.0)
    assert service.system.lease_mgr.gpu_maintenance_owner is None
    assert service.system.lease_mgr.get_inhibition("gpu.inference") is None
    assert not service.system.lease_mgr.is_cooling_down("gpu.inference")
    replayed_operation = manager.operation_status("old-owner")
    assert replayed_operation["status"] == "released"
    repeated_acquire = await manager.acquire(acquire_payload("old-owner"))
    assert repeated_acquire["status"] == "conflict"
    assert "token" not in repeated_acquire
    second = await manager.acquire(acquire_payload("new-owner"))
    stale = await manager.release({
        "token": first["token"], "session_id": first["session_id"], "operator": "operator",
        "restoration_verified": True, "resume_miner": False,
        "operator_override": True, "override_reason": "Stale owner must not release",
    })
    assert second["status"] == "granted"
    assert stale["status"] == "stale"
    assert manager.status()["session_id"] == second["session_id"]
    if manager._expiry_task:
        manager._expiry_task.cancel()


class MaintenanceClock:
    def __init__(self):
        self.now = 1000.0
        self.waiters = []

    def time(self):
        return self.now

    async def sleep(self, seconds):
        future = asyncio.get_running_loop().create_future()
        self.waiters.append((self.now + seconds, future))
        try:
            await future
        finally:
            self.waiters = [(deadline, item) for deadline, item in self.waiters if item is not future]

    def advance(self, seconds):
        self.now += seconds
        for deadline, future in tuple(self.waiters):
            if deadline <= self.now and not future.done():
                future.set_result(None)


@pytest.mark.asyncio
async def test_expiry_revokes_token_and_keeps_recovery_hold(tmp_path: Path):
    clock = MaintenanceClock()
    service, backend, _ = make_maintenance_service(tmp_path)
    service.maintenance_manager.clock = clock.time
    service.maintenance_manager.sleep = clock.sleep
    manager = service.maintenance_manager
    acquired = await manager.acquire(acquire_payload("expiry-operation"))
    await asyncio.sleep(0)
    clock.advance(3600)
    for _ in range(10):
        if manager.state == "recovery_required":
            break
        await asyncio.sleep(0)
    assert manager.state == "recovery_required"
    assert backend.running is False
    assert service.system.lease_mgr.gpu_maintenance_owner == "maintenance:expiry-operation"
    assert service.system.lease_mgr.is_restart_inhibited("gpu.inference")
    late = await manager.heartbeat({"token": acquired["token"], "lease_seconds": 3600})
    assert late["status"] == "stale"


@pytest.mark.asyncio
async def test_authenticated_routes_gate_inference_reuse_and_general_recovery(tmp_path: Path):
    service, _, _ = make_maintenance_service(tmp_path)
    assert await service.start() is True
    reused = False

    async def reusable(_body):
        nonlocal reused
        reused = True
        return "already-loaded"

    service.system.gateway._compatible_loaded_instance = reusable
    app = service.system.gateway.create_app(service)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://coordinator.test") as client:
        denied = await client.post("/_coordinator/maintenance/acquire", json=acquire_payload(),
                                   headers={"Authorization": "Bearer wrong"})
        assert denied.status_code == 403
        acquired = await client.post("/_coordinator/maintenance/acquire", json=acquire_payload(),
                                     headers={"Authorization": "Bearer test-operator-secret"})
        assert acquired.status_code == 200
        session = acquired.json()
        load = await client.post("/api/v1/models/load", json={"model": "fake-model", "context_length": 4096})
        assert load.status_code == 503
        assert reused is False
        status = await client.get("/_coordinator/maintenance/status")
        assert status.status_code == 200
        assert status.json()["state"] == "active"
        assert session["token"] not in status.text
        general_recovery = await client.post(
            "/_coordinator/recover?resource=gpu.inference",
            json={"override": True, "operator": "operator", "reason": "must not bypass maintenance"},
            headers={"Authorization": "Bearer test-operator-secret"},
        )
        assert general_recovery.status_code == 409
        rejected_release = await client.post(
            "/_coordinator/maintenance/release",
            json={**session, "operator": "mining_optimizer", "restoration_verified": True, "resume_miner": True},
            headers={"Authorization": "Bearer test-operator-secret"},
        )
        assert rejected_release.status_code == 409
        assert rejected_release.json()["status"] == "recovery_required"
        release = await client.post(
            "/_coordinator/maintenance/release",
            json={**session, "operator": "operator", "restoration_verified": True, "resume_miner": False,
                  "operator_override": True, "override_reason": "Test release"},
            headers={"Authorization": "Bearer test-operator-secret"},
        )
        assert release.status_code == 200
    await service.stop("maintenance-api-test")
