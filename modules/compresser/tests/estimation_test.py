"""Tests for fixed-design estimation controller, resumption, locking, and stopping reasons."""

from __future__ import annotations

from pathlib import Path
import time
from PIL import Image
import pytest

from compresser.cache import AnalysisCache
from compresser.engine import CompressionEngine
from compresser.estimation import run_estimation
from compresser.estimation_models import (
    EstimationBudget,
    EstimationPlan,
    EstimationProgress,
    EstimationResult,
    PopulationMember,
    PopulationView,
    RecipeSpec,
    current_runtime_identity,
)
from compresser.plan_store import load_plan, plan_execution_lock, save_plan
from compresser.sampling_plan import build_plan
from compresser.workspace import CompressionWorkspace, initialize_workspace, resolve_workspace


@pytest.fixture
def test_workspace(tmp_path: Path) -> tuple[CompressionWorkspace, CompressionEngine]:
    target_dir = tmp_path / "test_target"
    target_dir.mkdir()
    ws = resolve_workspace(target_dir, tmp_path, owner="compresser")
    initialize_workspace(ws)
    cache = AnalysisCache(path=ws.trial_cache_file)
    engine = CompressionEngine(cache=cache)
    return ws, engine


@pytest.fixture
def populated_plan(
    test_workspace: tuple[CompressionWorkspace, CompressionEngine],
) -> tuple[EstimationPlan, CompressionWorkspace, CompressionEngine]:
    ws, engine = test_workspace
    target = ws.target

    # Create 16 sample images with different sizes
    members = []
    for i in range(16):
        p = target / f"img_{i:02d}.png"
        size_dim = 50 + (i % 4) * 20
        im = Image.new("RGB", (size_dim, size_dim), color=(i * 15, 80, 120))
        im.save(p, format="PNG")
        stat = p.stat()
        members.append(
            PopulationMember(
                identity=f"img_{i:02d}.png",
                relative_path=f"img_{i:02d}.png",
                size_bytes=stat.st_size,
                group="small" if i < 8 else "medium",
                fingerprint=(stat.st_size, stat.st_mtime_ns),
                codec_class="eligible",
            )
        )

    pop = PopulationView(
        population_id="pop-test-01",
        root=target,
        owner="compresser",
        depth="headers",
        filters=(),
        completed=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        members=tuple(members),
    )

    r_webp = RecipeSpec(
        format="webp",
        mode="lossy",
        quality=80,
        perceptual_target=0.95,
        encoder="pillow-webp",
        effort=4,
        runtime_identity=current_runtime_identity(),
    )
    r_png = RecipeSpec(
        format="png",
        mode="lossless",
        quality=None,
        perceptual_target=0.95,
        encoder="pillow-png",
        effort=4,
        runtime_identity=current_runtime_identity(),
    )

    budget = EstimationBudget(max_images=16, max_new_encodes=100, max_runtime_seconds=60.0, pilot_images=4)
    plan = build_plan(pop, recipes=[r_webp, r_png], budget=budget, seed=42)
    save_plan(ws, plan)
    return plan, ws, engine


def test_run_estimation_rejects_accuracy_target(populated_plan):
    plan, ws, engine = populated_plan
    plan_with_accuracy = EstimationPlan.create(
        population_id=plan.population_id,
        root=plan.root,
        owner=plan.owner,
        depth=plan.depth,
        filters=plan.filters,
        inventory_completed=plan.inventory_completed,
        seed=plan.seed,
        accuracy_pp=1.0,  # Explicit accuracy target
        allow_larger=plan.allow_larger,
        recipes=plan.recipes,
        budget=plan.budget,
        strata=plan.strata,
        selected_member_ids=plan.selected_member_ids,
        recipe_quotas=plan.recipe_quotas,
        members=plan.members,
        pilot_member_ids=plan.pilot_member_ids,
    )

    with pytest.raises(ValueError, match="accuracy target.*Task 8"):
        run_estimation(plan_with_accuracy, engine=engine, workspace=ws)


def test_run_estimation_fixed_design_end_to_end(populated_plan):
    plan, ws, engine = populated_plan
    progress_events = []

    def on_progress(p: EstimationProgress):
        progress_events.append(p)

    res = run_estimation(plan, engine=engine, workspace=ws, on_progress=on_progress)
    assert isinstance(res, EstimationResult)
    assert res.stopping_reason == "complete"
    assert len(res.estimates) == 2
    for est in res.estimates:
        assert est.complete is True
        assert est.interval is not None

    # Check that plan was updated with confirmation design and measurements
    saved = load_plan(ws, plan.plan_id)
    assert saved.confirmation is not None
    assert len(saved.measurements) > 0
    assert res.new_encodes > 0


def test_run_estimation_resume_with_allowance(populated_plan):
    plan, ws, engine = populated_plan

    # Run 1: Bounded budget allowing only pilot
    budget1 = EstimationBudget(max_images=4, max_new_encodes=8, max_runtime_seconds=60.0, pilot_images=4)
    res1 = run_estimation(plan, engine=engine, workspace=ws, invocation_budget=budget1)

    saved1 = load_plan(ws, plan.plan_id)
    measurements1 = len(saved1.measurements)
    assert measurements1 > 0
    assert res1.new_encodes > 0

    # Run 2: Resume with larger budget to finish confirmation
    budget2 = EstimationBudget(max_images=16, max_new_encodes=100, max_runtime_seconds=60.0, pilot_images=4)
    res2 = run_estimation(saved1, engine=engine, workspace=ws, invocation_budget=budget2)

    saved2 = load_plan(ws, plan.plan_id)
    assert len(saved2.measurements) > measurements1
    # Ensure pilot images were not re-encoded in Run 2 (only new confirmation observations)
    assert res2.new_encodes == len(saved2.measurements) - measurements1
    assert res2.total_observations == len(saved2.measurements)


def test_run_estimation_recovers_unjournaled_cache(populated_plan):
    plan, ws, engine = populated_plan

    # Full run
    res1 = run_estimation(plan, engine=engine, workspace=ws)
    assert res1.stopping_reason == "complete"

    # Save a fresh plan without measurements
    clean_plan = EstimationPlan.create(
        population_id=plan.population_id,
        root=plan.root,
        owner=plan.owner,
        depth=plan.depth,
        filters=plan.filters,
        inventory_completed=plan.inventory_completed,
        seed=plan.seed,
        accuracy_pp=None,
        allow_larger=plan.allow_larger,
        recipes=plan.recipes,
        budget=plan.budget,
        strata=plan.strata,
        selected_member_ids=plan.selected_member_ids,
        recipe_quotas=plan.recipe_quotas,
        members=plan.members,
        pilot_member_ids=plan.pilot_member_ids,
    )
    # Write back clean plan
    path = ws.plans_dir / f"{clean_plan.plan_id}.json"
    import json

    path.write_text(json.dumps(clean_plan.to_dict()), encoding="utf-8")

    # Run estimation again: cache should satisfy the measurements with 0 new encodes!
    budget_zero_encodes = EstimationBudget(max_images=16, max_new_encodes=100, max_runtime_seconds=60.0, pilot_images=4)
    res2 = run_estimation(clean_plan, engine=engine, workspace=ws, invocation_budget=budget_zero_encodes)

    assert res2.new_encodes == 0
    assert res2.cache_hits > 0
    assert res2.stopping_reason == "complete"


def test_run_estimation_locking_rejects_concurrent_execution(populated_plan):
    plan, ws, engine = populated_plan

    with plan_execution_lock(ws, plan.plan_id):
        with pytest.raises(RuntimeError, match="is locked by another running operation"):
            run_estimation(plan, engine=engine, workspace=ws)


def test_run_estimation_stopping_reasons(populated_plan):
    plan, ws, engine = populated_plan

    # 1. Immediate deadline triggers deadline_exceeded
    budget_deadline = EstimationBudget(max_images=16, max_new_encodes=100, max_runtime_seconds=0.0001, pilot_images=4)
    res_dead = run_estimation(plan, engine=engine, workspace=ws, invocation_budget=budget_deadline)
    assert res_dead.stopping_reason in ("deadline_exceeded", "max_trials_reached", "pilot_incomplete")

    # 2. Tight max_images triggers cap
    budget_tight = EstimationBudget(max_images=2, max_new_encodes=100, max_runtime_seconds=60.0, pilot_images=4)
    res_tight = run_estimation(plan, engine=engine, workspace=ws, invocation_budget=budget_tight)
    assert res_tight.stopping_reason in ("max_images_reached", "pilot_incomplete")


def test_estimation_progress_events(populated_plan):
    plan, ws, engine = populated_plan

    events: list[EstimationProgress] = []
    res = run_estimation(
        plan,
        engine=engine,
        workspace=ws,
        on_progress=events.append,
    )
    assert len(events) > 0
    assert [e.sequence for e in events] == list(range(1, len(events) + 1))
    stages = [e.stage for e in events]
    assert "pilot" in stages
    assert res.stopping_reason == "complete"
