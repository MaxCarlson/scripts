"""Frozen design prerequisites for unbiased confirmation inference."""

from dataclasses import replace
import hashlib
import json

import pytest

from compresser.estimation_models import EstimationBudget, EstimationPlan, PopulationMember, PopulationView, RecipeSpec
from compresser.sampling_plan import build_plan


def population(root, sizes, groups=None):
    return PopulationView(
        "population",
        root,
        "compresser",
        "headers",
        (),
        "2026-10-17T12:00:00+00:00",
        tuple(
            PopulationMember(str(i), str(i), size, groups[i] if groups else "PNG", (2, size, i))
            for i, size in enumerate(sizes)
        ),
    )


def recipe(fmt="webp"):
    return RecipeSpec(fmt, "lossless", None, 0.99, "pillow", 6, "runtime")


def test_plan_freezes_full_population_and_group_rankings_not_just_image_cap(tmp_path):
    source = population(tmp_path, [10] * 20)
    plan = build_plan(source, (recipe(),), EstimationBudget(6, 100, 30, 2), seed=3)
    assert plan.members == source.members
    assert len(plan.strata[0].ordered_member_ids) == 20
    assert plan.pilot_member_ids == plan.selected_member_ids[:2]
    expected = sorted(
        (str(i) for i in range(20)),
        key=lambda member: (
            hashlib.sha256(json.dumps([2, 3, plan.strata[0].key, member], separators=(",", ":")).encode()).hexdigest(),
            member,
        ),
    )
    assert plan.strata[0].ordered_member_ids == tuple(expected)
    assert EstimationPlan.from_dict(plan.to_dict()) == plan


def test_equal_width_exponent_bands_and_lowest_deficient_merge(tmp_path):
    # Observed exponents 0..7 => four intervals [0,1], [2,3], [4,5], [6,7].
    sizes = [1] * 3 + [2] * 5 + [4] * 7 + [8] + [16] * 7 + [32] + [64] * 7 + [128]
    plan = build_plan(population(tmp_path, sizes), (recipe(),), EstimationBudget(), seed=0)
    assert [row.member_count for row in plan.strata] == [8, 8, 8, 8]
    deficient = [1] * 2 + [2] * 3 + [4] * 6 + [8] + [16] * 7 + [32] + [64] * 7 + [128]
    plan = build_plan(population(tmp_path, deficient), (recipe(),), EstimationBudget(), seed=0)
    assert [row.member_count for row in plan.strata] == [12, 8, 8]
    sparse = build_plan(
        population(tmp_path, [1] * 8 + [2] * 8 + [8] * 8 + [128] * 8), (recipe(),), EstimationBudget(), seed=0
    )
    assert [row.member_count for row in sparse.strata] == [16, 8, 8]


def test_inference_population_requires_known_bytes_and_fingerprints(tmp_path):
    source = population(tmp_path, [10, 20])
    for member in (replace(source.members[0], size_bytes=None), replace(source.members[0], fingerprint=())):
        with pytest.raises(ValueError, match="inventory"):
            build_plan(replace(source, members=(member, source.members[1])), (recipe(),), EstimationBudget(), seed=0)


def test_changed_plan_fields_cannot_hide_behind_original_design_payload(tmp_path):
    plan = build_plan(population(tmp_path, [10, 20]), (recipe(),), EstimationBudget(), seed=0)
    value = plan.to_dict()
    value["seed"] = 9
    with pytest.raises(ValueError, match="identity"):
        EstimationPlan.from_dict(value)
    value = plan.to_dict()
    value["schema_version"] = 1
    with pytest.raises(ValueError, match="rebuild"):
        EstimationPlan.from_dict(value)


def test_shared_pilot_never_exceeds_64_or_promises_more_trials_than_available(tmp_path):
    source = population(tmp_path, [100] * 100)
    plan = build_plan(source, (recipe(),), EstimationBudget(100, 2000, 300, 100), seed=0)
    assert len(plan.pilot_member_ids) == 64
    plan = build_plan(source, (recipe(), recipe("png")), EstimationBudget(100, 1, 300, 64), seed=0)
    assert not plan.pilot_member_ids
    assert plan.coverage_gaps


def test_recipe_identity_distinguishes_actual_retention_policy(tmp_path):
    source = population(tmp_path, [100] * 10)
    kept = build_plan(source, (recipe(),), EstimationBudget(), seed=0)
    grown = build_plan(source, (recipe(),), EstimationBudget(), seed=0, allow_larger=True)
    assert kept.recipes[0].identity != grown.recipes[0].identity
    assert grown.recipes[0].retained_original_policy == "allow-larger"
