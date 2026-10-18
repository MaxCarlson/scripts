"""Bounded actual-encode measurement runner, shared decode, and typed observation emission."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextvars import copy_context
from dataclasses import dataclass
import os
from pathlib import Path
import time
from typing import Sequence

from PIL import Image

from .cancellation import check_cancelled
from .engine import (
    MEMORY_BUDGET_BYTES,
    CompressionEngine,
    resolve_output_format,
)
from .estimation_models import PopulationMember, RecipeObservation, RecipeSpec
from .models import CompressionStrategy, ImageMetadata, ImageResult
from .scheduler import MemoryScheduler
from .timing import phase
from .trial_budget import BudgetExceeded, TrialBudget, active_trial_scope


def recipe_to_strategy(recipe: RecipeSpec) -> CompressionStrategy:
    """Map immutable recipe specification to internal execution strategy."""
    return CompressionStrategy(
        name=recipe.identity,
        format=recipe.format,  # type: ignore[arg-type]
        mode=recipe.mode,  # type: ignore[arg-type]
        quality=recipe.quality if recipe.quality is not None else 80,
        perceptual_target=recipe.perceptual_target,
        method=recipe.effort,
        allow_larger=(recipe.retained_original_policy == "allow-larger"),
        allow_lossy=True,
        encoder=recipe.encoder,
    )


@dataclass(frozen=True, slots=True)
class MeasurementJob:
    """A unit of measurement evaluation targeting one source image and explicit recipes."""

    source_identity: str
    recipes: tuple[RecipeSpec, ...]
    path: Path
    fingerprint: tuple[int | str, ...] = ()
    input_bytes: int = 0

    @classmethod
    def from_member(
        cls,
        root: Path,
        member: PopulationMember,
        recipes: Sequence[RecipeSpec],
    ) -> "MeasurementJob":
        path = root / member.relative_path
        return cls(
            source_identity=member.identity,
            recipes=tuple(recipes),
            path=path,
            fingerprint=member.fingerprint,
            input_bytes=member.size_bytes or 0,
        )

    @classmethod
    def from_path(
        cls,
        path: Path,
        recipes: Sequence[RecipeSpec],
        source_identity: str = "",
        fingerprint: tuple[int | str, ...] = (),
    ) -> "MeasurementJob":
        resolved = path.resolve()
        size = path.stat().st_size if path.exists() else 0
        return cls(
            source_identity=source_identity or str(resolved),
            recipes=tuple(recipes),
            path=path,
            fingerprint=fingerprint,
            input_bytes=size,
        )


@dataclass(frozen=True, slots=True)
class MeasurementBatch:
    """Aggregate result of a bounded measurement run."""

    observations: tuple[RecipeObservation, ...]
    newly_admitted_sources: int
    cache_hits: int
    new_encodes: int
    stopping_reason: str = "complete"


def _evaluate_single_job(
    job: MeasurementJob,
    engine: CompressionEngine,
    budget: TrialBudget,
    callbacks: object | None,
) -> tuple[list[RecipeObservation], int, int]:
    """
    Process one MeasurementJob:
    1. Checks cache for each recipe.
    2. For uncached recipes, opens and decodes the source image once.
    3. Runs each uncached recipe under active trial permit.
    4. Caches validated results and emits RecipeObservations.
    """
    check_cancelled()
    observations: list[RecipeObservation] = []
    cache_hits = 0
    new_encodes = 0

    input_size = job.input_bytes
    if input_size <= 0 and job.path.exists():
        input_size = job.path.stat().st_size

    # Phase 1: Check cache for all recipes
    uncached_recipes: list[RecipeSpec] = []
    for recipe in job.recipes:
        strat = recipe_to_strategy(recipe)
        cached = engine.cache.get(job.path, strat)
        if cached is not None and not cached.error:
            cache_hits += 1
            kept = cached.skipped and (cached.compressed_bytes >= input_size) and not strat.allow_larger
            if not strat.allow_larger and cached.compressed_bytes >= input_size:
                state = "retained_by_policy"
                retained_bytes = input_size
            else:
                state = "measured"
                retained_bytes = cached.compressed_bytes

            obs = RecipeObservation(
                member_id=job.source_identity,
                recipe_id=recipe.identity,
                fingerprint=job.fingerprint,
                runtime_identity=recipe.runtime_identity,
                input_bytes=input_size,
                retained_bytes=retained_bytes,
                elapsed_seconds=cached.elapsed_s,
                state=state,
            )
            observations.append(obs)
            if callbacks and hasattr(callbacks, "on_observation"):
                callbacks.on_observation(obs)
        else:
            uncached_recipes.append(recipe)

    if not uncached_recipes:
        return observations, cache_hits, new_encodes

    # Phase 2: For uncached recipes, verify budget and decode image once
    if budget.is_exhausted:
        for recipe in uncached_recipes:
            obs = RecipeObservation(
                member_id=job.source_identity,
                recipe_id=recipe.identity,
                fingerprint=job.fingerprint,
                runtime_identity=recipe.runtime_identity,
                input_bytes=input_size,
                retained_bytes=None,
                elapsed_seconds=0.0,
                state="not_started" if budget.attempted == 0 else "interrupted",
            )
            observations.append(obs)
            if callbacks and hasattr(callbacks, "on_observation"):
                callbacks.on_observation(obs)
        return observations, cache_hits, new_encodes

    if not job.path.is_file():
        for recipe in uncached_recipes:
            obs = RecipeObservation(
                member_id=job.source_identity,
                recipe_id=recipe.identity,
                fingerprint=job.fingerprint,
                runtime_identity=recipe.runtime_identity,
                input_bytes=input_size,
                retained_bytes=None,
                elapsed_seconds=0.0,
                state="failed",
            )
            observations.append(obs)
            if callbacks and hasattr(callbacks, "on_observation"):
                callbacks.on_observation(obs)
        return observations, cache_hits, new_encodes

    # Open image once for all uncached recipes
    try:
        with phase("source_decode"), Image.open(job.path) as source_im:
            if source_im.width * source_im.height > 40_000_000:
                raise ValueError("Image exceeds enforced 40-million-pixel decode limit")
            source_im.load()
            orig_meta = ImageMetadata(
                job.path,
                source_im.format or "PNG",
                source_im.width,
                source_im.height,
                input_size,
            )

            for recipe in uncached_recipes:
                check_cancelled()
                if budget.is_exhausted:
                    obs = RecipeObservation(
                        member_id=job.source_identity,
                        recipe_id=recipe.identity,
                        fingerprint=job.fingerprint,
                        runtime_identity=recipe.runtime_identity,
                        input_bytes=input_size,
                        retained_bytes=None,
                        elapsed_seconds=0.0,
                        state="interrupted",
                    )
                    observations.append(obs)
                    if callbacks and hasattr(callbacks, "on_observation"):
                        callbacks.on_observation(obs)
                    continue

                strat = recipe_to_strategy(recipe)
                permit = None

                def on_attempt():
                    nonlocal new_encodes
                    new_encodes += 1

                try:
                    permit = budget.admit(recipe.identity)
                    with active_trial_scope(budget, recipe.identity, permit=permit, on_attempt=on_attempt):
                        target_fmt = resolve_output_format(orig_meta, strat)
                        start_t = time.monotonic()
                        if strat.format == "auto":
                            target_fmt, encoded_bytes, ssim, encoder = engine._encode_auto(source_im, orig_meta, strat)
                        else:
                            encoded_bytes, ssim, encoder = engine._encode_verified(source_im, target_fmt, strat)
                        elapsed = time.monotonic() - start_t

                        compressed_bytes = len(encoded_bytes)
                        kept = (compressed_bytes >= input_size) and not strat.allow_larger
                        res = ImageResult(
                            input_path=job.path,
                            output_path=job.path,
                            original_bytes=input_size,
                            compressed_bytes=input_size if kept else compressed_bytes,
                            original_format=orig_meta.format,
                            output_format=target_fmt.upper(),
                            ssim=1.0 if kept else ssim,
                            elapsed_s=elapsed,
                            applied=False,
                            skipped=kept,
                            encoder=encoder,
                            candidate_bytes=compressed_bytes,
                        )
                        engine.cache.set(job.path, strat, res)

                        state = "retained_by_policy" if kept else "measured"
                        retained = input_size if kept else compressed_bytes
                        obs = RecipeObservation(
                            member_id=job.source_identity,
                            recipe_id=recipe.identity,
                            fingerprint=job.fingerprint,
                            runtime_identity=recipe.runtime_identity,
                            input_bytes=input_size,
                            retained_bytes=retained,
                            elapsed_seconds=elapsed,
                            state=state,
                        )
                        observations.append(obs)
                        if callbacks and hasattr(callbacks, "on_observation"):
                            callbacks.on_observation(obs)
                except BudgetExceeded:
                    obs = RecipeObservation(
                        member_id=job.source_identity,
                        recipe_id=recipe.identity,
                        fingerprint=job.fingerprint,
                        runtime_identity=recipe.runtime_identity,
                        input_bytes=input_size,
                        retained_bytes=None,
                        elapsed_seconds=0.0,
                        state="interrupted",
                    )
                    observations.append(obs)
                    if callbacks and hasattr(callbacks, "on_observation"):
                        callbacks.on_observation(obs)
                except Exception:
                    obs = RecipeObservation(
                        member_id=job.source_identity,
                        recipe_id=recipe.identity,
                        fingerprint=job.fingerprint,
                        runtime_identity=recipe.runtime_identity,
                        input_bytes=input_size,
                        retained_bytes=None,
                        elapsed_seconds=0.0,
                        state="failed",
                    )
                    observations.append(obs)
                    if callbacks and hasattr(callbacks, "on_observation"):
                        callbacks.on_observation(obs)
                finally:
                    if permit is not None and not permit.consumed:
                        permit.release()

    except Exception:
        # Failed during image open or decode
        for recipe in uncached_recipes:
            # If not already recorded
            if not any(obs.recipe_id == recipe.identity for obs in observations):
                obs = RecipeObservation(
                    member_id=job.source_identity,
                    recipe_id=recipe.identity,
                    fingerprint=job.fingerprint,
                    runtime_identity=recipe.runtime_identity,
                    input_bytes=input_size,
                    retained_bytes=None,
                    elapsed_seconds=0.0,
                    state="failed",
                )
                observations.append(obs)
                if callbacks and hasattr(callbacks, "on_observation"):
                    callbacks.on_observation(obs)

    return observations, cache_hits, new_encodes


def measure_jobs(
    jobs: Sequence[MeasurementJob],
    *,
    engine: CompressionEngine,
    budget: TrialBudget,
    threads: int = 4,
    callbacks: object | None = None,
) -> MeasurementBatch:
    """Execute image-recipe measurement jobs bounded by invocation TrialBudget and memory limits."""
    if threads < 1:
        raise ValueError("Thread count must be positive")

    total_jobs = len(jobs)
    if total_jobs == 0:
        return MeasurementBatch(
            observations=(),
            newly_admitted_sources=0,
            cache_hits=0,
            new_encodes=0,
            stopping_reason="complete",
        )

    # Estimate memory cost per job for MemoryScheduler
    scheduled_jobs: list[tuple[MeasurementJob, int]] = []
    for job in jobs:
        # Conservative memory estimate based on input bytes or default
        cost = max(64 * 1024 * 1024, min(job.input_bytes * 16, MEMORY_BUDGET_BYTES))
        scheduled_jobs.append((job, cost))

    memory_workers = max(1, engine.memory_budget_bytes // (64 * 1024 * 1024))
    max_workers = min(threads, os.cpu_count() or 4, memory_workers, len(scheduled_jobs))
    scheduler = MemoryScheduler(scheduled_jobs, engine.memory_budget_bytes, max_workers)

    all_observations: list[RecipeObservation] = []
    total_cache_hits = 0
    total_new_encodes = 0
    newly_admitted_sources = 0
    stopping_reason = "complete"

    # Single-thread execution fast path
    if max_workers == 1:
        for job, _ in scheduled_jobs:
            check_cancelled()
            if budget.is_exhausted:
                if budget.deadline is not None and time.monotonic() >= budget.deadline:
                    stopping_reason = "deadline_exceeded"
                else:
                    stopping_reason = "budget_exhausted"
                # Mark remaining recipes as interrupted or not_started
                for recipe in job.recipes:
                    obs = RecipeObservation(
                        member_id=job.source_identity,
                        recipe_id=recipe.identity,
                        fingerprint=job.fingerprint,
                        runtime_identity=recipe.runtime_identity,
                        input_bytes=job.input_bytes,
                        retained_bytes=None,
                        elapsed_seconds=0.0,
                        state="not_started" if budget.attempted == 0 else "interrupted",
                    )
                    all_observations.append(obs)
                continue

            newly_admitted_sources += 1
            obs_list, hits, encodes = _evaluate_single_job(job, engine, budget, callbacks)
            all_observations.extend(obs_list)
            total_cache_hits += hits
            total_new_encodes += encodes
            if callbacks and hasattr(callbacks, "on_job_completed"):
                callbacks.on_job_completed(job, obs_list, hits, encodes)

        if budget.is_exhausted and stopping_reason == "complete":
            stopping_reason = "max_trials_reached"

        return MeasurementBatch(
            observations=tuple(all_observations),
            newly_admitted_sources=newly_admitted_sources,
            cache_hits=total_cache_hits,
            new_encodes=budget.attempted,
            stopping_reason=stopping_reason,
        )

    # Multi-threaded execution using ThreadPoolExecutor and MemoryScheduler
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        active_futures: dict = {}
        has_pending = True

        while active_futures or has_pending:
            check_cancelled()

            # Schedule new tasks while capacity allows
            while len(active_futures) < max_workers and has_pending:
                if budget.is_exhausted:
                    if budget.deadline is not None and time.monotonic() >= budget.deadline:
                        stopping_reason = "deadline_exceeded"
                    else:
                        stopping_reason = "budget_exhausted"
                    has_pending = False
                    break

                job_tuple = scheduler.next_job()
                if job_tuple is None:
                    break

                job, cost = job_tuple
                newly_admitted_sources += 1

                ctx = copy_context()
                fut = executor.submit(ctx.run, _evaluate_single_job, job, engine, budget, callbacks)
                active_futures[fut] = (job, cost)

            if not active_futures:
                break

            done, _ = wait(active_futures.keys(), return_when=FIRST_COMPLETED)
            for fut in done:
                job, cost = active_futures.pop(fut)
                scheduler.release(cost)
                try:
                    obs_list, hits, encodes = fut.result()
                    all_observations.extend(obs_list)
                    total_cache_hits += hits
                    total_new_encodes += encodes
                    if callbacks and hasattr(callbacks, "on_job_completed"):
                        callbacks.on_job_completed(job, obs_list, hits, encodes)
                except BudgetExceeded:
                    interrupted_obs = []
                    for recipe in job.recipes:
                        obs = RecipeObservation(
                            member_id=job.source_identity,
                            recipe_id=recipe.identity,
                            fingerprint=job.fingerprint,
                            runtime_identity=recipe.runtime_identity,
                            input_bytes=job.input_bytes,
                            retained_bytes=None,
                            elapsed_seconds=0.0,
                            state="interrupted",
                        )
                        all_observations.append(obs)
                        interrupted_obs.append(obs)
                    if callbacks and hasattr(callbacks, "on_job_completed"):
                        callbacks.on_job_completed(job, interrupted_obs, 0, 0)
                except Exception:
                    failed_obs = []
                    for recipe in job.recipes:
                        obs = RecipeObservation(
                            member_id=job.source_identity,
                            recipe_id=recipe.identity,
                            fingerprint=job.fingerprint,
                            runtime_identity=recipe.runtime_identity,
                            input_bytes=job.input_bytes,
                            retained_bytes=None,
                            elapsed_seconds=0.0,
                            state="failed",
                        )
                        all_observations.append(obs)
                        failed_obs.append(obs)
                    if callbacks and hasattr(callbacks, "on_job_completed"):
                        callbacks.on_job_completed(job, failed_obs, 0, 0)

        # Handle any jobs left in scheduler.pending when budget was exhausted
        while scheduler.pending:
            job, _ = scheduler.pending.pop(0)
            for recipe in job.recipes:
                obs = RecipeObservation(
                    member_id=job.source_identity,
                    recipe_id=recipe.identity,
                    fingerprint=job.fingerprint,
                    runtime_identity=recipe.runtime_identity,
                    input_bytes=job.input_bytes,
                    retained_bytes=None,
                    elapsed_seconds=0.0,
                    state="not_started" if budget.attempted == 0 else "interrupted",
                )
                all_observations.append(obs)

    if budget.is_exhausted and stopping_reason == "complete":
        stopping_reason = "max_trials_reached"

    # Preserve original job / recipe ordering in observations
    order_index = {(job.source_identity, recipe.identity): i for i, job in enumerate(jobs) for recipe in job.recipes}
    all_observations.sort(key=lambda o: order_index.get((o.member_id, o.recipe_id), 0))

    return MeasurementBatch(
        observations=tuple(all_observations),
        newly_admitted_sources=newly_admitted_sources,
        cache_hits=total_cache_hits,
        new_encodes=budget.attempted,
        stopping_reason=stopping_reason,
    )
