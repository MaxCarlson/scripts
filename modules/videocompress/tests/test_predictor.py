"""
Tests for zero-encode metadata predictor, container arithmetic, and feasibility screening.
Follows IMPLEMENTATION_PLAN.md §5, §6 and MEDIA_SAFETY_CONTRACT.md §1.
"""

from __future__ import annotations

import subprocess
import pytest

from videocompress.contracts import VideoAsset, VideoRecipe, VideoStream
from videocompress.predictor import (
    FeasibilityAssessment,
    StreamPayloadBreakdown,
    compute_nonvideo_payload,
    determine_quality_floor,
    evaluate_feasibility,
)
from videocompress.recipes import get_recipe


@pytest.fixture
def av1_recipe() -> VideoRecipe:
    return get_recipe("av1_nvenc_cq30")


def test_predictor_never_spawns_subprocesses(monkeypatch, av1_recipe):
    """Zero-encode invariant: predictor must NEVER invoke subprocesses or encoders."""
    def _forbidden(*args, **kwargs):
        raise RuntimeError("CRITICAL ERROR: Predictor attempted to invoke subprocess/encoder!")

    monkeypatch.setattr(subprocess, "run", _forbidden)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)

    vstream = VideoStream(
        stream_index=0,
        stream_type="video",
        codec_name="h264",
        width=1920,
        height=1080,
        fps_num=24,
        fps_den=1,
        bit_rate_bps=8_000_000,
        bitrate_provenance="ffprobe_stream",
    )
    astream = VideoStream(
        stream_index=1,
        stream_type="audio",
        codec_name="aac",
        channels=2,
        bit_rate_bps=192_000,
        bitrate_provenance="ffprobe_stream",
    )
    asset = VideoAsset(
        source_id="test-pure-math",
        relative_path="clip.mp4",
        file_bytes=100_000_000,
        container_format="mov,mp4",
        duration_seconds=95.0,
        streams=(vstream, astream),
    )

    assessment = evaluate_feasibility(asset, av1_recipe, min_savings_pct=20.0)
    assert assessment.decision in ("eligible_promising", "eligible_uncertain")
    assert assessment.video_bitrate_bps == 8_000_000


def test_container_size_decomposition_multi_streams(av1_recipe):
    """Exact size decomposition across audio, bitmap subtitles, font attachments, and mux overhead."""
    vstream = VideoStream(
        stream_index=0,
        stream_type="video",
        codec_name="h264",
        width=1920,
        height=1080,
        bit_rate_bps=6_000_000,
    )
    # Multitrack audio: 6ch AC3 (448k) + 2ch AAC (192k)
    a1 = VideoStream(
        stream_index=1,
        stream_type="audio",
        codec_name="ac3",
        channels=6,
        bit_rate_bps=448_000,
    )
    a2 = VideoStream(
        stream_index=2,
        stream_type="audio",
        codec_name="aac",
        channels=2,
        bit_rate_bps=192_000,
    )
    # PGS bitmap subtitle (higher bitrate) + ASS text subtitle
    s1 = VideoStream(stream_index=3, stream_type="subtitle", codec_name="hdmv_pgs_subtitle")
    s2 = VideoStream(stream_index=4, stream_type="subtitle", codec_name="ass")
    # 2 font attachments
    att1 = VideoStream(stream_index=5, stream_type="attachment", codec_name="ttf")
    att2 = VideoStream(stream_index=6, stream_type="attachment", codec_name="otf")

    duration = 3600.0  # 1 hour
    asset = VideoAsset(
        source_id="complex-asset",
        relative_path="anime_ep1.mkv",
        file_bytes=3_000_000_000,
        container_format="matroska",
        duration_seconds=duration,
        streams=(vstream, a1, a2, s1, s2, att1, att2),
    )

    breakdown = compute_nonvideo_payload(asset, av1_recipe)

    # Expected audio: (448k + 192k) bps * 3600s / 8 = 288,000,000 bytes
    expected_audio = int((448_000 + 192_000) * 3600 / 8)
    assert breakdown.audio_bytes == expected_audio

    # Subtitles: PGS ~4200 B/s * 3600 + text ~15 B/s * 3600 = ~15,174,000 bytes
    assert breakdown.subtitle_bytes > 15_000_000

    # Attachments: 2 fonts * 150,000 = 300,000 bytes
    assert breakdown.attachment_bytes == 300_000

    # Mux overhead > 128 KB
    assert breakdown.mux_overhead_bytes >= 131_072

    assert breakdown.total_nonvideo_bytes == (
        breakdown.audio_bytes + breakdown.subtitle_bytes + breakdown.attachment_bytes + breakdown.mux_overhead_bytes
    )


def test_hard_infeasibility_nonvideo_budget_overflow(av1_recipe):
    """When non-video streams and overhead exceed allowable output budget, report infeasible."""
    # Source is 1 GB. User requires 70% savings -> output budget max is 300 MB.
    # Non-video payload alone is 450 MB -> hard impossibility.
    vstream = VideoStream(stream_index=0, stream_type="video", codec_name="h264", width=1920, height=1080)
    astream = VideoStream(
        stream_index=1,
        stream_type="audio",
        codec_name="flac",
        channels=6,
        bit_rate_bps=1_500_000,  # ~675 MB for 3600s
    )
    asset = VideoAsset(
        source_id="overflow-asset",
        relative_path="huge_audio.mkv",
        file_bytes=1_000_000_000,
        container_format="matroska",
        duration_seconds=3600.0,
        streams=(vstream, astream),
    )

    assessment = evaluate_feasibility(asset, av1_recipe, min_savings_pct=70.0)
    assert assessment.decision == "infeasible"
    assert assessment.is_hard_infeasible is True
    assert any("exceed maximum allowable output budget" in r for r in assessment.rejection_reasons)


def test_hard_infeasibility_below_quality_floor(av1_recipe):
    """When required video bitrate falls below minimum viable quality floor, report infeasible."""
    # 4K video requiring 2.2 Mbps AV1 quality floor.
    # Total size 1 GB for 2 hours (7200s). Target 50% savings allows video budget of ~400 kbps,
    # which is far below 2.2 Mbps -> Potato quality violation!
    vstream = VideoStream(
        stream_index=0,
        stream_type="video",
        codec_name="h264",
        width=3840,
        height=2160,
        bit_rate_bps=1_100_000,
    )
    astream = VideoStream(stream_index=1, stream_type="audio", codec_name="aac", bit_rate_bps=128_000)
    asset = VideoAsset(
        source_id="potato-4k",
        relative_path="4k_low.mp4",
        file_bytes=1_000_000_000,
        container_format="mp4",
        duration_seconds=7200.0,
        streams=(vstream, astream),
    )

    assessment = evaluate_feasibility(asset, av1_recipe, min_savings_pct=50.0)
    assert assessment.decision == "quality_floor_violation"
    assert assessment.is_hard_infeasible is False
    assert any("below recommended visual quality floor" in r for r in assessment.rejection_reasons)


def test_missing_video_bitrate_approximation_provenance(av1_recipe):
    """Missing video-stream bitrate must be explicitly approximated and labeled, never substituted silently."""
    vstream = VideoStream(
        stream_index=0,
        stream_type="video",
        codec_name="h264",
        width=1920,
        height=1080,
        bit_rate_bps=None,  # Missing stream bitrate
        bitrate_provenance="missing",
    )
    astream = VideoStream(
        stream_index=1,
        stream_type="audio",
        codec_name="aac",
        channels=2,
        bit_rate_bps=192_000,
    )
    asset = VideoAsset(
        source_id="no-bitrate-asset",
        relative_path="headerless.mkv",
        file_bytes=500_000_000,
        container_format="matroska",
        duration_seconds=600.0,
        streams=(vstream, astream),
    )

    assessment = evaluate_feasibility(asset, av1_recipe, min_savings_pct=20.0)
    # Must explicitly state container_derived_approximation
    assert assessment.bitrate_provenance == "container_derived_approximation"
    assert assessment.video_bitrate_bps is not None
    assert assessment.video_bitrate_bps > 0
    assert any("approximated" in w.lower() for w in assessment.warnings)

    pred = assessment.prediction
    assert "video_bitrate_approximated_from_container" in pred.unknowns


def test_already_efficient_av1_source_unlikely_savings(av1_recipe):
    """Re-encoding already-efficient AV1 material should be recognized as unlikely to yield savings."""
    vstream = VideoStream(
        stream_index=0,
        stream_type="video",
        codec_name="av1",
        width=1920,
        height=1080,
        bit_rate_bps=2_000_000,
        bitrate_provenance="ffprobe_stream",
    )
    astream = VideoStream(stream_index=1, stream_type="audio", codec_name="opus", bit_rate_bps=128_000)
    asset = VideoAsset(
        source_id="av1-source",
        relative_path="already_av1.mkv",
        file_bytes=266_000_000,
        container_format="matroska",
        duration_seconds=1000.0,
        streams=(vstream, astream),
    )

    # Requiring 25% savings on an already-efficient AV1 file
    assessment = evaluate_feasibility(asset, av1_recipe, min_savings_pct=25.0)
    assert assessment.decision == "eligible_unlikely"
    assert any("below required threshold" in r for r in assessment.rejection_reasons)


def test_low_bpppf_flagging(av1_recipe):
    """Assets with already low bits-per-pixel-per-frame (bpppf < 0.05) must generate quality risk warnings."""
    # 1080p 24fps = 49,766,400 pixels/sec. Bitrate 800 kbps -> bpppf ~ 0.016
    vstream = VideoStream(
        stream_index=0,
        stream_type="video",
        codec_name="h264",
        width=1920,
        height=1080,
        fps_num=24,
        fps_den=1,
        bit_rate_bps=800_000,
        bitrate_provenance="ffprobe_stream",
    )
    asset = VideoAsset(
        source_id="low-bpppf-asset",
        relative_path="compressed_1080p.mp4",
        file_bytes=100_000_000,
        container_format="mp4",
        duration_seconds=1000.0,
        streams=(vstream,),
    )

    assessment = evaluate_feasibility(asset, av1_recipe)
    assert any("low bits-per-pixel-per-frame" in w for w in assessment.warnings)


def test_hdr10_uncertainty_widening(av1_recipe):
    """HDR10 content must widen the prediction interval to protect high bit-depth color precision."""
    vstream = VideoStream(
        stream_index=0,
        stream_type="video",
        codec_name="hevc",
        width=3840,
        height=2160,
        bit_rate_bps=20_000_000,
        bit_depth=10,
        is_hdr=True,
    )
    asset = VideoAsset(
        source_id="hdr-movie",
        relative_path="4k_hdr.mkv",
        file_bytes=15_000_000_000,
        container_format="matroska",
        duration_seconds=6000.0,
        streams=(vstream,),
    )

    assessment = evaluate_feasibility(asset, av1_recipe)
    assert any("HDR10/10-bit content detected" in w for w in assessment.warnings)
    # p10 output bytes should be less than p90 output bytes (valid interval)
    assert assessment.p10_output_bytes < assessment.p90_output_bytes


def test_missing_duration_and_bitrate_abstains(av1_recipe):
    """When duration is zero and bitrate is missing, predictor must honestly abstain."""
    vstream = VideoStream(
        stream_index=0,
        stream_type="video",
        codec_name="h264",
        width=1920,
        height=1080,
        bit_rate_bps=None,
    )
    asset = VideoAsset(
        source_id="zero-dur",
        relative_path="broken.mp4",
        file_bytes=50_000_000,
        container_format="mp4",
        duration_seconds=0.0,
        streams=(vstream,),
    )

    assessment = evaluate_feasibility(asset, av1_recipe, min_savings_pct=20.0)
    assert assessment.decision == "abstained"
    assert assessment.confidence == "abstain"


def test_no_video_stream_infeasible(av1_recipe):
    """Asset with audio-only or non-video streams must be reported as infeasible."""
    astream = VideoStream(
        stream_index=0,
        stream_type="audio",
        codec_name="flac",
        channels=2,
        bit_rate_bps=800_000,
    )
    asset = VideoAsset(
        source_id="audio-only",
        relative_path="track.flac",
        file_bytes=30_000_000,
        container_format="flac",
        duration_seconds=300.0,
        streams=(astream,),
    )

    assessment = evaluate_feasibility(asset, av1_recipe)
    assert assessment.decision == "infeasible"
    assert assessment.is_hard_infeasible is True
    assert any("No compatible video stream" in r for r in assessment.rejection_reasons)


def test_savings_policy_both_vs_either(av1_recipe):
    """Verify 'both' (% AND bytes) vs 'either' (% OR bytes) policy logic."""
    # 100 MB file. Say predicted savings is 15 MB (15%).
    # Condition: 10% savings (10 MB) OR/AND 30 MB savings.
    # Meets 10% (10 MB), but fails 30 MB.
    vstream = VideoStream(
        stream_index=0,
        stream_type="video",
        codec_name="h264",
        width=1920,
        height=1080,
        bit_rate_bps=5_000_000,
        bitrate_provenance="ffprobe_stream",
    )
    asset = VideoAsset(
        source_id="policy-test",
        relative_path="clip.mp4",
        file_bytes=100_000_000,
        container_format="mp4",
        duration_seconds=160.0,
        streams=(vstream,),
    )

    # 'both': requires 10% AND 35 MB. Since 35 MB is unlikely/impossible with 100MB input, max output budget is 65 MB.
    # 'either': requires 10% OR 35 MB. Max output budget is 90 MB (from 10%).
    both_ass = evaluate_feasibility(asset, av1_recipe, min_savings_pct=10.0, min_savings_bytes=35_000_000, savings_policy="both")
    either_ass = evaluate_feasibility(asset, av1_recipe, min_savings_pct=10.0, min_savings_bytes=35_000_000, savings_policy="either")

    assert both_ass.max_output_container_bytes < either_ass.max_output_container_bytes


def test_recipe_cq_delta_scaling():
    """Higher CQ value (more aggressive compression) must predict smaller output video bytes."""
    r_cq30 = get_recipe("av1_nvenc_cq30")
    r_cq34 = get_recipe("av1_nvenc_cq34")

    vstream = VideoStream(
        stream_index=0,
        stream_type="video",
        codec_name="h264",
        width=1920,
        height=1080,
        bit_rate_bps=8_000_000,
        bitrate_provenance="ffprobe_stream",
    )
    asset = VideoAsset(
        source_id="cq-scaling",
        relative_path="clip.mp4",
        file_bytes=100_000_000,
        container_format="mp4",
        duration_seconds=100.0,
        streams=(vstream,),
    )

    ass30 = evaluate_feasibility(asset, r_cq30)
    ass34 = evaluate_feasibility(asset, r_cq34)

    assert ass34.p50_output_bytes < ass30.p50_output_bytes
    assert ass34.p50_savings_pct > ass30.p50_savings_pct


@pytest.mark.parametrize(
    "codec,width,height,bitrate,duration,file_bytes",
    [
        ("h264", 1920, 1080, 8_000_000, 1440.0, 1_500_000_000),
        ("hevc", 3840, 2160, 20_000_000, 600.0, 1_600_000_000),
        ("av1", 1280, 720, 1_200_000, 300.0, 50_000_000),
        ("h264", 640, 480, 600_000, 60.0, 5_000_000),
    ],
)
def test_quantile_identity_and_monotonicity_invariants(
    codec, width, height, bitrate, duration, file_bytes
):
    """Output bytes and savings bytes must strictly satisfy identity: Output(q) + Savings(q) == Source."""
    recipe = get_recipe("av1_nvenc_cq30")
    vstream = VideoStream(
        stream_index=0,
        stream_type="video",
        codec_name=codec,
        width=width,
        height=height,
        bit_rate_bps=bitrate,
        bitrate_provenance="ffprobe_stream",
    )
    astream = VideoStream(stream_index=1, stream_type="audio", codec_name="aac", bit_rate_bps=192_000)
    asset = VideoAsset(
        source_id="inv-asset",
        relative_path="asset.mp4",
        file_bytes=file_bytes,
        container_format="mp4",
        duration_seconds=duration,
        streams=(vstream, astream),
    )

    ass = evaluate_feasibility(asset, recipe)

    # 1. Strict additive identity: Output(q) + Savings(q) == Source
    assert ass.p10_output_bytes + ass.p10_savings_bytes == asset.file_bytes
    assert ass.p50_output_bytes + ass.p50_savings_bytes == asset.file_bytes
    assert ass.p90_output_bytes + ass.p90_savings_bytes == asset.file_bytes

    # 2. Monotonicity of output sizes: p10 <= p50 <= p90
    assert ass.p10_output_bytes <= ass.p50_output_bytes <= ass.p90_output_bytes

    # 3. Monotonicity of savings (inverses output size): p10 savings >= p50 savings >= p90 savings
    # Because p10 output is the smallest, its savings is the largest (optimistic)
    assert ass.p10_savings_bytes >= ass.p50_savings_bytes >= ass.p90_savings_bytes

    # 4. Calibration status must state uncalibrated scenario assumptions
    assert ass.calibration_status == "uncalibrated_scenario_assumptions"


def test_size_reconciliation_7_5mbps_discrepancy():
    """Test size reconciliation on 7.5 Mbps video stream over 1440s in a 1.5 GB source."""
    # 7.5 Mbps over 1440s implies 1.35 GB video payload.
    # Total source = 1.50 GB. Non-video streams ~42.748 MB.
    # Unaccounted container bytes ~107.252 MB (~7.15% discrepancy).
    recipe = get_recipe("av1_nvenc_cq30")
    vstream = VideoStream(
        stream_index=0,
        stream_type="video",
        codec_name="h264",
        width=1920,
        height=1080,
        bit_rate_bps=7_500_000,
        bitrate_provenance="ffprobe_stream",
    )
    # Audio 224 kbps stereo over 1440s = 40,320,000 bytes
    astream = VideoStream(stream_index=1, stream_type="audio", codec_name="aac", channels=2, bit_rate_bps=224_000)
    asset = VideoAsset(
        source_id="reconcile-test",
        relative_path="movie.mp4",
        file_bytes=1_500_000_000,
        container_format="mp4",
        duration_seconds=1440.0,
        streams=(vstream, astream),
    )

    ass = evaluate_feasibility(asset, recipe)
    recon = ass.reconciliation

    assert recon.source_bytes == 1_500_000_000
    assert recon.duration_seconds == 1440.0
    assert recon.probed_video_bitrate_bps == 7_500_000
    assert recon.implied_video_bytes == 1_350_000_000
    # Reconciliation must capture the unaccounted container bytes
    assert recon.unaccounted_container_bytes > 0
    assert abs(recon.unaccounted_ratio) > 0.05
    assert any("Container size discrepancy" in w for w in ass.warnings)


def test_estimated_nonvideo_decomposition_heuristics():
    """Non-video decomposition must explicitly label heuristics and never claim exact breakdown."""
    recipe = get_recipe("av1_nvenc_cq30")
    vstream = VideoStream(
        stream_index=0,
        stream_type="video",
        codec_name="h264",
        width=1920,
        height=1080,
        bit_rate_bps=5_000_000,
    )
    # Audio with missing bitrate -> estimated fallback
    astream = VideoStream(stream_index=1, stream_type="audio", codec_name="aac", channels=2, bit_rate_bps=None)
    asset = VideoAsset(
        source_id="heuristic-decomp",
        relative_path="heuristic.mkv",
        file_bytes=500_000_000,
        container_format="matroska",
        duration_seconds=600.0,
        streams=(vstream, astream),
    )

    ass = evaluate_feasibility(asset, recipe)
    assert ass.breakdown.decomposition_tier == "estimated_stream_heuristics"
    assert ass.breakdown.audio_provenance == "estimated_fallback"
    assert ass.breakdown.subtitle_provenance == "estimated_heuristic"
    assert ass.breakdown.mux_provenance == "estimated_container_model"
    # When heuristics are used, confidence must not be high
    assert ass.confidence in ("medium", "low")


