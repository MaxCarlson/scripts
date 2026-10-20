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
    def locked(path, **kwargs):
        raise PermissionError("locked")
    monkeypatch.setattr("agent_benchmark.lifecycle.shutil.rmtree", locked)
    assert not cleanup_workspace(evidence.workspace, evidence.termination, attempts=1).removed
    assert trial.status == "passed"
    assert convert(evidence, tmp_path).status == "passed"


def test_scope_audit_in_details_and_timed_out_precedence(tmp_path):
    from agent_benchmark.evidence import MutationEvent, ScopeAudit
    evidence = attempt(tmp_path, Worker())
    audit = ScopeAudit(
        snapshot_violations=(),
        transcript_violations=("C:/temp/outside.py",),
        all_violations=("C:/temp/outside.py",),
        mutated_paths=("C:/temp/outside.py", "grep.py"),
        mutation_events=(
            MutationEvent("write", "C:/temp/outside.py", "C:/temp/outside.py", False, False, "completed", "m1", "c1"),
        ),
        unverifiable_operations=(),
    )
    with_audit = replace(evidence, scope_violations=audit.all_violations, scope_audit=audit, task_budget_expired=True)
    trial = convert(with_audit, tmp_path)
    assert trial.status == "timed_out"
    assert trial.metrics["agent.scope_violations"].value == 1
    assert trial.metrics["agent.worker_first_pass"].value == 0
    assert trial.details["scope_violations"] == ["C:/temp/outside.py"]
    assert trial.details["scope_audit"]["transcript_violations"] == ["C:/temp/outside.py"]



@pytest.mark.parametrize("budget_expired, code, expected", [
    (False, None, "unscored"), (True, None, "timed_out"),
    (False, "def grep(*args, **kwargs): return []\n", "failed"),
])
def test_opaque_operations_never_imply_scope_compliance(tmp_path, budget_expired, code, expected):
    worker = Worker() if code is None else Worker(code)
    worker.last_history = [{
        "info": {"id": "assistant-1", "sessionID": "session-1", "role": "assistant", "parentID": "user-1"},
        "parts": [{"type": "tool", "callID": "call-shell", "tool": "bash", "state": {
            "status": "completed", "input": {"command": "python -B public_check.py"},
            "output": "ok", "time": {"start": 1, "end": 2},
        }}],
    }]
    evidence = replace(attempt(tmp_path, worker), task_budget_expired=budget_expired)
    trial = convert(evidence, tmp_path)
    assert trial.status == expected
    assert trial.metrics["agent.scope_compliance"].quality == "unavailable"
    assert trial.details["scope_audit"]["compliance"] == "uncertain"
    assert trial.metrics["agent.worker_first_pass"].value != 1
    if expected == "unscored":
        assert trial.metrics["agent.worker_first_pass"].value is None



def test_structured_completion_report_is_not_an_opaque_filesystem_operation(tmp_path):
    worker = Worker()
    worker.last_history[0]["parts"].append({
        "type": "tool", "tool": "StructuredOutput", "callID": "report-1",
        "state": {"status": "completed", "input": {"outcome": "completed", "changed_paths": ["grep.py"]},
                  "output": "Structured output accepted", "time": {"start": 1, "end": 2}},
    })
    trial = convert(attempt(tmp_path, worker), tmp_path)
    assert trial.status == "passed"
    assert trial.metrics["agent.scope_compliance"].value == 1
    assert not trial.details["scope_audit"]["unverifiable_operations"]


def test_missing_scope_audit_cannot_be_scored_full_success(tmp_path):
    trial = convert(replace(attempt(tmp_path, Worker()), scope_audit=None), tmp_path)
    assert trial.status == "unscored"
    assert trial.metrics["agent.scope_compliance"].value is None


def test_artifact_and_execution_judgments_preserve_opaque_shell_uncertainty(tmp_path):
    from agent_benchmark.evidence import UnverifiableOperation
    evidence = attempt(tmp_path, Worker())
    opaque = replace(evidence.scope_audit, unverifiable_operations=(
        UnverifiableOperation("bash", "opaque", "m1", "c1", {}),))
    trial = convert(replace(evidence, scope_audit=opaque), tmp_path)
    assert trial.status == "unscored"
    assert trial.details["judgments"] == {"functional": "passed", "artifact": "passed",
        "execution": "unknown", "budget": "passed", "termination": "passed"}
    assert trial.metrics["agent.artifact_compliance"].value == 1
    assert trial.metrics["agent.execution_compliance"].value is None
    assert trial.metrics["agent.scope_compliance"].value is None


def test_artifact_violation_and_execution_violation_are_distinct(tmp_path):
    evidence = attempt(tmp_path, Worker(extra=True))
    trial = convert(evidence, tmp_path)
    assert trial.details["judgments"]["artifact"] == "failed"
    assert trial.metrics["agent.scope_compliance"].value == 0


def test_cli_artifact_without_execution_history_remains_unscored(tmp_path, monkeypatch):
    import asyncio
    from agent_benchmark.attempt import run_cli_attempt
    from agent_benchmark.evidence import load_task
    from agent_benchmark.lifecycle import DispatchGuard

    monkeypatch.setattr("agent_benchmark.attempt.shutil.which", lambda name: "codex.exe")

    async def runner(command, workspace):
        (workspace / "grep.py").write_text(GOOD, encoding="utf-8")
        return 0, "complete", ""

    evidence = asyncio.run(run_cli_attempt(load_task(TASK), DispatchGuard(), workspace_root=tmp_path / "workers",
        evidence_dir=tmp_path / "cli-evidence", provider="codex", model="test-model", cli_runner=runner))
    trial = convert(evidence, tmp_path)
    assert trial.status == "unscored"
    assert trial.details["judgments"]["functional"] == "passed"
    assert trial.details["judgments"]["artifact"] == "passed"
    assert trial.details["judgments"]["execution"] == "unknown"


def test_inconsistent_scope_sets_cannot_produce_strict_pass(tmp_path):
    evidence = attempt(tmp_path, Worker())
    malformed = replace(evidence.scope_audit, all_violations=("forbidden.txt",),
                        snapshot_violations=(), transcript_violations=())
    trial = convert(replace(evidence, scope_audit=malformed, scope_violations=("forbidden.txt",)), tmp_path)
    assert trial.status == "infrastructure_error"
    assert trial.details["judgments"]["artifact"] == "unknown"
    assert trial.details["judgments"]["execution"] == "unknown"
    assert trial.metrics["agent.scope_compliance"].value is None
    assert "disagree" in trial.details["evidence_diagnostic"]
