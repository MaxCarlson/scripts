from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from termdash.table import _visible_len

from compresser.estimation_models import (
    EstimationBudget,
    EstimationPlan,
    PopulationMember,
    PopulationView,
    RecipeSpec,
)
from compresser.sampling_plan import build_plan
from compresser.plan_reporting import build_plan_summary, render_plan_summary

NOW = datetime(2026, 10, 17, 22, 31, tzinfo=timezone.utc)
COMPLETED = (NOW - timedelta(hours=2, minutes=6)).isoformat()


def recipe(format_name, mode, quality=None, *, target=0.99, encoder="auto", effort=6):
    return RecipeSpec(format_name, mode, quality, target, encoder, effort)


def default_recipes():
    return (
        recipe("auto", "lossless"),
        recipe("auto", "lossy", 85),
        recipe("auto", "lossy", 70),
        recipe("webp", "lossless"),
        recipe("webp", "lossy", 85),
        recipe("webp", "lossy", 70),
        recipe("jpeg", "lossless"),
        recipe("jpeg", "lossy", 85),
        recipe("jpeg", "lossy", 70),
        recipe("avif", "lossy", 85),
        recipe("avif", "lossy", 70),
        recipe("png", "lossless"),
    )


def make_plan(*, recipes=None, budget=None, filters=(), accuracy_pp=None, allow_larger=False, depth="headers"):
    groups = (
        "JPEG",
        "JPEG small",
        "JPEG large",
        "JPEG scans",
        "PNG",
        "PNG small",
        "PNG large",
        "WEBP",
        "WEBP small",
        "WEBP large",
        "WEBP scans",
    )
    members = []
    for group_index, group in enumerate(groups):
        count = 2 if group_index == len(groups) - 1 else 18
        for index in range(count):
            identity = f"image-{group_index:02}-{index:03}"
            members.append(
                PopulationMember(
                    identity,
                    f"{identity}.jpg",
                    2048 + group_index,
                    group,
                    (2048 + group_index, 1, "JPEG"),
                )
            )
    population = PopulationView(
        "population-id-secret",
        Path("B:/Hent/hent1imageperpage"),
        "mangadl",
        depth,
        tuple(filters),
        COMPLETED,
        tuple(members),
    )
    return build_plan(
        population,
        tuple(recipes if recipes is not None else default_recipes()),
        budget or EstimationBudget(max_images=200, max_new_encodes=750, max_runtime_seconds=900, pilot_images=64),
        seed=7,
        accuracy_pp=accuracy_pp,
        allow_larger=allow_larger,
    )


@pytest.fixture
def summary():
    return build_plan_summary(make_plan(), population_count=66_233, now=NOW)


def test_summary_groups_registered_formats_and_reports_actual_pilot(summary):
    assert summary.headers == ("Format", "Lossless", "Lossy qualities")
    assert summary.rows == (
        ("AUTO", "Yes", "85, 70"),
        ("WebP", "Yes", "85, 70"),
        ("JPEG", "Yes*", "85, 70"),
        ("AVIF", "—", "85, 70"),
        ("PNG", "Yes", "—"),
    )
    overview = " ".join(summary.overview)
    assert "66,233 images" in overview
    assert "12 recipes" in overview
    assert "11 groups covered" in overview
    assert "62 shared images across 12 recipes" in overview
    assert "2h 6m ago" in overview
    assert "population-id-secret" not in overview
    assert not any(len(value) == 64 for value in (*summary.overview, *summary.annotations, *summary.warnings))
    assert any("744 image/recipe measurements" in warning for warning in summary.warnings)
    assert any("AUTO may need multiple encodes" in warning for warning in summary.warnings)


@pytest.mark.parametrize(("measurements", "budget", "expected"), [(79, 100, False), (80, 100, True)])
def test_tight_budget_warning_uses_eighty_percent_threshold(measurements, budget, expected):
    recipes = tuple(recipe("webp", "lossy", quality) for quality in range(1, measurements + 1))
    plan = make_plan(
        recipes=recipes,
        budget=EstimationBudget(max_images=200, max_new_encodes=budget, max_runtime_seconds=900, pilot_images=64),
    )
    summary = build_plan_summary(plan, population_count=200, now=NOW)
    assert any("Encode budget is tight" in item for item in summary.warnings) is expected


def test_no_auto_recipe_omits_auto_cache_warning():
    plan = make_plan(
        recipes=(recipe("webp", "lossless"),),
        budget=EstimationBudget(max_images=200, max_new_encodes=10, max_runtime_seconds=900, pilot_images=10),
    )
    summary = build_plan_summary(plan, population_count=200, now=NOW)
    assert any("Encode budget is tight" in item for item in summary.warnings)
    assert not any("AUTO may" in item for item in summary.warnings)


def test_large_encode_budget_does_not_show_tight_warning():
    plan = make_plan(
        budget=EstimationBudget(max_images=200, max_new_encodes=2000, max_runtime_seconds=900, pilot_images=64)
    )
    summary = build_plan_summary(plan, population_count=200, now=NOW)
    assert not any("Encode budget is tight" in item for item in summary.warnings)


@pytest.mark.parametrize(
    "mode,headers,row",
    [
        ("lossless", ("Format", "Lossless"), ("WebP", "Yes")),
        ("lossy", ("Format", "Lossy qualities"), ("WebP", "85")),
    ],
)
def test_only_requested_modes_are_shown(mode, headers, row):
    recipe_spec = recipe("webp", mode, 85 if mode == "lossy" else None)
    plan = make_plan(recipes=(recipe_spec,))
    summary = build_plan_summary(plan, population_count=200, now=NOW)
    assert summary.headers == headers
    assert summary.rows == (row,)


def test_perceptual_recipe_has_target_column_without_lossless_claim():
    plan = make_plan(recipes=(recipe("webp", "perceptual", target=0.99),))
    summary = build_plan_summary(plan, population_count=200, now=NOW)
    assert summary.headers == ("Format", "Perceptual target")
    assert summary.rows == (("WebP", "SSIM ≥ 0.990"),)


def test_distinct_encoder_effort_and_filters_remain_visible():
    variants = (recipe("webp", "lossy", 85), recipe("webp", "lossy", 85, encoder="pillow-webp", effort=3))
    plan = make_plan(recipes=variants, filters=("https://example.invalid/gallery/*",), accuracy_pp=2)
    summary = build_plan_summary(plan, population_count=200, now=NOW)
    text = " ".join((*summary.overview, *summary.annotations, *summary.warnings))
    assert "https://example.invalid/gallery/*" in text
    assert "2 pp" in text
    assert "pillow-webp" in text
    assert "effort 3" in text


def test_allow_larger_files_depth_and_coverage_gap_are_explicit():
    plan = make_plan(
        recipes=(recipe("webp", "lossless"),),
        budget=EstimationBudget(max_images=1, max_new_encodes=20, max_runtime_seconds=900, pilot_images=4),
        allow_larger=True,
        depth="files",
    )
    summary = build_plan_summary(plan, population_count=200, now=NOW)
    text = " ".join((*summary.overview, *summary.annotations, *summary.warnings))
    assert "Larger outputs are allowed" in text
    assert "files" in text and "unverified" in text.lower()
    assert "coverage" in text.lower() or "uncovered" in text.lower()


def test_unequal_quota_sum_and_actual_pilot_below_ceiling():
    plan = make_plan(
        recipes=(recipe("webp", "lossless"), recipe("png", "lossless")),
        budget=EstimationBudget(max_images=20, max_new_encodes=20, max_runtime_seconds=900, pilot_images=64),
    )
    quotas = tuple(
        replace(
            quota,
            per_stratum=quota.per_stratum[:-1]
            + ((quota.per_stratum[-1][0], max(0, quota.per_stratum[-1][1] - index)),),
        )
        for index, quota in enumerate(plan.recipe_quotas)
    )
    inputs = {
        field.name: getattr(plan, field.name)
        for field in fields(EstimationPlan)
        if field.name not in {"plan_id", "design_identity", "design_payload", "measurements", "confirmation"}
    }
    inputs["recipe_quotas"] = quotas
    altered = EstimationPlan.create(**inputs)
    summary = build_plan_summary(altered, population_count=200, now=NOW)
    overview = " ".join(summary.overview)
    assert f"{len(plan.pilot_member_ids)} shared images" in overview
    assert f"{plan.budget.pilot_images} shared images" not in overview
    assert any("19 image/recipe measurements" in warning for warning in summary.warnings)


def test_future_snapshot_age_clamps_to_zero():
    plan = make_plan()
    summary = build_plan_summary(plan, population_count=200, now=datetime(2026, 10, 17, tzinfo=timezone.utc))
    assert any("saved 0m ago" in line for line in summary.overview)


def test_subminute_runtime_budget_rounds_up_to_one_minute():
    plan = make_plan(
        budget=EstimationBudget(max_images=200, max_new_encodes=2000, max_runtime_seconds=30, pilot_images=64)
    )
    summary = build_plan_summary(plan, population_count=200, now=NOW)
    assert "1 min active time" in summary.overview[2]


def test_summary_uses_singular_counts_for_one_image_recipe_and_group():
    plan = make_plan(
        recipes=(recipe("webp", "lossless"),),
        budget=EstimationBudget(max_images=1, max_new_encodes=100, max_runtime_seconds=900, pilot_images=64),
    )
    summary = build_plan_summary(plan, population_count=1, now=NOW)
    assert summary.overview[0] == "1 image · 1 recipe · 1 group covered"
    assert summary.overview[3] == "Pilot    1 shared image across 1 recipe"


def test_budget_line_uses_singular_image_and_encode_counts():
    plan = make_plan(
        recipes=(recipe("webp", "lossless"),),
        budget=EstimationBudget(max_images=1, max_new_encodes=1, max_runtime_seconds=60, pilot_images=64),
    )
    summary = build_plan_summary(plan, population_count=1, now=NOW)
    assert summary.overview[2] == "Limits   1 image · 1 new encode · 1 min active time"


@pytest.mark.parametrize("width", [40, 80, 120, 160])
@pytest.mark.parametrize("color", [False, True])
def test_renderer_wraps_without_losing_values_or_ansi_when_disabled(summary, width, color):
    path = r"B:\Hent\.mangadl\hent1imageperpage\reports\a-very-long-report-name-that-needs-wrapping.md"
    output = render_plan_summary(summary, report_path=path, width=width, color=color)
    assert all(_visible_len(line) <= width for line in output.splitlines())
    assert "plan-" in output
    assert "Planning only; no images encoded." in output
    assert path in output.replace("\n", "")
    if not color:
        assert "\x1b[" not in output


def test_approved_summary_is_compact_and_has_one_format_table(summary):
    output = render_plan_summary(
        summary,
        report_path=r"B:\Hent\.mangadl\hent1imageperpage\reports\latest.md",
        width=120,
        color=False,
    )
    assert len(output.splitlines()) <= 35
    assert output.count("┌") == 1
    assert "Panel " not in output
    assert "population-id-secret" not in output
    assert "Immutable design identity" not in output
    assert "PER-RECIPE PILOT QUOTAS" not in output
    assert "POPULATION STRATA" not in output
    assert "744 image/recipe measurements" in output
    assert output.count("Report ") == 1


def test_renderer_omits_report_path_when_publication_failed(summary):
    output = render_plan_summary(summary, report_path=None, width=80, color=False)
    assert "Report" not in output
    assert "plan-" in output
