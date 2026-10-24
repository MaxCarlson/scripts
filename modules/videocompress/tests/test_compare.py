"""Tests for videocompress.compare multi-recipe comparison and Pareto ranking."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from videocompress.adapters.ffmpeg import SampleEncodeResult
from videocompress.compare import (
    AssetComparisonReport,
    RecipeComparisonResult,
    compute_pareto_efficiency,
    run_recipe_comparison,
)
from videocompress.contracts import VideoAsset, VideoStream
from videocompress.quality import QualityMetrics
from videocompress.recipes import get_recipe
from videocompress.workspace import resolve_workspace


def test_compute_pareto_efficiency():
    """Verify Pareto dominance logic: recipe dominated in both savings and quality is non-efficient."""
    # A: 40% savings, SSIM 0.98, speed 300 fps (High quality)
    r_a = RecipeComparisonResult(
        recipe_id="recipe_a",
        encoder="nvenc",
        codec="av1",
        cq=30.0,
        measured_mean_bps=2_000_000,
        predicted_container_bytes=600_000_000,
        predicted_savings_bytes=400_000_000,
        predicted_savings_pct=40.0,
        fps_throughput=300.0,
        encode_seconds=1.0,
        quality_ssim=0.98,
        quality_psnr=42.0,
        quality_vmaf=None,
        is_pareto_efficient=True,
        rank=1,
    )
    # B: 60% savings, SSIM 0.94, speed 290 fps (High savings)
    r_b = RecipeComparisonResult(
        recipe_id="recipe_b",
        encoder="nvenc",
        codec="av1",
        cq=34.0,
        measured_mean_bps=1_500_000,
        predicted_container_bytes=400_000_000,
        predicted_savings_bytes=600_000_000,
        predicted_savings_pct=60.0,
        fps_throughput=290.0,
        encode_seconds=1.0,
        quality_ssim=0.94,
        quality_psnr=39.0,
        quality_vmaf=None,
        is_pareto_efficient=True,
        rank=2,
    )
    # C: 30% savings, SSIM 0.93, speed 150 fps (Strictly worse than A in savings, quality, and speed!)
    r_c = RecipeComparisonResult(
        recipe_id="recipe_c",
        encoder="cpu",
        codec="h264",
        cq=24.0,
        measured_mean_bps=3_000_000,
        predicted_container_bytes=700_000_000,
        predicted_savings_bytes=300_000_000,
        predicted_savings_pct=30.0,
        fps_throughput=150.0,
        encode_seconds=2.0,
        quality_ssim=0.93,
        quality_psnr=38.0,
        quality_vmaf=None,
        is_pareto_efficient=True,
        rank=3,
    )

    ranked = compute_pareto_efficiency([r_a, r_b, r_c])
    lookup = {r.recipe_id: r for r in ranked}

    assert lookup["recipe_a"].is_pareto_efficient is True
    assert lookup["recipe_b"].is_pareto_efficient is True
    assert lookup["recipe_c"].is_pareto_efficient is False  # Dominated by recipe_a!
    assert ranked[0].recipe_id in ("recipe_a", "recipe_b")


def test_run_recipe_comparison_workflow(tmp_path: Path):
    """Verify multi-recipe comparison runs trials, computes quality, and produces a structured report."""
    media_dir = tmp_path / "videos"
    media_dir.mkdir()
    source_file = media_dir / "vid.mp4"
    source_file.write_bytes(b"content" * 100)

    ws = resolve_workspace(media_dir)
    vstream = VideoStream(stream_index=0, stream_type="video", codec_name="h264", width=1920, height=1080, bit_rate_bps=6_000_000)
    asset = VideoAsset(
        source_id="comp-asset",
        relative_path="vid.mp4",
        file_bytes=100_000_000,
        container_format="mp4",
        duration_seconds=100.0,
        streams=(vstream,),
    )

    r30 = get_recipe("av1_nvenc_cq30")
    r34 = get_recipe("av1_nvenc_cq34")

    mock_encode = SampleEncodeResult(
        sample_path=tmp_path / "mock.mp4",
        source_path=source_file,
        recipe_id="av1_nvenc_cq30",
        window_index=0,
        window_start=0.0,
        window_duration=10.0,
        actual_duration=10.0,
        sample_file_bytes=2_000_000,
        sample_video_bytes=1_998_000,
        sample_video_bps=1_598_400,
        encode_seconds=0.4,
        fps_throughput=500.0,
        encoder="av1_nvenc",
    )
    mock_qm = QualityMetrics(ssim_all=0.975, psnr_all=41.5)

    with patch("videocompress.adapters.ffmpeg.FFmpegAdapter.encode_sample_clip", return_value=mock_encode):
        with patch("videocompress.quality.calculate_quality_metrics", return_value=mock_qm):
            report = run_recipe_comparison(
                asset=asset,
                canonical_path=str(source_file),
                candidate_recipes=[r30, r34],
                workspace=ws,
                schedule="s3",
            )

            assert report.source_id == "comp-asset"
            assert len(report.recipe_results) == 2
            assert report.recommended_recipe_id is not None

            # Verify JSON serializability
            d = report.to_dict()
            assert d["source_id"] == "comp-asset"
            assert len(d["recipe_results"]) == 2
