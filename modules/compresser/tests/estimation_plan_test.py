from dataclasses import FrozenInstanceError, replace
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

import pytest

from compresser.estimation_models import (
    EstimationBudget,
    PopulationMember,
    PopulationView,
    RecipeSpec,
)
from compresser.sampling_plan import build_plan
from compresser.plan_store import append_plan_measurements, load_plan, save_plan
from compresser.workspace import initialize_workspace, resolve_workspace


def _population(root: Path, *, count=80, galleries=24):
    members = tuple(
        PopulationMember(
            identity=f"chapter-{index % galleries}/page-{index:04}.png",
            relative_path=f"chapter-{index % galleries}/page-{index:04}.png",
            size_bytes=2 ** (10 + index % 12),
            group="PNG",
            fingerprint=(2, 2 ** (10 + index % 12), 1000 + index),
        )
        for index in range(count)
    )
    return PopulationView(
        population_id="population-1",
        root=root,
        owner="compresser",
        depth="headers",
        filters=(),
        completed="2026-10-17T12:00:00+00:00",
        members=members,
    )


def _recipe(fmt="webp", quality=None):
    return RecipeSpec(fmt, "lossless" if quality is None else "lossy", quality, 0.99, "pillow", 6)


def test_plan_is_reproducible_and_cap_expansion_preserves_selected_prefix(tmp_path):
    population = _population(tmp_path)
    recipes = (_recipe(), _recipe("avif", 85))
    small = build_plan(population, recipes, EstimationBudget(16, 100, 30, 8), seed=7)
    repeated = build_plan(population, recipes, EstimationBudget(16, 100, 30, 8), seed=7)
    expanded = build_plan(population, recipes, EstimationBudget(32, 100, 30, 8), seed=7)

    assert small.design_identity == repeated.design_identity
    assert small.selected_member_ids == expanded.selected_member_ids[:16]
    assert len(small.selected_member_ids) == 16
    assert len({row.recipe_id for row in small.recipe_quotas}) == 2
    assert max(row.total for row in small.recipe_quotas) <= 8


def test_size_bands_are_merged_and_gallery_count_does_not_set_pilot_size(tmp_path):
    population = _population(tmp_path, count=80, galleries=80)
    plan = build_plan(population, (_recipe(),), EstimationBudget(80, 2000, 300, 64), seed=0)

    assert len(plan.strata) <= 4
    assert all(row.member_count >= 8 for row in plan.strata)
    assert plan.recipe_quotas[0].total == 64
    assert plan.budget.max_images == 80


def test_plan_design_depends_on_recipes_scope_and_seed(tmp_path):
    population = _population(tmp_path)
    budget = EstimationBudget(20, 100, 30, 8)
    baseline = build_plan(population, (_recipe(),), budget, seed=1)
    assert baseline.design_identity != build_plan(population, (_recipe("avif"),), budget, seed=1).design_identity
    assert baseline.design_identity != build_plan(population, (_recipe(),), budget, seed=2).design_identity
    filtered = replace(population, filters=("https://example.test/a",))
    assert baseline.design_identity != build_plan(filtered, (_recipe(),), budget, seed=1).design_identity


def test_contracts_are_immutable_and_reject_invalid_limits(tmp_path):
    with pytest.raises(ValueError, match="positive"):
        EstimationBudget(max_images=0)
    budget = EstimationBudget()
    with pytest.raises(FrozenInstanceError):
        budget.max_images = 10
    with pytest.raises(ValueError, match="recipe"):
        build_plan(_population(tmp_path), (), budget, seed=0)


def _workspace(tmp_path):
    target = tmp_path / "library"
    target.mkdir(exist_ok=True)
    workspace = resolve_workspace(target, None, owner="compresser")
    initialize_workspace(workspace)
    return target, workspace


def test_plan_store_round_trips_atomic_measurements_and_rejects_path_traversal(tmp_path):
    target, workspace = _workspace(tmp_path)
    plan = build_plan(
        replace(_population(target), root=target), (_recipe(),), EstimationBudget(20, 100, 30, 8), seed=1
    )
    path = save_plan(workspace, plan)
    assert path == workspace.plans_dir / f"{plan.plan_id}.json"
    loaded = load_plan(workspace, plan.plan_id)
    assert loaded == plan

    updated = append_plan_measurements(
        workspace, plan.plan_id, [{"trial": 1, "status": "completed"}],
        expected_design_identity=plan.design_identity,
    )
    assert updated.design_identity == plan.design_identity
    assert load_plan(workspace, plan.plan_id).measurements == ({"trial": 1, "status": "completed"},)
    for invalid in ("../outside", "..", "plan-../bad", "C:/outside"):
        with pytest.raises(ValueError, match="Invalid plan ID"):
            load_plan(workspace, invalid)


def test_plan_store_rejects_hardlinked_plan_artifact(tmp_path):
    import os

    target, workspace = _workspace(tmp_path)
    plan = build_plan(replace(_population(target), root=target), (_recipe(),), EstimationBudget(), seed=1)
    path = save_plan(workspace, plan)
    alias = workspace.plans_dir / "linked-plan.json"
    os.link(path, alias)

    with pytest.raises(ValueError, match="owned regular file"):
        load_plan(workspace, plan.plan_id)


def test_plan_cli_rejects_explicit_resume_mismatches_and_changed_population(tmp_path, capsys, monkeypatch):
    from PIL import Image

    from cli_test_support import main

    target = tmp_path / "library"
    target.mkdir()
    Image.new("RGB", (32, 32), "white").save(target / "01.png")
    state = tmp_path / "state"
    base = ["-i", str(target), "-I", str(state), "-J"]
    assert main(["inventory", *base]) == 0
    capsys.readouterr()
    assert main(["plan", *base]) == 0
    plan_id = json.loads(capsys.readouterr().out)["plan"]["plan_id"]

    for extra, expected in ((["-f", "jpeg"], "recipe"), (["-z", "99"], "seed"), (["-s", "9"], "image cap")):
        assert main(["plan", *base, "-r", plan_id, *extra]) == 2
        assert expected in capsys.readouterr().err

    import compresser.sampling_plan as sampling_plan

    monkeypatch.setattr(sampling_plan, "current_runtime_identity", lambda: {"runtime": "changed"})
    assert main(["plan", *base, "-r", plan_id]) == 2
    assert "different runtime identity" in capsys.readouterr().err
    monkeypatch.undo()

    Image.new("RGB", (32, 32), "black").save(target / "02.png")
    assert main(["inventory", *base]) == 0
    capsys.readouterr()
    assert main(["plan", *base, "-r", plan_id]) == 2
    assert "changed inventory/filter scope" in capsys.readouterr().err


def test_interrupted_atomic_replace_keeps_last_parseable_plan(tmp_path, monkeypatch):
    import compresser.plan_store as store

    target, workspace = _workspace(tmp_path)
    plan = build_plan(replace(_population(target), root=target), (_recipe(),), EstimationBudget(), seed=2)
    save_plan(workspace, plan)
    monkeypatch.setattr(store.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("interrupted")))
    with pytest.raises(OSError, match="interrupted"):
        append_plan_measurements(workspace, plan.plan_id, [{"trial": 1}])
    assert load_plan(workspace, plan.plan_id) == plan


def test_concurrent_measurement_updates_serialize_without_lost_rows(tmp_path):
    target, workspace = _workspace(tmp_path)
    plan = build_plan(replace(_population(target), root=target), (_recipe(),), EstimationBudget(), seed=3)
    save_plan(workspace, plan)
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(
            lambda index: append_plan_measurements(workspace, plan.plan_id, [{"trial": index}]),
            range(6),
        ))
    loaded = load_plan(workspace, plan.plan_id)
    assert {row["trial"] for row in loaded.measurements} == set(range(6))


@pytest.mark.parametrize("depth", ["headers", "files"])
def test_plan_cli_requires_existing_inventory_and_never_opens_trial_cache_or_images(
    tmp_path, capsys, monkeypatch, depth
):
    from PIL import Image

    from cli_test_support import main
    from compresser.engine import CompressionEngine

    target = tmp_path / "library"
    target.mkdir()
    Image.new("RGB", (32, 32), "white").save(target / "01.png")
    workspace_parent = tmp_path / "state"
    base = ["-i", str(target), "-I", str(workspace_parent), "-J", "-v"]
    if depth == "headers":
        assert main(["inventory", *base]) == 0
    else:
        assert main(["inventory", *base, "-D", "files"]) == 0
    capsys.readouterr()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("planning must not encode or open a source image")

    monkeypatch.setattr(CompressionEngine, "_encode_verified", forbidden)
    monkeypatch.setattr(Image, "open", forbidden)
    assert main(["plan", *base, "-s", "8", "-T", "40", "-M", "30s"]) == 0
    report = json.loads(capsys.readouterr().out)
    workspace = workspace_parent / ".compresser" / "library"
    assert report["plan"]["depth"] == depth
    assert report["plan"]["budget"]["max_images"] == 8
    assert report["plan"]["budget"]["max_new_encodes"] == 40
    assert report["plan"]["budget"]["max_runtime_seconds"] == 30
    markdown = Path(report["report_artifacts"]["archive"]).read_text(encoding="utf-8")
    assert "Snapshot age (seconds)" in markdown
    assert "Uncovered groups" in markdown
    assert (workspace / "plans" / f"{report['plan']['plan_id']}.json").is_file()
    assert not (workspace / "trials.sqlite3").exists()


def test_plan_cli_fails_with_inventory_hint_and_rejects_unsafe_plan_id(tmp_path, capsys):
    from cli_test_support import main

    target = tmp_path / "library"
    target.mkdir()
    workspace = tmp_path / "state"
    base = ["-i", str(target), "-I", str(workspace)]
    assert main(["plan", *base]) == 2
    assert "run inventory first" in capsys.readouterr().err

    assert main(["inventory", *base, "-J"]) == 0
    capsys.readouterr()
    assert main(["plan", *base, "-r", "../outside"]) == 2
    assert "Invalid plan ID" in capsys.readouterr().err
