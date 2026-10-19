"""Tests for benchmark adapter bridging benchmark_core contracts to interactive report models."""

from benchmark_core.compare import aggregate_experiment
from benchmark_core.models import (
    ExperimentConfig,
    MetricValue,
    RunInfo,
    TrialResult,
    TrialStatus,
)
from interactive_reports.adapter import (
    convert_trial_to_detail,
    from_experiment_comparison,
)


def _make_benchmark_trial(
    trial_id: str,
    run_id: str,
    variant_id: str,
    task_id: str,
    status: TrialStatus,
    duration_ms: float = 1500.0,
    inp_tok: int = 100,
    out_tok: int = 200,
    rea_tok: int = 50,
) -> TrialResult:
    return TrialResult(
        trial_id=trial_id,
        run_id=run_id,
        task_id=task_id,
        variant_id=variant_id,
        repetition=0,
        status=status,
        metrics={
            "duration.wall_ms": MetricValue(value=duration_ms, unit="ms", source="timer", quality="measured"),
            "tokens.worker.input": MetricValue(value=float(inp_tok), unit="count", source="worker", quality="measured"),
            "tokens.worker.output": MetricValue(value=float(out_tok), unit="count", source="worker", quality="measured"),
            "tokens.worker.reasoning": MetricValue(value=float(rea_tok), unit="count", source="worker", quality="measured"),
            "tokens.worker.total": MetricValue(value=float(inp_tok + out_tok), unit="count", source="worker", quality="measured"),
            "audit.scope_compliance": MetricValue(value=1.0, unit="flag", source="auditor", quality="measured"),
        },
        details={
            "artifacts": {
                "verifier_output": f"Tests passed for {task_id}",
                "patch_diff": "diff --git a/test.py b/test.py",
            }
        },
    )


def test_convert_trial_to_detail():
    bt = _make_benchmark_trial("tr_01", "run_01", "m_alpha", "t_sort", TrialStatus.PASSED)
    td = convert_trial_to_detail(bt)

    assert td.trial_id == "tr_01"
    assert td.variant_id == "m_alpha"
    assert td.task_id == "t_sort"
    assert td.status == "passed"
    assert td.duration_ms == 1500.0
    assert td.input_tokens == 100
    assert td.output_tokens == 200
    assert td.reasoning_tokens == 50
    assert td.total_tokens == 300
    assert td.reasoning_token_share == 0.25
    # 200 tokens / 1.5s = 133.33
    assert td.throughput_tok_per_s == 133.33
    assert td.scope_compliance is True
    assert td.verifier_output == "Tests passed for t_sort"
    assert td.diff == "diff --git a/test.py b/test.py"


def test_from_experiment_comparison():
    config = ExperimentConfig(
        experiment_id="EXP_TEST_ADAPTER",
        created_at="2026-10-19T12:00:00Z",
        suite_id="agent_suite",
        suite_version="1.0.0",
        budget_profile="canonical-60s",
        scoring_basis="strict",
        task_ids=["t_add", "t_sub"],
        variant_ids=["m_winner", "m_loser", "m_ref"],
        repetitions=1,
    )

    run_winner = RunInfo(
        run_id="run_winner",
        created_at="2026-10-19T12:00:00Z",
        suite_id="agent_suite",
        suite_version="1.0.0",
        task_ids=["t_add", "t_sub"],
        variants={"m_winner": {}},
        repetitions=1,
        scoring_basis="strict",
        metadata={"budget_profile": "canonical-60s", "comparison_eligible": True},
    )
    trials_winner = [
        _make_benchmark_trial("tw_1", "run_winner", "m_winner", "t_add", TrialStatus.PASSED, 1000.0),
        _make_benchmark_trial("tw_2", "run_winner", "m_winner", "t_sub", TrialStatus.PASSED, 1200.0),
    ]

    run_loser = RunInfo(
        run_id="run_loser",
        created_at="2026-10-19T12:00:00Z",
        suite_id="agent_suite",
        suite_version="1.0.0",
        task_ids=["t_add", "t_sub"],
        variants={"m_loser": {}},
        repetitions=1,
        scoring_basis="strict",
        metadata={"budget_profile": "canonical-60s", "comparison_eligible": True},
    )
    trials_loser = [
        _make_benchmark_trial("tl_1", "run_loser", "m_loser", "t_add", TrialStatus.FAILED, 2000.0),
        _make_benchmark_trial("tl_2", "run_loser", "m_loser", "t_sub", TrialStatus.TIMED_OUT, 60000.0),
    ]

    run_ref = RunInfo(
        run_id="run_ref",
        created_at="2026-10-19T12:00:00Z",
        suite_id="agent_suite",
        suite_version="1.0.0",
        task_ids=["t_add", "t_sub"],
        variants={"m_ref": {}},
        repetitions=1,
        scoring_basis="strict",
        metadata={"budget_profile": "experimental-10s", "comparison_eligible": False},
    )
    trials_ref = [
        _make_benchmark_trial("tr_1", "run_ref", "m_ref", "t_add", TrialStatus.PASSED, 500.0),
        _make_benchmark_trial("tr_2", "run_ref", "m_ref", "t_sub", TrialStatus.PASSED, 600.0),
    ]

    runs = [
        (run_winner, trials_winner),
        (run_loser, trials_loser),
        (run_ref, trials_ref),
    ]

    comparison = aggregate_experiment(config, runs)

    all_trials = trials_winner + trials_loser + trials_ref
    report_data = from_experiment_comparison(
        comparison,
        all_trials,
        task_categories={"t_add": "math", "t_sub": "math"},
    )

    assert report_data.experiment_id == "EXP_TEST_ADAPTER"
    assert report_data.suite_id == "agent_suite"
    assert len(report_data.variants) == 3

    # Check that m_winner is rank 1
    v_winner = report_data.variants[0]
    assert v_winner.variant_id == "m_winner"
    assert v_winner.rank == 1
    assert v_winner.is_eligible is True
    assert v_winner.strict_acceptance_rate == 1.0
    assert v_winner.scored_denominator == 2

    # Check that m_loser has timed_out in denominator
    v_loser = report_data.variants[1]
    assert v_loser.variant_id == "m_loser"
    assert v_loser.rank == 2
    assert v_loser.is_eligible is True
    assert v_loser.strict_acceptance_rate == 0.0
    assert v_loser.scored_denominator == 2
    assert v_loser.failed == 1
    assert v_loser.timed_out == 1

    # Check that m_ref is marked reference / ineligible
    v_ref = report_data.variants[2]
    assert v_ref.variant_id == "m_ref"
    assert v_ref.is_eligible is False
    assert v_ref.rank is None
    assert len(v_ref.exclusion_reasons) > 0

    # Check divergence matrix
    assert len(report_data.divergence_matrix) == 2
    assert report_data.divergence_matrix[0].category == "math"

    # Check efficiency points
    assert len(report_data.efficiency_points) == 6

    # Check trials lookup map
    assert "tw_1" in report_data.trials
    assert report_data.trials["tw_1"].verifier_output == "Tests passed for t_add"
