"""Independent arithmetic and fixed-design integration checks."""

from dataclasses import replace
from itertools import combinations

import pytest

from compresser.estimation_models import (
    EstimationBudget,
    LinearPredictor,
    PopulationMember,
    PopulationView,
    RecipeObservation,
    RecipeSpec,
)
from compresser.estimation_stats import allocate_confirmation, estimate_fixed, estimate_group
from compresser.sampling_plan import build_plan
from estimation_reference import fixed_group


def make_plan(root, sizes, *, max_images=None, pilot=2, recipes=1, allow_larger=False, groups=None):
    members = tuple(
        PopulationMember(str(i), str(i), size, groups[i] if groups else "PNG", (2, size, i))
        for i, size in enumerate(sizes)
    )
    source = PopulationView("population", root, "compresser", "headers", (), "2026-10-17", members)
    settings = tuple(
        RecipeSpec(fmt, "lossless", None, 0.99, "pillow", 6, "runtime") for fmt in ("webp", "png")[:recipes]
    )
    return build_plan(
        source,
        settings,
        EstimationBudget(max_images or len(sizes), 2000, 300, pilot),
        seed=13,
        allow_larger=allow_larger,
    )


def observe(plan, ids, *, state="measured", saved=None):
    members = {row.identity: row for row in plan.members}
    return tuple(
        RecipeObservation(
            member_id,
            recipe.identity,
            members[member_id].fingerprint,
            recipe.runtime_identity,
            members[member_id].size_bytes,
            (
                None
                if state == "failed"
                else members[member_id].size_bytes
                - (saved[member_id] if saved is not None else members[member_id].size_bytes // 2)
            ),
            0.1,
            state,
        )
        for recipe in plan.recipes
        for member_id in ids
    )


def confirmation_observations(plan, design, *, saved=None):
    rows = []
    for group in design.groups:
        rows.extend(row for row in observe(plan, group.selected_ids, saved=saved) if row.recipe_id == group.recipe_id)
    return tuple(rows)


def test_unpredicted_estimator_matches_fraction_oracle_for_every_confirmation_subset():
    sizes, savings = (30, 40, 50), (9, -4, 20)
    estimates = []
    for draw in combinations(range(3), 2):
        actual = estimate_group((1, 5), sizes, tuple((i, savings[i]) for i in draw))
        want, variance = fixed_group([1, 5], sizes, savings, draw)
        assert actual.estimated_saved_bytes == pytest.approx(float(want))
        assert actual.variance == pytest.approx(float(variance))
        estimates.append(actual.estimated_saved_bytes)
    assert sum(estimates) / len(estimates) == pytest.approx(31)


def test_census_signed_growth_unsampled_and_singleton_uncertainty():
    census = estimate_group((), (10, 20), ((0, -20), (1, -10)))
    assert (census.estimated_saved_bytes, census.variance) == (-30, 0)
    assert estimate_group((6,), (), ()).estimated_saved_bytes == 6
    unsampled = estimate_group((6,), (10, 20), ())
    assert unsampled.estimated_saved_bytes == 6
    assert unsampled.variance is None
    assert unsampled.gaps == ("unsampled remainder",)
    pred = LinearPredictor(origin_x=10, mean_offset=0, mean_savings=4, slope=0.5, origin_y=4)
    unsampled_pred = estimate_group((6,), (10, 20), (), predictor=pred)
    assert unsampled_pred.estimated_saved_bytes == 27
    assert unsampled_pred.variance is None
    assert unsampled_pred.gaps == ("unsampled remainder",)
    singleton = estimate_group((6,), (10, 20), ((0, 3),))
    assert singleton.estimated_saved_bytes == 12
    assert singleton.variance is None


def test_full_estimate_is_ratio_of_sums_and_retains_signed_growth(tmp_path):
    plan = make_plan(tmp_path, [10, 1000, 20, 2000], allow_larger=True)
    saved = {"0": 9, "1": 100, "2": -10, "3": 200}
    pilot = observe(plan, plan.pilot_member_ids, saved=saved)
    design = allocate_confirmation(plan, pilot)
    (result,) = estimate_fixed(plan, design, pilot, confirmation_observations(plan, design, saved=saved))
    assert result.estimated_saved_bytes == 299
    assert result.variance == 0
    assert result.savings_percent == pytest.approx(100 * 299 / 3030)
    assert result.interval == (299, 299)
    assert result.complete
    assert result.interval_kind == "approximate_fixed_normal_95"


def test_confirmation_allocation_bounds_sum_across_recipes_without_assuming_overlap(tmp_path):
    plan = make_plan(tmp_path, [100] * 30, max_images=8, recipes=2)
    pilot = observe(plan, plan.pilot_member_ids)
    design = allocate_confirmation(plan, pilot)
    assert len(plan.pilot_member_ids) + sum(len(row.selected_ids) for row in design.groups) == 8
    assert [len(row.selected_ids) for row in design.groups] == [3, 3]
    for row in design.groups:
        assert not set(row.selected_ids) & set(plan.pilot_member_ids)
        assert row.selected_ids == row.remaining_ids[:3]
    assert allocate_confirmation(plan, tuple(reversed(pilot))) == design


def test_missing_failed_and_singleton_draws_never_get_complete_intervals(tmp_path):
    plan = make_plan(tmp_path, [100] * 12, max_images=5)
    pilot = observe(plan, plan.pilot_member_ids)
    design = allocate_confirmation(plan, pilot)
    observations = confirmation_observations(plan, design)
    (complete,) = estimate_fixed(plan, design, pilot, observations)
    assert complete.complete
    for bad in (observations[:-1], (replace(observations[0], state="failed", retained_bytes=None), *observations[1:])):
        (result,) = estimate_fixed(plan, design, pilot, bad)
        assert result.interval is None
        assert result.estimated_saved_bytes is None
        assert result.gaps
    singleton_plan = make_plan(tmp_path, [100] * 12, max_images=3)
    pilot = observe(singleton_plan, singleton_plan.pilot_member_ids)
    design = allocate_confirmation(singleton_plan, pilot)
    (result,) = estimate_fixed(singleton_plan, design, pilot, confirmation_observations(singleton_plan, design))
    assert result.estimated_saved_bytes is not None
    assert result.interval is None

    # Unsampled remainder stratum has a pilot-projected point estimate but no interval
    unsampled_plan = make_plan(tmp_path, [100] * 12, max_images=2, pilot=2)
    unsampled_pilot = observe(unsampled_plan, unsampled_plan.pilot_member_ids)
    unsampled_design = allocate_confirmation(unsampled_plan, unsampled_pilot)
    assert all(len(g.selected_ids) == 0 for g in unsampled_design.groups)
    (unsampled_result,) = estimate_fixed(unsampled_plan, unsampled_design, unsampled_pilot, ())
    assert unsampled_result.estimated_saved_bytes is not None
    assert unsampled_result.variance is None
    assert unsampled_result.interval is None
    assert not unsampled_result.complete
    assert any("unsampled remainder" in g for g in unsampled_result.gaps)


def test_duplicate_stale_runtime_and_unselected_results_fail_closed(tmp_path):
    plan = make_plan(tmp_path, [100] * 12, max_images=5)
    pilot = observe(plan, plan.pilot_member_ids)
    design = allocate_confirmation(plan, pilot)
    observations = confirmation_observations(plan, design)
    first = observations[0]
    for bad in (
        (*observations, first),
        (replace(first, fingerprint=(999,)), *observations[1:]),
        (replace(first, runtime_identity="other"), *observations[1:]),
        (replace(first, input_bytes=99), *observations[1:]),
        (replace(first, member_id=plan.pilot_member_ids[0]), *observations[1:]),
    ):
        with pytest.raises(ValueError):
            estimate_fixed(plan, design, pilot, bad)
    with pytest.raises(ValueError, match="pilot"):
        allocate_confirmation(plan, pilot[:-1])


def test_terminal_failed_pilot_uses_labelled_proxy_but_cannot_become_an_interval(tmp_path):
    plan = make_plan(tmp_path, [100] * 12, max_images=6)
    pilot = observe(plan, plan.pilot_member_ids, state="failed")
    design = allocate_confirmation(plan, pilot)
    assert all(row.allocation_basis == "metadata_proxy" for row in design.groups)
    (result,) = estimate_fixed(plan, design, pilot, confirmation_observations(plan, design))
    assert result.interval is None
    assert result.gaps


def test_wrong_frozen_predictor_still_matches_exact_oracle_conditional_on_each_pilot():
    sizes, savings = (10, 20, 30, 40, 50), (3, -4, 9, 12, 18)
    for pilots in combinations(range(5), 2):
        remaining = [i for i in range(5) if i not in pilots]
        values = []
        for selected in combinations(range(3), 2):
            result = estimate_group(
                tuple(savings[i] for i in pilots),
                tuple(sizes[i] for i in remaining),
                tuple((i, savings[remaining[i]]) for i in selected),
                predictor=LinearPredictor(mean_savings=7, slope=2),
            )
            exact, variance = fixed_group(
                [savings[i] for i in pilots],
                [sizes[i] for i in remaining],
                [savings[i] for i in remaining],
                selected,
                (7, 2),
            )
            assert result.estimated_saved_bytes == pytest.approx(float(exact))
            assert result.variance == pytest.approx(float(variance))
            values.append(result.estimated_saved_bytes)
        assert sum(values) / len(values) == pytest.approx(38)


def test_pilot_only_linear_predictor_eliminates_exact_linear_residuals(tmp_path):
    plan = make_plan(tmp_path, [100 * i for i in range(1, 9)], max_images=5, pilot=3)
    pilot = observe(plan, plan.pilot_member_ids)
    design = allocate_confirmation(plan, pilot)
    assert design.groups[0].predictor.slope == 0.5
    (result,) = estimate_fixed(plan, design, pilot, confirmation_observations(plan, design))
    assert result.estimated_saved_bytes == 1800
    assert result.variance == 0
    altered = replace(design, groups=(replace(design.groups[0], predictor=LinearPredictor(mean_savings=999)),))
    with pytest.raises(ValueError, match="frozen pilot"):
        estimate_fixed(plan, altered, pilot, confirmation_observations(plan, design))


def test_centered_predictor_preserves_small_offsets_on_large_byte_sizes():
    from compresser.estimation_stats import fit_predictor

    base = 10**18
    rows = tuple(
        RecipeObservation(str(i), "recipe", (1,), "runtime", base + i, base + i - (9 + 2 * i), 0.1) for i in (1, 2, 3)
    )
    model = fit_predictor(rows)
    assert model.predict(base + 100) == pytest.approx(209)
    assert fit_predictor(rows[:2]).predict(base + 100) == 12
    assert fit_predictor(()).predict(base + 100) == 0
    shifted = tuple(
        replace(row, retained_bytes=row.input_bytes - (base - 100 + 2 * int(row.member_id))) for row in rows
    )
    shifted_model = fit_predictor(shifted)
    assert shifted_model.slope == 2
    assert shifted_model.residual(base + 100, base + 100) == 0


def test_allocation_keeps_coverage_floors_then_accounts_for_observed_cost(tmp_path):
    plan = make_plan(tmp_path, [100] * 20, groups=["JPEG"] * 10 + ["PNG"] * 10, max_images=12, pilot=4)
    pilot = tuple(
        replace(row, elapsed_seconds=100 if int(row.member_id) < 10 else 0.1)
        for row in observe(plan, plan.pilot_member_ids)
    )
    design = allocate_confirmation(plan, pilot)
    assert [len(row.selected_ids) for row in design.groups] == [2, 6]
    assert all(row.allocation_basis == "measured_pilot" for row in design.groups)


def test_allocation_exhausts_allowance_in_group_order_when_below_floor_quota(tmp_path):
    plan = make_plan(tmp_path, [100] * 30, groups=["JPEG"] * 10 + ["PNG"] * 10 + ["WEBP"] * 10, max_images=6, pilot=3)
    pilot = observe(plan, plan.pilot_member_ids)
    design = allocate_confirmation(plan, pilot)
    assert [len(row.selected_ids) for row in design.groups] == [2, 1, 0]


def test_zero_byte_census_has_undefined_percentage(tmp_path):
    plan = make_plan(tmp_path, [0, 0, 0])
    pilot = observe(plan, plan.pilot_member_ids)
    design = allocate_confirmation(plan, pilot)
    (result,) = estimate_fixed(plan, design, pilot, confirmation_observations(plan, design))
    assert result.estimated_saved_bytes == 0
    assert result.savings_percent is None


def test_stratified_variances_add_and_interval_uses_fixed_normal_quantile(tmp_path):
    import math

    plan = make_plan(tmp_path, [100] * 20, groups=["JPEG"] * 10 + ["PNG"] * 10, max_images=8, pilot=4)
    pilot = observe(plan, plan.pilot_member_ids, saved={str(i): 0 for i in range(20)})
    design = allocate_confirmation(plan, pilot)
    saved = dict(zip(design.groups[0].selected_ids + design.groups[1].selected_ids, (1, 5, 2, 8)))
    (result,) = estimate_fixed(plan, design, pilot, confirmation_observations(plan, design, saved=saved))
    assert result.estimated_saved_bytes == 64
    assert result.variance == pytest.approx(624)
    radius = 1.959963984540054 * math.sqrt(624)
    assert result.interval == pytest.approx((64 - radius, 64 + radius))


def test_policy_retention_observation_cannot_invent_savings():
    with pytest.raises(ValueError, match="policy"):
        RecipeObservation("source", "recipe", (1,), "runtime", 100, 99, 0.1, "retained_by_policy")


def test_confirmation_models_persist_once_without_replanning_or_losing_observations(tmp_path):
    from compresser.plan_store import append_plan_measurements, freeze_confirmation, load_plan, save_plan
    from compresser.workspace import initialize_workspace, resolve_workspace

    target = tmp_path / "library"
    target.mkdir()
    workspace = resolve_workspace(target, None, owner="compresser")
    initialize_workspace(workspace)
    plan = make_plan(target, [100] * 12, max_images=6)
    save_plan(workspace, plan)
    design = allocate_confirmation(plan, observe(plan, plan.pilot_member_ids))
    freeze_confirmation(workspace, plan.plan_id, design)
    append_plan_measurements(workspace, plan.plan_id, [{"trial": "preserved"}])
    save_plan(workspace, plan)
    loaded = load_plan(workspace, plan.plan_id)
    assert loaded.confirmation == design
    assert loaded.measurements == ({"trial": "preserved"},)
    with pytest.raises(ValueError, match="frozen"):
        freeze_confirmation(workspace, plan.plan_id, replace(design, pilot_digest="changed"))
