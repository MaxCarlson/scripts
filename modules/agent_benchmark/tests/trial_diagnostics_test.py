"""Actionable trial diagnostics preserve independent outcome dimensions."""

from benchmark_core import MetricValue, TrialResult
from agent_benchmark.diagnostics import describe_trial


def trial(status, details=None, metrics=None):
    return TrialResult("run", "trial", "task", "model", 1, status, metrics or {}, details or {})


def test_code_success_with_cache_violation_explains_strict_failure():
    result = trial("failed", {
        "verifier_status": "passed", "scope_violations": ["__pycache__/grep.cpython-312.pyc"],
        "scope_audit": {"compliance": "violated", "unverifiable_operations": [{"tool": "bash"}]},
        "termination": {"confirmed": True},
    }, {"agent.budget_pass": MetricValue(1, "boolean", "test", "derived")})
    output = "\n".join(describe_trial(result))
    assert "code PASS | scope FAIL | budget PASS | termination CONFIRMED" in output
    assert "__pycache__/grep.cpython-312.pyc" in output
    assert "python -B" in output
    assert "1 operation" in output


def test_uncertain_scope_does_not_claim_functional_failure():
    output = "\n".join(describe_trial(trial("unscored", {
        "verifier_status": "passed", "scope_audit": {"compliance": "uncertain",
            "unverifiable_operations": [{"tool": "bash", "reason": "Opaque execution"}]},
    }, {"agent.functional_pass": MetricValue(1, "boolean", "test", "derived")})))
    assert "code PASS | scope UNKNOWN" in output
    assert "bash: Opaque execution" in output


def test_verifier_error_and_provider_error_are_visible_and_terminal_safe():
    output = "\n".join(describe_trial(trial("infrastructure_error", {
        "verifier_status": "failed", "verifier_diagnostic": "AssertionError: wrong result",
        "worker_diagnostic": "ProviderError: context exceeded\x1b[2J", "execution_error": "transport failed",
    })))
    assert "AssertionError: wrong result" in output
    assert "ProviderError: context exceeded" in output
    assert "transport failed" in output
    assert "\x1b" not in output


def test_timeout_explains_budget_expiration_even_with_correct_code():
    output = "\n".join(describe_trial(trial("timed_out", {"verifier_status": "passed"}, {
        "agent.functional_pass": MetricValue(1, "boolean", "test", "derived")})))
    assert "code PASS" in output
    assert "observation budget expired" in output


def test_unconfirmed_verification_never_promotes_unknown_functional_metric():
    output = "\n".join(describe_trial(trial("infrastructure_error", {"verifier_status": "passed"}, {
        "agent.functional_pass": MetricValue(None, "boolean", "test", "unavailable", "Unconfirmed termination")})))
    assert "code UNKNOWN" in output
