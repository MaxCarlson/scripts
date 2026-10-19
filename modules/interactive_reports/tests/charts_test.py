"""Tests for execution efficiency analytics and SVG scatterplot generation."""

from interactive_reports.charts import (
    build_efficiency_points,
    render_scatter_svg,
)
from interactive_reports.models import EfficiencyPoint, TrialDetail


def test_build_efficiency_points_calculations():
    trials = [
        TrialDetail(
            trial_id="t1",
            variant_id="model_a",
            task_id="task_1",
            status="passed",
            duration_ms=2000.0,
            input_tokens=100,
            output_tokens=200,
            reasoning_tokens=50,
            total_tokens=300,
        ),
        TrialDetail(
            trial_id="t2",
            variant_id="model_b",
            task_id="task_1",
            status="failed",
            duration_ms=4000.0,
            input_tokens=150,
            output_tokens=100,
            reasoning_tokens=0,
            total_tokens=None,  # should auto-sum to 250
        ),
    ]

    points = build_efficiency_points(trials)
    assert len(points) == 2

    p1 = points[0]
    assert p1.trial_id == "t1"
    assert p1.variant_id == "model_a"
    assert p1.strict_pass is True
    assert p1.total_tokens == 300
    # 200 tokens / 2.0s = 100 tok/s
    assert p1.throughput_tok_per_s == 100.0
    # 50 reasoning / 200 output = 0.25
    assert p1.reasoning_token_share == 0.25

    p2 = points[1]
    assert p2.trial_id == "t2"
    assert p2.strict_pass is False
    assert p2.total_tokens == 250
    # 100 tokens / 4.0s = 25 tok/s
    assert p2.throughput_tok_per_s == 25.0
    assert p2.reasoning_token_share == 0.0


def test_render_scatter_svg_empty():
    svg = render_scatter_svg([])
    assert "<svg" in svg
    assert "No efficiency data available" in svg


def test_render_scatter_svg_with_data():
    points = [
        EfficiencyPoint(
            trial_id="trial_101",
            variant_id="model_alpha",
            task_id="task_sort",
            status="passed",
            strict_pass=True,
            duration_ms=1500.0,
            total_tokens=450,
            throughput_tok_per_s=85.0,
            reasoning_token_share=0.2,
        ),
        EfficiencyPoint(
            trial_id="trial_102",
            variant_id="model_beta",
            task_id="task_sort",
            status="failed",
            strict_pass=False,
            duration_ms=3000.0,
            total_tokens=600,
            throughput_tok_per_s=40.0,
            reasoning_token_share=0.1,
        ),
    ]

    svg = render_scatter_svg(points, x_metric="duration_s", y_metric="throughput")

    assert "<svg" in svg
    assert "</svg>" in svg
    assert 'class="chart-svg"' in svg
    assert 'role="img"' in svg

    # Legend elements
    assert "model_alpha" in svg
    assert "model_beta" in svg
    assert "Passed" in svg
    assert "Failed/Timeout" in svg

    # Interactive data points
    assert 'data-trial-id="trial_101"' in svg
    assert 'data-variant="model_alpha"' in svg
    assert 'data-throughput="85.0"' in svg

    assert 'data-trial-id="trial_102"' in svg
    assert 'data-variant="model_beta"' in svg
    assert 'data-throughput="40.0"' in svg
