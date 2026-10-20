"""
Unit tests for durable state persistence, atomic serialization, and PID reconciliation.
"""

from pathlib import Path
import pytest

from resource_coordinator.core.durable_state import (
    CoordinatorState,
    PersistedProcess,
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
