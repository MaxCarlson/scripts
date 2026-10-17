"""Fixed-design estimation controller, resumption, locking, and reporting integration."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import asdict, replace
import time
from typing import Callable

from .cancellation import check_cancelled
from .engine import CompressionEngine
from .estimation_models import (
    EstimationBudget,
    EstimationPlan,
    EstimationProgress,
    EstimationResult,
    RecipeEstimate,
    RecipeObservation,
    RecipeSpec,
)
from .estimation_stats import allocate_confirmation, estimate_fixed
from .measurement import MeasurementJob, measure_jobs
from .plan_store import (
    append_plan_measurements,
    freeze_confirmation,
    load_plan,
    plan_execution_lock,
)
from .trial_budget import TrialBudget
from .workspace import CompressionWorkspace


def run_estimation(
    plan: EstimationPlan,
    *,
    engine: CompressionEngine,
    workspace: CompressionWorkspace | None = None,
    invocation_budget: EstimationBudget | None = None,
    threads: int = 4,
    on_progress: Callable[[EstimationProgress], None] | None = None,
) -> EstimationResult:
    """
    Coordinate bounded fixed-design estimation:
    1. Rejects accuracy-target requests until Task 8.
    2. Serializes writers per-plan using OS-backed plan lock.
    3. Evaluates prescribed pilot across all recipes.
    4. Freezes confirmation design once in plan before confirmation measurements.
    5. Evaluates requested per-recipe confirmation jobs without forcing a full matrix.
    6. Persists measurements promptly and computes fixed RecipeEstimates.
    """
    check_cancelled()

    # Task 8 gate: reject accuracy targets until certified sequential inference is implemented
    if plan.accuracy_pp is not None:
        raise ValueError(
            "Certified repeated-stopping accuracy target (--accuracy-pp) is not supported yet (requires Task 8); "
            "run fixed estimation without --accuracy-pp"
        )

    lock_ctx = plan_execution_lock(workspace, plan.plan_id) if workspace is not None else nullcontext()

    with lock_ctx:
        check_cancelled()
        # Refresh plan from workspace under lock if workspace is available
        if workspace is not None:
            plan = load_plan(workspace, plan.plan_id)

        plan.validate_design()

        effective_budget = invocation_budget or plan.budget
        trial_budget = TrialBudget(
            max_trials=effective_budget.max_new_encodes,
            max_runtime_seconds=effective_budget.max_runtime_seconds,
        )
        max_images = effective_budget.max_images

        members_by_id = {m.identity: m for m in plan.members}
        recipes_by_id = {r.identity: r for r in plan.recipes}

        # Index existing observations
        known_observations: dict[tuple[str, str], RecipeObservation] = {}
        for item in plan.measurements:
            obs = RecipeObservation(**item) if isinstance(item, dict) else item
            known_observations[(obs.recipe_id, obs.member_id)] = obs

        total_cache_hits = 0
        total_new_encodes = 0
        newly_admitted_sources = 0
        progress_seq = 0

        def emit_progress(
            stage: str,
            phase: str,
            active_recipe: str = "",
            completed: int = 0,
            total: int = 0,
            estimates: tuple[RecipeEstimate, ...] = (),
            stopping_reason: str | None = None,
        ):
            nonlocal progress_seq
            progress_seq += 1
            if on_progress is not None:
                rem_trials = trial_budget.remaining
                rem_seconds = (
                    max(0.0, trial_budget.deadline - time.monotonic())
                    if trial_budget.deadline is not None
                    else effective_budget.max_runtime_seconds
                )
                on_progress(
                    EstimationProgress(
                        sequence=progress_seq,
                        stage=stage,
                        phase=phase,
                        active_recipe=active_recipe,
                        completed_sources=completed,
                        total_sources=total,
                        new_encodes=total_new_encodes,
                        cache_hits=total_cache_hits,
                        remaining_trials=rem_trials,
                        remaining_seconds=rem_seconds,
                        estimates=estimates,
                        stopping_reason=stopping_reason,
                    )
                )

        # -------------------------------------------------------------
        # Stage 1: Pilot Evaluation
        # -------------------------------------------------------------
        emit_progress("pilot", "pilot_scheduling", total=len(plan.pilot_member_ids))

        pilot_jobs: list[MeasurementJob] = []
        for m_id in plan.pilot_member_ids:
            member = members_by_id[m_id]
            missing_recipes = [
                r
                for r in plan.recipes
                if (r.identity, m_id) not in known_observations or not known_observations[(r.identity, m_id)].complete
            ]
            if missing_recipes:
                pilot_jobs.append(MeasurementJob.from_member(plan.root, member, missing_recipes))

        if pilot_jobs:
            batch = measure_jobs(pilot_jobs, engine=engine, budget=trial_budget, threads=threads)
            total_cache_hits += batch.cache_hits
            total_new_encodes += batch.new_encodes
            newly_admitted_sources += batch.newly_admitted_sources
            for obs in batch.observations:
                known_observations[(obs.recipe_id, obs.member_id)] = obs

            new_dicts = [asdict(obs) for obs in batch.observations]
            if workspace is not None:
                plan = append_plan_measurements(workspace, plan.plan_id, new_dicts)
            else:
                plan = replace(plan, measurements=(*plan.measurements, *new_dicts))

        pilot_observations: list[RecipeObservation] = []
        pilot_complete = True
        for r in plan.recipes:
            for m_id in plan.pilot_member_ids:
                obs = known_observations.get((r.identity, m_id))
                if obs is None or not obs.complete:
                    pilot_complete = False
                if obs is not None:
                    pilot_observations.append(obs)

        emit_progress(
            "pilot",
            "pilot_completed" if pilot_complete else "pilot_incomplete",
            completed=len(plan.pilot_member_ids),
            total=len(plan.pilot_member_ids),
        )

        if not pilot_complete:
            stopping_reason = "pilot_incomplete"
            if trial_budget.is_exhausted:
                stopping_reason = (
                    "deadline_exceeded"
                    if trial_budget.deadline and time.monotonic() >= trial_budget.deadline
                    else "max_trials_reached"
                )
            return EstimationResult(
                plan=plan,
                estimates=(),
                stopping_reason=stopping_reason,
                stage="pilot",
                cache_hits=total_cache_hits,
                new_encodes=total_new_encodes,
                newly_admitted_sources=newly_admitted_sources,
                total_observations=len(known_observations),
            )

        # -------------------------------------------------------------
        # Stage 2: Freeze Confirmation Design
        # -------------------------------------------------------------
        if plan.confirmation is not None:
            confirmation_design = plan.confirmation
        else:
            confirmation_design = allocate_confirmation(plan, pilot_observations)
            if workspace is not None:
                plan = freeze_confirmation(workspace, plan.plan_id, confirmation_design)
            else:
                plan = replace(plan, confirmation=confirmation_design)

        emit_progress("confirmation", "design_frozen")

        # -------------------------------------------------------------
        # Stage 3: Confirmation Evaluation
        # -------------------------------------------------------------
        # Collect required confirmation pairs per member
        member_to_recipes: dict[str, list[RecipeSpec]] = {}
        for group in confirmation_design.groups:
            recipe = recipes_by_id[group.recipe_id]
            for m_id in group.selected_ids:
                obs = known_observations.get((recipe.identity, m_id))
                if obs is None or not obs.complete:
                    member_to_recipes.setdefault(m_id, []).append(recipe)

        confirmation_jobs: list[MeasurementJob] = []
        for m_id, needed_recipes in member_to_recipes.items():
            member = members_by_id[m_id]
            confirmation_jobs.append(MeasurementJob.from_member(plan.root, member, needed_recipes))

        # Respect image budget for newly admitted sources
        rem_images = max(0, max_images - newly_admitted_sources)
        if len(confirmation_jobs) > rem_images:
            confirmation_jobs = confirmation_jobs[:rem_images]

        if confirmation_jobs:
            batch = measure_jobs(confirmation_jobs, engine=engine, budget=trial_budget, threads=threads)
            total_cache_hits += batch.cache_hits
            total_new_encodes += batch.new_encodes
            newly_admitted_sources += batch.newly_admitted_sources
            for obs in batch.observations:
                known_observations[(obs.recipe_id, obs.member_id)] = obs

            new_dicts = [asdict(obs) for obs in batch.observations]
            if workspace is not None:
                plan = append_plan_measurements(workspace, plan.plan_id, new_dicts)
            else:
                plan = replace(plan, measurements=(*plan.measurements, *new_dicts))

        # -------------------------------------------------------------
        # Stage 4: Statistical Estimation
        # -------------------------------------------------------------
        confirmation_observations: list[RecipeObservation] = []
        confirmation_complete = True
        for group in confirmation_design.groups:
            for m_id in group.selected_ids:
                obs = known_observations.get((group.recipe_id, m_id))
                if obs is None or not obs.complete:
                    confirmation_complete = False
                if obs is not None:
                    confirmation_observations.append(obs)

        # Estimate fixed
        estimates: tuple[RecipeEstimate, ...] = ()
        try:
            estimates = estimate_fixed(
                plan,
                confirmation_design,
                pilot_observations,
                confirmation_observations,
            )
        except Exception:
            estimates = ()

        if confirmation_complete and all(e.complete for e in estimates):
            stopping_reason = "complete"
        elif trial_budget.is_exhausted:
            stopping_reason = (
                "deadline_exceeded"
                if trial_budget.deadline and time.monotonic() >= trial_budget.deadline
                else "max_trials_reached"
            )
        elif newly_admitted_sources >= max_images:
            stopping_reason = "max_images_reached"
        elif any(e.gaps for e in estimates):
            stopping_reason = "missing_group_coverage"
        else:
            stopping_reason = "incomplete_confirmation"

        emit_progress(
            "complete" if stopping_reason == "complete" else "confirmation",
            "finished",
            estimates=estimates,
            stopping_reason=stopping_reason,
        )

        last_complete = estimates if stopping_reason == "complete" else ()

        return EstimationResult(
            plan=plan,
            estimates=estimates,
            stopping_reason=stopping_reason,
            stage="complete" if stopping_reason == "complete" else "confirmation",
            cache_hits=total_cache_hits,
            new_encodes=total_new_encodes,
            newly_admitted_sources=newly_admitted_sources,
            total_observations=len(known_observations),
            last_complete_estimates=last_complete,
        )


def execute_estimate_operation(args, options, *, owner: str) -> int:
    """Execute or resume bounded statistical estimation and publish shared report."""
    from dataclasses import replace
    import json

    from .cache import create_analysis_cache
    from .engine import CompressionEngine, MEMORY_BUDGET_BYTES
    from .estimation_models import EstimationBudget, current_runtime_identity
    from .estimation_ui import EstimationProgressUI
    from .plan_store import load_plan, save_plan
    from .report_session import current_session
    from .sampling_plan import build_plan, load_population

    workspace = args._workspace
    population = load_population(workspace, owner=owner, filters=options.filters)
    runtime = current_runtime_identity()

    if options.plan_id:
        plan = load_plan(workspace, options.plan_id)
        if plan.population_id != population.population_id:
            raise ValueError("The saved plan belongs to a changed inventory/filter scope; rebuild it")
        if any(recipe.runtime_identity != runtime for recipe in plan.recipes):
            raise ValueError(
                "The saved plan uses a different runtime identity; rebuild it: compress plan ... (or verify codecs)"
            )
        if options.plan_recipes_explicit:
            requested = tuple(recipe for recipe in options.recipes)
            saved = tuple(replace(recipe, runtime_identity="") for recipe in plan.recipes)
            if requested != saved:
                raise ValueError("The requested recipe differs from the saved plan; rebuild it")
        if options.plan_seed_explicit and options.seed != plan.seed:
            raise ValueError("The requested seed differs from the saved plan; rebuild it")
        if options.allow_larger and not plan.allow_larger:
            raise ValueError("The requested allow-larger policy differs from the saved plan; rebuild it")

        invocation_budget = EstimationBudget(
            max_images=options.max_images if options.max_images is not None else plan.budget.max_images,
            max_new_encodes=options.max_trials if options.max_trials is not None else plan.budget.max_new_encodes,
            max_runtime_seconds=(
                options.max_time_seconds if options.max_time_seconds is not None else plan.budget.max_runtime_seconds
            ),
            pilot_images=plan.budget.pilot_images,
        )
    else:
        recipes = tuple(replace(recipe, runtime_identity=runtime) for recipe in options.recipes)
        budget = EstimationBudget(
            max_images=options.max_images or 512,
            max_new_encodes=options.max_trials or 2000,
            max_runtime_seconds=options.max_time_seconds or 300.0,
            pilot_images=64,
        )
        plan = build_plan(
            population,
            recipes,
            budget,
            seed=options.seed,
            accuracy_pp=options.accuracy_pp,
            allow_larger=options.allow_larger,
        )
        save_plan(workspace, plan)
        invocation_budget = budget

    session = current_session()
    if session is None:
        raise RuntimeError("Estimate report session was not initialized")

    cache = create_analysis_cache(args, workspace.target)
    mem_mb = getattr(args, "memory_budget_mib", None)
    engine = CompressionEngine(
        cache=cache,
        memory_budget_bytes=(mem_mb * 1024**2) if mem_mb else MEMORY_BUDGET_BYTES,
        memory_policy=getattr(args, "_memory_policy", None),
    )

    ui_enabled = not args.json and not getattr(args, "no_ui", False)
    threads = getattr(args, "threads", None) or 4
    with EstimationProgressUI(workspace.target, enabled=ui_enabled) as ui:
        result = run_estimation(
            plan,
            engine=engine,
            workspace=workspace,
            invocation_budget=invocation_budget,
            threads=threads,
            on_progress=ui.on_progress,
        )

    report, artifacts = session.estimate(result.plan, result, population_count=len(population.members))

    if args.json:
        payload = {
            "operation": "estimate",
            "plan": result.plan.to_dict(),
            "stopping_reason": result.stopping_reason,
            "stage": result.stage,
            "cache_hits": result.cache_hits,
            "new_encodes": result.new_encodes,
            "newly_admitted_sources": result.newly_admitted_sources,
            "total_observations": result.total_observations,
            "estimates": [
                {
                    "recipe_id": est.recipe_id,
                    "estimated_saved_bytes": est.estimated_saved_bytes,
                    "variance": est.variance,
                    "savings_percent": est.savings_percent,
                    "interval": est.interval,
                    "gaps": list(est.gaps),
                }
                for est in result.estimates
            ],
            "report_artifacts": artifacts,
            "report": {
                "title": report.title,
                "operation": report.operation,
                "status": report.status,
            },
        }
        print(json.dumps(payload, indent=2, allow_nan=False))

    return 0
