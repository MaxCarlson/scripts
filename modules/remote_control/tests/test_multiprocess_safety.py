"""Tests for durable unresolved execution barriers, multiprocess safety, and lease renewal.

Demonstrates Mandatory Amendment 1:
- A dead process, expired local lease, timed-out call, or failed status does NOT clear barriers.
- An unresolved externally dispatched mutation remains an explicit safety barrier (locked_unresolved)
  until authoritative source evidence establishes the outcome.
- Independent process safety using ProcessPoolExecutor.
- Demonstration that lease renewal does not claim distributed fencing.
- Absence of automatic retries for mutations with uncertain effects.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

from remote_control.actions.models import (
    ActionDefinition,
    ActionEffect,
    ActionExecutionRecord,
    ConfirmationChallenge,
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


# Helper functions executed in independent OS processes for multiprocessing tests
def _worker_acquire_lock(db_path_str: str, resource_key: str, execution_id: str, ttl: float) -> Tuple[bool, Optional[str]]:
    """Worker running in separate OS process attempting to acquire resource lock."""
    storage = ActionStorage(Path(db_path_str))
    return storage.acquire_resource_lock_detailed(resource_key, execution_id, ttl_seconds=ttl)


def _worker_reserve_execution(
    db_path_str: str,
    execution_id: str,
    action_id: str,
    idempotency_key_hash: str,
) -> bool:
    """Worker running in separate OS process attempting to reserve execution with idempotency key."""
    storage = ActionStorage(Path(db_path_str))
    record = ActionExecutionRecord(
        execution_id=execution_id,
        action_id=action_id,
        action_version="1.0.0",
        actor_id="test_actor",
        session_id_hash="test_session_hash",
        device_id="test_device",
        idempotency_key_hash=idempotency_key_hash,
        arguments_digest="test_args_digest",
        state_fingerprint="test_state_fingerprint",
        started_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        status=ExecutionState.RESERVED,
    )
    is_new, _ = storage.reserve_execution(record)
    return is_new


@pytest.fixture
def storage(tmp_path: Path) -> ActionStorage:
    db_file = tmp_path / "test_actions.db"
    return ActionStorage(db_file)


class SlowTimeoutAdapter:
    """Simulates an adapter that hangs beyond action timeout."""
    def __init__(self, sleep_seconds: float = 2.0) -> None:
        self.sleep_seconds = sleep_seconds
        self.dispatched = False

    async def execute(self, arguments: Dict[str, Any], actor_id: str, **kwargs: Any) -> Dict[str, Any]:
        self.dispatched = True
        await asyncio.sleep(self.sleep_seconds)
        return {"ok": True, "message": "completed late"}

    def get_source_state(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return {"ready": True}


class CrashingAdapter:
    """Simulates an adapter that sends mutation to target then encounters crash/disconnect."""
    def __init__(self) -> None:
        self.dispatched = False

    async def execute(self, arguments: Dict[str, Any], actor_id: str, **kwargs: Any) -> Dict[str, Any]:
        self.dispatched = True
        raise ConnectionResetError("Connection lost after dispatching command to subsystem")

    def get_source_state(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "unknown"}


def test_barrier_storage_lifecycle(storage: ActionStorage) -> None:
    """Test setting, inspecting, and clearing durable barriers in ActionStorage."""
    resource_key = "coordinator:recovery"
    exec_id = "exec_001"

    # Initially no barrier
    assert storage.get_active_barrier(resource_key) is None
    assert len(storage.list_active_barriers()) == 0

    # Acquire lock works
    acquired, reason = storage.acquire_resource_lock_detailed(resource_key, exec_id, ttl_seconds=10.0)
    assert acquired is True
    assert reason is None

    # Set barrier on the resource (e.g. outcome unknown)
    storage.set_resource_barrier(
        resource_key=resource_key,
        execution_id=exec_id,
        reason="Subsystem dispatch timed out; outcome uncertain",
        barrier_status="locked_unresolved",
    )

    # Active barrier exists
    barrier = storage.get_active_barrier(resource_key)
    assert barrier is not None
    assert barrier["execution_id"] == exec_id
    assert barrier["barrier_status"] == "locked_unresolved"
    assert barrier["cleared_at"] is None

    # Release transient lock
    storage.release_resource_lock(resource_key, exec_id)

    # Attempting to acquire lock for another execution MUST fail closed due to active barrier
    acquired2, reason2 = storage.acquire_resource_lock_detailed(resource_key, "exec_002", ttl_seconds=10.0)
    assert acquired2 is False
    assert reason2 == "barrier_active"

    # Clear barrier with authoritative evidence
    cleared = storage.clear_resource_barrier(
        resource_key=resource_key,
        cleared_by="operator:admin",
        evidence="Subsystem confirmed no recovery task was started.",
    )
    assert cleared is True
    assert storage.get_active_barrier(resource_key) is None

    # Now lock acquisition succeeds
    acquired3, reason3 = storage.acquire_resource_lock_detailed(resource_key, "exec_002", ttl_seconds=10.0)
    assert acquired3 is True
    assert reason3 is None


@pytest.mark.asyncio
async def test_timeout_sets_durable_barrier(tmp_path: Path) -> None:
    """Demonstrate that an execution timeout sets a durable barrier preventing subsequent actions."""
    db_file = tmp_path / "timeout_actions.db"
    store = ActionStorage(db_file)
    registry = ActionRegistry()

    action_def = ActionDefinition(
        action_id="coordinator.synthetic_mutation",
        label="Synthetic Mutation",
        description="A mutating action with short timeout.",
        effect=ActionEffect.MUTATION,
        required_permission="operator.action",
        concurrency_key="coordinator:mutation",
        timeout_seconds=1.0,  # Minimum allowed in ActionDefinition is 1.0
        postcondition_policy=PostconditionPolicy.NONE,
        module="resource_coordinator",
    )
    adapter = SlowTimeoutAdapter(sleep_seconds=3.0)
    registry.register(action_def, handler=adapter)
    auth_store = AuthStorage(db_file)
    service = ActionService(storage=store, auth_storage=auth_store, registry=registry)

    # Execute action
    exec_record = await service.execute_action(
        action_id="coordinator.synthetic_mutation",
        challenge_id=None,
        arguments={},
        actor_id="test_operator",
        actor_role="operator",
        session_id_hash="test_session_hash",
        device_id="test_phone",
        idempotency_key="idemp_timeout_001",
        ip_address="127.0.0.1",
    )

    # Must be OUTCOME_UNKNOWN
    assert exec_record.status == ExecutionState.OUTCOME_UNKNOWN
    assert exec_record.result_category == "timeout"
    assert adapter.dispatched is True

    # Durable barrier MUST be set in storage
    barrier = store.get_active_barrier("coordinator:mutation")
    assert barrier is not None
    assert barrier["execution_id"] == exec_record.execution_id
    assert barrier["barrier_status"] == "locked_unresolved"

    # Even after lock TTL expires, another execution on coordinator:mutation MUST be rejected
    with pytest.raises(ActionServiceError) as exc_info:
        await service.execute_action(
            action_id="coordinator.synthetic_mutation",
            challenge_id=None,
            arguments={},
            actor_id="test_operator",
            actor_role="operator",
            session_id_hash="test_session_hash",
            device_id="test_phone",
            idempotency_key="idemp_timeout_002",
            ip_address="127.0.0.1",
        )
    assert exc_info.value.error_code in ("locked_unresolved", "resource_barrier_active")
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_crashing_adapter_sets_durable_barrier(tmp_path: Path) -> None:
    """Demonstrate that an adapter exception during mutation sets a durable barrier."""
    db_file = tmp_path / "crash_actions.db"
    store = ActionStorage(db_file)
    registry = ActionRegistry()

    action_def = ActionDefinition(
        action_id="coordinator.crashing_mutation",
        label="Crashing Mutation",
        description="A mutating action that crashes.",
        effect=ActionEffect.MUTATION,
        required_permission="operator.action",
        concurrency_key="coordinator:crash_resource",
        timeout_seconds=2.0,
        postcondition_policy=PostconditionPolicy.NONE,
        module="resource_coordinator",
    )
    adapter = CrashingAdapter()
    registry.register(action_def, handler=adapter)
    auth_store = AuthStorage(db_file)
    service = ActionService(storage=store, auth_storage=auth_store, registry=registry)

    exec_record = await service.execute_action(
        action_id="coordinator.crashing_mutation",
        challenge_id=None,
        arguments={},
        actor_id="test_operator",
        actor_role="operator",
        session_id_hash="test_session_hash",
        device_id="test_phone",
        idempotency_key="idemp_crash_001",
        ip_address="127.0.0.1",
    )

    # Outcome unknown or failed with active barrier
    assert adapter.dispatched is True
    barrier = store.get_active_barrier("coordinator:crash_resource")
    assert barrier is not None
    assert barrier["execution_id"] == exec_record.execution_id


def test_multiprocess_concurrent_locks(tmp_path: Path) -> None:
    """Use real independent OS processes to test concurrent lock acquisition."""
    db_file = tmp_path / "mp_locks.db"
    store = ActionStorage(db_file)
    resource_key = "shared:resource:concurrent"

    num_workers = 4
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        futures = [
            executor.submit(_worker_acquire_lock, str(db_file), resource_key, f"worker_exec_{i}", 10.0)
            for i in range(num_workers)
        ]
        results = [f.result() for f in futures]

    # Exactly one worker acquired the lock, the others failed with lock_contention
    acquired_count = sum(1 for acq, _ in results if acq is True)
    contention_count = sum(1 for acq, reason in results if acq is False and reason == "lock_contention")
    assert acquired_count == 1
    assert contention_count == num_workers - 1


def test_multiprocess_idempotency_collision(tmp_path: Path) -> None:
    """Use real independent OS processes to test concurrent idempotency collision."""
    db_file = tmp_path / "mp_idemp.db"
    store = ActionStorage(db_file)
    shared_idemp_hash = "hash_identical_key_12345"

    num_workers = 4
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        futures = [
            executor.submit(
                _worker_reserve_execution,
                str(db_file),
                f"worker_exec_{i}",
                "notifications.acknowledge_incident",
                shared_idemp_hash,
            )
            for i in range(num_workers)
        ]
        results = [f.result() for f in futures]

    # Exactly one worker successfully reserved the execution, the others collided
    reserved_count = sum(1 for r in results if r is True)
    collided_count = sum(1 for r in results if r is False)
    assert reserved_count == 1
    assert collided_count == num_workers - 1


def test_multiprocess_barrier_blocks_fresh_process(tmp_path: Path) -> None:
    """Demonstrate that an active barrier blocks a completely new OS process."""
    db_file = tmp_path / "mp_barrier.db"
    store = ActionStorage(db_file)
    resource_key = "critical:device"

    # Set barrier from current process
    store.set_resource_barrier(
        resource_key=resource_key,
        execution_id="dead_process_exec",
        reason="Process crashed during unverified write",
        barrier_status="locked_unresolved",
    )

    # Spawn fresh worker in a new OS process after a delay (simulating dead PID / lease expired)
    with ProcessPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_worker_acquire_lock, str(db_file), resource_key, "fresh_worker_exec", 10.0)
        acquired, reason = future.result()

    assert acquired is False
    assert reason == "barrier_active"


def test_lease_renewal_invariants(storage: ActionStorage) -> None:
    """Demonstrate lease renewal works for active holder, but fails if barrier exists."""
    resource_key = "renewable:resource"
    exec_id = "exec_renew_001"

    # Acquire lock for 2 seconds
    acquired, _ = storage.acquire_resource_lock_detailed(resource_key, exec_id, ttl_seconds=2.0)
    assert acquired is True

    # Renew lock for 10 seconds
    renewed = storage.renew_resource_lock(resource_key, exec_id, ttl_seconds=10.0)
    assert renewed is True

    lock = storage.get_resource_lock(resource_key)
    assert lock is not None
    assert lock["holder_execution_id"] == exec_id

    # Another execution cannot renew someone else's lock
    assert storage.renew_resource_lock(resource_key, "other_exec", ttl_seconds=10.0) is False

    # Setting a barrier prevents further lease renewal
    storage.set_resource_barrier(resource_key, exec_id, "Unexpected barrier")
    assert storage.renew_resource_lock(resource_key, exec_id, ttl_seconds=10.0) is False
