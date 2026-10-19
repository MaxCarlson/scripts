"""
Tests for benchmark_core multi-run experiment data models, aggregation,
eligibility enforcement, denominator semantics, Wilson confidence intervals,
and atomic persistence.
"""

from __future__ import annotations

from pathlib import Path
import pytest

from benchmark_core.compare import (
    aggregate_experiment,
    render_experiment_comparison_md,
)
from benchmark_core.models import (
    Experiment,
    ExperimentConfig,
    ExperimentRunRef,
    MetricQuality,
    MetricValue,
    RunInfo,
    TrialResult,
    TrialStatus,
)
from benchmark_core.stats import (
    ScoreConfidenceInterval,
    compute_wilson_score_interval,
    summarize,
)
from benchmark_core.reporting import (
    generate_experiment_reports,
    render_experiment_comparison_csv,
)
from benchmark_core.storage import (
    load_experiment,
    save_experiment,
)


# =============================================================================
# Helper Fixtures & Builders
# =============================================================================


def _create_sample_config(
    experiment_id: str = "exp-20261019-01",
    suite_id: str = "agent-benchmark-suite",
    suite_version: str = "1.0.0",
    scoring_basis: str = "worker_first_attempt_full_success",
    budget_profile: str = "canonical-60s",
    task_ids: list[str] | None = None,
    variant_ids: list[str] | None = None,
    repetitions: int = 3,
) -> ExperimentConfig:
    return ExperimentConfig(
        experiment_id=experiment_id,
        created_at="2026-10-19T10:00:00Z",
        suite_id=suite_id,
        suite_version=suite_version,
        task_ids=task_ids or ["task-1", "task-2"],
        variant_ids=variant_ids or ["model-a", "model-b"],
        repetitions=repetitions,
        scoring_basis=scoring_basis,
        budget_profile=budget_profile,
        random_seed=42,
        metadata={"coordinator": "gemini"},
    )


def _create_run(
    run_id: str,
    variant_id: str,
    suite_id: str = "agent-benchmark-suite",
    suite_version: str = "1.0.0",
    scoring_basis: str = "worker_first_attempt_full_success",
    budget_profile: str = "canonical-60s",
    comparison_eligible: bool = True,
    exclusion_reason: str | None = None,
    task_ids: list[str] | None = None,
) -> RunInfo:
    tasks = task_ids or ["task-1", "task-2"]
    meta: dict[str, object] = {
        "budget_profile": budget_profile,
        "comparison_eligible": comparison_eligible,
    }
    if exclusion_reason:
        meta["exclusion_reason"] = exclusion_reason
    return RunInfo(
        run_id=run_id,
        created_at="2026-10-19T10:05:00Z",
        suite_id=suite_id,
        suite_version=suite_version,
        task_ids=tasks,
        variants={variant_id: {"model": variant_id}},
        repetitions=len(tasks),
        scoring_basis=scoring_basis,
        metadata=meta,
    )


def _create_trial(
    run_id: str,
    task_id: str,
    variant_id: str,
    repetition: int,
    status: TrialStatus,
    duration_ms: float = 1200.0,
) -> TrialResult:
    return TrialResult(
        run_id=run_id,
        trial_id=f"{run_id}-{task_id}-r{repetition}",
        task_id=task_id,
        variant_id=variant_id,
        repetition=repetition,
        status=status,
        metrics={
            "duration.wall_ms": MetricValue(
                value=duration_ms,
                unit="ms",
                source="timer",
                quality=MetricQuality.MEASURED,
            )
        },
    )


# =============================================================================
# Unit Tests
# =============================================================================


def test_experiment_models_validation_and_serialization() -> None:
    config = _create_sample_config()
    ref1 = ExperimentRunRef(
        run_id="run-01",
        run_dir="runs/run-01",
        variant_id="model-a",
        suite_id="agent-benchmark-suite",
        suite_version="1.0.0",
        scoring_basis="worker_first_attempt_full_success",
        budget_profile="canonical-60s",
        comparison_eligible=True,
    )
    ref2 = ExperimentRunRef(
        run_id="run-02",
        run_dir="runs/run-02",
        variant_id="model-b",
        suite_id="agent-benchmark-suite",
        suite_version="1.0.0",
        scoring_basis="worker_first_attempt_full_success",
        budget_profile="experimental-120s",
        comparison_eligible=False,
        exclusion_reasons=["Experimental budget profile used"],
    )

    exp = Experiment(
        config=config,
        run_refs=[ref1, ref2],
        metadata={"tags": ["fast", "nightly"]},
    )

    # Roundtrip serialization
    exp_dict = exp.to_dict()
    exp_restored = Experiment.from_dict(exp_dict)
    assert exp_restored.config.experiment_id == "exp-20261019-01"
    assert len(exp_restored.run_refs) == 2
    assert exp_restored.run_refs[0].comparison_eligible is True
    assert exp_restored.run_refs[1].comparison_eligible is False
    assert exp_restored.run_refs[1].exclusion_reasons == ["Experimental budget profile used"]

    # JSON roundtrip
    exp_json = exp.to_json()
    exp_from_json = Experiment.from_json(exp_json)
    assert exp_from_json.config == exp.config

    # Validation errors
    with pytest.raises(ValueError, match="ExperimentConfig.repetitions must be a positive int"):
        ExperimentConfig(
            experiment_id="exp-bad",
            created_at="2026-10-19T10:00:00Z",
            suite_id="suite-1",
            suite_version="1.0",
            task_ids=["t1"],
            variant_ids=["v1"],
            repetitions=0,
            scoring_basis="basis",
            budget_profile="canonical",
        )

    with pytest.raises(ValueError, match="ExperimentConfig.task_ids must be a non-empty list"):
        ExperimentConfig(
            experiment_id="exp-bad",
            created_at="2026-10-19T10:00:00Z",
            suite_id="suite-1",
            suite_version="1.0",
            task_ids=[],
            variant_ids=["v1"],
            repetitions=1,
            scoring_basis="basis",
            budget_profile="canonical",
        )


def test_wilson_score_confidence_interval_math() -> None:
    # 0 / 10 successes
    ci_0 = compute_wilson_score_interval(0, 10, confidence=0.95)
    assert ci_0 is not None
    assert ci_0.lower == 0.0
    assert 0.25 < ci_0.upper < 0.32

    # 10 / 10 successes
    ci_10 = compute_wilson_score_interval(10, 10, confidence=0.95)
    assert ci_10 is not None
    assert 0.68 < ci_10.lower < 0.75
    assert ci_10.upper == 1.0

    # 5 / 10 successes (symmetric around 0.5)
    ci_5 = compute_wilson_score_interval(5, 10, confidence=0.95)
    assert ci_5 is not None
    midpoint = round((ci_5.lower + ci_5.upper) / 2.0, 2)
    assert midpoint == 0.50
    assert 0.20 < ci_5.lower < 0.26
    assert 0.74 < ci_5.upper < 0.80

    # Invalid / empty
    assert compute_wilson_score_interval(0, 0) is None
    with pytest.raises(ValueError):
        compute_wilson_score_interval(-1, 10)
    with pytest.raises(ValueError):
        compute_wilson_score_interval(11, 10)

    # Serialization
    ci_dict = ci_5.to_dict()
    ci_restored = ScoreConfidenceInterval.from_dict(ci_dict)
    assert ci_restored == ci_5


def test_scored_denominator_semantics_mixed_statuses() -> None:
    """
    Critical correctness rule:
    - Scored denominator = passed + failed + timed_out
    - failed and timed_out trials REMAIN in denominator
    - infrastructure_error and unscored trials do NOT increment denominator and are isolated
    """
    config = _create_sample_config(task_ids=["t1", "t2", "t3", "t4", "t5", "t6"], variant_ids=["model-a"])
    run_a = _create_run("run-a", "model-a", task_ids=["t1", "t2", "t3", "t4", "t5", "t6"])

    trials = [
        _create_trial("run-a", "t1", "model-a", 1, TrialStatus.PASSED, 1000.0),
        _create_trial("run-a", "t2", "model-a", 1, TrialStatus.PASSED, 1200.0),
        _create_trial("run-a", "t3", "model-a", 1, TrialStatus.FAILED, 1100.0),
        _create_trial("run-a", "t4", "model-a", 1, TrialStatus.TIMED_OUT, 60000.0),
        _create_trial("run-a", "t5", "model-a", 1, TrialStatus.INFRASTRUCTURE_ERROR, 500.0),
        _create_trial("run-a", "t6", "model-a", 1, TrialStatus.UNSCORED, 200.0),
    ]

    comp = aggregate_experiment(config, [(run_a, trials)])

    assert "model-a" in comp.eligible_variants
    vm = comp.eligible_variants["model-a"]

    assert vm.total_trials == 6
    assert vm.passed == 2
    assert vm.failed == 1
    assert vm.timed_out == 1
    assert vm.infrastructure_error == 1
    assert vm.unscored == 1

    # Scored denominator MUST be 2 + 1 + 1 = 4
    assert vm.scored_denominator == 4

    # Strict acceptance rate = passed / scored_denominator = 2 / 4 = 0.50
    assert vm.strict_acceptance_rate == 0.50
    assert vm.confidence_interval_95 is not None
    assert vm.confidence_interval_95.lower < 0.50 < vm.confidence_interval_95.upper


def test_production_comparison_eligibility_enforcement() -> None:
    """
    Runs marked comparison_eligible=False or with mismatched budget profiles
    must be segregated into reference_variants and never enter canonical_rankings.
    """
    config = _create_sample_config(
        variant_ids=["canonical-model", "experimental-model", "mismatched-budget-model"],
        budget_profile="canonical-60s",
    )

    # 1. Canonical run (eligible)
    run_canon = _create_run("run-canon", "canonical-model", budget_profile="canonical-60s")
    trials_canon = [
        _create_trial("run-canon", "task-1", "canonical-model", 1, TrialStatus.PASSED),
        _create_trial("run-canon", "task-2", "canonical-model", 1, TrialStatus.PASSED),
    ]

    # 2. Ineligible run via explicit flag
    run_exp = _create_run(
        "run-exp",
        "experimental-model",
        comparison_eligible=False,
        exclusion_reason="Custom prompt tuning applied",
    )
    trials_exp = [
        _create_trial("run-exp", "task-1", "experimental-model", 1, TrialStatus.PASSED),
        _create_trial("run-exp", "task-2", "experimental-model", 1, TrialStatus.PASSED),
    ]

    # 3. Ineligible run via mismatched budget profile
    run_budget = _create_run(
        "run-budget",
        "mismatched-budget-model",
        budget_profile="experimental-120s",
    )
    trials_budget = [
        _create_trial("run-budget", "task-1", "mismatched-budget-model", 1, TrialStatus.PASSED),
        _create_trial("run-budget", "task-2", "mismatched-budget-model", 1, TrialStatus.PASSED),
    ]

    comp = aggregate_experiment(
        config,
        [
            (run_canon, trials_canon),
            (run_exp, trials_exp),
            (run_budget, trials_budget),
        ],
    )

    # Canonical rankings must contain ONLY eligible variants
    assert comp.canonical_rankings == ["canonical-model"]
    assert "canonical-model" in comp.eligible_variants
    assert "experimental-model" not in comp.eligible_variants
    assert "mismatched-budget-model" not in comp.eligible_variants

    # Ineligible variants must be collected in reference_variants with recorded reasons
    assert "experimental-model" in comp.reference_variants
    assert "Custom prompt tuning applied" in comp.reference_variants["experimental-model"].exclusion_reasons

    assert "mismatched-budget-model" in comp.reference_variants
    assert any("Budget profile mismatch" in r for r in comp.reference_variants["mismatched-budget-model"].exclusion_reasons)


def test_variant_demotion_if_any_constituent_run_ineligible() -> None:
    """
    If multiple runs are combined for the same variant and one is ineligible,
    the entire variant must be demoted to reference_variants to avoid data pollution.
    """
    config = _create_sample_config(variant_ids=["hybrid-model"])

    run_valid = _create_run("run-1", "hybrid-model", comparison_eligible=True)
    trials_valid = [_create_trial("run-1", "task-1", "hybrid-model", 1, TrialStatus.PASSED)]

    run_invalid = _create_run(
        "run-2",
        "hybrid-model",
        comparison_eligible=False,
        exclusion_reason="Manual intervention occurred",
    )
    trials_invalid = [_create_trial("run-2", "task-2", "hybrid-model", 1, TrialStatus.PASSED)]

    comp = aggregate_experiment(config, [(run_valid, trials_valid), (run_invalid, trials_invalid)])

    assert "hybrid-model" not in comp.eligible_variants
    assert "hybrid-model" in comp.reference_variants
    assert comp.canonical_rankings == []
    assert any("Manual intervention occurred" in r for r in comp.reference_variants["hybrid-model"].exclusion_reasons)
    assert any("demoted to reference comparisons" in w for w in comp.warnings)


def test_run_compatibility_checks_hard_rejections() -> None:
    """
    Suite ID mismatch, suite version mismatch, scoring basis mismatch,
    or disjoint task sets must cause run rejection into incompatible_runs.
    """
    config = _create_sample_config()

    # Suite ID mismatch
    run_bad_suite = _create_run("run-bad-suite", "m1", suite_id="other-suite")
    # Suite version mismatch
    run_bad_ver = _create_run("run-bad-ver", "m2", suite_version="2.0.0")
    # Scoring basis mismatch
    run_bad_basis = _create_run("run-bad-basis", "m3", scoring_basis="other_basis")
    # Disjoint task IDs
    run_disjoint = _create_run("run-disjoint", "m4", task_ids=["unrelated-task"])

    comp = aggregate_experiment(
        config,
        [
            (run_bad_suite, [_create_trial("run-bad-suite", "task-1", "m1", 1, TrialStatus.PASSED)]),
            (run_bad_ver, [_create_trial("run-bad-ver", "task-1", "m2", 1, TrialStatus.PASSED)]),
            (run_bad_basis, [_create_trial("run-bad-basis", "task-1", "m3", 1, TrialStatus.PASSED)]),
            (run_disjoint, [_create_trial("run-disjoint", "unrelated-task", "m4", 1, TrialStatus.PASSED)]),
        ],
    )

    assert len(comp.incompatible_runs) == 4
    rejected_ids = {r["run_id"] for r in comp.incompatible_runs}
    assert rejected_ids == {"run-bad-suite", "run-bad-ver", "run-bad-basis", "run-disjoint"}
    assert comp.canonical_rankings == []
    assert len(comp.warnings) == 4


def test_canonical_rankings_sorting_order() -> None:
    """
    Canonical rankings are sorted strictly by strict_acceptance_rate DESC,
    then by mean duration ASC for ties.
    """
    config = _create_sample_config(variant_ids=["model-high", "model-mid-fast", "model-mid-slow", "model-low"])

    # High: 100% (2/2)
    run_high = _create_run("r1", "model-high")
    trials_high = [
        _create_trial("r1", "task-1", "model-high", 1, TrialStatus.PASSED, 2000.0),
        _create_trial("r1", "task-2", "model-high", 1, TrialStatus.PASSED, 2000.0),
    ]

    # Mid Fast: 50% (1/2), dur 1000ms
    run_mid_fast = _create_run("r2", "model-mid-fast")
    trials_mid_fast = [
        _create_trial("r2", "task-1", "model-mid-fast", 1, TrialStatus.PASSED, 1000.0),
        _create_trial("r2", "task-2", "model-mid-fast", 1, TrialStatus.FAILED, 1000.0),
    ]

    # Mid Slow: 50% (1/2), dur 3000ms
    run_mid_slow = _create_run("r3", "model-mid-slow")
    trials_mid_slow = [
        _create_trial("r3", "task-1", "model-mid-slow", 1, TrialStatus.PASSED, 3000.0),
        _create_trial("r3", "task-2", "model-mid-slow", 1, TrialStatus.FAILED, 3000.0),
    ]

    # Low: 0% (0/2)
    run_low = _create_run("r4", "model-low")
    trials_low = [
        _create_trial("r4", "task-1", "model-low", 1, TrialStatus.FAILED, 1500.0),
        _create_trial("r4", "task-2", "model-low", 1, TrialStatus.FAILED, 1500.0),
    ]

    comp = aggregate_experiment(
        config,
        [
            (run_high, trials_high),
            (run_mid_slow, trials_mid_slow),
            (run_mid_fast, trials_mid_fast),
            (run_low, trials_low),
        ],
    )

    assert comp.canonical_rankings == ["model-high", "model-mid-fast", "model-mid-slow", "model-low"]


def test_atomic_persistence_save_and_load(tmp_path: Path) -> None:
    config = _create_sample_config()
    run_ref = ExperimentRunRef(
        run_id="run-01",
        run_dir="runs/run-01",
        variant_id="model-a",
        suite_id="agent-benchmark-suite",
        suite_version="1.0.0",
        scoring_basis="worker_first_attempt_full_success",
        budget_profile="canonical-60s",
        comparison_eligible=True,
    )
    exp = Experiment(config=config, run_refs=[run_ref])

    run_info = _create_run("run-01", "model-a")
    trials = [_create_trial("run-01", "task-1", "model-a", 1, TrialStatus.PASSED)]
    comp = aggregate_experiment(config, [(run_info, trials)])

    exp_dir = tmp_path / "test-experiment"

    # Save
    saved_path = save_experiment(exp_dir, exp, comparison=comp)
    assert saved_path == exp_dir
    assert (exp_dir / "experiment.json").exists()
    assert (exp_dir / "run-references.json").exists()
    assert (exp_dir / "comparison.json").exists()

    # Re-saving without overwrite must raise FileExistsError
    with pytest.raises(FileExistsError):
        save_experiment(exp_dir, exp, comparison=comp, overwrite=False)

    # Re-saving with overwrite=True succeeds
    save_experiment(exp_dir, exp, comparison=comp, overwrite=True)

    # Load and verify
    loaded_exp, loaded_comp = load_experiment(exp_dir)
    assert loaded_exp.config.experiment_id == exp.config.experiment_id
    assert len(loaded_exp.run_refs) == 1
    assert loaded_exp.run_refs[0].run_id == "run-01"

    assert loaded_comp is not None
    assert loaded_comp.experiment_id == comp.experiment_id
    assert loaded_comp.canonical_rankings == ["model-a"]
    assert loaded_comp.eligible_variants["model-a"].scored_denominator == 1


def test_render_experiment_comparison_md() -> None:
    config = _create_sample_config(variant_ids=["m1", "m2"])
    run1 = _create_run("r1", "m1")
    t1 = [_create_trial("r1", "task-1", "m1", 1, TrialStatus.PASSED, 1000.0)]

    run2 = _create_run("r2", "m2", comparison_eligible=False, exclusion_reason="Experimental budget")
    t2 = [_create_trial("r2", "task-1", "m2", 1, TrialStatus.PASSED, 1500.0)]

    comp = aggregate_experiment(config, [(run1, t1), (run2, t2)])
    md = render_experiment_comparison_md(comp)

    assert "# Benchmark Experiment Comparison: `exp-20261019-01`" in md
    assert "## Canonical Model Leaderboard (Eligible Only)" in md
    assert "| 1 | `m1` |" in md
    assert "## Reference & Comparison-Ineligible Variants" in md
    assert "| `m2` | Experimental budget |" in md


def test_backward_compatibility_single_run_summary() -> None:
    """
    Ensure single-run summarize() computes Wilson score intervals and doesn't break
    existing VariantSummary / TaskSummary consumers.
    """
    run_info = _create_run("r-single", "v-single", task_ids=["task-1"])
    trials = [
        _create_trial("r-single", "task-1", "v-single", 1, TrialStatus.PASSED),
        _create_trial("r-single", "task-1", "v-single", 2, TrialStatus.FAILED),
    ]

    summary = summarize(run_info, trials)
    assert "v-single" in summary.variants
    vs = summary.variants["v-single"]
    assert vs.confidence_interval is not None
    assert vs.confidence_interval.confidence == 0.95
    assert vs.confidence_interval.lower < 0.50 < vs.confidence_interval.upper

    # Task summary also has CI
    ts = vs.tasks["task-1"]
    assert ts.confidence_interval is not None
    assert ts.confidence_interval.confidence == 0.95

    # to_dict / from_dict roundtrip intact
    summary_dict = summary.to_dict()
    assert summary_dict["variants"]["v-single"]["confidence_interval"] is not None


def test_render_experiment_comparison_csv() -> None:
    config = _create_sample_config(variant_ids=["m_fast", "m_slow"])
    run1 = _create_run("r1", "m_fast")
    t1 = [_create_trial("r1", "task-1", "m_fast", 1, TrialStatus.PASSED, 1000.0)]

    run2 = _create_run("r2", "m_slow", comparison_eligible=False, exclusion_reason="Oversized budget")
    t2 = [_create_trial("r2", "task-1", "m_slow", 1, TrialStatus.PASSED, 2000.0)]

    comp = aggregate_experiment(config, [(run1, t1), (run2, t2)])
    csv_str = render_experiment_comparison_csv(comp)

    assert "rank,variant_id,is_eligible,exclusion_reasons,strict_acceptance_rate" in csv_str
    # m_fast is rank 1 and eligible
    assert "1,m_fast,true,,1.0" in csv_str
    # m_slow is reference/ineligible with exclusion reason
    assert ",m_slow,false,Oversized budget,1.0" in csv_str


def test_generate_experiment_reports_and_save(tmp_path: Path) -> None:
    config = _create_sample_config(variant_ids=["m_a"])
    run1 = _create_run("r1", "m_a")
    t1 = [_create_trial("r1", "task-1", "m_a", 1, TrialStatus.PASSED, 1000.0)]

    comp = aggregate_experiment(config, [(run1, t1)])

    # Test in-memory report generation
    reports = generate_experiment_reports(comp, trials=t1)
    assert "comparison.json" in reports
    assert "comparison.csv" in reports
    assert "report.md" in reports
    assert "index.html" in reports

    # HTML report is standalone and contains m_a
    assert "<!DOCTYPE html>" in reports["index.html"]
    assert "m_a" in reports["index.html"]

    # Test saving experiment with generate_reports=True
    run_ref = ExperimentRunRef(
        run_id="r1",
        run_dir="runs/r1",
        variant_id="m_a",
        suite_id="agent-benchmark-suite",
        suite_version="1.0.0",
        scoring_basis="worker_first_attempt_full_success",
        budget_profile="canonical-60s",
        comparison_eligible=True,
    )
    exp = Experiment(config=config, run_refs=[run_ref])
    exp_dir = tmp_path / "exp_saved"

    save_experiment(exp_dir, exp, comparison=comp, trials=t1, generate_reports=True)

    assert (exp_dir / "experiment.json").is_file()
    assert (exp_dir / "run-references.json").is_file()
    assert (exp_dir / "comparison.json").is_file()
    assert (exp_dir / "comparison.csv").is_file()
    assert (exp_dir / "report.md").is_file()
    assert (exp_dir / "index.html").is_file()
