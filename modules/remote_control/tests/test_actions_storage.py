"""Tests for Stage B: Durable action and confirmation storage."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from remote_control.actions.models import (
    ActionExecutionRecord,
    ConfirmationChallenge,
    ExecutionState,
)
from remote_control.actions.storage import ActionStorage
from remote_control.auth.storage import AuthStorage


def test_additive_schema_migration(tmp_path: Path) -> None:
    """ActionStorage additively migrates auth.db preserving existing tables."""
    db_file = tmp_path / "auth.db"

    # 1. Initialize AuthStorage (v1)
    auth_store = AuthStorage(db_file)
    auth_store.create_operator("op-1", "admin", "argon_hash", "JBSWY3DPEHPK3PXP")
    assert auth_store.get_operator() is not None

    # 2. Initialize ActionStorage on same database
    action_store = ActionStorage(db_file)

    # Operator row is preserved!
    assert auth_store.get_operator()["username"] == "admin"

    # Schema version updated to 3 (with additive v3 action_resource_barriers)
    with action_store._get_connection() as conn:
        ver = conn.execute("SELECT version FROM schema_version").fetchone()[0]
        assert ver == 3


def test_challenge_lifecycle_and_atomic_consumption(tmp_path: Path) -> None:
    """Challenges are persisted, atomically consumed, and reject replay or expiration."""
    action_store = ActionStorage(tmp_path / "auth.db")

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat().replace("+00:00", "Z")
    expires_iso = (now + timedelta(seconds=120)).isoformat().replace("+00:00", "Z")

    challenge = ConfirmationChallenge(
        challenge_id="chal-123",
        operator_id="op-1",
        session_id_hash="sess-hash-1",
        device_id="dev-1",
        action_id="notifications.acknowledge_incident",
        action_version="1.0.0",
        arguments_digest="digest-123",
        state_fingerprint="fp-123",
        prepared_at=now_iso,
        expires_at=expires_iso,
        status="pending",
    )

    action_store.save_challenge(challenge)

    # Retrieval
    retrieved = action_store.get_challenge("chal-123")
    assert retrieved is not None
    assert retrieved.challenge_id == "chal-123"
    assert retrieved.status == "pending"

    # Atomic consumption with exact matching credentials
    consumed = action_store.consume_challenge(
        challenge_id="chal-123",
        operator_id="op-1",
        device_id="dev-1",
        session_id_hash="sess-hash-1",
        action_id="notifications.acknowledge_incident",
        arguments_digest="digest-123",
        now_iso=now_iso,
    )
    assert consumed is True

    # Challenge is now marked 'consumed'
    assert action_store.get_challenge("chal-123").status == "consumed"

    # Second consumption attempt fails (replay protection)
    replayed = action_store.consume_challenge(
        challenge_id="chal-123",
        operator_id="op-1",
        device_id="dev-1",
        session_id_hash="sess-hash-1",
        action_id="notifications.acknowledge_incident",
        arguments_digest="digest-123",
        now_iso=now_iso,
    )
    assert replayed is False


def test_challenge_expired_consumption_fails(tmp_path: Path) -> None:
    """Expired challenges cannot be consumed."""
    action_store = ActionStorage(tmp_path / "auth.db")

    past = datetime.now(timezone.utc) - timedelta(seconds=10)
    past_iso = past.isoformat().replace("+00:00", "Z")

    challenge = ConfirmationChallenge(
        challenge_id="chal-expired",
        operator_id="op-1",
        session_id_hash="sess-hash-1",
        device_id="dev-1",
        action_id="notifications.acknowledge_incident",
        action_version="1.0.0",
        arguments_digest="digest-123",
        state_fingerprint="fp-123",
        prepared_at=past_iso,
        expires_at=past_iso,  # Already expired
        status="pending",
    )
    action_store.save_challenge(challenge)

    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    consumed = action_store.consume_challenge(
        challenge_id="chal-expired",
        operator_id="op-1",
        device_id="dev-1",
        session_id_hash="sess-hash-1",
        action_id="notifications.acknowledge_incident",
        arguments_digest="digest-123",
        now_iso=now_iso,
    )
    assert consumed is False


def test_execution_reservation_atomic_idempotency(tmp_path: Path) -> None:
    """Execution reservation is atomic and duplicate idempotency keys return existing record."""
    action_store = ActionStorage(tmp_path / "auth.db")

    exec_record = ActionExecutionRecord(
        execution_id="exec-101",
        action_id="notifications.acknowledge_incident",
        action_version="1.0.0",
        actor_id="op-1",
        session_id_hash="sess-hash-1",
        device_id="dev-1",
        idempotency_key_hash="idem-hash-abc",
        arguments_digest="arg-digest-1",
        state_fingerprint="fp-1",
        started_at="2026-11-11T12:00:00Z",
        status=ExecutionState.RESERVED,
        summary="Awaiting dispatch",
    )

    # 1. First reservation succeeds
    created, record1 = action_store.reserve_execution(exec_record)
    assert created is True
    assert record1.execution_id == "exec-101"
    assert record1.status == ExecutionState.RESERVED

    # 2. Second reservation with same action_id and idempotency_key_hash returns existing record
    dup_record = ActionExecutionRecord(
        execution_id="exec-102",  # Different execution ID
        action_id="notifications.acknowledge_incident",
        action_version="1.0.0",
        actor_id="op-1",
        session_id_hash="sess-hash-1",
        device_id="dev-1",
        idempotency_key_hash="idem-hash-abc",  # Duplicate key!
        arguments_digest="arg-digest-1",
        state_fingerprint="fp-1",
        started_at="2026-11-11T12:00:05Z",
        status=ExecutionState.RESERVED,
        summary="Duplicate attempt",
    )

    created_dup, record2 = action_store.reserve_execution(dup_record)
    assert created_dup is False
    assert record2.execution_id == "exec-101"  # Returns original record!


def test_execution_outcome_updating_and_redaction(tmp_path: Path) -> None:
    """Execution update records outcome, bounds summary, and redacts sensitive payload details."""
    action_store = ActionStorage(tmp_path / "auth.db")

    exec_record = ActionExecutionRecord(
        execution_id="exec-update-test",
        action_id="notifications.acknowledge_incident",
        action_version="1.0.0",
        actor_id="op-1",
        session_id_hash="sess-hash-1",
        device_id="dev-1",
        idempotency_key_hash="idem-hash-upd",
        arguments_digest="arg-digest-1",
        state_fingerprint="fp-1",
        started_at="2026-11-11T12:00:00Z",
        status=ExecutionState.RESERVED,
    )
    action_store.reserve_execution(exec_record)

    details_payload = {
        "status": "succeeded",
        "api_key": "supersecretkey123",
        "output": "Incident acknowledged with Bearer secret_abc_123 successfully",
    }

    action_store.update_execution(
        execution_id="exec-update-test",
        status=ExecutionState.SUCCEEDED,
        finished_at="2026-11-11T12:00:02Z",
        result_category="success",
        postcondition_verified=True,
        summary="Acknowledged incident inc-1",
        details=details_payload,
    )

    updated = action_store.get_execution("exec-update-test")
    assert updated is not None
    assert updated.status == ExecutionState.SUCCEEDED
    assert updated.postcondition_verified is True
    assert updated.result_category == "success"

    # Bearer token and api key are redacted in stored details_json!
    assert "secret_abc_123" not in updated.details_json
    assert "supersecretkey123" not in updated.details_json
    assert "Bearer [REDACTED]" in updated.details_json
    assert "[REDACTED]" in updated.details_json
