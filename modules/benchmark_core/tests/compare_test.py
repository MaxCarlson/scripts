"""
Tests for benchmark_core run and variant comparisons.
"""

from benchmark_core.compare import (
    compare_runs,
    compute_delta,
    render_comparison_md,
)
from benchmark_core.models import (
    MetricValue,
    RunInfo,
    TrialResult,
    TrialStatus,
)
from benchmark_core.stats import summarize


def test_compute_delta_calculations() -> None:
    # Basic positive delta
    d1 = compute_delta(100.0, 150.0)
    assert d1.absolute_change == 50.0
    assert d1.percentage_change == 50.0

    # Negative delta
    d2 = compute_delta(200.0, 100.0)
    assert d2.absolute_change == -100.0
    assert d2.percentage_change == -50.0

    # None values
    d3 = compute_delta(None, 100.0)
    assert d3.absolute_change is None
    assert d3.percentage_change is None


def test_compare_runs_matching_and_scoring_basis_mismatch() -> None:
    run_a = RunInfo(
        run_id="run-a",
        created_at="2026-10-19T02:00:00Z",
        suite_id="eval-suite",
        suite_version="1.0",
        task_ids=["t1"],
        variants={"var-1": {}},
        repetitions=2,
        scoring_basis="worker_first_attempt_full_success",
    )
    trials_a = [
        TrialResult("run-a", "a1", "t1", "var-1", 1, TrialStatus.PASSED,
                    metrics={"duration.wall_ms": MetricValue(1000.0, "ms", "timer", "measured")}),
        TrialResult("run-a", "a2", "t1", "var-1", 2, TrialStatus.FAILED,
                    metrics={"duration.wall_ms": MetricValue(1000.0, "ms", "timer", "measured")}),
    ]

    # Run B with DIFFERENT scoring basis
    run_b_diff_basis = RunInfo(
        run_id="run-b",
        created_at="2026-10-19T03:00:00Z",
        suite_id="eval-suite",
        suite_version="1.0",
        task_ids=["t1"],
        variants={"var-1": {}},
        repetitions=2,
        scoring_basis="workflow_final_success",  # Different!
    )
    trials_b = [
        TrialResult("run-b", "b1", "t1", "var-1", 1, TrialStatus.PASSED,
                    metrics={"duration.wall_ms": MetricValue(800.0, "ms", "timer", "measured")}),
        TrialResult("run-b", "b2", "t1", "var-1", 2, TrialStatus.PASSED,
                    metrics={"duration.wall_ms": MetricValue(800.0, "ms", "timer", "measured")}),
    ]

    summary_a = summarize(run_a, trials_a)
    summary_b = summarize(run_b_diff_basis, trials_b)

    comp = compare_runs(summary_a, summary_b)

    # Must flag critical warning about scoring basis mismatch
    assert any("CRITICAL: Scoring basis mismatch" in w for w in comp.warnings)

    # Check variant delta - success rate deltas MUST be suppressed when scoring basis mismatches
    vc = comp.variant_comparisons["var-1"]
    assert vc.micro_success_rate.baseline == 0.5
    assert vc.micro_success_rate.candidate == 1.0
    assert vc.micro_success_rate.absolute_change is None
    assert vc.micro_success_rate.percentage_change is None

    # Check Markdown rendering
    md = render_comparison_md(comp)
    assert "# Benchmark Comparison: `run-b` vs `run-a`" in md
    assert "CRITICAL: Scoring basis mismatch" in md


def test_compare_runs_matching_scoring_basis_computes_deltas() -> None:
    run_a = RunInfo(
        run_id="run-a",
        created_at="2026-10-19T02:00:00Z",
        suite_id="eval-suite",
        suite_version="1.0",
        task_ids=["t1"],
        variants={"var-1": {}},
        repetitions=2,
        scoring_basis="worker_first_attempt_full_success",
    )
    trials_a = [
        TrialResult("run-a", "a1", "t1", "var-1", 1, TrialStatus.PASSED,
                    metrics={"duration.wall_ms": MetricValue(1000.0, "ms", "timer", "measured")}),
        TrialResult("run-a", "a2", "t1", "var-1", 2, TrialStatus.FAILED,
                    metrics={"duration.wall_ms": MetricValue(1000.0, "ms", "timer", "measured")}),
    ]

    # Run B with SAME scoring basis
    run_b = RunInfo(
        run_id="run-b",
        created_at="2026-10-19T03:00:00Z",
        suite_id="eval-suite",
        suite_version="1.0",
        task_ids=["t1"],
        variants={"var-1": {}},
        repetitions=2,
        scoring_basis="worker_first_attempt_full_success",
    )
    trials_b = [
        TrialResult("run-b", "b1", "t1", "var-1", 1, TrialStatus.PASSED,
                    metrics={"duration.wall_ms": MetricValue(800.0, "ms", "timer", "measured")}),
        TrialResult("run-b", "b2", "t1", "var-1", 2, TrialStatus.PASSED,
                    metrics={"duration.wall_ms": MetricValue(800.0, "ms", "timer", "measured")}),
    ]

    from experiment_test import _conditions
    run_a.metadata["comparison_contract"] = _conditions(["t1"])
    run_b.metadata["comparison_contract"] = _conditions(["t1"])
    summary_a = summarize(run_a, trials_a)
    summary_b = summarize(run_b, trials_b)
    comp = compare_runs(summary_a, summary_b)

    vc = comp.variant_comparisons["var-1"]
    assert vc.micro_success_rate.baseline == 0.5
    assert vc.micro_success_rate.candidate == 1.0
    assert vc.micro_success_rate.absolute_change == 0.5
    assert vc.micro_success_rate.percentage_change == 100.0


def test_compare_runs_allows_only_a_declared_tool_surface_intervention() -> None:
    from experiment_test import _conditions

    base_contract = _conditions(["task-a"])
    candidate_contract = _conditions(["task-a"])
    base_contract["execution_profiles"]["task-a"] = "file-tools-v1"
    candidate_contract["execution_profiles"]["task-a"] = "retrieval-files-v1"
    base_tools = ["StructuredOutput", "edit", "glob", "grep", "list", "read"]
    b2_tools = ["StructuredOutput", "code_context", "code_locate", "edit", "glob", "grep", "list", "read"]
    common_settings = {"context": 16384, "output": 8192, "temperature": 0.2, "top_p": 0.9,
                       "reasoning_effort": "medium", "options_sha256": "d" * 64}
    base_contract["environment"]["runtime"].update(
        agent="benchmark-files", prompt_sha256="a" * 64, allowed_tools=base_tools,
        model_settings=common_settings, permissions_sha256="b" * 64,
    )
    candidate_contract["environment"]["runtime"].update(
        agent="benchmark-files", prompt_sha256="a" * 64, allowed_tools=b2_tools,
        model_settings=common_settings, permissions_sha256="c" * 64,
    )
    identity = {"provider": "lmstudio", "runtime_model_id": "model-key", "quantization": "Q4_K_M"}
    base_contract["environment"]["model_identity"] = identity
    candidate_contract["environment"]["model_identity"] = identity
    design = {
        "schema": "declared-tool-intervention-v1",
        "design_id": "local-agent-efficiency-b0-b2-b3-v1",
        "factor": "tool_profile",
        "allowed_differences": [
            "execution_profiles", "environment.runtime.allowed_tools", "environment.runtime.permissions_sha256",
        ],
        "conditions": {
            "B0": {"profile": "file-tools-v1", "allowed_tools": base_tools},
            "B2": {"profile": "retrieval-files-v1", "allowed_tools": b2_tools},
            "B3": {"profile": "retrieval-structural-v1", "allowed_tools": [
                "StructuredOutput", "code_context", "code_locate", "code_map", "code_symbols",
                "edit", "glob", "grep", "list", "read",
            ]},
        },
    }
    run_a = RunInfo("base", "2026-10-19T02:00:00Z", "eval-suite", "1.0", ["task-a"],
                    {"worker": {}}, 1, "worker_first_attempt_full_success",
                    metadata={"comparison_contract": base_contract, "suite_fingerprint": "e" * 64,
                              "intervention_contract": {**design, "assignment": "B0"}})
    run_b = RunInfo("candidate", "2026-10-19T03:00:00Z", "eval-suite", "1.0", ["task-a"],
                    {"worker": {}}, 1, "worker_first_attempt_full_success",
                    metadata={"comparison_contract": candidate_contract, "suite_fingerprint": "e" * 64,
                              "intervention_contract": {**design, "assignment": "B2"}})
    summary_a = summarize(run_a, [TrialResult("base", "a1", "task-a", "worker", 1, TrialStatus.PASSED)])
    summary_b = summarize(run_b, [TrialResult("candidate", "b1", "task-a", "worker", 1, TrialStatus.PASSED)])

    comparison = compare_runs(summary_a, summary_b)

    assert comparison.condition_comparison["status"] == "declared_intervention", comparison.condition_comparison
    assert comparison.condition_comparison["baseline_condition"] == "B0"
    assert comparison.condition_comparison["candidate_condition"] == "B2"
    assert not any("numerical deltas suppressed" in warning for warning in comparison.warnings)

    import copy
    def rejected(candidate_copy, expected, label):
        candidate_copy.run_info.metadata["comparison_contract"] = copy.deepcopy(candidate_contract)
        expected(candidate_copy.run_info.metadata)
        result = compare_runs(summary_a, candidate_copy)
        assert result.condition_comparison["status"] == "refused", (label, result.condition_comparison)
        assert all(metric.absolute_change is None
                   for comparison_item in result.variant_comparisons.values()
                   for metric in comparison_item.metrics.values())

    for index, mutate in enumerate((
        lambda metadata: metadata["comparison_contract"]["environment"]["model_identity"].update(
            runtime_model_id="other-model"),
        lambda metadata: metadata["comparison_contract"]["environment"]["runtime"]["model_settings"].update(
            output=4096),
        lambda metadata: metadata["comparison_contract"]["tasks"]["task-a"].update(task_sha256="f" * 64),
        lambda metadata: metadata["comparison_contract"]["tasks"]["task-a"].update(verifier_sha256="f" * 64),
        lambda metadata: metadata["comparison_contract"]["environment"]["runtime"].update(prompt_sha256="f" * 64),
        lambda metadata: metadata["comparison_contract"]["environment"]["runtime"]["model_settings"].pop("top_p"),
        lambda metadata: metadata["comparison_contract"]["environment"]["runtime"].update(
            allowed_tools=[*metadata["comparison_contract"]["environment"]["runtime"]["allowed_tools"], "bash"]),
        lambda metadata: metadata.pop("suite_fingerprint"),
        lambda metadata: metadata.update(suite_fingerprint="f" * 64),
    )):
        rejected(copy.deepcopy(summary_b), lambda metadata: mutate(metadata), index)

    missing_contract = copy.deepcopy(summary_b)
    missing_contract.run_info.metadata.pop("intervention_contract")
    refused = compare_runs(summary_a, missing_contract)
    assert refused.condition_comparison["status"] == "refused"
    assert "Missing declared intervention provenance" in refused.condition_comparison["reason"]

    missing_settings = copy.deepcopy(summary_b)
    missing_settings.run_info.metadata["comparison_contract"]["environment"]["runtime"].pop("model_settings")
    refused = compare_runs(summary_a, missing_settings)
    assert refused.condition_comparison["status"] == "refused"
    assert "Effective inference settings are missing" in refused.condition_comparison["reason"]

    # B3 is also admitted only when its exact, separately declared tools are present.
    b3 = copy.deepcopy(summary_b)
    b3.run_info.metadata["intervention_contract"]["assignment"] = "B3"
    b3_contract = b3.run_info.metadata["comparison_contract"]
    b3_contract["execution_profiles"]["task-a"] = "retrieval-structural-v1"
    b3_contract["environment"]["runtime"]["allowed_tools"] = design["conditions"]["B3"]["allowed_tools"]
    b3_contract["environment"]["runtime"]["permissions_sha256"] = "c" * 64
    comparison_b3 = compare_runs(summary_a, b3)
    assert comparison_b3.condition_comparison["status"] == "declared_intervention"
    assert comparison_b3.condition_comparison["candidate_condition"] == "B3"


def test_compare_runs_rejects_undeclared_intervention_mismatches() -> None:
    from experiment_test import _conditions

    base = _conditions(["task-a"])
    candidate = _conditions(["task-a"])
    base["execution_profiles"]["task-a"] = "file-tools-v1"
    candidate["execution_profiles"]["task-a"] = "retrieval-files-v1"
    run_a = RunInfo("base", "2026-10-19T02:00:00Z", "eval-suite", "1.0", ["task-a"],
                    {"worker": {}}, 1, "worker_first_attempt_full_success", metadata={"comparison_contract": base})
    run_b = RunInfo("candidate", "2026-10-19T03:00:00Z", "eval-suite", "1.0", ["task-a"],
                    {"worker": {}}, 1, "worker_first_attempt_full_success", metadata={"comparison_contract": candidate})

    comparison = compare_runs(summarize(run_a, []), summarize(run_b, []))

    assert comparison.condition_comparison["status"] == "refused"
    assert any("numerical deltas suppressed" in warning for warning in comparison.warnings)


def test_compare_runs_unit_mismatch_warning() -> None:
    run_a = RunInfo(
        run_id="run-u1",
        created_at="2026-10-19T02:00:00Z",
        suite_id="eval-suite",
        suite_version="1.0",
        task_ids=["t1"],
        variants={"var-1": {}},
        repetitions=1,
        scoring_basis="worker_first_attempt_full_success",
    )
    run_b = RunInfo(
        run_id="run-u2",
        created_at="2026-10-19T02:00:00Z",
        suite_id="eval-suite",
        suite_version="1.0",
        task_ids=["t1"],
        variants={"var-1": {}},
        repetitions=1,
        scoring_basis="worker_first_attempt_full_success",
    )
    trials_a = [
        TrialResult(
            "run-u1", "t1", "t1", "var-1", 1, TrialStatus.PASSED,
            metrics={"mem": MetricValue(512.0, "MB", "os", "measured")},
        ),
    ]
    trials_b = [
        TrialResult(
            "run-u2", "t2", "t1", "var-1", 1, TrialStatus.PASSED,
            metrics={"mem": MetricValue(536870912.0, "bytes", "os", "measured")},
        ),
    ]
    s_a = summarize(run_a, trials_a)
    s_b = summarize(run_b, trials_b)
    comp = compare_runs(s_a, s_b)

    assert any("Unit mismatch for metric 'mem'" in w for w in comp.warnings)
    md = render_comparison_md(comp)
    assert "WARNING: Unit mismatch for metric 'mem'" in md
