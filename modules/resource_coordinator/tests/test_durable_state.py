"""
Unit tests for durable state persistence, atomic serialization, and PID reconciliation.
"""

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json
import pytest
import psutil

from resource_coordinator.core.durable_state import (
    CoordinatorState,
    PersistedProcess,
    PersistedRequest,
    ReconciliationOutcome,
    StateCodec,
    reconcile_pid,
)
from resource_coordinator.core.leases import LeaseManager


def test_durable_state_roundtrip():
    """Verify serialization and deserialization preserves all state attributes."""
    state = CoordinatorState(
        version="1.0",
        updated_at=1729350000.0,
        inhibitions={
            "gpu.inference": {
                "resource": "gpu.inference",
                "reason": "client_disconnect",
                "holder_id": "req-123",
                "inhibited_at": 1729349999.0,
                "details": {"model": "qwen32b"},
            }
        },
        processes={
            "krig": PersistedProcess(
                name="krig",
                pid=9999,
                create_time=1729340000.0,
                lifecycle_owner="coordinator",
                was_stopped_by_coordinator=True,
                last_stopped_at=1729349000.0,
                last_started_at=1729340000.0,
            )
        },
    )

    encoded = StateCodec.serialize(state)
    decoded = StateCodec.deserialize(encoded)

    assert decoded.version == "1.0"
    assert decoded.updated_at == 1729350000.0
    assert "gpu.inference" in decoded.inhibitions
    assert decoded.inhibitions["gpu.inference"]["reason"] == "client_disconnect"
    assert "krig" in decoded.processes
    proc = decoded.processes["krig"]
    assert proc.pid == 9999
    assert proc.was_stopped_by_coordinator is True


def test_save_atomic_and_load(tmp_path: Path):
    """Verify atomic write and subsequent load from disk."""
    state_file = tmp_path / "state.json"
    state = CoordinatorState(
        inhibitions={"gpu.model": {"reason": "load_failure", "holder_id": "h1"}},
        processes={"p1": PersistedProcess(name="p1", pid=123, create_time=100.0)},
    )

    StateCodec.save_atomic(state, state_file)
    assert state_file.exists()

    loaded = StateCodec.load(state_file)
    assert "gpu.model" in loaded.inhibitions
    assert "p1" in loaded.processes
    assert loaded.processes["p1"].pid == 123


def test_load_non_existent_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        StateCodec.load(tmp_path / "does_not_exist.json")


def test_state_revision_increments_once_per_successful_transaction(tmp_path: Path):
    state_file = tmp_path / "state.json"
    StateCodec.initialize(state_file)
    initialized = StateCodec.load(state_file)

    StateCodec.record_inhibition(state_file, "gpu.inference", "uncertain", "req-a")
    changed = StateCodec.load(state_file)

    assert initialized.revision == 1
    assert changed.revision == initialized.revision + 1


def test_legacy_state_defaults_revision_to_zero():
    legacy = {
        "version": "1.0", "updated_at": 1.0, "inhibitions": {}, "processes": {},
    }
    state = StateCodec.deserialize(json.dumps(legacy))
    assert state.revision == 0


def test_concurrent_durable_writers_do_not_lose_holds(tmp_path: Path):
    state_file = tmp_path / "state.json"
    StateCodec.initialize(state_file)

    def write(index: int) -> None:
        StateCodec.record_inhibition(state_file, f"gpu.test{index}", "test", f"holder-{index}")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(16)))

    state = StateCodec.load(state_file)
    assert set(state.inhibitions) == {f"gpu.test{index}" for index in range(16)}
    assert state.revision == 17


def test_save_rejects_a_stale_state_snapshot(tmp_path: Path):
    from resource_coordinator.core.durable_state import ConcurrentJournalUpdateError

    state_file = tmp_path / "state.json"
    StateCodec.initialize(state_file)
    stale = StateCodec.load(state_file)
    StateCodec.record_inhibition(state_file, "gpu.inference", "uncertain", "req-a")
    stale.gaming_mode = {"state": "active", "models": [], "miner_was_running": False}

    with pytest.raises(ConcurrentJournalUpdateError):
        StateCodec.save_atomic(stale, state_file)


def test_recovery_transaction_marks_exact_request_and_preserves_other_holders(tmp_path: Path):
    state_file = tmp_path / "state.json"
    StateCodec.initialize(state_file)
    StateCodec.record_request_phase(
        state_file, "req-a", "gpu.inference", "reserved", details={"forwarded": False}
    )
    StateCodec.record_inhibition(state_file, "gpu.inference", "uncertain", "req-a")
    StateCodec.record_inhibition(state_file, "gpu.inference", "operator_hold", "operator-1")
    before = StateCodec.load(state_file)

    committed = StateCodec.reconcile_requests_and_clear_holders(
        state_file,
        expected_revision=before.revision,
        reconciliations=[{
            "request_id": "req-a", "expected_phase": "reserved", "disposition": "not_forwarded_verified",
            "evidence": {"source": "durable_dispatch_boundary"},
        }],
        holder_ids=["req-a"],
    )

    assert committed.revision == before.revision + 1
    assert committed.requests["req-a"].phase == "reconciled"
    assert committed.requests["req-a"].details["reconciliation_disposition"] == "not_forwarded_verified"
    assert committed.inhibitions["gpu.inference"]["holder_id"] == "operator-1"


def test_exact_holder_removal_flattens_and_preserves_nested_legacy_holders(tmp_path: Path):
    state_file = tmp_path / "state.json"
    state = CoordinatorState(inhibitions={"gpu.inference": {
        "resource": "gpu.inference", "reason": "request", "holder_id": "req-a",
        "inhibited_at": 1.0, "details": {"additional_uncertain_holders": [{
            "resource": "gpu.inference", "reason": "operator", "holder_id": "operator-1",
            "inhibited_at": 2.0, "details": {"additional_uncertain_holders": [{
                "resource": "gpu.inference", "reason": "maintenance", "holder_id": "maintenance-1",
                "inhibited_at": 3.0, "details": {},
            }]},
        }]},
    }})
    StateCodec.save_atomic(state, state_file)

    updated = StateCodec.clear_inhibition_holder(state_file, "gpu.inference", "operator-1")

    from resource_coordinator.core.durable_state import _all_inhibition_holders

    assert [item["holder_id"] for item in _all_inhibition_holders(
        updated.inhibitions["gpu.inference"]
    )] == ["req-a", "maintenance-1"]


def test_recovery_transaction_rejects_changed_revision_without_mutation(tmp_path: Path):
    from resource_coordinator.core.durable_state import ConcurrentJournalUpdateError

    state_file = tmp_path / "state.json"
    StateCodec.initialize(state_file)
    StateCodec.record_request_phase(state_file, "req-a", "gpu.inference", "reserved")
    stale_revision = StateCodec.load(state_file).revision
    StateCodec.record_inhibition(state_file, "gpu.model_loading", "independent", "other")

    with pytest.raises(ConcurrentJournalUpdateError):
        StateCodec.reconcile_requests_and_clear_holders(
            state_file, expected_revision=stale_revision, reconciliations=[], holder_ids=[]
        )
    assert StateCodec.load(state_file).inhibitions["gpu.model_loading"]["holder_id"] == "other"


def test_legacy_downgrade_export_archives_only_reconciled_history_and_keeps_holds(tmp_path: Path):
    source = tmp_path / "state.json"
    target = tmp_path / "rollback-state.json"
    StateCodec.initialize(source)
    StateCodec.record_request_phase(source, "done", "gpu.inference", "reconciled",
                                    details={"reconciliation_disposition": "not_forwarded_verified"})
    StateCodec.record_request_phase(source, "uncertain", "gpu.inference", "uncertain")
    StateCodec.record_inhibition(source, "gpu.inference", "uncertain", "uncertain")

    archive_path = StateCodec.export_legacy_compatible(source, target)

    legacy = json.loads(target.read_text(encoding="utf-8"))
    archive = json.loads(archive_path.read_text(encoding="utf-8"))
    assert "revision" not in legacy
    assert set(legacy["requests"]) == {"uncertain"}
    assert legacy["inhibitions"]["gpu.inference"]["holder_id"] == "uncertain"
    assert archive["archived_requests"][0]["request_id"] == "done"


def test_legacy_downgrade_export_refuses_to_overwrite_source(tmp_path: Path):
    from resource_coordinator.core.durable_state import LegacyExportError

    source = tmp_path / "state.json"
    StateCodec.initialize(source)
    with pytest.raises(LegacyExportError):
        StateCodec.export_legacy_compatible(source, source)


@pytest.mark.asyncio
async def test_startup_canonicalizes_request_holders_in_durable_and_live_state(tmp_path: Path):
    from resource_coordinator.core.durable_state import reconcile_startup_state

    state_file = tmp_path / "state.json"
    state = CoordinatorState(
        inhibitions={"gpu.inference": {
            "resource": "gpu.inference", "reason": "uncertain", "holder_id": "coord-req-a",
            "inhibited_at": 1.0, "details": {},
        }},
        requests={"req-a": PersistedRequest(
            request_id="req-a", resource="gpu.inference", phase="uncertain", updated_at=1.0,
        )},
    )
    StateCodec.save_atomic(state, state_file)
    manager = LeaseManager()

    await reconcile_startup_state(state, manager, state_path=state_file, query_fn=lambda _pid: None)

    durable = StateCodec.load(state_file).inhibitions["gpu.inference"]
    live = manager.get_inhibition("gpu.inference")
    assert durable["holder_id"] == "req-a"
    assert not durable.get("details", {}).get("additional_uncertain_holders")
    assert live is not None and live.holder_id == "req-a"


@pytest.mark.asyncio
async def test_startup_canonicalizes_nested_legacy_holders_idempotently(tmp_path: Path):
    from resource_coordinator.core.durable_state import _all_inhibition_holders, reconcile_startup_state

    state_file = tmp_path / "nested-state.json"
    state = CoordinatorState(
        inhibitions={"gpu.inference": {
            "resource": "gpu.inference", "reason": "legacy", "holder_id": "coord-req-a",
            "inhibited_at": 1.0, "details": {"additional_uncertain_holders": [
                {"resource": "gpu.inference", "reason": "legacy", "holder_id": "crash_recovery:coord-req-b",
                 "inhibited_at": 2.0, "details": {}},
                {"resource": "gpu.inference", "reason": "operator", "holder_id": "operator-hold",
                 "inhibited_at": 3.0, "details": {}},
            ]},
        }},
        requests={request_id: PersistedRequest(
            request_id=request_id, resource="gpu.inference", phase="uncertain", updated_at=1.0,
        ) for request_id in ("req-a", "req-b")},
    )
    StateCodec.save_atomic(state, state_file)
    initial_revision = StateCodec.load(state_file).revision

    await reconcile_startup_state(StateCodec.load(state_file), LeaseManager(), state_path=state_file,
                                  query_fn=lambda _pid: None)
    first = StateCodec.load(state_file)
    await reconcile_startup_state(first, LeaseManager(), state_path=state_file, query_fn=lambda _pid: None)
    second = StateCodec.load(state_file)

    holders = _all_inhibition_holders(second.inhibitions["gpu.inference"])
    assert [item["holder_id"] for item in holders] == ["req-a", "req-b", "operator-hold"]
    assert second.revision == first.revision
    assert first.revision == initial_revision + 1


@pytest.mark.asyncio
async def test_startup_canonicalization_persistence_failure_restores_no_partial_live_state(
    tmp_path: Path, monkeypatch
):
    from resource_coordinator.core.durable_state import reconcile_startup_state

    state_file = tmp_path / "state.json"
    state = CoordinatorState(
        inhibitions={"gpu.inference": {
            "resource": "gpu.inference", "reason": "uncertain", "holder_id": "coord-req-a",
            "inhibited_at": 1.0, "details": {},
        }},
        requests={"req-a": PersistedRequest(
            request_id="req-a", resource="gpu.inference", phase="uncertain", updated_at=1.0,
        )},
    )
    StateCodec.save_atomic(state, state_file)
    manager = LeaseManager()

    def fail_persist(*_args, **_kwargs):
        raise OSError("injected startup canonicalization write failure")

    monkeypatch.setattr(StateCodec, "save_atomic", fail_persist)
    with pytest.raises(OSError, match="canonicalization write failure"):
        await reconcile_startup_state(state, manager, state_path=state_file, query_fn=lambda _pid: None)

    assert StateCodec.load(state_file).inhibitions["gpu.inference"]["holder_id"] == "coord-req-a"
    assert manager.get_inhibition("gpu.inference") is None


@pytest.mark.asyncio
async def test_startup_pid_access_denied_is_not_treated_as_absence(tmp_path: Path, monkeypatch):
    from resource_coordinator.core.durable_state import reconcile_startup_state

    state = CoordinatorState(processes={"krig": PersistedProcess(
        name="krig", pid=123, create_time=1.0, lifecycle_owner="coordinator",
    )})
    manager = LeaseManager()
    def inaccessible_process(pid: int):
        assert pid == 123
        raise psutil.AccessDenied(pid=pid)

    monkeypatch.setattr(psutil, "Process", inaccessible_process)
    audit = await reconcile_startup_state(state, manager)

    assert audit["reconciled_processes"]["krig"]["outcome"] == "access_denied"


def test_load_corrupted_file_fails_closed(tmp_path: Path):
    corrupted = tmp_path / "corrupt.json"
    corrupted.write_text("{ this is not valid json : [", encoding="utf-8")
    with pytest.raises(ValueError):
        StateCodec.load(corrupted)


def test_reconcile_pid_not_running():
    """When PID does not exist in the OS table, returns NOT_RUNNING."""

    def query(pid: int) -> None:
        return None

    res = reconcile_pid(persisted_pid=1234, persisted_create_time=100.0, query_fn=query)
    assert res == ReconciliationOutcome.NOT_RUNNING


def test_reconcile_pid_verified_running():
    """When PID exists and create_time matches, returns VERIFIED_RUNNING."""

    def query(pid: int) -> float | None:
        return 100.0 if pid == 1234 else None

    res = reconcile_pid(
        persisted_pid=1234,
        persisted_create_time=100.0,
        query_fn=query,
        create_time_tolerance_seconds=0.0,
    )
    assert res == ReconciliationOutcome.VERIFIED_RUNNING


def test_reconcile_pid_recycled_hazard():
    """When PID exists but create_time does NOT match, detects PID recycling hazard."""
    # Process exists with PID 1234, but was created at time 500.0, not 100.0!

    def query(pid: int) -> float | None:
        return 500.0 if pid == 1234 else None

    res = reconcile_pid(
        persisted_pid=1234,
        persisted_create_time=100.0,
        query_fn=query,
        create_time_tolerance_seconds=0.0,
    )
    assert res == ReconciliationOutcome.PID_RECYCLED


@pytest.mark.asyncio
async def test_restore_into_leases():
    """Verify that persisted restart inhibitions are correctly injected into LeaseManager."""
    lease_mgr = LeaseManager()
    state = CoordinatorState(
        inhibitions={
            "gpu.inference": {
                "resource": "gpu.inference",
                "reason": "crash_recovery",
                "holder_id": "req-999",
                "details": {"info": "retained"},
            }
        }
    )

    assert lease_mgr.is_restart_inhibited("gpu.inference") is False

    count = await StateCodec.restore_into_leases(state, lease_mgr)
    assert count == 1
    assert lease_mgr.is_restart_inhibited("gpu.inference") is True

    inh = lease_mgr.get_inhibition("gpu.inference")
    assert inh is not None
    assert inh.reason == "crash_recovery"
    assert inh.holder_id == "req-999"
