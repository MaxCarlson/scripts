"""
Unit tests for the bounded live terminal dashboard and quiet mode adapter.
"""

from __future__ import annotations

import io
import os
import pytest

import agent_benchmark.dashboard as dashboard_module
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
from termdash.table import _strip_ansi


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
    plain_stats = _strip_ansi(stats_lines[0])
    assert "RAM 16.0/32.0 GiB 50%" in plain_stats
    assert "GPU 81%" in plain_stats
    assert "GPU-MEM 37%" in plain_stats
    assert "VRAM 20.0/24.0 GiB 83%" in plain_stats
    assert len(plain_stats) <= 80
    assert len(lines) <= 12
    assert sampler.start_count == 1
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


def test_dashboard_does_not_mark_failed_model_as_successful(sample_plan) -> None:
    _, plan = sample_plan
    buf = io.StringIO()
    dashboard = ExperimentDashboard(plan, quiet=True, stream=buf)
    trial = plan.planned_trials[0]
    result = TrialResult(
        run_id=trial.run_id,
        trial_id="trial-001",
        task_id=trial.task_id,
        variant_id=trial.model_key,
        repetition=trial.repetition,
        status=TrialStatus.FAILED,
    )

    dashboard.on_trial_complete(trial, result)
    dashboard.on_model_complete(trial.model_key, None, [result])

    assert dashboard.models[trial.model_key].status == "FAILED"
    assert "[MODEL RESULT] model-alpha" in buf.getvalue()
    assert "[MODEL COMPLETE] model-alpha" not in buf.getvalue()
    dashboard.close()


@pytest.mark.parametrize("quiet", [True, False])
def test_dashboard_explains_scope_failure_and_preserves_code_success(sample_plan, quiet):
    _, plan = sample_plan
    buf = io.StringIO()
    dashboard = ExperimentDashboard(plan, quiet=quiet, stream=buf)
    trial = plan.planned_trials[0]
    result = TrialResult(trial.run_id, "trial-001", trial.task_id, trial.model_key, 1, "failed", {
        "agent.functional_pass": MetricValue(1, "boolean", "verifier", "derived"),
        "agent.budget_pass": MetricValue(1, "boolean", "budget", "derived"),
    }, {"verifier_status": "passed", "scope_audit": {"compliance": "violated"},
        "scope_violations": ["__pycache__/grep.cpython-312.pyc"],
        "termination": {"confirmed": True}, "evidence_path": "evidence/trial-001"})
    dashboard.on_trial_complete(trial, result)
    dashboard.on_model_complete(trial.model_key, None, [result])
    output = _strip_ansi(buf.getvalue())
    assert "code PASS | scope FAIL | budget PASS" in output
    assert "__pycache__/grep.cpython-312.pyc" in output
    assert "Code checks: 1/1 passed" in output
    assert "Evidence:" in output
    assert len(dashboard._render_live_lines()) <= 12
    comparison = ExperimentComparison(plan.experiment_id, plan.config, {}, {}, [], [], [])
    dashboard.on_experiment_complete(comparison)
    assert "FUNCTIONAL CODE CHECKS" in buf.getvalue()
    assert "model-alpha: 1/1 passed; 0 unavailable" in buf.getvalue()


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


def test_final_summary_shows_every_outcome_and_fits_terminal_width(sample_plan, monkeypatch) -> None:
    config, plan = sample_plan
    monkeypatch.setattr(dashboard_module.shutil, "get_terminal_size", lambda fallback: os.terminal_size((80, 24)))
    buf = io.StringIO()
    dashboard = ExperimentDashboard(plan, quiet=False, stream=buf)
    vm = AggregatedVariantMetrics(
        variant_id="lmstudio/openai/gpt-oss-20b",
        is_eligible=True,
        exclusion_reasons=[],
        total_trials=5,
        passed=2,
        failed=1,
        timed_out=1,
        infrastructure_error=1,
        unscored=0,
        scored_denominator=4,
        strict_acceptance_rate=0.5,
        confidence_interval_95=None,
        task_summaries={},
        metrics={},
        duration=DurationStats(None, None),
        constituent_run_ids=["run-1"],
    )
    comparison = ExperimentComparison(
        experiment_id=config.experiment_id,
        config=config,
        eligible_variants={vm.variant_id: vm},
        reference_variants={},
        incompatible_runs=[],
        canonical_rankings=[vm.variant_id],
        warnings=[],
    )

    dashboard.on_experiment_complete(comparison)
    lines = buf.getvalue().splitlines()

    assert "Scored (P/F/T)" in buf.getvalue()
    assert "Other (I/U)" in buf.getvalue()
    assert "4 (2/1/1)" in buf.getvalue()
    assert "1/0" in buf.getvalue()
    assert max(map(len, lines)) <= 80
