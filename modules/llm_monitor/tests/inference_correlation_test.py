from __future__ import annotations

import pytest

from llm_monitor.inference_correlation import (
    ExecutionCredentialRegistry,
    ExecutionContext,
)


def test_execution_context_round_trip_is_bounded_and_token_free():
    context = ExecutionContext(run_id="run-1", task_id="task-1", execution_id="exec-1")
    restored = ExecutionContext.from_dict(context.to_dict())
    assert restored == context
    assert "token" not in context.to_dict()


def test_registry_associates_multiple_requests_and_reconciles_trial():
    registry = ExecutionCredentialRegistry()
    context, token = registry.register(
        "run-1", "task-1", "exec-1", repetition_id="rep-1", variant_id="variant-1"
    )
    assert registry.verify_and_record(token, "request-1") == context
    assert registry.verify_and_record(token, "request-2") == context
    registry.complete("exec-1", "trial-1")
    result = registry.requests("exec-1")
    assert result["request_ids"] == ["request-1", "request-2"]
    assert result["trial_id"] == "trial-1"
    assert result["context"]["repetition_id"] == "rep-1"
    assert result["context"]["variant_id"] == "variant-1"
    assert result["verification_status"] == "verified"


def test_registry_rejects_duplicate_ids_bad_tokens_and_closed_execution():
    registry = ExecutionCredentialRegistry()
    _, token = registry.register("run-1", "task-1", "exec-1")
    with pytest.raises(ValueError):
        registry.register("run-1", "task-1", "exec-1")
    assert registry.verify_and_record("forged", "request-1") is None
    registry.complete("exec-1", "trial-1")
    assert registry.verify_and_record(token, "request-2") is None


def test_registry_rejects_expired_token_and_marks_evidence_incomplete():
    now = [10.0]
    registry = ExecutionCredentialRegistry(ttl_seconds=2, clock=lambda: now[0])
    _, token = registry.register("run-1", "task-1", "exec-1")
    now[0] = 13.0
    assert registry.verify_and_record(token, "request-late") is None
    assert registry.requests("exec-1")["verification_status"] == "incomplete"


def test_overlapping_attempts_with_same_task_name_cannot_exchange_requests():
    registry = ExecutionCredentialRegistry()
    first, first_token = registry.register("run-1", "same-task", "exec-a")
    second, second_token = registry.register("run-1", "same-task", "exec-b")
    assert registry.verify_and_record(first_token, "request-a") == first
    assert registry.verify_and_record(second_token, "request-b") == second
    assert registry.requests("exec-a")["request_ids"] == ["request-a"]
    assert registry.requests("exec-b")["request_ids"] == ["request-b"]
    assert registry.verify_and_record(first_token, "request-b") == first


def test_context_rejects_unbounded_or_malformed_identifiers():
    with pytest.raises(ValueError):
        ExecutionContext(run_id="x" * 257, task_id="task", execution_id="exec")
    with pytest.raises(ValueError):
        ExecutionContext(run_id="run", task_id="task", execution_id="bad value")
