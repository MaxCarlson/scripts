"""Unit tests for Harbor trial status evaluation and ErrorPolicy categorization."""

from __future__ import annotations

from pathlib import Path

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



def test_evaluate_status_nonzero_agent_exit_code_passing_verifier():
    trial = _make_trial(
        rewards={"reward": 1.0},
        exception_type="NonZeroAgentExitCodeError",
        exception_msg="Command failed (exit 1): EPIPE: broken pipe",
    )
    res = evaluate_trial_status(trial)
    assert res.canonical_status == "passed"
    assert res.points_awarded == 1.0
    assert res.primary_reward == 1.0
    assert res.failure_cause is None


def test_evaluate_status_nonzero_agent_exit_code_failing_verifier():
    trial = _make_trial(
        rewards={"reward": 0.0},
        exception_type="NonZeroAgentExitCodeError",
        exception_msg="Command failed (exit 1)",
    )
    res = evaluate_trial_status(trial)
    assert res.canonical_status == "failed"
    assert res.points_awarded == 0.0
    assert res.primary_reward == 0.0
    assert res.failure_cause == "agent_failed"


def test_broken_agent_output_pipe_is_infrastructure_invalid_despite_failing_verifier():
    trial = _make_trial(
        rewards={"reward": 0.0}, exception_type="NonZeroAgentExitCodeError",
        exception_msg="Command failed (exit 1): opencode ...\nstdout: error: EPIPE: broken pipe, write\nstderr: None",
    )
    result = evaluate_trial_status(trial)
    assert result.canonical_status == "infrastructure_error"
    assert result.points_awarded is None


def test_broken_pipe_mentioned_only_in_prompt_is_not_an_agent_pipe_error():
    trial = _make_trial(
        rewards={"reward": 0.0}, exception_type="NonZeroAgentExitCodeError",
        exception_msg="prompt: EPIPE broken pipe\nstdout: ordinary agent output\nstderr: None",
    )
    assert evaluate_trial_status(trial).canonical_status == "failed"


def test_evaluate_status_nonzero_agent_exit_code_missing_verifier():
    trial = _make_trial(
        rewards=None,
        exception_type="NonZeroAgentExitCodeError",
        exception_msg="Command failed (exit 1)",
    )
    res = evaluate_trial_status(trial)
    assert res.canonical_status == "failed"
    assert res.points_awarded == 0.0
    assert res.primary_reward == 0.0
    assert res.failure_cause == "agent_failed"


def test_evaluate_status_endpoint_404_failure_classified_as_infrastructure_error():
    # Matches the observed OpenCode 404 failure pattern on /v1/responses
    trial = _make_trial(
        rewards={"reward": 0.0},
        exception_type="NonZeroAgentExitCodeError",
        exception_msg=(
            'Command failed (exit 1): opencode --model=openai/qwen38_23GB run ...\n'
            '{"name":"APIError","data":{"message":"Not Found: {\\"detail\\":\\"Not Found\\"}","statusCode":404},'
            '"metadata":{"url":"http://host.docker.internal:8788/v1/responses"}}'
        ),
    )
    res = evaluate_trial_status(trial)
    assert res.canonical_status == "infrastructure_error"
    assert res.points_awarded is None
    assert res.primary_reward is None
    assert res.failure_cause == "model_provider_failed"
    assert "404 Not Found" in res.diagnostics
    assert "original verifier reward: 0.0" in res.diagnostics


def test_evaluate_status_connection_refused_classified_as_infrastructure_error():
    trial = _make_trial(
        rewards={"reward": 0.0},
        exception_type="NonZeroAgentExitCodeError",
        exception_msg="Command failed (exit 1): connect ECONNREFUSED 127.0.0.1:1234",
    )
    res = evaluate_trial_status(trial)
    assert res.canonical_status == "infrastructure_error"
    assert res.points_awarded is None
    assert res.failure_cause == "model_provider_failed"


def test_evaluate_status_endpoint_failure_via_trial_dir_log(tmp_path: Path):
    trial = _make_trial(
        rewards={"reward": 0.0},
        exception_type="NonZeroAgentExitCodeError",
        exception_msg="Command failed (exit 1)",
    )
    # Put 404 in trial log directory
    trial_dir = tmp_path / "trial_run"
    agent_log_dir = trial_dir / "agent"
    agent_log_dir.mkdir(parents=True)
    (agent_log_dir / "opencode.txt").write_text(
        'APIError: Not Found (statusCode": 404)',
        encoding="utf-8",
    )
    res = evaluate_trial_status(trial, trial_dir=trial_dir)
    assert res.canonical_status == "infrastructure_error"
    assert res.failure_cause == "model_provider_failed"
