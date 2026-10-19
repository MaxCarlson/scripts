"""Canonical scoring must preserve frozen first-attempt evidence."""

from dataclasses import replace

import pytest
from benchmark_core import MetricValue, TrialResult, append_result, load_trials

from attempt_test import GOOD, TASK, Worker, attempt
from agent_benchmark.evidence import capture, verify
from agent_benchmark.results import trial_from_attempt


def convert(evidence, tmp_path):
    return trial_from_attempt(evidence, run_id="run-1", trial_id="trial-1", task_id="py-grep-smoke",
                              variant_id="model-1", repetition=1, evidence_path="evidence/trial-1")


def test_canonical_failed_s1_stays_failed_after_s3_repair_and_reload(tmp_path):
    evidence = attempt(tmp_path, Worker("def grep(*args, **kwargs): return []\n"))
    trial = convert(evidence, tmp_path)
    append_result(tmp_path / "reports", trial)
    (evidence.workspace.path / "grep.py").write_text(GOOD, encoding="utf-8")
    s3 = capture(evidence.workspace.path, tmp_path / "S3")
    assert verify(s3, TASK / "verifier/check.py", tmp_path / "verify3").status == "passed"
    reloaded = load_trials(tmp_path / "reports/trials.jsonl")[0]
    assert isinstance(trial, TrialResult)
    assert reloaded.status == trial.status == "failed"
    assert reloaded.metrics["agent.worker_first_pass"].value == 0
    assert reloaded.details["checkpoints"]["S1"]["tree_hash"] == evidence.s1.tree_hash
    assert reloaded.metrics["agent.workflow_final_pass"].quality == "unavailable"


@pytest.mark.parametrize("override, expected", [
    ({"task_budget_expired": True}, "timed_out"),
    ({"execution_error": "TransportFailure"}, "infrastructure_error"),
    ({"scope_violations": ("protected.txt",)}, "failed"),
])
def test_verifier_pass_cannot_override_disqualifying_attempt_facts(tmp_path, override, expected):
    evidence = attempt(tmp_path, Worker())
    assert evidence.verification.status == "passed"
    trial = convert(replace(evidence, **override), tmp_path)
    assert trial.status == expected
    assert trial.metrics["agent.worker_first_pass"].value != 1


def test_unresolved_and_abnormal_runtime_completion_cannot_pass(tmp_path):
    evidence = attempt(tmp_path, Worker())
    unresolved = replace(evidence.termination, confirmed=False)
    assert convert(replace(evidence, termination=unresolved), tmp_path).status == "infrastructure_error"
    abnormal = replace(evidence.termination.last_observation, job_status="failed")
    assert convert(replace(evidence, termination=replace(evidence.termination, last_observation=abnormal)), tmp_path).status == "infrastructure_error"


def test_unavailable_tokens_are_not_zero_and_cleanup_cannot_rewrite_score(tmp_path, monkeypatch):
    from agent_benchmark.lifecycle import cleanup_workspace
    evidence = attempt(tmp_path, Worker())
    trial = convert(evidence, tmp_path)
    assert isinstance(trial.metrics["tokens.worker.input"], MetricValue)
    assert trial.metrics["tokens.worker.input"].value is None
    assert trial.metrics["tokens.worker.input"].quality == "unavailable"
    def locked(path):
        raise PermissionError("locked")
    monkeypatch.setattr("agent_benchmark.lifecycle.shutil.rmtree", locked)
    assert not cleanup_workspace(evidence.workspace, evidence.termination, attempts=1).removed
    assert trial.status == "passed"
    assert convert(evidence, tmp_path).status == "passed"
