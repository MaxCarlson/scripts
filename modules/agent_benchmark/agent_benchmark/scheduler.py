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
from dataclasses import dataclass, replace
import hashlib
import json
import logging
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

from benchmark_core.conditions import contract_error
from .comparison_conditions import build_conditions, runtime_conditions
from . import __version__
from .attempt import run_attempt, run_cli_attempt
from .telemetry import ResourceLimitExceeded, RuntimeMemoryGuard
from .bridge import ModelConfigurationError, connected_bridge
from .evidence import EVIDENCE_LIMITS, Task, load_task
from .tool_profile import FILE_PROFILE, RETRIEVAL_PROFILE, STRUCTURAL_PROFILE
from .diagnostics import describe_trial
from .git_workspace import ISOLATION_POLICY
from .identity import ModelIdentity, resolve_lmstudio_identity
from .models_lifecycle import (
    CommandRunner,
    DEFAULT_BENCHMARK_CONTEXT_LENGTH,
    list_downloaded_models,
    resolve_model_provider_and_key,
    transition_model,
)
from .results import base_metrics, trial_from_attempt, unavailable
from .runner import BUDGET_PROFILES, reconcile_pending
from .scratch import SCOPE_POLICY
from .state import command_lock, reserved_trial

logger = logging.getLogger(__name__)

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
        max_ram_percent: float = 100.0,
        base_url: str = "http://127.0.0.1:4096",
        provider: str = "lmstudio",
        agent: str = "local-worker",
        lms_path: str = "lms",
        lms_runner: Optional[CommandRunner] = None,
        trial_executor: Optional[TrialExecutor] = None,
        tool_profile: str | None = None,
        inference_profile: dict[str, Any] | None = None,
        before_dispatch: Optional[Callable[[dict[str, Any]], None]] = None,
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
        self.max_ram_percent = max_ram_percent
        self.base_url = base_url
        self.provider = provider
        self.agent = agent
        self.lms_path = lms_path
        self.lms_runner = lms_runner
        self.trial_executor = trial_executor
        self.inference_profile = inference_profile
        self.before_dispatch = before_dispatch
        if tool_profile not in {None, FILE_PROFILE, RETRIEVAL_PROFILE, STRUCTURAL_PROFILE}:
            raise ValueError(f"Unsupported experiment tool profile: {tool_profile}")
        self.tool_profile = tool_profile

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
        self.model_identities: dict[str, ModelIdentity] = {}
        self.current_stage = "preflight"
        self.current_model: str | None = None

    async def run(self) -> ExperimentComparison:
        """
        Execute all planned trials while holding the host-wide model command lock.

        The lock covers preflight, model transitions, dispatch, and completion so
        another benchmark invocation cannot unload a model during this run.
        """
        with command_lock(self.state_dir):
            await reconcile_pending(
                state=self.state_dir, base_url=self.base_url, lock_held=True
            )
            try:
                return await self._run_locked()
            except BaseException as error:
                logger.exception(
                    "Experiment aborted; preserving completed runs experiment_id=%s",
                    self.plan.experiment_id,
                    extra={"event_type": "EXPERIMENT_ABORTED"},
                )
                self._persist_partial_results()
                experiment_dir = self.reports_dir / self.plan.experiment_id
                if experiment_dir.is_dir():
                    try:
                        failure = {"experiment_id": self.plan.experiment_id, "stage": self.current_stage,
                                   "model": self.current_model, "error_type": type(error).__name__,
                                   "message": str(error), "diagnostic_log": "benchmark.log"}
                        (experiment_dir / "experiment-failure.json").write_text(
                            json.dumps(failure, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
                        )
                    except OSError:
                        logger.exception("Could not persist experiment failure diagnostics")
                raise

    async def _run_locked(self) -> ExperimentComparison:
        """Run the plan with command_lock held by run()."""
        config = self.plan.config
        profile_cfg = BUDGET_PROFILES.get(config.budget_profile, BUDGET_PROFILES["canonical-120s"])
        task_seconds = float(profile_cfg["task_seconds"])
        grace_seconds = float(profile_cfg["grace_seconds"])
        verifier_seconds = 10.0
        context_length = int(config.metadata.get("requested_context_length", DEFAULT_BENCHMARK_CONTEXT_LENGTH))

        for task_dir in self.task_dirs.values():
            load_task(task_dir)  # Refuse unsupported execution profiles before any model transition.
        await self._preflight_local_models()

        experiment_dir = self.reports_dir / config.experiment_id
        experiment_dir.mkdir(parents=True, exist_ok=True)

        # Iterate model by model
        for model_key in self.plan.model_keys:
            self.current_model = model_key
            self.current_stage = "model_transition"
            logger.info("Model batch starting model=%s", model_key,
                        extra={"event_type": "MODEL_BATCH_START"})
            if self.on_model_start:
                self.on_model_start(model_key)

            resolved_provider, resolved_model = resolve_model_provider_and_key(
                model_key, default_provider=self.provider
            )

            # 1. Ensure target model is loaded in LM Studio (only for lmstudio provider)
            loaded_model = None
            if resolved_provider == "lmstudio":
                logger.info("Model transition requested model=%s runtime_key=%s", model_key, resolved_model,
                            extra={"event_type": "MODEL_TRANSITION_REQUEST"})
                loaded_model = await transition_model(
                    resolved_model,
                    allow_transitions=self.allow_model_transitions,
                    lms_path=self.lms_path,
                    context_length=context_length,
                    expected_model_size_bytes=(
                        self.model_identities[model_key].size_bytes
                        if model_key in self.model_identities else None
                    ),
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
                variants={model_key: {"provider": resolved_provider, "model": resolved_model,
                                      "effective_context_length": loaded_model.context_length if loaded_model else None}},
                repetitions=config.repetitions,
                scoring_basis=config.scoring_basis,
                environment={
                    "python": platform.python_version(),
                    "platform": platform.platform(),
                    "machine": platform.machine(),
                },
                metadata={
                    "budget_profile": config.budget_profile,
                    "requested_context_length": context_length,
                    "task_tool_profiles": {
                        tid: (self.tool_profile or load_task(self.task_dirs[tid]).opencode_tool_profile
                              if resolved_provider == "lmstudio" else "cli-shell-v1")
                        for tid in self.plan.task_ids
                    },
                    "effective_context_length": loaded_model.context_length if loaded_model else None,
                    "comparison_eligible": profile_cfg.get("comparison_eligible", True),
                    "suite_fingerprint": fingerprint.hexdigest(),
                    "random_seed": config.random_seed,
                    "benchmark_version": __version__,
                    "isolation_policy": ISOLATION_POLICY,
                    "scope_policy": SCOPE_POLICY,
                    "evidence_limits": EVIDENCE_LIMITS.to_dict() if hasattr(EVIDENCE_LIMITS, "to_dict") else {},
                    "model_identity": self.model_identities[model_key].to_dict()
                    if model_key in self.model_identities else None,
                    "requested_inference_profile": self.inference_profile,
                },
            )
            save_run(run_dir, run_info, overwrite=True)

            # 2. Execute trials for this model sequentially
            self.current_stage = "trial_execution"
            run_trial_results: list[TrialResult] = []
            for planned_trial in model_trials:
                if self.on_trial_start:
                    self.on_trial_start(planned_trial, None)

                task = load_task(self.task_dirs[planned_trial.task_id])
                if self.tool_profile is not None and resolved_provider == "lmstudio":
                    task = replace(task, opencode_tool_profile=self.tool_profile)
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
                        self.inference_profile,
                        self.before_dispatch,
                    )

                runtime = ({"kind": "injected", "version": "test-executor"} if self.trial_executor is not None else runtime_conditions(evidence_dir))
                conditions = build_conditions(self.task_dirs,
                    loaded_model.context_length if loaded_model else (context_length if self.trial_executor else None),
                    config.budget_profile, {"task_seconds": task_seconds, "grace_seconds": grace_seconds,
                                            "verifier_seconds": verifier_seconds}, runtime, provider=resolved_provider,
                    tool_profile=self.tool_profile)
                assignment = ({FILE_PROFILE: "B0", RETRIEVAL_PROFILE: "B2",
                               STRUCTURAL_PROFILE: "B3"}.get(self.tool_profile)
                              if resolved_provider == "lmstudio" else None)
                if assignment:
                    from benchmark_core.conditions import TOOL_INTERVENTION_PROFILES
                    run_info.metadata["intervention_contract"] = {
                        "schema": "declared-tool-intervention-v1",
                        "design_id": "local-agent-efficiency-b0-b2-b3-v1",
                        "factor": "tool_profile",
                        "allowed_differences": ["execution_profiles", "environment.runtime.allowed_tools",
                                                "environment.runtime.permissions_sha256"],
                        "conditions": {key: {"profile": profile, "allowed_tools": tools}
                                       for key, (profile, tools) in TOOL_INTERVENTION_PROFILES.items()},
                        "assignment": assignment,
                    }
                previous = run_info.metadata.get("comparison_contract")
                if previous is not None and previous != conditions:
                    run_info.metadata["comparison_contract_error"] = "Runtime conditions changed within this model batch"
                run_info.metadata["comparison_contract"] = (None if run_info.metadata.get("comparison_contract_error") else conditions)
                if "comparison_contract" not in config.metadata and contract_error(conditions) is None:
                    config.metadata["comparison_contract"] = conditions
                run_info.metadata["agent_runtime"] = runtime
                save_run(run_dir, run_info, overwrite=True)

                append_result(run_dir, result)
                run_trial_results.append(result)
                self.executed_trials.append((planned_trial, result))
                logger.info(
                    "Trial completed model=%s task=%s repetition=%s status=%s duration_wall_ms=%s "
                    "verifier_status=%s scope_compliance=%s budget_pass=%s execution_error=%s "
                    "worker_job_status=%s worker_diagnostic=%s",
                    planned_trial.model_key, planned_trial.task_id, planned_trial.repetition,
                    result.status.value if hasattr(result.status, "value") else result.status,
                    result.metrics.get("duration.wall_ms").value
                    if result.metrics.get("duration.wall_ms") else None,
                    result.details.get("verifier_status"),
                    result.metrics.get("agent.scope_compliance").value
                    if result.metrics.get("agent.scope_compliance") else None,
                    result.metrics.get("agent.budget_pass").value
                    if result.metrics.get("agent.budget_pass") else None,
                    result.details.get("execution_error"),
                    result.details.get("worker_job_status"),
                    result.details.get("worker_diagnostic"),
                    extra={"event_type": "TRIAL_COMPLETE"},
                )

                if self.on_trial_complete:
                    self.on_trial_complete(planned_trial, result)
                for diagnostic in describe_trial(result):
                    logger.info("Trial diagnostic model=%s task=%s repetition=%s detail=%s",
                                planned_trial.model_key, planned_trial.task_id, planned_trial.repetition, diagnostic,
                                extra={"event_type": "TRIAL_DIAGNOSTIC"})

                if result.details.get("execution_error") == "ResourceLimitExceeded":
                    self.completed_runs.append((run_info, run_trial_results))
                    self.run_refs.append(ExperimentRunRef(
                        run_id=run_id, run_dir=str(run_dir.relative_to(self.reports_dir).as_posix()),
                        variant_id=model_key, suite_id=config.suite_id, suite_version=config.suite_version,
                        scoring_basis=config.scoring_basis, budget_profile=config.budget_profile,
                        comparison_eligible=profile_cfg.get("comparison_eligible", True),
                        exclusion_reasons=[] if profile_cfg.get("comparison_eligible", True) else [
                            f"Non-canonical budget profile '{config.budget_profile}'"
                        ],
                    ))
                    raise ResourceLimitExceeded(
                        result.details.get("execution_diagnostic") or "Host memory limit exceeded; experiment halted."
                    )

            # Generate single run reports
            self.current_stage = "report_generation"
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

    def _persist_partial_results(self) -> None:
        """Write a usable partial experiment report after an aborted later stage."""
        if not self.completed_runs:
            return
        try:
            config = self.plan.config
            experiment_dir = self.reports_dir / config.experiment_id
            comparison = aggregate_experiment(config, self.completed_runs)
            manifest = Experiment(config=config, run_refs=self.run_refs)
            save_experiment(
                experiment_dir,
                manifest,
                comparison=comparison,
                trials=[result for _, result in self.executed_trials],
                overwrite=True,
                generate_reports=True,
            )
            logger.info(
                "Partial experiment reports saved experiment_id=%s completed_models=%s path=%s",
                config.experiment_id, len(self.completed_runs), experiment_dir,
                extra={"event_type": "PARTIAL_REPORT_SAVED"},
            )
        except Exception:
            logger.exception(
                "Failed to save partial experiment report experiment_id=%s",
                self.plan.experiment_id,
                extra={"event_type": "PARTIAL_REPORT_ERROR"},
            )

    async def _preflight_local_models(self) -> None:
        """Resolve exact local identities and verify provider readiness before any load or trial allocation."""
        if self.trial_executor is not None:
            return
        requests = []
        for model_key in self.plan.model_keys:
            provider, model = resolve_model_provider_and_key(model_key, default_provider=self.provider)
            if provider == "lmstudio":
                requests.append((provider, model))
        if not requests:
            return

        inventory = await list_downloaded_models(lms_path=self.lms_path, runner=self.lms_runner)
        self.model_identities = {
            model_key: resolve_lmstudio_identity(model, inventory)
            for model_key in self.plan.model_keys
            for provider, model in [resolve_model_provider_and_key(model_key, default_provider=self.provider)]
            if provider == "lmstudio"
        }
        requested_context = int(self.plan.config.metadata.get(
            "requested_context_length", DEFAULT_BENCHMARK_CONTEXT_LENGTH
        ))
        if requested_context <= 0:
            raise ValueError("requested_context_length must be positive")
        for identity in self.model_identities.values():
            if not identity.max_context_length:
                raise ValueError(
                    f"LM Studio did not report a maximum context for '{identity.runtime_model_id}'; "
                    "cannot validate the requested benchmark context."
                )
            if requested_context > identity.max_context_length:
                raise ValueError(
                    f"Requested context {requested_context} exceeds maximum {identity.max_context_length} "
                    f"for '{identity.runtime_model_id}'."
                )

        validation_error: Exception | None = None
        async with connected_bridge(base_url=self.base_url) as bridge:
            try:
                await bridge.validate_provider("lmstudio")
            except Exception as error:
                # Raise only after the adapter context exits normally, avoiding TaskGroup-wrapped diagnostics.
                validation_error = error
        if validation_error is not None:
            raise validation_error

    async def _execute_real_trial(
        self,
        trial: PlannedTrial,
        task: Task,
        run_dir: Path,
        evidence_dir: Path,
        task_seconds: float,
        grace_seconds: float,
        verifier_seconds: float,
        inference_profile: dict[str, Any] | None = None,
        before_dispatch: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> TrialResult:
        """Run a single live trial via CLI worker (`agy`/`codex`) or OpenCodeBridge (`lmstudio`)."""
        resolved_provider, resolved_model = resolve_model_provider_and_key(
            trial.model_key, default_provider=self.provider
        )
        dispatch_callback = None
        if before_dispatch is not None:
            benchmark_trial_id = f"trial-{trial.trial_index + 1:03d}"
            monitor_trial_id = f"{trial.run_id}/{benchmark_trial_id}"

            def dispatch_callback(details: dict[str, Any]) -> None:
                before_dispatch({
                    **details,
                    "run_id": trial.run_id,
                    "trial_id": benchmark_trial_id,
                    "monitor_trial_id": monitor_trial_id,
                    "task_id": trial.task_id,
                })

        with reserved_trial(self.state_dir, evidence_dir, lock_held=True) as guard:
            trial_res: Optional[TrialResult] = None
            cancelled = False
            failure = "UnknownError"
            failure_message: str | None = None
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
                            model_identity=self.model_identities.get(trial.model_key),
                            resource_check=RuntimeMemoryGuard(max_ram_pct=self.max_ram_percent),
                            task_seconds=task_seconds,
                            grace_seconds=grace_seconds,
                            verifier_seconds=verifier_seconds,
                            inference_profile=inference_profile,
                            before_dispatch=dispatch_callback,
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
                logger.exception(
                    "Trial execution raised model=%s task=%s repetition=%s",
                    trial.model_key, trial.task_id, trial.repetition,
                    extra={"event_type": "TRIAL_EXCEPTION"},
                )
                failure = type(exc).__name__
                if isinstance(exc, ModelConfigurationError):
                    failure_message = str(exc)
                journal_path = evidence_dir / "lifecycle.json"
                if failure_message is None and journal_path.is_file():
                    try:
                        journal = json.loads(journal_path.read_text(encoding="utf-8"))
                        if journal.get("stage") == "preflight_failed":
                            failure_message = journal.get("diagnostic_message")
                    except (OSError, json.JSONDecodeError):
                        pass

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
                        **({"execution_error_message": failure_message} if failure_message else {}),
                        "evidence_path": f"evidence/trial-{trial.trial_index + 1:03d}",
                    },
                )

            if cancelled:
                raise asyncio.CancelledError()

            return trial_res
