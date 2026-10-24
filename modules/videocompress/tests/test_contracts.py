"""
Tests for videocompress typed contracts and schema serialization.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import pytest

from videocompress.contracts import (
    CompressionReport,
    EligibilityDecision,
    Prediction,
    SamplingWindow,
    SourceIdentity,
    TrialObservation,
    VideoApplyJob,
    VideoAsset,
    VideoEstimationPlan,
    VideoRecipe,
    VideoStream,
)


def test_source_identity_roundtrip():
    ident = SourceIdentity(
        scope_id="target-1",
        relative_path="movies/test.mkv",
        canonical_path="C:/media/movies/test.mkv",
        stat_fingerprint="12345:67890",
        strong_digest="sha256:abcdef",
    )
    d = ident.to_dict()
    restored = SourceIdentity.from_dict(d)
    assert restored == ident
    assert restored.scope_id == "target-1"
    with pytest.raises(FrozenInstanceError):
        restored.scope_id = "target-2"  # type: ignore


def test_video_stream_and_asset_roundtrip():
    vstream = VideoStream(
        stream_index=0,
        stream_type="video",
        codec_name="h264",
        width=1920,
        height=1080,
        fps_num=24000,
        fps_den=1001,
        bit_rate_bps=5000000,
        bitrate_provenance="ffprobe_stream",
        pix_fmt="yuv420p",
        bit_depth=8,
    )
    astream = VideoStream(
        stream_index=1,
        stream_type="audio",
        codec_name="aac",
        channels=2,
        sample_rate=48000,
        language="eng",
        bit_rate_bps=192000,
    )
    asset = VideoAsset(
        source_id="src-100",
        relative_path="video.mp4",
        file_bytes=1000000,
        container_format="mp4",
        duration_seconds=120.5,
        streams=(vstream, astream),
        chapters_count=4,
    )

    assert asset.primary_video_stream == vstream
    d = asset.to_dict()
    restored = VideoAsset.from_dict(d)
    assert restored == asset
    assert restored.schema_version == 1
    assert len(restored.streams) == 2


def test_eligibility_decision_roundtrip():
    dec = EligibilityDecision(
        stage="metadata",
        status="eligible",
        reasons=("bitrate_above_threshold", "resolution_1080p"),
        applied_thresholds={"min_bitrate": 4000000},
    )
    d = dec.to_dict()
    restored = EligibilityDecision.from_dict(d)
    assert restored == dec
    assert restored.status == "eligible"


def test_video_recipe_roundtrip():
    recipe = VideoRecipe(
        recipe_id="recipe-av1-p5-cq28",
        codec="av1",
        encoder="av1_nvenc",
        preset="p5",
        rate_control_mode="cq",
        rate_control_value=28.0,
        container="matroska",
        pix_fmt="yuv420p10le",
        bit_depth=10,
        audio_policy="copy",
        subtitle_policy="copy",
    )
    d = recipe.to_dict()
    restored = VideoRecipe.from_dict(d)
    assert restored == recipe
    assert restored.rate_control_value == 28.0


def test_estimation_plan_and_windows_roundtrip():
    w1 = SamplingWindow(source_id="src-1", window_index=0, start_seconds=10.0, duration_seconds=20.0)
    w2 = SamplingWindow(source_id="src-1", window_index=1, start_seconds=60.0, duration_seconds=20.0)
    recipe = VideoRecipe(
        recipe_id="r1",
        codec="av1",
        encoder="av1_nvenc",
        preset="p5",
        rate_control_mode="cq",
        rate_control_value=28.0,
    )
    plan = VideoEstimationPlan(
        plan_id="plan-20261024-001",
        target_scope="lib-a",
        workspace_parent="C:/workspaces",
        source_ids=("src-1", "src-2"),
        recipes=(recipe,),
        sampling_windows=(w1, w2),
        work_budget_seconds=300.0,
    )
    d = plan.to_dict()
    restored = VideoEstimationPlan.from_dict(d)
    assert restored == plan
    assert len(restored.sampling_windows) == 2


def test_trial_observation_roundtrip():
    obs = TrialObservation(
        observation_id="obs-1",
        plan_id="p1",
        source_id="s1",
        recipe_id="r1",
        window_index=0,
        clip_duration_seconds=20.0,
        encoded_video_bytes=500000,
        encoded_video_bps=200000,
        elapsed_seconds=1.8,
        quality_metric_name="vmaf",
        quality_score=94.5,
    )
    d = obs.to_dict()
    restored = TrialObservation.from_dict(d)
    assert restored == obs
    assert restored.quality_score == 94.5


def test_prediction_roundtrip():
    pred = Prediction(
        source_id="s1",
        recipe_id="r1",
        tier="sampled",
        source_container_bytes=1000000000,
        predicted_video_bytes=400000000,
        predicted_nonvideo_bytes=50000000,
        predicted_mux_overhead_bytes=2000000,
        predicted_output_container_bytes=452000000,
        predicted_gross_saved_bytes=548000000,
        decision="candidate",
        prediction_interval=(430000000, 470000000),
        interval_status="calibrated",
    )
    d = pred.to_dict()
    restored = Prediction.from_dict(d)
    assert restored == pred
    assert restored.prediction_interval == (430000000, 470000000)


def test_apply_job_and_report_roundtrip():
    job = VideoApplyJob(
        job_id="job-1",
        source_id="s1",
        recipe_id="r1",
        plan_id="p1",
        status="PLANNED",
        source_canonical_path="C:/media/video.mkv",
        candidate_path="C:/scratch/candidate.mkv",
        output_path="C:/output/video.mkv",
    )
    d = job.to_dict()
    assert VideoApplyJob.from_dict(d) == job

    report = CompressionReport(
        run_id="run-1",
        operation="apply",
        total_sources=10,
        eligible_sources=8,
        processed_sources=8,
        skipped_sources=2,
        failed_sources=0,
        total_input_bytes=10000000,
        total_output_bytes=4500000,
        predicted_savings_bytes=5500000,
        realized_savings_bytes=5500000,
        elapsed_seconds=45.2,
    )
    dr = report.to_dict()
    assert CompressionReport.from_dict(dr) == report
