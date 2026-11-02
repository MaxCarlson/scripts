"""Unit tests for Harbor trial status evaluation and ErrorPolicy categorization."""

from __future__ import annotations

from agent_benchmark.harbor.models import (
    AgentInfo,
    ExceptionInfo,
    FailureCause,
    HarborTrialResult,
    VerifierResult,
    classify_exception_type,
    evaluate_trial_status,
)


def _make_trial(
    *,
    rewards: dict[str, float | int] | None = None,
    exception_type: str | None = None,
    exception_msg: str = "Test exception",
) -> HarborTrialResult:
    exc = (
        ExceptionInfo(
            exception_type=exception_type,
            exception_message=exception_msg,
        )
        if exception_type
        else None
    )
    v_res = VerifierResult(rewards=rewards) if rewards is not None else None
    return HarborTrialResult(
        id="00000000-0000-0000-0000-000000000001",
        task_name="test-task",
        trial_name="test-task__oracle",
        agent_info=AgentInfo(name="oracle", version="1.0.0"),
        verifier_result=v_res,
        exception_info=exc,
    )


def test_classify_exception_type():
    assert classify_exception_type("AgentTimeoutError") == FailureCause.AGENT_EXHAUSTED_BUDGET
    assert classify_exception_type("SandboxBuildFailedError") == FailureCause.SANDBOX_FAILED
    assert classify_exception_type("RateLimitError") == FailureCause.MODEL_PROVIDER_FAILED
    assert classify_exception_type("RewardFileNotFoundError") == FailureCause.VERIFIER_FAILED
    assert classify_exception_type("CancelledError") == FailureCause.CANCELLED
    assert classify_exception_type("UnknownCustomError") == FailureCause.UNCLASSIFIED


def test_evaluate_status_passing():
    trial = _make_trial(rewards={"reward": 1.0})
    res = evaluate_trial_status(trial)
    assert res.canonical_status == "passed"
    assert res.points_awarded == 1.0
    assert res.primary_reward == 1.0
    assert res.failure_cause is None


def test_evaluate_status_failing():
    trial = _make_trial(rewards={"reward": 0.0})
    res = evaluate_trial_status(trial)
    assert res.canonical_status == "failed"
    assert res.points_awarded == 0.0
    assert res.primary_reward == 0.0
    assert res.failure_cause is None


def test_evaluate_status_budget_timeout():
    trial = _make_trial(exception_type="AgentTimeoutError")
    res = evaluate_trial_status(trial)
    assert res.canonical_status == "timed_out"
    assert res.points_awarded == 0.0
    assert res.failure_cause == "agent_exhausted_budget"


def test_evaluate_status_agent_refusal():
    trial = _make_trial(exception_type="AgentSafetyRefusalError")
    res = evaluate_trial_status(trial)
    assert res.canonical_status == "failed"
    assert res.points_awarded == 0.0
    assert res.failure_cause == "agent_refused_task"


def test_evaluate_status_sandbox_failure():
    trial = _make_trial(exception_type="SandboxBuildFailedError")
    res = evaluate_trial_status(trial)
    assert res.canonical_status == "infrastructure_error"
    assert res.points_awarded is None  # Unavailable!
    assert res.failure_cause == "sandbox_failed"


def test_evaluate_status_missing_verifier():
    trial = _make_trial(rewards=None)
    res = evaluate_trial_status(trial)
    assert res.canonical_status == "infrastructure_error"
    assert res.points_awarded is None


def test_evaluate_status_nan_reward():
    trial = _make_trial(rewards={"reward": float("nan")})
    res = evaluate_trial_status(trial)
    assert res.canonical_status == "infrastructure_error"
    assert res.points_awarded is None
    assert res.primary_reward is None
    assert "non-finite" in res.diagnostics.lower()


def test_evaluate_status_inf_reward():
    trial = _make_trial(rewards={"reward": float("inf")})
    res = evaluate_trial_status(trial)
    assert res.canonical_status == "infrastructure_error"
    assert res.points_awarded is None
    assert res.primary_reward is None
    assert "non-finite" in res.diagnostics.lower()


def test_evaluate_status_contradictory_verifier_and_terminal_error():
    # Stale or partial verifier output must NEVER override a terminal infrastructure failure
    trial = _make_trial(
        rewards={"reward": 1.0},
        exception_type="SandboxBuildFailedError",
        exception_msg="Container exited abruptly",
    )
    res = evaluate_trial_status(trial)
    assert res.canonical_status == "infrastructure_error"
    assert res.points_awarded is None
    assert res.failure_cause == "sandbox_failed"


def test_evaluate_status_multi_reward_with_authoritative_key():
    trial = _make_trial(rewards={"aux_metric": 0.5, "reward": 1.0})
    res = evaluate_trial_status(trial)
    assert res.canonical_status == "passed"
    assert res.points_awarded == 1.0
    assert res.primary_reward == 1.0


def test_evaluate_status_multi_reward_without_authoritative_key():
    # If no authoritative key ("reward", "score", "acc") exists, reject arbitrary averaging
    trial = _make_trial(rewards={"metric_a": 1.0, "metric_b": 0.0})
    res = evaluate_trial_status(trial)
    assert res.canonical_status == "infrastructure_error"
    assert res.points_awarded is None
    assert "authoritative" in res.diagnostics.lower()


def test_evaluate_status_fractional_reward_binary_policy():
    # For binary benchmarks, fractional reward is an unverified / unsuccessful attempt (0 points)
    trial = _make_trial(rewards={"reward": 0.75})
    res = evaluate_trial_status(trial)
    assert res.canonical_status == "failed"
    assert res.points_awarded == 0.0
    assert res.primary_reward == 0.75

