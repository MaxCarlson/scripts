"""
Tests for configurable lower-bound eligibility and exclusion filtering.
"""

from __future__ import annotations

import pytest

from videocompress.contracts import VideoAsset, VideoStream
from videocompress.eligibility import (
    evaluate_eligibility,
    parse_bitrate,
    parse_duration,
    parse_resolution,
    parse_size,
)


def test_parsers():
    assert parse_bitrate("4M") == 4_000_000
    assert parse_bitrate("2.5M") == 2_500_000
    assert parse_bitrate("500k") == 500_000
    assert parse_bitrate(2000000) == 2000000

    assert parse_resolution("1920x1080") == (1920, 1080)
    assert parse_resolution("3840X2160") == (3840, 2160)

    assert parse_size("100M") == 100_000_000
    assert parse_size("1G") == 1_000_000_000
    assert parse_size(5000) == 5000

    assert parse_duration("60") == 60.0
    assert parse_duration("10m") == 600.0
    assert parse_duration("1.5h") == 5400.0


def test_evaluate_eligibility_all_pass():
    vs = VideoStream(
        stream_index=0,
        stream_type="video",
        codec_name="h264",
        width=1920,
        height=1080,
        bit_rate_bps=6_000_000,
        bitrate_provenance="ffprobe_stream",
        rotation_degrees=0,
    )
    asset = VideoAsset(
        source_id="s1",
        relative_path="clip.mp4",
        file_bytes=200_000_000,
        container_format="mp4",
        duration_seconds=300.0,
        streams=(vs,),
    )

    dec = evaluate_eligibility(
        asset,
        min_video_bitrate="4M",
        min_resolution="1920x1080",
        min_size="50M",
        min_duration="60",
    )
    assert dec.status == "eligible"
    assert "all_thresholds_met" in dec.reasons


def test_evaluate_eligibility_below_bitrate():
    vs = VideoStream(
        stream_index=0,
        stream_type="video",
        codec_name="h264",
        width=1920,
        height=1080,
        bit_rate_bps=2_000_000,
        bitrate_provenance="ffprobe_stream",
    )
    asset = VideoAsset(
        source_id="s1",
        relative_path="clip.mp4",
        file_bytes=200_000_000,
        container_format="mp4",
        duration_seconds=300.0,
        streams=(vs,),
    )

    dec = evaluate_eligibility(asset, min_video_bitrate="4M")
    assert dec.status == "excluded"
    assert any("below_min_bitrate" in r for r in dec.reasons)


def test_evaluate_eligibility_missing_bitrate_is_unknown():
    vs = VideoStream(
        stream_index=0,
        stream_type="video",
        codec_name="h264",
        width=1920,
        height=1080,
        bit_rate_bps=None,
        bitrate_provenance="missing",
    )
    asset = VideoAsset(
        source_id="s1",
        relative_path="clip.mp4",
        file_bytes=200_000_000,
        container_format="mp4",
        duration_seconds=300.0,
        streams=(vs,),
    )

    dec = evaluate_eligibility(asset, min_video_bitrate="4M")
    assert dec.status == "unknown"
    assert "unknown_video_bitrate" in dec.unknowns


def test_evaluate_eligibility_rotated_resolution():
    # Video encoded at 1080x1920 with 90 deg rotation -> display orientation is 1920x1080
    vs = VideoStream(
        stream_index=0,
        stream_type="video",
        codec_name="h264",
        width=1080,
        height=1920,
        bit_rate_bps=5_000_000,
        bitrate_provenance="ffprobe_stream",
        rotation_degrees=90,
    )
    asset = VideoAsset(
        source_id="s1",
        relative_path="clip.mp4",
        file_bytes=100_000_000,
        container_format="mp4",
        duration_seconds=120.0,
        streams=(vs,),
    )

    dec = evaluate_eligibility(asset, min_resolution="1920x1080")
    assert dec.status == "eligible"


def test_evaluate_eligibility_multiple_video_streams():
    vs1 = VideoStream(stream_index=0, stream_type="video", codec_name="h264", width=1920, height=1080, bit_rate_bps=5000000)
    vs2 = VideoStream(stream_index=1, stream_type="video", codec_name="h264", width=1280, height=720, bit_rate_bps=2000000)
    asset = VideoAsset(
        source_id="s1",
        relative_path="clip.mkv",
        file_bytes=100_000_000,
        container_format="matroska",
        duration_seconds=120.0,
        streams=(vs1, vs2),
    )

    dec = evaluate_eligibility(asset)
    assert dec.status == "unsupported"
    assert any("multiple_video_streams" in r for r in dec.reasons)
