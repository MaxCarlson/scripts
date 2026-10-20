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
