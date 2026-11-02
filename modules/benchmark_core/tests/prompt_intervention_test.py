"""Comparison safety for declared prompt policy variants."""

import copy

from benchmark_core.conditions import declared_prompt_intervention_error
from experiment_test import _conditions


def inputs():
    baseline = _conditions(["task-a"])
    runtime = baseline["environment"]["runtime"]
    runtime.update(prompt_policy={"id": "sv0-unmodified-v1", "sha256": "a" * 64},
                   prompt_sha256="b" * 64,
                   model_settings={"context": 16384, "output": 8192, "temperature": 0.2, "top_p": 0.9,
                                   "top_k": 40, "reasoning_effort": "medium", "options_sha256": "d" * 64})
    baseline["environment"]["model_identity"] = {"runtime_model_id": "model", "quantization": "Q6"}
    intervention = copy.deepcopy(baseline)
    runtime = intervention["environment"]["runtime"]
    runtime["prompt_policy"] = {"id": "sv1-specification-verification-v1", "sha256": "c" * 64}
    runtime["prompt_sha256"] = "d" * 64
    declaration = {"schema": "declared-prompt-intervention-v1", "design_id": "pilot", "assignment": "SV0"}
    base_meta = {"prompt_intervention": declaration, "suite_fingerprint": "e" * 64}
    intervention_meta = {"prompt_intervention": {**declaration, "assignment": "SV1"},
                         "suite_fingerprint": "e" * 64}
    return baseline, intervention, base_meta, intervention_meta


def test_declared_prompt_difference_only():
    args = inputs()
    error, result = declared_prompt_intervention_error(*args)
    assert error is None
    assert result["candidate_condition"] == "SV1"


def test_other_changes_and_unknown_provenance_fail_closed():
    baseline, intervention, left, right = inputs()
    intervention["tasks"]["task-a"]["verifier_sha256"] = "f" * 64
    assert declared_prompt_intervention_error(baseline, intervention, left, right)[0]
    baseline, intervention, left, right = inputs()
    intervention["environment"]["model_identity"]["quantization"] = "unknown"
    assert declared_prompt_intervention_error(baseline, intervention, left, right)[0]
    baseline, intervention, left, right = inputs()
    right["prompt_intervention"]["assignment"] = "SV0"
    assert declared_prompt_intervention_error(baseline, intervention, left, right)[0]


def test_compare_runs_applies_declared_prompt_intervention():
    from benchmark_core.compare import compare_runs
    from benchmark_core.models import RunInfo, TrialResult, TrialStatus
    from benchmark_core.stats import summarize

    baseline, intervention, left, right = inputs()
    left["comparison_contract"] = baseline
    right["comparison_contract"] = intervention
    base = RunInfo("base", "2026-01-01T00:00:00Z", "suite", "1", ["task-a"], {"worker": {}}, 1, "score",
                   metadata=left)
    candidate = RunInfo("candidate", "2026-01-01T00:00:00Z", "suite", "1", ["task-a"], {"worker": {}}, 1,
                        "score", metadata=right)
    result = compare_runs(summarize(base, [TrialResult("base", "a", "task-a", "worker", 1, TrialStatus.PASSED)]),
                          summarize(candidate, [TrialResult("candidate", "b", "task-a", "worker", 1, TrialStatus.FAILED)]))
    assert result.condition_comparison["status"] == "declared_intervention"
