"""Targeted tests for Section 5: Crash reconciliation and resource identity.

Invariants:
1. Persist authoritative resource_key with each execution record (Schema V3).
2. Startup reconciliation with only_expired=True never terminates an active worker's execution.
3. Startup reconciliation preserves Worker A in dispatch_started if its lock lease is active.
4. Reconstruct dispatch uncertainty under the execution's original persisted resource_key.
5. Crash after dispatch_started establishes durable barrier under persisted resource_key.
6. Crash before dispatch reconciles cleanly without barrier.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import pytest

from remote_control.actions.models import (
    ActionExecutionRecord,
    DispatchPhase,
    ExecutionState,
)
from remote_control.actions.registry import ActionRegistry
from remote_control.actions.service import ActionService
from remote_control.actions.storage import ActionStorage
from remote_control.auth.storage import AuthStorage


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def test_schema_v3_additive_migration_persists_resource_key(tmp_path: Path) -> None:
    """Verify resource_key column exists, persists, and is retrieved on ActionExecutionRecord."""
    db = tmp_path / "migration.db"
    store = ActionStorage(db)

    rec = ActionExecutionRecord(
        execution_id="exec_res_001",
        action_id="notifications.acknowledge_incident",
        action_version="1.0.0",
        actor_id="admin_op",
        session_id_hash="sess_hash",
        device_id="device_1",
        idempotency_key_hash="idemp_hash_001",
        arguments_digest="arg_digest",
        state_fingerprint="state_fp",
        started_at=_now(),
        status=ExecutionState.RESERVED,
        dispatch_phase=DispatchPhase.RESERVED_NOT_DISPATCHED.value,
        resource_key="notifications:incident:999",
    )
    is_new, loaded = store.reserve_execution(rec)
    assert is_new is True
    assert loaded.resource_key == "notifications:incident:999"

    # Query directly by execution ID
    fetched = store.get_execution("exec_res_001")
    assert fetched is not None
    assert fetched.resource_key == "notifications:incident:999"

    # Query via list_executions
    listed = store.list_executions()
    assert len(listed) == 1
    assert listed[0].resource_key == "notifications:incident:999"


def test_startup_reconciliation_does_not_terminate_live_active_worker(tmp_path: Path) -> None:
    """Worker B initializing while Worker A is running with active lease must not terminate Worker A."""
    db = tmp_path / "live_worker.db"
    store_a = ActionStorage(db)
    res_key = "notifications:incident:100"
    exec_a = "exec_worker_a"

    # Worker A reserves execution with a long lease TTL (60s)
    rec_a = ActionExecutionRecord(
        execution_id=exec_a,
        action_id="notifications.acknowledge_incident",
        action_version="1.0.0",
        actor_id="admin_op",
        session_id_hash="sess_hash",
        device_id="device_1",
        idempotency_key_hash="hash_live_a",
        arguments_digest="digest",
        state_fingerprint="fp",
        started_at=_now(),
        status=ExecutionState.RESERVED,
        dispatch_phase=DispatchPhase.RESERVED_NOT_DISPATCHED.value,
        resource_key=res_key,
    )
    store_a.reserve_execution(rec_a)
    acquired, _ = store_a.acquire_resource_lock_detailed(res_key, exec_a, ttl_seconds=60.0)
    assert acquired is True

    # Worker B starts up (ActionService initialization with only_expired=True)
    auth_store = AuthStorage(db)
    registry = ActionRegistry()
    service_b = ActionService(storage=ActionStorage(db), auth_storage=auth_store, registry=registry)

    # Worker A's execution must NOT be touched or terminated
    rec_after = store_a.get_execution(exec_a)
    assert rec_after is not None
    assert rec_after.status == ExecutionState.RESERVED
    assert rec_after.finished_at is None
    assert rec_after.dispatch_phase == DispatchPhase.RESERVED_NOT_DISPATCHED.value

    # Lock must still be held by Worker A
    lock_info = store_a.get_resource_lock(res_key)
    assert lock_info is not None
    assert lock_info["holder_execution_id"] == exec_a


def test_startup_reconciliation_does_not_overwrite_worker_in_dispatch_started(tmp_path: Path) -> None:
    """Worker A in dispatch_started with an active lease must not be overwritten or converted to barrier by Worker B."""
    db = tmp_path / "dispatch_worker.db"
    store_a = ActionStorage(db)
    res_key = "notifications:incident:200"
    exec_a = "exec_worker_a_dispatched"

    rec_a = ActionExecutionRecord(
        execution_id=exec_a,
        action_id="notifications.acknowledge_incident",
        action_version="1.0.0",
        actor_id="admin_op",
        session_id_hash="sess_hash",
        device_id="device_1",
        idempotency_key_hash="hash_live_a2",
        arguments_digest="digest",
        state_fingerprint="fp",
        started_at=_now(),
        status=ExecutionState.RESERVED,
        dispatch_phase=DispatchPhase.DISPATCH_STARTED.value,
        resource_key=res_key,
    )
    store_a.reserve_execution(rec_a)
    store_a.acquire_resource_lock_detailed(res_key, exec_a, ttl_seconds=60.0)
    store_a.update_execution_dispatch_phase(exec_a, DispatchPhase.DISPATCH_STARTED.value)

    # Worker B starts up
    auth_store = AuthStorage(db)
    registry = ActionRegistry()
    service_b = ActionService(storage=ActionStorage(db), auth_storage=auth_store, registry=registry)

    # Worker A's execution must remain in progress, no barrier established yet
    rec_after = store_a.get_execution(exec_a)
    assert rec_after is not None
    assert rec_after.dispatch_phase == DispatchPhase.DISPATCH_STARTED.value
    assert rec_after.finished_at is None
    assert store_a.get_active_barrier(res_key) is None


def test_expired_lease_crashed_after_dispatch_establishes_barrier_under_persisted_key(tmp_path: Path) -> None:
    """When a worker crashed post-dispatch and its lease expires, startup reconciliation establishes barrier under persisted resource_key."""
    db = tmp_path / "expired_crash.db"
    store = ActionStorage(db)
    res_key = "notifications:incident:300"
    exec_id = "exec_crashed_post_dispatch"

    rec = ActionExecutionRecord(
        execution_id=exec_id,
        action_id="notifications.acknowledge_incident",
        action_version="1.0.0",
        actor_id="admin_op",
        session_id_hash="sess_hash",
        device_id="device_1",
        idempotency_key_hash="hash_crash_300",
        arguments_digest="digest",
        state_fingerprint="fp",
        started_at="2026-11-11T00:00:00Z",  # in the past (> 30s)
        status=ExecutionState.RESERVED,
        dispatch_phase=DispatchPhase.DISPATCH_STARTED.value,
        resource_key=res_key,
    )
    store.reserve_execution(rec)
    store.acquire_resource_lock_detailed(res_key, exec_id, ttl_seconds=0.1)
    store.update_execution_dispatch_phase(exec_id, DispatchPhase.DISPATCH_STARTED.value)

    # Artificially expire the lease in the past
    with store._get_connection() as conn:
        conn.execute("UPDATE action_resource_locks SET expires_at = '2026-11-11T00:00:01Z' WHERE resource_key = ?", (res_key,))

    # Now startup reconciliation runs
    reconciled = store.reconcile_dangling_executions(only_expired=True)
    assert len(reconciled) == 1
    assert reconciled[0]["action"] == "barrier_established"
    assert reconciled[0]["resource_key"] == res_key

    # Barrier must be established under the persisted resource_key
    barrier = store.get_active_barrier(res_key)
    assert barrier is not None
    assert barrier["execution_id"] == exec_id
    assert barrier["barrier_status"] == "locked_unresolved"


def test_expired_lease_crashed_before_dispatch_reconciles_cleanly_without_barrier(tmp_path: Path) -> None:
    """When a worker crashed before dispatch and lease expired, startup reconciliation cleans up without barrier."""
    db = tmp_path / "expired_clean.db"
    store = ActionStorage(db)
    res_key = "notifications:incident:400"
    exec_id = "exec_crashed_pre_dispatch"

    rec = ActionExecutionRecord(
        execution_id=exec_id,
        action_id="notifications.acknowledge_incident",
        action_version="1.0.0",
        actor_id="admin_op",
        session_id_hash="sess_hash",
        device_id="device_1",
        idempotency_key_hash="hash_clean_400",
        arguments_digest="digest",
        state_fingerprint="fp",
        started_at="2026-11-11T00:00:00Z",  # in the past
        status=ExecutionState.RESERVED,
        dispatch_phase=DispatchPhase.RESERVED_NOT_DISPATCHED.value,
        resource_key=res_key,
    )
    store.reserve_execution(rec)
    store.acquire_resource_lock_detailed(res_key, exec_id, ttl_seconds=0.1)

    with store._get_connection() as conn:
        conn.execute("UPDATE action_resource_locks SET expires_at = '2026-11-11T00:00:01Z' WHERE resource_key = ?", (res_key,))

    reconciled = store.reconcile_dangling_executions(only_expired=True)
    assert len(reconciled) == 1
    assert reconciled[0]["action"] == "terminated_without_dispatch"

    # Zero barriers established
    assert store.get_active_barrier(res_key) is None

    # Record marked as failed
    updated_rec = store.get_execution(exec_id)
    assert updated_rec is not None
    assert updated_rec.status == ExecutionState.FAILED
    assert updated_rec.dispatch_phase == DispatchPhase.TERMINAL_WITHOUT_DISPATCH.value
