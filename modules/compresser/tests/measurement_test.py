"""Tests for bounded actual-encode measurement runner, shared decode, and states."""

from __future__ import annotations

from pathlib import Path
import time
from PIL import Image
import pytest

from compresser.cache import AnalysisCache
from compresser.engine import CompressionEngine
from compresser.estimation_models import RecipeObservation, RecipeSpec
from compresser.models import ImageMetadata
from compresser.measurement import (
    MeasurementBatch,
    MeasurementJob,
    measure_jobs,
    recipe_to_strategy,
)
from compresser.trial_budget import TrialBudget


@pytest.fixture
def test_engine(tmp_path: Path) -> CompressionEngine:
    cache_path = tmp_path / "test_cache.sqlite"
    cache = AnalysisCache(path=cache_path)
    return CompressionEngine(cache=cache)


@pytest.fixture
def sample_test_images(tmp_path: Path) -> dict[str, Path]:
    out = {}

    # 1. Color JPEG
    p_jpg = tmp_path / "test_01.jpg"
    im1 = Image.new("RGB", (100, 100), color=(200, 100, 50))
    im1.save(p_jpg, format="JPEG", quality=90)
    out["jpeg"] = p_jpg

    # 2. Color PNG with transparency
    p_png = tmp_path / "test_02.png"
    im2 = Image.new("RGBA", (100, 100), color=(50, 150, 200, 128))
    im2.save(p_png, format="PNG")
    out["png"] = p_png

    # 3. WebP
    p_webp = tmp_path / "test_03.webp"
    im3 = Image.new("RGB", (100, 100), color=(80, 180, 80))
    im3.save(p_webp, format="WEBP", quality=80)
    out["webp"] = p_webp

    return out


def test_measure_jobs_single_recipe(test_engine: CompressionEngine, sample_test_images: dict[str, Path]):
    jpg_path = sample_test_images["jpeg"]
    recipe = RecipeSpec(
        format="webp",
        mode="lossy",
        quality=75,
        perceptual_target=0.95,
        encoder="pillow-webp",
        effort=4,
    )
    job = MeasurementJob.from_path(jpg_path, (recipe,))
    budget = TrialBudget(max_trials=5)

    batch = measure_jobs([job], engine=test_engine, budget=budget)
    assert isinstance(batch, MeasurementBatch)
    assert len(batch.observations) == 1
    obs = batch.observations[0]
    assert isinstance(obs, RecipeObservation)
    assert obs.state in ("measured", "retained_by_policy")
    assert obs.recipe_id == recipe.identity
    assert obs.complete is True
    assert budget.attempted == 1
    assert batch.new_encodes == 1
    assert batch.cache_hits == 0


def test_measure_jobs_cache_hits_consume_zero(test_engine: CompressionEngine, sample_test_images: dict[str, Path]):
    jpg_path = sample_test_images["jpeg"]
    recipe = RecipeSpec(
        format="webp",
        mode="lossy",
        quality=75,
        perceptual_target=0.95,
        encoder="pillow-webp",
        effort=4,
    )
    job = MeasurementJob.from_path(jpg_path, (recipe,))

    # First run: encodes and caches
    budget1 = TrialBudget(max_trials=5)
    batch1 = measure_jobs([job], engine=test_engine, budget=budget1)
    assert budget1.attempted == 1
    assert batch1.new_encodes == 1
    assert batch1.cache_hits == 0

    # Second run: must hit cache and consume ZERO attempts
    budget2 = TrialBudget(max_trials=5)
    batch2 = measure_jobs([job], engine=test_engine, budget=budget2)
    assert budget2.attempted == 0
    assert budget2.reserved == 0
    assert batch2.new_encodes == 0
    assert batch2.cache_hits == 1
    assert len(batch2.observations) == 1
    assert batch2.observations[0].complete is True


def test_measure_jobs_concurrent_cap_of_three(test_engine: CompressionEngine, tmp_path: Path):
    # Create 8 images
    jobs = []
    recipe = RecipeSpec(
        format="webp",
        mode="lossy",
        quality=80,
        perceptual_target=0.95,
        encoder="pillow-webp",
        effort=4,
    )
    for i in range(8):
        p = tmp_path / f"img_{i:02d}.png"
        im = Image.new("RGB", (60, 60), color=(i * 20, 100, 100))
        im.save(p, format="PNG")
        jobs.append(MeasurementJob.from_path(p, (recipe,)))

    cap = 3
    budget = TrialBudget(max_trials=cap)
    batch = measure_jobs(jobs, engine=test_engine, budget=budget, threads=4)

    assert budget.attempted == cap
    assert budget.reserved == 0
    assert batch.new_encodes == cap
    # The remaining jobs must be recorded as interrupted or not_started
    interrupted_or_not_started = [obs for obs in batch.observations if obs.state in ("interrupted", "not_started")]
    assert len(interrupted_or_not_started) == len(jobs) - cap
    assert batch.stopping_reason in ("budget_exhausted", "max_trials_reached")


def test_measure_jobs_perceptual_search_consumes_per_candidate(test_engine: CompressionEngine, sample_test_images: dict[str, Path]):
    jpg_path = sample_test_images["jpeg"]
    recipe = RecipeSpec(
        format="webp",
        mode="perceptual",
        quality=None,
        perceptual_target=0.995,
        encoder="pillow-webp",
        effort=4,
    )
    job = MeasurementJob.from_path(jpg_path, (recipe,))

    # Cap at 2 attempts: perceptual search needs multiple candidates, so it should stop at 2
    budget = TrialBudget(max_trials=2)
    batch = measure_jobs([job], engine=test_engine, budget=budget)

    assert budget.attempted == 2
    assert len(batch.observations) == 1
    obs = batch.observations[0]
    assert obs.state == "interrupted"
    assert obs.complete is False

    # Ensure no partial measurement was committed to cache for this strategy
    strat = recipe_to_strategy(recipe)
    assert test_engine.cache.get(jpg_path, strat) is None


def test_measure_jobs_auto_candidates_consume_per_candidate(test_engine: CompressionEngine, sample_test_images: dict[str, Path]):
    jpg_path = sample_test_images["jpeg"]
    recipe = RecipeSpec(
        format="auto",
        mode="lossy",
        quality=80,
        perceptual_target=0.99,
        encoder="auto",
        effort=4,
    )
    job = MeasurementJob.from_path(jpg_path, (recipe,))

    # Cap at 2 attempts: AUTO tests 3 formats (webp, png, jpeg), so cap of 2 must interrupt
    budget = TrialBudget(max_trials=2)
    batch = measure_jobs([job], engine=test_engine, budget=budget)

    assert budget.attempted == 2
    assert len(batch.observations) == 1
    assert batch.observations[0].state == "interrupted"


def test_measure_jobs_shared_decode_and_no_source_mutation(test_engine: CompressionEngine, sample_test_images: dict[str, Path]):
    png_path = sample_test_images["png"]
    stat_before = png_path.stat()
    bytes_before = png_path.read_bytes()

    # 3 recipes on the same source image
    r_webp = RecipeSpec(format="webp", mode="lossy", quality=80, perceptual_target=0.95, encoder="pillow-webp", effort=4)
    r_png = RecipeSpec(format="png", mode="lossless", quality=None, perceptual_target=0.95, encoder="pillow-png", effort=4)
    r_webp_ll = RecipeSpec(format="webp", mode="lossless", quality=None, perceptual_target=0.95, encoder="pillow-webp", effort=4)

    job = MeasurementJob.from_path(png_path, (r_webp, r_png, r_webp_ll))
    budget = TrialBudget(max_trials=10)

    batch = measure_jobs([job], engine=test_engine, budget=budget)
    assert len(batch.observations) == 3
    for obs in batch.observations:
        assert obs.complete is True

    # Check source file was NOT mutated in any way
    stat_after = png_path.stat()
    assert stat_before.st_size == stat_after.st_size
    assert stat_before.st_mtime_ns == stat_after.st_mtime_ns
    assert bytes_before == png_path.read_bytes()

    # Verify identical output to calling engine.compress_image directly
    for recipe in (r_webp, r_png, r_webp_ll):
        strat = recipe_to_strategy(recipe)
        meta = ImageMetadata(png_path, "PNG", 100, 100, len(bytes_before))
        direct_res = test_engine.compress_image(meta, strat, write_mode=False)
        cached_res = test_engine.cache.get(png_path, strat)
        assert cached_res is not None
        assert cached_res.compressed_bytes == direct_res.compressed_bytes


def test_measure_jobs_monotonic_deadline(test_engine: CompressionEngine, tmp_path: Path):
    jobs = []
    recipe = RecipeSpec(format="webp", mode="lossy", quality=80, perceptual_target=0.95, encoder="pillow-webp", effort=4)
    for i in range(5):
        p = tmp_path / f"dead_{i}.jpg"
        Image.new("RGB", (50, 50), color=(i * 30, 50, 50)).save(p, format="JPEG")
        jobs.append(MeasurementJob.from_path(p, (recipe,)))

    # Very short deadline
    budget = TrialBudget(max_trials=10, max_runtime_seconds=0.01)
    time.sleep(0.015)

    batch = measure_jobs(jobs, engine=test_engine, budget=budget)
    assert batch.stopping_reason in ("deadline_exceeded", "budget_exhausted")
    assert all(obs.state in ("not_started", "interrupted") for obs in batch.observations)
    assert budget.attempted == 0
