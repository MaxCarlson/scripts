"""Preserved renderer fixtures; estimator phase/unknown/cache/cancel cases join in Task 7."""

from pathlib import Path
import io
import re

import pytest

from compresser.estimation_models import (
    EstimationBudget,
    EstimationPlan,
    EstimationProgress,
    EstimationResult,
    RecipeEstimate,
    RecipeProgressStat,
    RecipeSpec,
    current_runtime_identity,
)
from compresser.estimation_ui import EstimationProgressUI
from compresser.markdown_report import render_markdown_report
from compresser.inventory_ui import InventoryProgress
from compresser.plan_reporting import build_estimate_summary, render_estimate_summary
from compresser.report_models import ReportContext
from compresser.reporting import (
    build_comparison_report,
    build_estimate_report,
    build_inventory_report,
    render_console_report,
)
from reporting_test import sample_row
from termdash.table import _visible_len

FIXTURES = Path(__file__).parent / "fixtures" / "preserved_reports"


@pytest.mark.parametrize("width", [80, 120, 160])
def test_preserved_inventory_progress_layout(width, monkeypatch):
    import compresser.inventory_ui as inventory_ui
    from termdash.table import _truncate_cell

    clock = [10.0]
    monkeypatch.setattr(inventory_ui.time, "monotonic", lambda: clock[0])
    progress = InventoryProgress(Path("fixtures/library"), stream=io.StringIO(), interactive=False)
    try:
        progress.set_folder_total(3)
        gallery = Path("fixtures/library/漫画")
        progress.start_gallery(gallery, total_files=4)
        progress.advance_file(
            gallery / "01.jpg",
            size_bytes=1024,
            reused=True,
            gallery_key=gallery,
        )
        clock[0] = 12.0
        progress.advance_file(gallery / "02.webp", size_bytes=2048, inspected=True, gallery_key=gallery)
        lines = [_truncate_cell(line, width) for line in progress._lines()]
        expected = (FIXTURES / f"progress-{width}.txt").read_text(encoding="utf-8").splitlines()
        assert lines == expected
        assert all("\x1b" not in line for line in lines)
    finally:
        progress.close()


@pytest.fixture(params=["comparison", "inventory"])
def preserved_report(request):
    context = ReportContext(
        Path("fixtures/library"),
        snapshot={
            "age_seconds": 123,
            "completed": "2026-10-17T12:00:00+00:00",
            "membership_verified": False,
        },
    )
    if request.param == "comparison":
        return request.param, build_comparison_report([sample_row()], context=context)
    return request.param, build_inventory_report(
        {
            "depth": "files",
            "candidate_images": 1234,
            "candidate_bytes": 1073741824,
            "content_verified": False,
            "galleries": {"gallery": {"files": 1234, "bytes": 1073741824}},
        },
        context=context,
    )


@pytest.mark.parametrize("width", [80, 120, 160])
def test_preserved_report_layout(preserved_report, width):
    name, report = preserved_report
    text = render_console_report(report, width=width, color=False)
    expected = (FIXTURES / f"{name}-{width}.txt").read_text(encoding="utf-8")
    assert text.replace("fixtures\\library", "fixtures/library") + "\n" == expected.replace(
        "fixtures\\library", "fixtures/library"
    )
    assert all(_visible_len(line) <= width for line in text.splitlines())
    assert "\x1b" not in text
    markdown = render_markdown_report(report)
    assert "\x1b" not in markdown
    if name == "comparison":
        assert "512.00 MiB" in text and "512.00 MiB" in markdown


@pytest.mark.parametrize("width", [80, 120, 160])
def test_wrapped_cjk_and_control_labels_preserve_values(width):
    label = "漫画" * 24 + "end\x1b[31m\tvalue"
    report = build_comparison_report(
        [sample_row(strategy_name=label)],
        context=ReportContext(Path("fixtures/library")),
    )
    text = render_console_report(report, width=width, color=False)
    assert all(_visible_len(line) <= width for line in text.splitlines())
    assert "\x1b" not in text and "\t" not in text
    assert "漫画" * 24 + "end" in re.sub(r"[\s│]", "", text)
    assert "512.00 MiB" in text
    assert "漫画" * 24 + "end" in render_markdown_report(report)


def _sample_plan_and_result():
    r = RecipeSpec("webp", "lossy", 80, 0.95, "pillow", 4, runtime_identity=current_runtime_identity())
    budget = EstimationBudget(16, 100, 60.0, 4)
    plan = EstimationPlan.create(
        population_id="pop-ui-1",
        root=Path("fixtures/library"),
        owner="compresser",
        depth="headers",
        filters=(),
        inventory_completed="2026-10-17T12:00:00+00:00",
        seed=42,
        accuracy_pp=None,
        allow_larger=False,
        recipes=(r,),
        budget=budget,
        strata=(),
        selected_member_ids=(),
        recipe_quotas=(),
        members=(),
        pilot_member_ids=(),
    )
    estimate = RecipeEstimate(
        recipe_id=r.identity,
        plan_identity=plan.design_identity,
        confirmation_identity="conf-1",
        estimated_saved_bytes=1024 * 1024 * 15,
        variance=1024 * 1024 * 2,
        total_input_bytes=1024 * 1024 * 100,
        savings_percent=15.0,
        interval=(1024 * 1024 * 13, 1024 * 1024 * 17),
        groups=(),
        gaps=(),
    )
    result = EstimationResult(
        plan=plan,
        estimates=(estimate,),
        stopping_reason="complete",
        stage="complete",
        cache_hits=4,
        new_encodes=12,
        newly_admitted_sources=8,
        total_observations=16,
        last_complete_estimates=(estimate,),
    )
    return plan, result


@pytest.mark.parametrize("width", [80, 120, 160])
def test_estimation_progress_ui_layout(width, monkeypatch):
    plan, result = _sample_plan_and_result()
    stream = io.StringIO()
    ui = EstimationProgressUI(plan.root, enabled=True, stream=stream, interactive=False)
    try:
        prog = EstimationProgress(
            sequence=1,
            stage="pilot",
            phase="pilot_scheduling",
            active_recipe="webp lossy 80",
            completed_sources=2,
            total_sources=4,
            new_encodes=2,
            cache_hits=0,
            remaining_trials=98,
            remaining_seconds=58.5,
            estimates=result.estimates,
            stopping_reason=None,
        )
        ui.on_progress(prog)
        lines = ui._lines()
        assert all(_visible_len(line) <= width for line in lines)
        assert all("\x1b" not in line for line in lines)
        assert any("ESTIMATION: PILOT" in line for line in lines)
        assert any("Sources: 2/4" in line for line in lines)
    finally:
        ui.close()


@pytest.mark.parametrize("width", [80, 120, 160])
def test_estimation_report_console_and_markdown(width):
    plan, result = _sample_plan_and_result()
    context = ReportContext(
        plan.root,
        snapshot={
            "age_seconds": 123,
            "completed": "2026-10-17T12:00:00+00:00",
            "membership_verified": False,
        },
        status="completed",
        operation="estimate",
    )
    report = build_estimate_report(plan, result, population_count=100, context=context)

    # Console rendering
    text = render_console_report(report, width=width, color=False)
    assert all(_visible_len(line) <= width for line in text.splitlines())
    assert "\x1b" not in text
    assert "15.00 MiB" in text
    assert "15.0%" in text

    # Markdown rendering
    md = render_markdown_report(report)
    assert "\x1b" not in md
    assert "15.00 MiB" in md
    assert "15.0%" in md
    assert "# ESTIMATION REPORT" in md


@pytest.mark.parametrize("width", [80, 120, 160])
def test_plan_reporting_estimate_summary(width):
    plan, result = _sample_plan_and_result()
    summary = build_estimate_summary(plan, result, population_count=100)
    rendered = render_estimate_summary(summary, report_path="reports/latest.md", width=width, color=False)
    assert all(_visible_len(line) <= width for line in rendered.splitlines())
    assert "\x1b" not in rendered
    assert "15.00 MiB" in rendered
    assert "Plan     " in rendered
    assert "Report   reports/latest.md" in rendered


@pytest.mark.parametrize("width", [80, 120, 160])
def test_estimation_progress_ui_live_table_and_dual_bars(width):
    plan, result = _sample_plan_and_result()
    stream = io.StringIO()
    ui = EstimationProgressUI(
        plan.root,
        enabled=True,
        stream=stream,
        interactive=False,
        max_width=width,
        population_total_bytes=100_000_000,
    )
    try:
        stats = (RecipeProgressStat("webp-lossy-80", 10, 20_000_000, 6_000_000, 14_000_000),)
        prog = EstimationProgress(
            sequence=1,
            stage="pilot",
            phase="measuring_recipes",
            active_recipe="webp-lossy-80",
            completed_sources=10,
            total_sources=20,
            new_encodes=10,
            cache_hits=0,
            remaining_trials=90,
            remaining_seconds=45.0,
            last_completed_text="img.jpg (2.00 MB) -> webp-lossy-80 (600 kB, -70.0%)",
            budget_total=100,
            recipe_stats=stats,
        )
        ui.on_progress(prog)
        lines = ui._lines()
        assert all(_visible_len(line) <= width for line in lines)
        assert all("\x1b" not in line for line in lines)
        assert any("Stage:" in line and "10/20 sources" in line for line in lines)
        assert any("Overall:" in line and "10/100 budget" in line for line in lines)
        assert any("MEASURED RECIPES & PROJECTED SAVINGS (LIVE)" in line for line in lines)
        assert any("webp-lossy-80" in line and "-70.0%" in line for line in lines)
        assert any("~66.76 MB" in line for line in lines)
    finally:
        ui.close()


def _sample_multi_recipe_plan_and_result():
    r_webp_lossless = RecipeSpec(
        "webp", "lossless", None, 0.99, "pillow", 4, runtime_identity=current_runtime_identity()
    )
    r_webp_85 = RecipeSpec("webp", "lossy", 85, 0.99, "pillow", 4, runtime_identity=current_runtime_identity())
    r_webp_70 = RecipeSpec("webp", "lossy", 70, 0.99, "pillow", 4, runtime_identity=current_runtime_identity())
    r_jpeg_lossless = RecipeSpec(
        "jpeg", "lossless", None, 0.99, "pillow", 4, runtime_identity=current_runtime_identity()
    )
    r_auto_lossless = RecipeSpec(
        "auto", "lossless", None, 0.99, "pillow", 4, runtime_identity=current_runtime_identity()
    )
    recipes = (r_auto_lossless, r_webp_lossless, r_webp_85, r_webp_70, r_jpeg_lossless)
    budget = EstimationBudget(100, 2000, 600.0, 32)
    plan = EstimationPlan.create(
        population_id="pop-multi-1",
        root=Path("fixtures/library"),
        owner="mangadl",
        depth="headers",
        filters=(),
        inventory_completed="2026-10-17T12:00:00+00:00",
        seed=42,
        accuracy_pp=None,
        allow_larger=False,
        recipes=recipes,
        budget=budget,
        strata=(),
        selected_member_ids=(),
        recipe_quotas=(),
        members=(),
        pilot_member_ids=(),
    )
    est_auto_lossless = RecipeEstimate(
        recipe_id=r_auto_lossless.identity,
        plan_identity=plan.design_identity,
        confirmation_identity="conf-auto-lossless",
        estimated_saved_bytes=100 * 1024 * 1024,
        variance=1024 * 1024,
        total_input_bytes=1024 * 1024 * 1024,
        savings_percent=10.0,
        interval=(90 * 1024 * 1024, 110 * 1024 * 1024),
        groups=(),
        gaps=(),
    )
    est_webp_lossless = RecipeEstimate(
        recipe_id=r_webp_lossless.identity,
        plan_identity=plan.design_identity,
        confirmation_identity="conf-webp-lossless",
        estimated_saved_bytes=100 * 1024 * 1024,
        variance=1024 * 1024,
        total_input_bytes=1024 * 1024 * 1024,
        savings_percent=10.0,
        interval=(90 * 1024 * 1024, 110 * 1024 * 1024),
        groups=(),
        gaps=(),
    )
    est_webp_85 = RecipeEstimate(
        recipe_id=r_webp_85.identity,
        plan_identity=plan.design_identity,
        confirmation_identity="conf-webp-85",
        estimated_saved_bytes=250 * 1024 * 1024,
        variance=1024 * 1024,
        total_input_bytes=1024 * 1024 * 1024,
        savings_percent=25.0,
        interval=(240 * 1024 * 1024, 260 * 1024 * 1024),
        groups=(),
        gaps=(),
    )
    est_webp_70 = RecipeEstimate(
        recipe_id=r_webp_70.identity,
        plan_identity=plan.design_identity,
        confirmation_identity="conf-webp-70",
        estimated_saved_bytes=400 * 1024 * 1024,
        variance=1024 * 1024,
        total_input_bytes=1024 * 1024 * 1024,
        savings_percent=40.0,
        interval=(390 * 1024 * 1024, 410 * 1024 * 1024),
        groups=(),
        gaps=(),
    )
    est_jpeg_lossless = RecipeEstimate(
        recipe_id=r_jpeg_lossless.identity,
        plan_identity=plan.design_identity,
        confirmation_identity="conf-jpeg-lossless",
        estimated_saved_bytes=None,
        variance=None,
        total_input_bytes=1024 * 1024 * 1024,
        savings_percent=None,
        interval=None,
        groups=(),
        gaps=("unresolved",),
    )
    estimates = (est_auto_lossless, est_webp_lossless, est_webp_85, est_webp_70, est_jpeg_lossless)
    result = EstimationResult(
        plan=plan,
        estimates=estimates,
        stopping_reason="complete",
        stage="confirmation",
        cache_hits=10,
        new_encodes=50,
        newly_admitted_sources=20,
        total_observations=60,
        last_complete_estimates=estimates,
    )
    return plan, result


def test_estimate_summary_sorting_and_highlighting():
    plan, result = _sample_multi_recipe_plan_and_result()

    # Sorted summary (default)
    sorted_summary = build_estimate_summary(plan, result, population_count=100, sort=True, owner="mangadl")
    assert sorted_summary.rows[0][0] == "WebP lossy 70 (best lossy)"
    assert sorted_summary.row_tones[0] == "green"
    assert sorted_summary.rows[1][0] == "WebP lossy 85"
    assert sorted_summary.row_tones[1] is None
    # Best lossless preferred specific format (WebP) over AUTO on tie
    assert sorted_summary.rows[2][0] == "WebP lossless (best lossless)"
    assert sorted_summary.row_tones[2] == "cyan"
    assert sorted_summary.rows[3][0] == "AUTO lossless"
    assert sorted_summary.row_tones[3] is None
    assert sorted_summary.rows[4][0] == "JPEG lossless"
    assert sorted_summary.rows[4][4] == "—"

    # Example commands
    assert len(sorted_summary.example_commands) == 3
    assert any(
        "estimate" in cmd and "-f webp -m lossy -q 85 70 -T 3000" in cmd for cmd in sorted_summary.example_commands
    )
    assert any("preview" in cmd and "-f webp -q 85 70 -n 10" in cmd for cmd in sorted_summary.example_commands)
    assert any("estimate" in cmd and "-f webp -m lossless -T 3000" in cmd for cmd in sorted_summary.example_commands)

    # Unsorted summary
    unsorted_summary = build_estimate_summary(plan, result, population_count=100, sort=False, owner="mangadl")
    assert unsorted_summary.rows[0][0] == "AUTO lossless"
    assert unsorted_summary.rows[1][0] == "WebP lossless (best lossless)"


@pytest.mark.parametrize("width", [80, 120, 160])
@pytest.mark.parametrize("color", [False, True])
def test_estimate_summary_rendering_layout_and_color(width, color):
    plan, result = _sample_multi_recipe_plan_and_result()
    summary = build_estimate_summary(plan, result, population_count=100, sort=True, owner="mangadl")
    rendered = render_estimate_summary(summary, report_path="reports/latest.md", width=width, color=color)

    assert all(_visible_len(line) <= width for line in rendered.splitlines())
    assert "WebP lossy 70 (best lossy)" in rendered
    assert "WebP lossless (best lossless)" in rendered
    assert "Next-step commands" in rendered
    assert "mangadl compress estimate" in rendered
    assert "mangadl compress preview" in rendered

    if not color:
        assert "\x1b" not in rendered
    else:
        assert "\x1b" in rendered
