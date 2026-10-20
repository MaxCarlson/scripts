"""
Unit tests for the bounded live terminal dashboard and quiet mode adapter.
"""

from __future__ import annotations

import io
import pytest

from agent_benchmark.dashboard import ExperimentDashboard
from agent_benchmark.scheduler import ExperimentPlan, expand_experiment_plan
from benchmark_core import (
    AggregatedVariantMetrics,
    DurationStats,
    ExperimentComparison,
    ExperimentConfig,
    MetricQuality,
    MetricValue,
    ScoreConfidenceInterval,
    TrialResult,
    TrialStatus,
)


@pytest.fixture
def sample_plan() -> tuple[ExperimentConfig, ExperimentPlan]:
    config = ExperimentConfig(
        experiment_id="exp-dash-01",
        created_at="2026-10-19T10:00:00Z",
        suite_id="agent-smoke",
        suite_version="0.1.1",
        task_ids=["py-grep-smoke"],
        variant_ids=["model-alpha", "model-beta"],
        repetitions=2,
        scoring_basis="worker_first_attempt_full_success",
        budget_profile="canonical-60s",
    )
    plan = expand_experiment_plan(config)
    return config, plan


def test_dashboard_live_lines_bounded_height(sample_plan) -> None:
    _, plan = sample_plan
    buf = io.StringIO()
    dashboard = ExperimentDashboard(plan, quiet=False, stream=buf)

    lines = dashboard._render_live_lines()

    # Must be strictly bounded to <= 12 rows
    assert 5 <= len(lines) <= 12

    # Check content elements
    combined = "\n".join(lines)
    assert "exp-dash-01" in combined
    assert "model-alpha" in combined
    assert "model-beta" in combined
    assert "Ctrl+C halts safely" in combined

    dashboard.close()


def test_dashboard_shows_live_ram_gpu_and_vram_statistics(sample_plan) -> None:
    _, plan = sample_plan

    class Snapshot:
        ram_used_bytes = 16 * 1024**3
        ram_total_bytes = 32 * 1024**3
        ram_pct = 50.0
        gpu_name = "NVIDIA GeForce RTX 5090"
        gpu_utilization_pct = 81.0
        gpu_memory_utilization_pct = 37.0
        gpu_memory_used_bytes = 20 * 1024**3
        gpu_memory_total_bytes = 24 * 1024**3

    class Sampler:
        start_count = 0
        stop_count = 0

        def snapshot(self):
            return Snapshot()

        def start(self):
            self.start_count += 1

        def stop(self):
            self.stop_count += 1

    sampler = Sampler()
    dashboard = ExperimentDashboard(plan, quiet=False, stream=io.StringIO(), resource_sampler=sampler)

    lines = dashboard._render_live_lines()
    stats_lines = [line for line in lines if "RAM" in line and "VRAM" in line]

    assert len(stats_lines) == 1
    assert "RAM 16.0/32.0 GiB (50%)" in stats_lines[0]
    assert "GPU 81%" in stats_lines[0]
    assert "GPU MEM 37%" in stats_lines[0]
    assert "VRAM 20.0/24.0 GiB (83%)" in stats_lines[0]
    assert len(lines) <= 12
    assert sampler.start_count == 0
    dashboard.close()
    assert sampler.stop_count == 1


def test_dashboard_max_visible_models_truncation() -> None:
    """When evaluating many models, table must truncate with '+N more' to maintain bounds."""
    config = ExperimentConfig(
        experiment_id="exp-many-01",
        created_at="2026-10-19T10:00:00Z",
        suite_id="agent-smoke",
        suite_version="0.1.1",
        task_ids=["task-1"],
        variant_ids=[f"model-{i:02d}" for i in range(1, 11)],  # 10 models
        repetitions=1,
        scoring_basis="worker_first_attempt_full_success",
        budget_profile="canonical-60s",
    )
    plan = expand_experiment_plan(config)
    buf = io.StringIO()
    dashboard = ExperimentDashboard(plan, quiet=False, stream=buf, max_visible_models=3)

    lines = dashboard._render_live_lines()

    # Even with 10 models, rows remain strictly bounded
    assert len(lines) <= 12
    combined = "\n".join(lines)
    assert "+7 more models..." in combined

    dashboard.close()


def test_dashboard_quiet_mode_milestone_logging(sample_plan) -> None:
    """
    In quiet mode (-Q/--quiet):
    - LiveBlock is disabled (no cursor hopping).
    - Outputs milestone lines only.
    - No ANSI cursor control escape codes in output.
    """
    _, plan = sample_plan
    buf = io.StringIO()

    dashboard = ExperimentDashboard(plan, quiet=True, stream=buf)
    assert dashboard.live_block.enabled is False

    trial = plan.planned_trials[0]
    dashboard.on_model_start(trial.model_key)
    dashboard.on_trial_start(trial)

    res = TrialResult(
        run_id=trial.run_id,
        trial_id="trial-001",
        task_id=trial.task_id,
        variant_id=trial.model_key,
        repetition=trial.repetition,
        status=TrialStatus.PASSED,
        metrics={"duration.wall_ms": MetricValue(1400.0, "ms", "timer", MetricQuality.MEASURED)},
    )
    dashboard.on_trial_complete(trial, res)
    dashboard.on_model_complete(trial.model_key, None, [res])

    output = buf.getvalue()

    # Verify milestones present
    assert "[EXPERIMENT START]" in output
    assert "[MODEL START] model-alpha" in output
    assert "[TRIAL START] 1/4 [model-alpha]" in output
    assert "[TRIAL COMPLETE] 1/4 [model-alpha] py-grep-smoke r1 -> PASSED (1.4s)" in output
    assert "[MODEL COMPLETE] model-alpha" in output

    # Verify NO ANSI cursor reposition codes (\033[A or \033[2K)
    assert "\033[A" not in output
    assert "\033[2K" not in output

    dashboard.close()


def test_dashboard_final_experiment_complete_leaderboard(sample_plan) -> None:
    config, plan = sample_plan
    buf = io.StringIO()
    dashboard = ExperimentDashboard(plan, quiet=False, stream=buf)

    # Build mock comparison
    ci = ScoreConfidenceInterval(lower=0.55, upper=1.0, confidence=0.95, sample_size=2)
    vm = AggregatedVariantMetrics(
        variant_id="model-alpha",
        is_eligible=True,
        exclusion_reasons=[],
        total_trials=2,
        passed=2,
        failed=0,
        timed_out=0,
        infrastructure_error=0,
        unscored=0,
        scored_denominator=2,
        strict_acceptance_rate=1.0,
        confidence_interval_95=ci,
        task_summaries={},
        metrics={},
        duration=DurationStats(None, None),
        constituent_run_ids=["run-1"],
    )

    comp = ExperimentComparison(
        experiment_id=config.experiment_id,
        config=config,
        eligible_variants={"model-alpha": vm},
        reference_variants={},
        incompatible_runs=[],
        canonical_rankings=["model-alpha"],
        warnings=[],
    )

    dashboard.on_experiment_complete(comp)
    output = buf.getvalue()

    assert "BENCHMARK EXPERIMENT RESULTS SUMMARY" in output
    assert "CANONICAL LEADERBOARD (Comparison-Eligible Models Only)" in output
    assert "model-alpha" in output
    assert "100.0% [55.0% - 100.0%]" in output
