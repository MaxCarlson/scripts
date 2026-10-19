"""Tests for scoring and reporting redesign, telemetry extraction, and budget profiles."""

import json
from pathlib import Path
from dataclasses import replace

from agent_benchmark.cli import main
from agent_benchmark.attempt import extract_telemetry
from agent_benchmark.evidence import (
    ScopeAudit,
    UnverifiableOperation,
    classify_shell_command,
)
from agent_benchmark.results import trial_from_attempt
from agent_benchmark.runner import BUDGET_PROFILES


TASK_DIR = Path(__file__).resolve().parents[1] / "agent_benchmark/tasks/py-grep-smoke"


def test_classify_shell_command():
    # Read-only inspection
    cat, reason = classify_shell_command("Get-ChildItem -Force | Select-Object Name, Length")
    assert cat == "read_only_inspection"
    assert "Read-only" in reason

    cat, _ = classify_shell_command("ls | Select Name")
    assert cat == "read_only_inspection"

    cat, _ = classify_shell_command("dir")
    assert cat == "read_only_inspection"

    cat, _ = classify_shell_command("git status")
    assert cat == "read_only_inspection"

    # Redirection prevents read-only classification
    cat, _ = classify_shell_command("Get-ChildItem > files.txt")
    assert cat == "arbitrary_execution"

    cat, _ = classify_shell_command("Get-ChildItem | Out-File files.txt")
    assert cat == "arbitrary_execution"

    # Trusted probe command
    cat, reason = classify_shell_command(
        "$env:TEMP = '...'; & '...\\python.exe' -I -B .\\temp_probe.py"
    )
    assert cat == "trusted_probe"
    assert "Trusted benchmark probe" in reason

    # Worker test script execution (unverifiable shell)
    cat, _ = classify_shell_command(
        "$env:TEMP = '...'; & '...\\python.exe' -I -B .\\.agent-bench-scratch\\sanity_grep.py"
    )
    assert cat == "arbitrary_execution"

    # None / empty / arbitrary
    assert classify_shell_command(None)[0] == "arbitrary_execution"
    assert classify_shell_command("")[0] == "arbitrary_execution"
    assert classify_shell_command("rm -rf file")[0] == "arbitrary_execution"


def test_unverifiable_operation_category_in_audit_dict():
    op = UnverifiableOperation(
        tool="bash",
        reason="Read-only inspection command without redirection",
        message_id="msg-1",
        call_id="call-1",
        input_summary={"command": "Get-ChildItem"},
        category="read_only_inspection",
    )
    assert op.category == "read_only_inspection"

    audit = ScopeAudit(
        snapshot_violations=(),
        transcript_violations=(),
        all_violations=(),
        mutated_paths=("grep.py",),
        mutation_events=(),
        unverifiable_operations=(op,),
    )
    # Scope compliance MUST remain uncertain when unverifiable operations exist
    assert audit.compliance == "uncertain"
    d = audit.to_dict()
    assert d["compliance"] == "uncertain"
    assert d["unverifiable_operations"][0]["category"] == "read_only_inspection"


def test_extract_telemetry_from_session_and_history():
    session = {
        "tokens": {
            "input": 112871,
            "output": 2477,
            "reasoning": 1368,
        }
    }
    history = [
        {"info": {"role": "user", "id": "m0"}, "parts": [{"type": "text", "text": "start"}]},
        {
            "info": {"role": "assistant", "id": "m1", "tokens": {"input": 8192, "output": 100}},
            "parts": [
                {"type": "tool", "tool": "read", "callID": "c1", "state": {"status": "completed"}},
                {"type": "tool", "tool": "bash", "callID": "c2", "state": {"status": "completed", "metadata": {"exit": 0}}},
            ],
        },
        {
            "info": {"role": "assistant", "id": "m2", "tokens": {"input": 13791, "output": 200}},
            "parts": [
                {"type": "tool", "tool": "bash", "callID": "c3", "state": {"status": "completed", "metadata": {"exit": 1}}},
                {"type": "tool", "tool": "edit", "callID": "c4", "state": {"status": "completed"}},
            ],
        },
    ]

    tokens_data, tools_data = extract_telemetry(session, history)
    assert tokens_data["input"] == 112871
    assert tokens_data["output"] == 2477
    assert tokens_data["reasoning"] == 1368
    assert tokens_data["initial_prompt"] == 8192
    assert tokens_data["peak_context"] == 13791

    assert tools_data["total_calls"] == 4
    assert tools_data["total_failures"] == 1
    assert tools_data["tool_counts"] == {"read": 1, "bash": 2, "edit": 1}


def test_trial_from_attempt_with_telemetry_and_scoring_dimensions(tmp_path):
    from attempt_test import Worker, attempt

    worker = Worker()
    ev = attempt(tmp_path, worker)

    session_tokens = {
        "input": 112871,
        "output": 2477,
        "reasoning": 1368,
        "initial_prompt": 8192,
        "peak_context": 13791,
    }
    tool_telemetry = {
        "total_calls": 13,
        "total_failures": 1,
        "tool_counts": {"read": 4, "bash": 4, "edit": 3, "write": 2},
    }

    # Case A: Timed out but functionally passed
    ev_timeout = replace(
        ev,
        task_budget_expired=True,
        session_tokens=session_tokens,
        tool_telemetry=tool_telemetry,
    )
    trial_timeout = trial_from_attempt(
        ev_timeout, run_id="r1", trial_id="t1", task_id="py-grep-smoke",
        variant_id="model", repetition=1, evidence_path="evidence/t1",
    )
    assert trial_timeout.status == "timed_out"
    assert trial_timeout.metrics["agent.worker_first_pass"].value == 0
    # Multi-dimensional scoring preserves functional achievement
    assert trial_timeout.metrics["agent.functional_pass"].value == 1
    assert trial_timeout.metrics["agent.budget_pass"].value == 0
    assert trial_timeout.metrics["agent.clean_termination"].value == 1
    assert trial_timeout.metrics["tokens.worker.input"].value == 112871
    assert trial_timeout.metrics["tokens.worker.input"].quality == "measured"
    assert trial_timeout.metrics["tokens.worker.output"].value == 2477
    assert trial_timeout.metrics["tokens.worker.reasoning"].value == 1368
    assert trial_timeout.metrics["tokens.worker.peak_context"].value == 13791
    assert trial_timeout.metrics["tokens.worker.initial_prompt"].value == 8192
    assert trial_timeout.metrics["tools.calls"].value == 13
    assert trial_timeout.metrics["tools.failures"].value == 1
    assert trial_timeout.details["turn_completion"] == "aborted_at_budget"

    # Case B: Completed within budget and passed
    ev_pass = replace(
        ev,
        task_budget_expired=False,
        session_tokens=session_tokens,
        tool_telemetry=tool_telemetry,
    )
    trial_pass = trial_from_attempt(
        ev_pass, run_id="r1", trial_id="t1", task_id="py-grep-smoke",
        variant_id="model", repetition=1, evidence_path="evidence/t1",
    )
    assert trial_pass.status == "passed"
    assert trial_pass.metrics["agent.worker_first_pass"].value == 1
    assert trial_pass.metrics["agent.functional_pass"].value == 1
    assert trial_pass.metrics["agent.budget_pass"].value == 1
    assert trial_pass.details["turn_completion"] == "completed"


def test_trial_from_attempt_backward_compatibility_when_no_telemetry(tmp_path):
    from attempt_test import Worker, attempt

    worker = Worker()
    ev = attempt(tmp_path, worker)
    # Ensure session_tokens and tool_telemetry are None
    ev = replace(ev, session_tokens=None, tool_telemetry=None)

    trial = trial_from_attempt(
        ev, run_id="r1", trial_id="t1", task_id="py-grep-smoke",
        variant_id="model", repetition=1, evidence_path="evidence/t1",
    )
    assert trial.status == "passed"
    assert trial.metrics["tokens.worker.input"].quality == "unavailable"
    assert trial.metrics["tokens.worker.output"].quality == "unavailable"
    assert trial.metrics["tools.calls"].quality == "unavailable"
    assert trial.metrics["agent.functional_pass"].value == 1
    assert trial.metrics["agent.budget_pass"].value == 1


def test_budget_profiles():
    assert "canonical-60s" in BUDGET_PROFILES
    assert BUDGET_PROFILES["canonical-60s"]["task_seconds"] == 60.0
    assert BUDGET_PROFILES["canonical-60s"]["grace_seconds"] == 10.0
    assert BUDGET_PROFILES["canonical-60s"]["comparison_eligible"] is True

    for p in ("extended-90s", "extended-120s", "extended-180s"):
        assert p in BUDGET_PROFILES
        assert BUDGET_PROFILES[p]["task_seconds"] in (90.0, 120.0, 180.0)
        assert BUDGET_PROFILES[p]["comparison_eligible"] is False


def test_plan_cli_outputs_budget_profile_info(capsys):
    rc = main(["plan", "--budget-profile", "extended-90s"])
    assert rc == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["budget_profile"] == "extended-90s"
    assert "canonical-60s" in payload["budget_profiles"]
    assert payload["budget_profiles"]["canonical-60s"]["comparison_eligible"] is True
    assert payload["budget_profiles"]["extended-90s"]["comparison_eligible"] is False
