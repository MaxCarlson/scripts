"""Recommendations must use the sampling design and never invent eligible winners."""

from dataclasses import replace

import pytest

from compresser.models import ComparisonRow
from compresser.ui import recommend_comparison_strategies


def _row(name="x", **changes):
    row = ComparisonRow(
        name, "webp", "lossy", "q=80", 200, 1800, 90, 0.99, 1, measured_images=10, retained_formats=("WEBP",)
    )
    return replace(row, **changes)


def test_target_recommendations_use_projected_not_raw_sample_savings():
    x = _row(
        mode="lossless",
        retained_formats=("WEBP",),
        estimate={"projected_total_saved_bytes": 9000, "scope": "gallery_random_sample"},
    )
    y = _row(
        "y",
        mode="lossless",
        retained_formats=("WEBP",),
        saved_bytes=1000,
        estimate={"projected_total_saved_bytes": 100000, "scope": "gallery_random_sample"},
    )
    result = recommend_comparison_strategies([x, y])
    assert result["maximum_savings"]["strategy"] == "y"
    assert result["maximum_savings"]["ranking_scope"] == "whole_target_projection"
    assert result["maximum_savings"]["encoder_speed_used"] is False
    assert result["best_lossless"]["strategy"] == "y"
    assert result["practical_tradeoff"]["strategy"] == "y"


@pytest.mark.parametrize(
    "changes",
    [
        {"failed_count": 10},
        {"measured_images": 0},
        {"saved_bytes": 0},
        {"sampling": {"inventory_images": 100}, "estimate": {"projected_total_saved_bytes": None}},
        {"sampling": {"inventory_images": 100}},
    ],
)
def test_unsupported_rows_never_become_fallback_winners(changes):
    result = recommend_comparison_strategies([_row(mode="lossless", **changes)])
    assert result["maximum_savings"] is None
    assert result["best_lossless"] is None
    assert result["practical_tradeoff"] is None


@pytest.mark.parametrize("ssim", [None, 0.97])
def test_practical_does_not_fall_back_to_unmeasured_or_low_fidelity(ssim):
    assert recommend_comparison_strategies([_row(average_ssim=ssim)])["practical_tradeoff"] is None


def test_warm_cache_rate_does_not_change_practical_recommendation():
    x = _row(saved_bytes=1000, retained_formats=("WEBP",))
    y = _row("y", saved_bytes=999, retained_formats=("WEBP",), cache_hits=10, throughput_images_per_s=1e9)
    result = recommend_comparison_strategies([x, y])
    assert result["practical_tradeoff"]["strategy"] == "x"
    assert result["practical_tradeoff"]["encoder_speed_used"] is False


def test_auto_compatibility_uses_retained_formats_not_auto_label():
    auto = _row(output_format="auto", retained_formats=("AVIF",))
    assert recommend_comparison_strategies([auto])["practical_tradeoff"] is None
    known = replace(auto, retained_formats=("PNG", "WEBP"))
    recommendation = recommend_comparison_strategies([known])["practical_tradeoff"]
    assert recommendation is not None
    assert "conditional" in recommendation["reader_compatibility"]


def test_incomplete_projection_cannot_win_even_with_large_sample_savings():
    bad = _row(saved_bytes=999999, estimate={"projected_total_saved_bytes": None, "unestimated_images": 1})
    good = _row("good", estimate={"projected_total_saved_bytes": 100})
    assert recommend_comparison_strategies([bad, good])["maximum_savings"]["strategy"] == "good"


def test_text_explicitly_reports_unavailable_winners(capsys):
    from compresser.ui import print_comparison_matrix

    print_comparison_matrix([_row(saved_bytes=0)])
    output = capsys.readouterr().out
    assert "No eligible positive-savings" in output
    assert "READY TO COMPRESS" not in output
