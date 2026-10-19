"""
Multi-model experiment planning and sequential execution scheduler.

Enforces:
1. Strictly sequential local execution (at most 1 active GPU trial).
2. Deterministic, batched model trial expansion (all tasks/repetitions for Model A before Model B).
3. Explicitly authorized model transitions via LM Studio.
4. Per-trial dispatch reservation and recovery state preservation.
5. Incremental experiment persistence and comparison aggregation via benchmark_core.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import hashlib
from pathlib import Path
import platform
import random
from typing import Any, Optional

from benchmark_core import (
    Experiment,
    ExperimentComparison,
    ExperimentConfig,
    ExperimentRunRef,
    RunInfo,
    TrialResult,
    TrialStatus,
    aggregate_experiment,
    append_result,
    format_utc_timestamp,
    generate_reports,
    save_experiment,
    save_run,
    summarize,
)

from . import __version__
from .attempt import run_attempt, run_cli_attempt
from .bridge import connected_bridge
from .evidence import EVIDENCE_LIMITS, Task, load_task
from .git_workspace import ISOLATION_POLICY
from .models_lifecycle import (
    CommandRunner,
    resolve_model_provider_and_key,
    transition_model,
)
from .results import base_metrics, trial_from_attempt, unavailable
from .runner import BUDGET_PROFILES
from .scratch import SCOPE_POLICY
from .state import reserved_trial

TrialCallback = Callable[["PlannedTrial", Optional[TrialResult]], None]
ModelCallback = Callable[[str, Optional[RunInfo], list[TrialResult]], None]
ExperimentCallback = Callable[[ExperimentComparison], None]


@dataclass(frozen=True, slots=True)
class PlannedTrial:
    """A single scheduled evaluation trial within an experiment."""

    trial_index: int  # 0-indexed position across entire experiment
    model_key: str
    task_id: str
    repetition: int
    total_trials: int
    run_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "trial_index": self.trial_index,
            "model_key": self.model_key,
            "task_id": self.task_id,
            "repetition": self.repetition,
            "total_trials": self.total_trials,
            "run_id": self.run_id,
        }


@dataclass(frozen=True, slots=True)
class ExperimentPlan:
    """Deterministic schedule for a multi-model benchmark experiment."""

    experiment_id: str
    config: ExperimentConfig
    planned_trials: list[PlannedTrial]
    model_keys: list[str]
    task_ids: list[str]
    repetitions: int
    budget_profile: str

    @property
    def total_trials(self) -> int:
        return len(self.planned_trials)

    def trials_for_model(self, model_key: str) -> list[PlannedTrial]:
        return [t for t in self.planned_trials if t.model_key == model_key]

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "config": self.config.to_dict(),
            "planned_trials": [t.to_dict() for t in self.planned_trials],
            "model_keys": list(self.model_keys),
            "task_ids": list(self.task_ids),
            "repetitions": self.repetitions,
            "budget_profile": self.budget_profile,
            "total_trials": self.total_trials,
        }


def expand_experiment_plan(
    config: ExperimentConfig,
    *,
    randomize_tasks: bool = False,
    run_id_prefix: str = "run",
) -> ExperimentPlan:
    """
    Expand an ExperimentConfig into a deterministic sequence of planned trials.

    Trials are strictly grouped by model key to prevent thrashing GPU memory.
    Within each model, tasks and repetitions are sequenced deterministically,
    or shuffled pseudo-randomly when randomize_tasks=True and config.random_seed is set.
    """
    planned_trials: list[PlannedTrial] = []
    total_trials_count = len(config.variant_ids) * len(config.task_ids) * config.repetitions
    trial_idx = 0

    rng = random.Random(config.random_seed) if config.random_seed is not None else random.Random(0)

    for model_key in config.variant_ids:
        # Create a stable or unique run_id for this model's constituent run
        # Sanitize model_key for safe filesystem path
        safe_model = model_key.replace("/", "_").replace(":", "_").replace("@", "_")
        run_id = f"{run_id_prefix}-{config.experiment_id}-{safe_model}"

        model_task_reps: list[tuple[str, int]] = []
        for task_id in config.task_ids:
            for rep in range(1, config.repetitions + 1):
                model_task_reps.append((task_id, rep))

        if randomize_tasks and config.random_seed is not None:
            rng.shuffle(model_task_reps)

        for task_id, rep in model_task_reps:
            planned_trials.append(
                PlannedTrial(
                    trial_index=trial_idx,
                    model_key=model_key,
                    task_id=task_id,
                    repetition=rep,
                    total_trials=total_trials_count,
                    run_id=run_id,
                )
            )
            trial_idx += 1

    return ExperimentPlan(
        experiment_id=config.experiment_id,
        config=config,
        planned_trials=planned_trials,
        model_keys=list(config.variant_ids),
        task_ids=list(config.task_ids),
        repetitions=config.repetitions,
        budget_profile=config.budget_profile,
    )


TrialExecutor = Callable[
    [PlannedTrial, Task, Path, Path, str, float, float, float],
    Awaitable[TrialResult],
]


class ExperimentScheduler:
    """
    Executes a multi-model ExperimentPlan sequentially with resource safety.
    """

    def __init__(
        self,
        plan: ExperimentPlan,
        *,
        task_dirs: dict[str, Path],
        reports_dir: Path,
        state_dir: Path,
        allow_model_transitions: bool = False,
        base_url: str = "http://127.0.0.1:4096",
        provider: str = "lmstudio",
        agent: str = "local-worker",
        lms_path: str = "lms",
        lms_runner: Optional[CommandRunner] = None,
        trial_executor: Optional[TrialExecutor] = None,
        on_trial_start: Optional[TrialCallback] = None,
        on_trial_complete: Optional[TrialCallback] = None,
        on_model_start: Optional[Callable[[str], None]] = None,
        on_model_complete: Optional[ModelCallback] = None,
        on_experiment_complete: Optional[ExperimentCallback] = None,
    ) -> None:
        self.plan = plan
        self.task_dirs = {k: Path(v).resolve() for k, v in task_dirs.items()}
        self.reports_dir = Path(reports_dir).resolve()
        self.state_dir = Path(state_dir).resolve()
        self.allow_model_transitions = allow_model_transitions
        self.base_url = base_url
        self.provider = provider
        self.agent = agent
        self.lms_path = lms_path
        self.lms_runner = lms_runner
        self.trial_executor = trial_executor

        # Event callbacks
        self.on_trial_start = on_trial_start
        self.on_trial_complete = on_trial_complete
        self.on_model_start = on_model_start
        self.on_model_complete = on_model_complete
        self.on_experiment_complete = on_experiment_complete

        # State tracking
        self.executed_trials: list[tuple[PlannedTrial, TrialResult]] = []
        self.completed_runs: list[tuple[RunInfo, list[TrialResult]]] = []
        self.run_refs: list[ExperimentRunRef] = []

    async def run(self) -> ExperimentComparison:
        """
        Execute all planned trials sequentially.

        Returns:
            The final ExperimentComparison object.
        """
        config = self.plan.config
        profile_cfg = BUDGET_PROFILES.get(config.budget_profile, BUDGET_PROFILES["canonical-60s"])
        task_seconds = float(profile_cfg["task_seconds"])
        grace_seconds = float(profile_cfg["grace_seconds"])
        verifier_seconds = 10.0

        experiment_dir = self.reports_dir / config.experiment_id
        experiment_dir.mkdir(parents=True, exist_ok=True)

        # Iterate model by model
        for model_key in self.plan.model_keys:
            if self.on_model_start:
                self.on_model_start(model_key)

            resolved_provider, resolved_model = resolve_model_provider_and_key(
                model_key, default_provider=self.provider
            )

            # 1. Ensure target model is loaded in LM Studio (only for lmstudio provider)
            if resolved_provider == "lmstudio":
                await transition_model(
                    resolved_model,
                    allow_transitions=self.allow_model_transitions,
                    lms_path=self.lms_path,
                    runner=self.lms_runner,
                )

            model_trials = self.plan.trials_for_model(model_key)
            if not model_trials:
                continue

            run_id = model_trials[0].run_id
            run_dir = experiment_dir / "runs" / run_id
            run_dir.mkdir(parents=True, exist_ok=True)

            # Build RunInfo
            fingerprint = hashlib.sha256()
            for tid in sorted(self.plan.task_ids):
                t_path = self.task_dirs[tid]
                for p in sorted(t_path.rglob("*")):
                    if p.is_file() and "__pycache__" not in p.parts:
                        fingerprint.update(p.relative_to(t_path).as_posix().encode())
                        fingerprint.update(hashlib.sha256(p.read_bytes()).digest())

            run_info = RunInfo(
                run_id=run_id,
                created_at=format_utc_timestamp(),
                suite_id=config.suite_id,
                suite_version=config.suite_version,
                task_ids=list(self.plan.task_ids),
                variants={model_key: {"provider": resolved_provider, "model": resolved_model}},
                repetitions=config.repetitions,
                scoring_basis=config.scoring_basis,
                environment={
                    "python": platform.python_version(),
                    "platform": platform.platform(),
                    "machine": platform.machine(),
                },
                metadata={
                    "budget_profile": config.budget_profile,
                    "comparison_eligible": profile_cfg.get("comparison_eligible", True),
                    "suite_fingerprint": fingerprint.hexdigest(),
                    "random_seed": config.random_seed,
                    "benchmark_version": __version__,
                    "isolation_policy": ISOLATION_POLICY,
                    "scope_policy": SCOPE_POLICY,
                    "evidence_limits": EVIDENCE_LIMITS.to_dict() if hasattr(EVIDENCE_LIMITS, "to_dict") else {},
                },
            )
            save_run(run_dir, run_info, overwrite=True)

            # 2. Execute trials for this model sequentially
            run_trial_results: list[TrialResult] = []
            for planned_trial in model_trials:
                if self.on_trial_start:
                    self.on_trial_start(planned_trial, None)

                task = load_task(self.task_dirs[planned_trial.task_id])
                evidence_dir = run_dir / "evidence" / f"trial-{planned_trial.trial_index + 1:03d}"

                if self.trial_executor is not None:
                    # Use custom/mock executor
                    result = await self.trial_executor(
                        planned_trial,
                        task,
                        run_dir,
                        evidence_dir,
                        self.base_url,
                        task_seconds,
                        grace_seconds,
                        verifier_seconds,
                    )
                else:
                    # Default execution via real bridge
                    result = await self._execute_real_trial(
                        planned_trial,
                        task,
                        run_dir,
                        evidence_dir,
                        task_seconds,
                        grace_seconds,
                        verifier_seconds,
                    )

                append_result(run_dir, result)
                run_trial_results.append(result)
                self.executed_trials.append((planned_trial, result))

                if self.on_trial_complete:
                    self.on_trial_complete(planned_trial, result)

            # Generate single run reports
            run_summary = summarize(run_info, run_trial_results)
            generate_reports(run_summary, run_dir, write=True)

            self.completed_runs.append((run_info, run_trial_results))

            # Build ExperimentRunRef
            run_ref = ExperimentRunRef(
                run_id=run_id,
                run_dir=str(run_dir.relative_to(self.reports_dir).as_posix()),
                variant_id=model_key,
                suite_id=config.suite_id,
                suite_version=config.suite_version,
                scoring_basis=config.scoring_basis,
                budget_profile=config.budget_profile,
                comparison_eligible=profile_cfg.get("comparison_eligible", True),
                exclusion_reasons=[] if profile_cfg.get("comparison_eligible", True) else [
                    f"Non-canonical budget profile '{config.budget_profile}'"
                ],
            )
            self.run_refs.append(run_ref)

            if self.on_model_complete:
                self.on_model_complete(model_key, run_info, run_trial_results)

            # Incremental experiment aggregation & saving
            comparison = aggregate_experiment(config, self.completed_runs)
            exp_manifest = Experiment(config=config, run_refs=self.run_refs)
            save_experiment(experiment_dir, exp_manifest, comparison=comparison, overwrite=True)

        # Final comparison
        final_comparison = aggregate_experiment(config, self.completed_runs)
        final_exp = Experiment(config=config, run_refs=self.run_refs)
        all_trials = [t for _, t in self.executed_trials]
        save_experiment(
            experiment_dir,
            final_exp,
            comparison=final_comparison,
            trials=all_trials,
            overwrite=True,
            generate_reports=True,
        )

        if self.on_experiment_complete:
            self.on_experiment_complete(final_comparison)

        return final_comparison

    async def _execute_real_trial(
        self,
        trial: PlannedTrial,
        task: Task,
        run_dir: Path,
        evidence_dir: Path,
        task_seconds: float,
        grace_seconds: float,
        verifier_seconds: float,
    ) -> TrialResult:
        """Run a single live trial via CLI worker (`agy`/`codex`) or OpenCodeBridge (`lmstudio`)."""
        resolved_provider, resolved_model = resolve_model_provider_and_key(
            trial.model_key, default_provider=self.provider
        )
        with reserved_trial(self.state_dir, evidence_dir) as guard:
            trial_res: Optional[TrialResult] = None
            cancelled = False
            failure = "UnknownError"
            try:
                if resolved_provider in ("gemini", "codex"):
                    evidence = await run_cli_attempt(
                        task,
                        guard,
                        workspace_root=self.state_dir / "workspaces",
                        evidence_dir=evidence_dir,
                        provider=resolved_provider,
                        model=resolved_model,
                        task_seconds=task_seconds,
                        grace_seconds=grace_seconds,
                        verifier_seconds=verifier_seconds,
                    )
                else:
                    async with connected_bridge(base_url=self.base_url) as bridge:
                        evidence = await run_attempt(
                            task,
                            bridge,
                            guard,
                            workspace_root=self.state_dir / "workspaces",
                            evidence_dir=evidence_dir,
                            provider=resolved_provider,
                            model=resolved_model,
                            agent=self.agent,
                            task_seconds=task_seconds,
                            grace_seconds=grace_seconds,
                            verifier_seconds=verifier_seconds,
                        )
                trial_res = trial_from_attempt(
                    evidence,
                    run_id=trial.run_id,
                    trial_id=f"trial-{trial.trial_index + 1:03d}",
                    task_id=trial.task_id,
                    variant_id=trial.model_key,
                    repetition=trial.repetition,
                    evidence_path=f"evidence/trial-{trial.trial_index + 1:03d}",
                )
            except asyncio.CancelledError:
                cancelled = True
            except Exception as exc:
                failure = type(exc).__name__

            if trial_res is None:
                metrics = base_metrics()
                metrics["agent.worker_first_pass"] = unavailable("boolean", "Infrastructure error")
                for key in ("duration.wall_ms", "duration.worker_ms", "duration.verification_ms"):
                    metrics[key] = unavailable("ms", "No completed first-attempt measurement")
                trial_res = TrialResult(
                    run_id=trial.run_id,
                    trial_id=f"trial-{trial.trial_index + 1:03d}",
                    task_id=trial.task_id,
                    variant_id=trial.model_key,
                    repetition=trial.repetition,
                    status=TrialStatus.INFRASTRUCTURE_ERROR,
                    metrics=metrics,
                    details={
                        "execution_error": "CallerCancelled" if cancelled else failure,
                        "evidence_path": f"evidence/trial-{trial.trial_index + 1:03d}",
                    },
                )

            if cancelled:
                raise asyncio.CancelledError()

            return trial_res
