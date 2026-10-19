"""
Tests for benchmark_core statistical aggregations and capability rates.

Validates:
- Hand-calculated descriptive statistics (mean, median, min, max, stdev)
- Missing/unavailable metric value handling and quality tracking
- Final Amendment 2: Eligible denominator (passed + failed + timed_out)
- Final Amendment 2: Three failed trials -> rate 0.0, included in macro-average
- Final Amendment 2: Three infra errors -> rate None, excluded from macro-average
- Final Amendment 2: Mixed valid and infra errors
- All-scored vs successful-only duration isolation
"""

import math
import statistics
import pytest

from benchmark_core.models import (
    MetricQuality,
    MetricValue,
    RunInfo,
    TrialResult,
    TrialStatus,
)
from benchmark_core.stats import (
    BenchmarkSummary,
    compute_metric_stats,
    summarize,
)


def test_descriptive_statistics_hand_calculated() -> None:
    # Hand-calculated values: [10.0, 20.0, 30.0, 40.0]
    # Mean = 25.0, Median = 25.0, Min = 10.0, Max = 40.0, Stdev = 12.9099
    values = [
        MetricValue(10.0, "ms", "timer", MetricQuality.MEASURED),
        MetricValue(20.0, "ms", "timer", MetricQuality.MEASURED),
        MetricValue(30.0, "ms", "timer", MetricQuality.MEASURED),
        MetricValue(40.0, "ms", "timer", MetricQuality.MEASURED),
    ]

    stats = compute_metric_stats("duration.wall_ms", values)

    assert stats.name == "duration.wall_ms"
    assert stats.unit == "ms"
    assert stats.observation_count == 4
    assert stats.available_count == 4
    assert stats.missing_count == 0
    assert stats.mean == 25.0
    assert stats.median == 25.0
    assert stats.min == 10.0
    assert stats.max == 40.0
    assert stats.stdev == 12.9099
    assert stats.quality_counts[MetricQuality.MEASURED] == 4


def test_metric_stats_single_and_zero_values() -> None:
    # Single value: stdev should be None
    stats_single = compute_metric_stats(
        "test", [MetricValue(50.0, "tokens", "api", MetricQuality.MEASURED)]
    )
    assert stats_single.available_count == 1
    assert stats_single.mean == 50.0
    assert stats_single.stdev is None

    # Zero values
    stats_empty = compute_metric_stats("empty", [])
    assert stats_empty.observation_count == 0
    assert stats_empty.available_count == 0
    assert stats_empty.mean is None
    assert stats_empty.stdev is None


def test_metric_stats_missing_and_quality_tracking() -> None:
    values = [
        MetricValue(100.0, "tokens", "api", MetricQuality.MEASURED),
        MetricValue(120.0, "tokens", "api", MetricQuality.ESTIMATED),
        MetricValue(None, "tokens", "api", MetricQuality.UNAVAILABLE, reason="timeout"),
    ]

    stats = compute_metric_stats("tokens.worker.input", values)
    assert stats.observation_count == 3
    assert stats.available_count == 2
    assert stats.missing_count == 1
    assert stats.mean == 110.0
    assert stats.min == 100.0
    assert stats.max == 120.0
    assert stats.quality_counts[MetricQuality.MEASURED] == 1
    assert stats.quality_counts[MetricQuality.ESTIMATED] == 1
    assert stats.quality_counts[MetricQuality.UNAVAILABLE] == 1


class TestMacroMicroEdgeCases:
    """Amendment 2 edge case tests for capability success rates."""

    @pytest.fixture
    def test_run_info(self) -> RunInfo:
        return RunInfo(
            run_id="run-macro-test",
            created_at="2026-10-19T02:30:00Z",
            suite_id="suite-eval",
            suite_version="1.0.0",
            task_ids=["task_all_failed", "task_all_infra", "task_mixed", "task_all_passed"],
            variants={"var-1": {"name": "model_a"}},
            repetitions=3,
            scoring_basis="worker_first_attempt_full_success",
        )

    def test_three_failed_trials_success_rate_zero_and_included_in_macro(
        self, test_run_info: RunInfo
    ) -> None:
        """Requirement: Three failed trials -> rate is 0.0%, include task in macro-average."""
        trials = [
            TrialResult("run-macro-test", "t1", "task_all_failed", "var-1", 1, TrialStatus.FAILED),
            TrialResult("run-macro-test", "t2", "task_all_failed", "var-1", 2, TrialStatus.FAILED),
            TrialResult("run-macro-test", "t3", "task_all_failed", "var-1", 3, TrialStatus.FAILED),
        ]
        summary = summarize(test_run_info, trials)
        var_summary = summary.variants["var-1"]
        task_summary = var_summary.tasks["task_all_failed"]

        assert task_summary.eligible_count == 3
        assert task_summary.passed == 0
        assert task_summary.failed == 3
        assert task_summary.success_rate == 0.0
        assert "task_all_failed" not in var_summary.insufficiently_sampled_tasks

    def test_three_infrastructure_errors_zero_scored_excluded_from_macro(
        self, test_run_info: RunInfo
    ) -> None:
        """Requirement: Three infra errors -> rate is null, exclude from macro-average and report."""
        trials = [
            TrialResult("run-macro-test", "t1", "task_all_infra", "var-1", 1, TrialStatus.INFRASTRUCTURE_ERROR),
            TrialResult("run-macro-test", "t2", "task_all_infra", "var-1", 2, TrialStatus.INFRASTRUCTURE_ERROR),
            TrialResult("run-macro-test", "t3", "task_all_infra", "var-1", 3, TrialStatus.INFRASTRUCTURE_ERROR),
        ]
        summary = summarize(test_run_info, trials)
        var_summary = summary.variants["var-1"]
        task_summary = var_summary.tasks["task_all_infra"]

        assert task_summary.eligible_count == 0
        assert task_summary.infrastructure_error == 3
        assert task_summary.success_rate is None
        assert "task_all_infra" in var_summary.insufficiently_sampled_tasks

    def test_mixed_valid_and_infrastructure_errors(self, test_run_info: RunInfo) -> None:
        """Requirement: Mixed valid and infra-errors -> calculate rate using only eligible scored trials."""
        trials = [
            TrialResult("run-macro-test", "t1", "task_mixed", "var-1", 1, TrialStatus.PASSED),
            TrialResult("run-macro-test", "t2", "task_mixed", "var-1", 2, TrialStatus.PASSED),
            TrialResult("run-macro-test", "t3", "task_mixed", "var-1", 3, TrialStatus.FAILED),
            TrialResult("run-macro-test", "t4", "task_mixed", "var-1", 4, TrialStatus.INFRASTRUCTURE_ERROR),
            TrialResult("run-macro-test", "t5", "task_mixed", "var-1", 5, TrialStatus.INFRASTRUCTURE_ERROR),
        ]
        summary = summarize(test_run_info, trials)
        var_summary = summary.variants["var-1"]
        task_summary = var_summary.tasks["task_mixed"]

        # Eligible = passed (2) + failed (1) = 3. Infra (2) excluded from denominator.
        assert task_summary.eligible_count == 3
        assert task_summary.infrastructure_error == 2
        assert task_summary.success_rate == round(2 / 3, 4)

    def test_macro_average_combination_rule(self, test_run_info: RunInfo) -> None:
        """
        A task is excluded from macro-average ONLY when eligible denominator == 0,
        not when successes == 0.

        Tasks:
        - task_all_passed: 3 passed -> rate 1.0 (included)
        - task_all_failed: 3 failed -> rate 0.0 (included)
        - task_all_infra: 3 infra errors -> rate None (excluded!)

        Expected macro average = (1.0 + 0.0) / 2 = 0.5
        """
        trials = [
            # task_all_passed: 3 passed
            TrialResult("run-macro-test", "t1", "task_all_passed", "var-1", 1, TrialStatus.PASSED),
            TrialResult("run-macro-test", "t2", "task_all_passed", "var-1", 2, TrialStatus.PASSED),
            TrialResult("run-macro-test", "t3", "task_all_passed", "var-1", 3, TrialStatus.PASSED),
            # task_all_failed: 3 failed
            TrialResult("run-macro-test", "t4", "task_all_failed", "var-1", 1, TrialStatus.FAILED),
            TrialResult("run-macro-test", "t5", "task_all_failed", "var-1", 2, TrialStatus.FAILED),
            TrialResult("run-macro-test", "t6", "task_all_failed", "var-1", 3, TrialStatus.FAILED),
            # task_all_infra: 3 infra errors
            TrialResult("run-macro-test", "t7", "task_all_infra", "var-1", 1, TrialStatus.INFRASTRUCTURE_ERROR),
            TrialResult("run-macro-test", "t8", "task_all_infra", "var-1", 2, TrialStatus.INFRASTRUCTURE_ERROR),
            TrialResult("run-macro-test", "t9", "task_all_infra", "var-1", 3, TrialStatus.INFRASTRUCTURE_ERROR),
        ]
        summary = summarize(test_run_info, trials)
        var_summary = summary.variants["var-1"]

        assert var_summary.tasks["task_all_passed"].success_rate == 1.0
        assert var_summary.tasks["task_all_failed"].success_rate == 0.0
        assert var_summary.tasks["task_all_infra"].success_rate is None

        # Excluded task recorded
        assert "task_all_infra" in var_summary.insufficiently_sampled_tasks
        assert "task_all_failed" not in var_summary.insufficiently_sampled_tasks

        # Macro average: (1.0 + 0.0) / 2 = 0.5
        assert var_summary.macro_success_rate == 0.5

        # Micro average: 3 passed / (3 passed + 3 failed) = 3 / 6 = 0.5
        assert var_summary.micro_success_rate == 0.5


def test_duration_all_scored_vs_successful_only() -> None:
    """Ensure fast failures do not distort successful-only duration."""
    run_info = RunInfo(
        run_id="run-dur",
        created_at="2026-10-19T02:30:00Z",
        suite_id="s1",
        suite_version="1.0",
        task_ids=["t1"],
        variants={"v1": {}},
        repetitions=3,
        scoring_basis="basis",
    )

    trials = [
        # Successful slow trial: 5000ms
        TrialResult(
            "run-dur", "t1", "t1", "v1", 1, TrialStatus.PASSED,
            metrics={"duration.wall_ms": MetricValue(5000.0, "ms", "timer", "measured")},
        ),
        # Failed fast trial: 100ms
        TrialResult(
            "run-dur", "t2", "t1", "v1", 2, TrialStatus.FAILED,
            metrics={"duration.wall_ms": MetricValue(100.0, "ms", "timer", "measured")},
        ),
        # Timed out trial: 30000ms
        TrialResult(
            "run-dur", "t3", "t1", "v1", 3, TrialStatus.TIMED_OUT,
            metrics={"duration.wall_ms": MetricValue(30000.0, "ms", "timer", "measured")},
        ),
        # Infrastructure error: 50ms (not scored)
        TrialResult(
            "run-dur", "t4", "t1", "v1", 4, TrialStatus.INFRASTRUCTURE_ERROR,
            metrics={"duration.wall_ms": MetricValue(50.0, "ms", "timer", "measured")},
        ),
    ]

    summary = summarize(run_info, trials)
    v_summary = summary.variants["v1"]

    dur = v_summary.duration
    assert dur.successful_only is not None
    assert dur.successful_only.observation_count == 1
    assert dur.successful_only.mean == 5000.0

    assert dur.all_scored is not None
    # All scored includes passed (5000), failed (100), timed_out (30000). Total 3 observations.
    assert dur.all_scored.observation_count == 3
    assert dur.all_scored.min == 100.0
    assert dur.all_scored.max == 30000.0
    assert dur.all_scored.mean == round((5000.0 + 100.0 + 30000.0) / 3, 4)
