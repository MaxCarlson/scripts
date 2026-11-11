"""Fault injection and multiprocess crash recovery test suite.

Covers the Section 6 requirements from Phase 08 Final Safety:
1. Terminate a worker before source dispatch (verify transitions to terminal_without_dispatch, no barrier).
2. Terminate immediately after simulated dispatch (verify transitions to outcome_unknown, establishes locked_unresolved barrier).
3. Terminate while waiting for source completion.
4. Restart with an incomplete execution and expired lease.
5. Attempt a conflicting new action (blocked by barrier / locked_unresolved).
6. Reconstruct uncertainty without an existing explicit barrier.
7. Verify no duplicate dispatch on re-attempt.
8. Verify successful completed execution does not permanently block subsequent safe actions.
"""

from __future__ import annotations

import multiprocessing
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from remote_control.actions.models import (
    ActionDefinition,
    ActionEffect,
    ActionExecutionRecord,
    DispatchPhase,
    ExecutionState,
    PostconditionPolicy,
)
from remote_control.actions.registry import ActionRegistry
from remote_control.actions.service import (
    ActionService,
    ActionServiceError,
    ResourceBarrierActiveError,
)
from remote_control.actions.storage import ActionStorage
from remote_control.auth.storage import AuthStorage


def _worker_terminate_before_dispatch(db_path_str: str, resource_key: str, execution_id: str, idempotency_key_hash: str) -> None:
    """Worker terminates abruptly (os._exit) BEFORE external dispatch."""
    storage = ActionStorage(Path(db_path_str))
    record = ActionExecutionRecord(
        execution_id=execution_id,
        action_id="notifications.acknowledge_incident",
        action_version="1.0.0",
        actor_id="test_actor",
        session_id_hash="test_session_hash",
        device_id="test_device",
        idempotency_key_hash=idempotency_key_hash,
        arguments_digest="test_digest",
        state_fingerprint="test_fingerprint",
        started_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        status=ExecutionState.RESERVED,
        dispatch_phase=DispatchPhase.RESERVED_NOT_DISPATCHED.value,
    )
    storage.reserve_execution(record)
    storage.acquire_resource_lock_detailed(resource_key, execution_id, ttl_seconds=1.0)
    # Simulate sudden crash / SIGKILL before mutation is sent
    os._exit(42)


def _worker_terminate_after_dispatch(db_path_str: str, resource_key: str, execution_id: str, idempotency_key_hash: str) -> None:
    """Worker terminates abruptly (os._exit) AFTER mutation is dispatched."""
    storage = ActionStorage(Path(db_path_str))
    record = ActionExecutionRecord(
        execution_id=execution_id,
        action_id="notifications.acknowledge_incident",
        action_version="1.0.0",
        actor_id="test_actor",
        session_id_hash="test_session_hash",
        device_id="test_device",
        idempotency_key_hash=idempotency_key_hash,
        arguments_digest="test_digest",
        state_fingerprint="test_fingerprint",
        started_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        status=ExecutionState.RESERVED,
        dispatch_phase=DispatchPhase.RESERVED_NOT_DISPATCHED.value,
    )
    storage.reserve_execution(record)
    storage.acquire_resource_lock_detailed(resource_key, execution_id, ttl_seconds=1.0)
    # Transition to DISPATCH_STARTED
    storage.update_execution_dispatch_phase(execution_id, DispatchPhase.DISPATCH_STARTED.value)
    # Simulate sudden crash while waiting for subsystem response (before barrier or finished_at set)
    os._exit(43)


def test_crash_before_dispatch_reconciles_cleanly(tmp_path: Path) -> None:
    """Scenario 1: Worker terminated before source dispatch.
    Must transition to terminal_without_dispatch / failed without establishing a barrier.
    """
    db_file = tmp_path / "crash_before.db"
    store = ActionStorage(db_file)
    res_key = "notifications:incident:inc_001"
    exec_id = "exec_before_001"
    idemp_hash = "hash_before_001"

    p = multiprocessing.Process(
        target=_worker_terminate_before_dispatch,
        args=(str(db_file), res_key, exec_id, idemp_hash),
    )
    p.start()
    p.join(timeout=5)
    assert p.exitcode == 42

    # Check database state: before reconciliation, finished_at is NULL
    rec_pre = store.get_execution(exec_id)
    assert rec_pre is not None
    assert rec_pre.finished_at is None
    assert rec_pre.dispatch_phase == DispatchPhase.RESERVED_NOT_DISPATCHED.value

    # Reconcile dangling executions
    reconciled = store.reconcile_dangling_executions(concurrency_key=res_key)
    assert len(reconciled) == 1
    assert reconciled[0]["action"] == "terminated_without_dispatch"

    # Verify updated record
    rec_post = store.get_execution(exec_id)
    assert rec_post is not None
    assert rec_post.status == ExecutionState.FAILED
    assert rec_post.dispatch_phase == DispatchPhase.TERMINAL_WITHOUT_DISPATCH.value
    assert rec_post.finished_at is not None
    assert rec_post.error_code == "process_terminated_before_dispatch"

    # Verify NO barrier was created
    assert store.get_active_barrier(res_key) is None

    # Verify resource lock can be acquired by a subsequent action immediately
    acquired, reason = store.acquire_resource_lock_detailed(res_key, "exec_subsequent_001", ttl_seconds=10.0)
    assert acquired is True
    assert reason is None


def test_crash_after_dispatch_establishes_durable_barrier(tmp_path: Path) -> None:
    """Scenario 2 & 3: Worker terminated after simulated dispatch or while waiting for response.
    Must transition to outcome_unknown and establish locked_unresolved barrier.
    """
    db_file = tmp_path / "crash_after.db"
    store = ActionStorage(db_file)
    res_key = "notifications:incident:inc_002"
    exec_id = "exec_after_001"
    idemp_hash = "hash_after_001"

    p = multiprocessing.Process(
        target=_worker_terminate_after_dispatch,
        args=(str(db_file), res_key, exec_id, idemp_hash),
    )
    p.start()
    p.join(timeout=5)
    assert p.exitcode == 43

    # Check database state pre-reconcile: no barrier exists yet in action_resource_barriers
    assert store.get_active_barrier(res_key) is None

    # Reconcile dangling executions
    reconciled = store.reconcile_dangling_executions(concurrency_key=res_key)
    assert len(reconciled) == 1
    assert reconciled[0]["action"] == "barrier_established"

    # Verify record
    rec = store.get_execution(exec_id)
    assert rec is not None
    assert rec.status == ExecutionState.OUTCOME_UNKNOWN
    assert rec.dispatch_phase == DispatchPhase.OUTCOME_UNKNOWN.value
    assert rec.finished_at is not None
    assert rec.error_code == "process_terminated_during_dispatch"

    # Durable barrier MUST be active in storage
    barrier = store.get_active_barrier(res_key)
    assert barrier is not None
    assert barrier["execution_id"] == exec_id
    assert barrier["barrier_status"] == "locked_unresolved"


def test_restart_reconciliation_and_conflict_rejection(tmp_path: Path) -> None:
    """Scenario 4 & 5: Restart with incomplete execution and expired lease.
    Attempting a conflicting new action is rejected with locked_unresolved barrier.
    """
    db_file = tmp_path / "crash_restart.db"
    store = ActionStorage(db_file)
    res_key = "notifications:incident:inc_003"
    exec_id = "exec_crash_003"
    idemp_hash = "hash_crash_003"

    # Worker crashes post-dispatch
    p = multiprocessing.Process(
        target=_worker_terminate_after_dispatch,
        args=(str(db_file), res_key, exec_id, idemp_hash),
    )
    p.start()
    p.join(timeout=5)
    assert p.exitcode == 43

    # Wait 1.1s for the 1.0s lease to expire in action_resource_locks
    time.sleep(1.1)

    # Now a new ActionService instance starts up (simulating host or daemon restart)
    registry = ActionRegistry()
    auth_store = AuthStorage(db_file)
    # ActionService constructor automatically runs reconcile_dangling_executions()
    service = ActionService(storage=store, auth_storage=auth_store, registry=registry)

    # Verify that barrier was established during service initialization
    barrier = store.get_active_barrier(res_key)
    assert barrier is not None
    assert barrier["execution_id"] == exec_id
    assert barrier["barrier_status"] == "locked_unresolved"

    # Attempting to acquire lock for a new execution MUST fail with barrier_active
    acquired, reason = store.acquire_resource_lock_detailed(res_key, "exec_new_001", ttl_seconds=10.0)
    assert acquired is False
    assert reason == "barrier_active"


def test_reconstruct_uncertainty_without_existing_explicit_barrier(tmp_path: Path) -> None:
    """Scenario 6: Reconstruct uncertainty without an existing explicit barrier.
    Even if the barrier row was never created (e.g. process died before set_resource_barrier),
    the acquisition path directly detects the dangling dispatch_started execution,
    reconciles it, establishes the barrier, and denies lock acquisition atomically.
    """
    db_file = tmp_path / "reconstruct.db"
    store = ActionStorage(db_file)
    res_key = "notifications:incident:inc_004"
    exec_id = "exec_reconstruct_001"
    idemp_hash = "hash_reconstruct_001"

    # Crash worker post-dispatch
    p = multiprocessing.Process(
        target=_worker_terminate_after_dispatch,
        args=(str(db_file), res_key, exec_id, idemp_hash),
    )
    p.start()
    p.join(timeout=5)
    assert p.exitcode == 43

    # 1. Before lease expires: contender is blocked by lock contention
    fresh_store = ActionStorage(db_file)
    with fresh_store._get_connection() as conn:
        b = conn.execute("SELECT 1 FROM action_resource_barriers WHERE resource_key = ?", (res_key,)).fetchone()
        assert b is None

    # While lock is still within its 1.0s TTL, cannot acquire due to lock_contention
    acquired_early, reason_early = fresh_store.acquire_resource_lock_detailed(res_key, "exec_contender", ttl_seconds=10.0)
    assert acquired_early is False
    assert reason_early == "lock_contention"

    # 2. Wait for transient lease to expire
    time.sleep(1.1)

    # 3. Now the transient lease has expired, but the execution was never finished (finished_at IS NULL).
    # Calling acquire_resource_lock_detailed must automatically detect the dangling execution,
    # reconstruct uncertainty, set the barrier, and return False, 'barrier_active'
    acquired, reason = fresh_store.acquire_resource_lock_detailed(res_key, "exec_contender", ttl_seconds=10.0)
    assert acquired is False
    assert reason == "barrier_active"

    # Verify barrier now exists
    barrier = fresh_store.get_active_barrier(res_key)
    assert barrier is not None
    assert barrier["execution_id"] == exec_id
    assert barrier["barrier_status"] == "locked_unresolved"


def test_idempotent_reexecution_does_not_redispatch(tmp_path: Path) -> None:
    """Scenario 7: Repeating the execution with the same idempotency key returns
    the existing record and does not dispatch a duplicate mutation.
    """
    db_file = tmp_path / "idemp_no_dupe.db"
    store = ActionStorage(db_file)
    res_key = "notifications:incident:inc_005"
    exec_id = "exec_idemp_001"
    idemp_hash = "hash_same_key_999"

    # Crash worker post-dispatch
    p = multiprocessing.Process(
        target=_worker_terminate_after_dispatch,
        args=(str(db_file), res_key, exec_id, idemp_hash),
    )
    p.start()
    p.join(timeout=5)
    assert p.exitcode == 43

    store.reconcile_dangling_executions(concurrency_key=res_key)

    # Attempt to reserve with same action_id and idempotency_key_hash
    new_candidate = ActionExecutionRecord(
        execution_id="exec_should_be_ignored",
        action_id="notifications.acknowledge_incident",
        action_version="1.0.0",
        actor_id="test_actor",
        session_id_hash="test_session_hash",
        device_id="test_device",
        idempotency_key_hash=idemp_hash,
        arguments_digest="test_digest",
        state_fingerprint="test_fingerprint",
        started_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        status=ExecutionState.RESERVED,
        dispatch_phase=DispatchPhase.RESERVED_NOT_DISPATCHED.value,
    )
    is_new, existing = store.reserve_execution(new_candidate)
    assert is_new is False
    assert existing.execution_id == exec_id
    assert existing.status == ExecutionState.OUTCOME_UNKNOWN
    assert existing.dispatch_phase == DispatchPhase.OUTCOME_UNKNOWN.value


def test_successful_execution_does_not_block_subsequent_actions(tmp_path: Path) -> None:
    """Scenario 8: Successful completed execution does not permanently block subsequent actions.
    Locks are released and no barrier is established.
    """
    db_file = tmp_path / "success_flow.db"
    store = ActionStorage(db_file)
    res_key = "notifications:incident:inc_006"
    exec_id = "exec_success_001"
    idemp_hash = "hash_success_001"

    # Reserve and acquire lock
    record = ActionExecutionRecord(
        execution_id=exec_id,
        action_id="notifications.acknowledge_incident",
        action_version="1.0.0",
        actor_id="test_actor",
        session_id_hash="test_session_hash",
        device_id="test_device",
        idempotency_key_hash=idemp_hash,
        arguments_digest="test_digest",
        state_fingerprint="test_fingerprint",
        started_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        status=ExecutionState.RESERVED,
        dispatch_phase=DispatchPhase.RESERVED_NOT_DISPATCHED.value,
    )
    is_new, _ = store.reserve_execution(record)
    assert is_new is True

    acquired, _ = store.acquire_resource_lock_detailed(res_key, exec_id, ttl_seconds=10.0)
    assert acquired is True

    store.update_execution_dispatch_phase(exec_id, DispatchPhase.DISPATCH_STARTED.value)

    # Complete successfully
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    store.update_execution(
        execution_id=exec_id,
        status=ExecutionState.SUCCEEDED,
        finished_at=now_iso,
        result_category="ok",
        postcondition_verified=True,
        summary="Incident acknowledged successfully.",
        dispatch_phase=DispatchPhase.POSTCONDITION_VERIFIED.value,
    )
    store.release_resource_lock(res_key, exec_id)

    # Verify no barrier
    assert store.get_active_barrier(res_key) is None

    # Next execution on same resource key succeeds in acquiring lock
    acquired2, reason2 = store.acquire_resource_lock_detailed(res_key, "exec_success_002", ttl_seconds=10.0)
    assert acquired2 is True
    assert reason2 is None
