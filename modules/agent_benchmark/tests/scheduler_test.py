"""
Unit tests for multi-model experiment planning and sequential execution scheduler.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
import pytest

from agent_benchmark.models_lifecycle import ModelTransitionNotAuthorizedError
from agent_benchmark.scheduler import (
    ExperimentScheduler,
    PlannedTrial,
    expand_experiment_plan,
)
from benchmark_core import (
    ExperimentComparison,
    ExperimentConfig,
    MetricQuality,
    MetricValue,
    RunInfo,
    TrialResult,
    TrialStatus,
)


@pytest.mark.asyncio
async def test_scheduler_rejects_missing_lmstudio_identity_before_trial_allocation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from agent_benchmark import scheduler as scheduler_module

    config = ExperimentConfig(
        experiment_id="exp-preflight-01",
        created_at="2026-10-19T10:00:00Z",
        suite_id="agent-smoke",
        suite_version="0.1.1",
        task_ids=["py-grep-smoke"],
        variant_ids=["qwen38-27b-q6k"],
        repetitions=2,
        scoring_basis="worker_first_attempt_full_success",
        budget_profile="canonical-60s",
    )
    plan = expand_experiment_plan(config)
    transition_commands: list[list[str]] = []

    class FakeBridge:
        async def validate_provider(self, provider):
            pytest.fail("Provider preflight must not run for a model absent from LM Studio")

    @asynccontextmanager
    async def fake_connected_bridge(**kwargs):
        yield FakeBridge()

    async def lms_runner(command: list[str]) -> tuple[int, str, str]:
        transition_commands.append(command)
        return 0, "[]", ""

    monkeypatch.setattr(scheduler_module, "connected_bridge", fake_connected_bridge)
    scheduler = ExperimentScheduler(
        plan,
        task_dirs={"py-grep-smoke": Path(__file__).resolve().parents[1] / "agent_benchmark" / "tasks" / "py-grep-smoke"},
        reports_dir=tmp_path / "reports",
        state_dir=tmp_path / "state",
        allow_model_transitions=True,
        lms_runner=lms_runner,
    )

    with pytest.raises(ValueError, match="no exact LM Studio model key matched"):
        await scheduler.run()

    assert transition_commands == [["lms", "ls", "--json"]]
    assert not (tmp_path / "reports" / config.experiment_id).exists()


@pytest.fixture
def sample_experiment_config() -> ExperimentConfig:
    return ExperimentConfig(
        experiment_id="exp-test-01",
        created_at="2026-10-19T10:00:00Z",
        suite_id="agent-smoke",
        suite_version="0.1.1",
        task_ids=["py-grep-smoke"],
        variant_ids=["qwen38-27b-q4km", "qwen38-27b-q6k"],
        repetitions=2,
        scoring_basis="worker_first_attempt_full_success",
        budget_profile="canonical-60s",
        random_seed=42,
    )


def test_expand_experiment_plan_ordering(sample_experiment_config: ExperimentConfig) -> None:
    """
    expand_experiment_plan must group trials strictly by model key,
    sequencing all tasks and repetitions for Model 1 before Model 2.
    """
    plan = expand_experiment_plan(sample_experiment_config)

    assert plan.experiment_id == "exp-test-01"
    assert plan.total_trials == 4  # 2 models * 1 task * 2 reps = 4
    assert len(plan.planned_trials) == 4

    # First two trials belong to first model
    assert plan.planned_trials[0].model_key == "qwen38-27b-q4km"
    assert plan.planned_trials[0].repetition == 1
    assert plan.planned_trials[0].trial_index == 0

    assert plan.planned_trials[1].model_key == "qwen38-27b-q4km"
    assert plan.planned_trials[1].repetition == 2
    assert plan.planned_trials[1].trial_index == 1

    # Next two trials belong to second model
    assert plan.planned_trials[2].model_key == "qwen38-27b-q6k"
    assert plan.planned_trials[2].repetition == 1
    assert plan.planned_trials[2].trial_index == 2

    assert plan.planned_trials[3].model_key == "qwen38-27b-q6k"
    assert plan.planned_trials[3].repetition == 2
    assert plan.planned_trials[3].trial_index == 3


def test_expand_experiment_plan_randomization_preserves_model_grouping() -> None:
    """
    Randomizing task order must only shuffle tasks within each model,
    never interleaving models.
    """
    config = ExperimentConfig(
        experiment_id="exp-rand-01",
        created_at="2026-10-19T10:00:00Z",
        suite_id="agent-smoke",
        suite_version="0.1.1",
        task_ids=["t1", "t2", "t3"],
        variant_ids=["m1", "m2"],
        repetitions=2,
        scoring_basis="worker_first_attempt_full_success",
        budget_profile="canonical-60s",
        random_seed=123,
    )

    plan = expand_experiment_plan(config, randomize_tasks=True)

    assert plan.total_trials == 12
    # First 6 trials must be m1
    for t in plan.planned_trials[:6]:
        assert t.model_key == "m1"

    # Next 6 trials must be m2
    for t in plan.planned_trials[6:]:
        assert t.model_key == "m2"


@pytest.mark.asyncio
async def test_scheduler_sequential_execution_and_aggregation(
    tmp_path: Path,
    sample_experiment_config: ExperimentConfig,
    monkeypatch,
) -> None:
    """
    Test end-to-end scheduler execution with mock model manager and mock trial executor.
    Asserts:
    - At most 1 trial active at any time.
    - All callbacks fire in order.
    - Incremental and final persistence of experiment artifacts.
    - Canonical rankings and Wilson intervals computed.
    """
    from agent_benchmark import models_lifecycle
    from agent_benchmark.telemetry import ResourceSnapshot

    monkeypatch.setattr(models_lifecycle, "collect_resource_snapshot", lambda: ResourceSnapshot(
        ram_pct=40, ram_available_bytes=32 * 1024**3,
        gpu_memory_used_bytes=4 * 1024**3, gpu_memory_total_bytes=32 * 1024**3,
    ))
    task_dir = Path(__file__).resolve().parents[1] / "agent_benchmark" / "tasks" / "py-grep-smoke"
    reports_dir = tmp_path / "reports"
    state_dir = tmp_path / "state"

    plan = expand_experiment_plan(sample_experiment_config)

    active_concurrent_trials = 0
    max_concurrent_observed = 0
    trial_start_count = 0
    trial_complete_count = 0
    models_started: list[str] = []
    models_completed: list[str] = []
    final_comparison_holder: list[ExperimentComparison] = []

    # Mock LMS runner simulating loaded model switching
    current_loaded_key = "qwen38-27b-q4km"

    async def mock_lms_runner(cmd: list[str]) -> tuple[int, str, str]:
        nonlocal current_loaded_key
        if cmd == ["lms", "ps", "--json"]:
            if current_loaded_key:
                return 0, json.dumps([{
                    "identifier": current_loaded_key,
                    "modelKey": current_loaded_key,
                    "status": "idle",
                    "contextLength": 16384,
                    "sizeBytes": 16000000000,
                    "maxContextLength": 262144,
                }]), ""
            return 0, "[]", ""
        elif cmd == ["lms", "unload", "-a"]:
            current_loaded_key = ""
            return 0, "Unloaded", ""
        elif len(cmd) >= 3 and cmd[:2] == ["lms", "load"]:
            if "--estimate-only" in cmd:
                return 0, "Estimated GPU Memory: 18 GiB\nEstimated Total Memory: 22 GiB", ""
            current_loaded_key = cmd[2]
            return 0, f"Loaded {current_loaded_key}", ""
        return 0, "", ""

    # Mock trial executor
    async def mock_trial_executor(
        trial: PlannedTrial,
        task,
        run_dir: Path,
        evidence_dir: Path,
        base_url: str,
        task_seconds: float,
        grace_seconds: float,
        verifier_seconds: float,
    ) -> TrialResult:
        nonlocal active_concurrent_trials, max_concurrent_observed
        active_concurrent_trials += 1
        max_concurrent_observed = max(max_concurrent_observed, active_concurrent_trials)

        # Simulate execution
        active_concurrent_trials -= 1

        # Model 1 passes, Model 2 fails
        status = TrialStatus.PASSED if trial.model_key == "qwen38-27b-q4km" else TrialStatus.FAILED
        return TrialResult(
            run_id=trial.run_id,
            trial_id=f"trial-{trial.trial_index + 1:03d}",
            task_id=trial.task_id,
            variant_id=trial.model_key,
            repetition=trial.repetition,
            status=status,
            metrics={
                "duration.wall_ms": MetricValue(1250.0, "ms", "timer", MetricQuality.MEASURED)
            },
            details={"evidence_path": f"evidence/trial-{trial.trial_index + 1:03d}"},
        )

    def on_trial_start(trial: PlannedTrial, res: TrialResult | None) -> None:
        nonlocal trial_start_count
        trial_start_count += 1

    def on_trial_complete(trial: PlannedTrial, res: TrialResult | None) -> None:
        nonlocal trial_complete_count
        trial_complete_count += 1

    def on_model_start(model_key: str) -> None:
        models_started.append(model_key)

    def on_model_complete(model_key: str, info: RunInfo | None, trials: list[TrialResult]) -> None:
        models_completed.append(model_key)

    def on_exp_complete(comp: ExperimentComparison) -> None:
        final_comparison_holder.append(comp)

    scheduler = ExperimentScheduler(
        plan,
        task_dirs={"py-grep-smoke": task_dir},
        reports_dir=reports_dir,
        state_dir=state_dir,
        allow_model_transitions=True,
        lms_runner=mock_lms_runner,
        trial_executor=mock_trial_executor,
        on_trial_start=on_trial_start,
        on_trial_complete=on_trial_complete,
        on_model_start=on_model_start,
        on_model_complete=on_model_complete,
        on_experiment_complete=on_exp_complete,
    )

    comparison = await scheduler.run()

    # Verification: Strictly 1 active trial on GPU
    assert max_concurrent_observed == 1
    assert active_concurrent_trials == 0

    # Verification: Callbacks
    assert trial_start_count == 4
    assert trial_complete_count == 4
    assert models_started == ["qwen38-27b-q4km", "qwen38-27b-q6k"]
    assert models_completed == ["qwen38-27b-q4km", "qwen38-27b-q6k"]
    assert len(final_comparison_holder) == 1

    # Verification: Comparison outcome
    assert comparison.canonical_rankings == ["qwen38-27b-q4km", "qwen38-27b-q6k"]
    assert comparison.eligible_variants["qwen38-27b-q4km"].strict_acceptance_rate == 1.0
    assert comparison.eligible_variants["qwen38-27b-q6k"].strict_acceptance_rate == 0.0

    # Verification: Persistent experiment artifacts
    exp_dir = reports_dir / "exp-test-01"
    assert (exp_dir / "experiment.json").is_file()
    assert (exp_dir / "run-references.json").is_file()
    assert (exp_dir / "comparison.json").is_file()

    # Constituent runs persisted
    assert len(list((exp_dir / "runs").iterdir())) == 2


@pytest.mark.asyncio
async def test_scheduler_saves_partial_reports_after_later_model_transition_fails(
    tmp_path: Path,
    sample_experiment_config: ExperimentConfig,
    monkeypatch,
) -> None:
    from agent_benchmark import scheduler as scheduler_module

    async def fake_transition(model_key: str, **kwargs):
        if model_key == "qwen38-27b-q6k":
            raise RuntimeError("simulated model load failure")

    async def fake_trial_executor(trial, *args):
        return TrialResult(
            run_id=trial.run_id,
            trial_id=f"trial-{trial.trial_index + 1:03d}",
            task_id=trial.task_id,
            variant_id=trial.model_key,
            repetition=trial.repetition,
            status=TrialStatus.PASSED,
            metrics={"duration.wall_ms": MetricValue(100.0, "ms", "timer", MetricQuality.MEASURED)},
        )

    monkeypatch.setattr(scheduler_module, "transition_model", fake_transition)
    task_dir = Path(__file__).resolve().parents[1] / "agent_benchmark" / "tasks" / "py-grep-smoke"
    scheduler = ExperimentScheduler(
        expand_experiment_plan(sample_experiment_config),
        task_dirs={"py-grep-smoke": task_dir},
        reports_dir=tmp_path / "reports",
        state_dir=tmp_path / "state",
        allow_model_transitions=True,
        trial_executor=fake_trial_executor,
    )

    with pytest.raises(RuntimeError, match="simulated model load failure"):
        await scheduler.run()

    experiment_dir = tmp_path / "reports" / sample_experiment_config.experiment_id
    assert (experiment_dir / "comparison.json").is_file()
    assert (experiment_dir / "report.md").is_file()
    manifest = json.loads((experiment_dir / "experiment.json").read_text(encoding="utf-8"))
    assert [item["variant_id"] for item in manifest["run_refs"]] == ["qwen38-27b-q4km"]
    failure = json.loads((experiment_dir / "experiment-failure.json").read_text(encoding="utf-8"))
    assert failure["stage"] == "model_transition"
    assert failure["model"] == "qwen38-27b-q6k"
    assert failure["error_type"] == "RuntimeError"
    assert failure["message"] == "simulated model load failure"


@pytest.mark.asyncio
async def test_scheduler_unauthorized_model_transition_halts_safely(
    tmp_path: Path,
    sample_experiment_config: ExperimentConfig,
    monkeypatch,
) -> None:
    """
    If target model is not loaded and allow_model_transitions=False,
    scheduler must raise ModelTransitionNotAuthorizedError and halt safely.
    """
    task_dir = Path(__file__).resolve().parents[1] / "agent_benchmark" / "tasks" / "py-grep-smoke"
    reports_dir = tmp_path / "reports"
    state_dir = tmp_path / "state"

    plan = expand_experiment_plan(sample_experiment_config)

    # Empty loaded models
    async def mock_lms_runner_empty(cmd: list[str]) -> tuple[int, str, str]:
        if cmd[1:2] == ["ls"]:
            return 0, json.dumps([{"modelKey": "qwen38-27b-q4km", "displayName": "Qwen Q4",
                                       "type": "llm", "quantization": {"name": "Q4_K_M"},
                                       "maxContextLength": 262144},
                                  {"modelKey": "qwen38-27b-q6k", "displayName": "Qwen Q6",
                                       "type": "llm", "quantization": {"name": "Q6_K"},
                                       "maxContextLength": 262144}]), ""
        return 0, "[]", ""

    from agent_benchmark import scheduler as scheduler_module

    class FakeBridge:
        async def validate_provider(self, provider):
            return None

    @asynccontextmanager
    async def fake_connected_bridge(**kwargs):
        yield FakeBridge()

    monkeypatch.setattr(scheduler_module, "connected_bridge", fake_connected_bridge)

    scheduler = ExperimentScheduler(
        plan,
        task_dirs={"py-grep-smoke": task_dir},
        reports_dir=reports_dir,
        state_dir=state_dir,
        allow_model_transitions=False,  # Not authorized!
        lms_runner=mock_lms_runner_empty,
    )

    with pytest.raises(ModelTransitionNotAuthorizedError, match="not authorized"):
        await scheduler.run()
