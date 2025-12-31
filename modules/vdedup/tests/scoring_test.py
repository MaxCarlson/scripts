from __future__ import annotations

from pathlib import Path

from vdedup import scoring
from vdedup.models import VideoMeta
from vdedup.pipeline import AlignmentResult


def _alignment(distance: float = 4.0) -> AlignmentResult:
    return AlignmentResult(
        distance=distance,
        base_offset=0,
        start_offset=0,
        step=1,
        shorter_len=120,
        longer_len=240,
    )


def test_score_subset_candidate_high_confidence() -> None:
    subset = VideoMeta(path=Path("a.mp4"), size=100, mtime=0.0, duration=30.0)
    superset = VideoMeta(path=Path("b.mp4"), size=200, mtime=0.0, duration=60.0)
    result = scoring.score_subset_candidate(
        subset=subset,
        superset=superset,
        match=_alignment(distance=3.0),
        detector="subset-phash",
    )
    assert result.final >= 0.5
    assert "subset-phash:visual" in result.positives
    assert result.negatives == {}


def test_score_subset_candidate_detects_penalty() -> None:
    subset = VideoMeta(path=Path("tiny.mp4"), size=50, mtime=0.0, duration=2.0)
    superset = VideoMeta(path=Path("long.mp4"), size=400, mtime=0.0, duration=300.0)
    result = scoring.score_subset_candidate(
        subset=subset,
        superset=superset,
        match=_alignment(distance=30.0),
        detector="subset-scene",
    )
    assert result.final < 0.5
    assert "duration_mismatch" in result.negatives or result.final == 0.0


def test_score_metadata_candidate_rewards_similarity() -> None:
    reference = VideoMeta(
        path=Path("ref.mp4"),
        size=1_000_000_000,
        mtime=0.0,
        duration=120.0,
        width=1920,
        height=1080,
        container="mp4",
        vcodec="h264",
        overall_bitrate=8_000_000,
        video_bitrate=6_000_000,
    )
    candidate = VideoMeta(
        path=Path("dup.mp4"),
        size=980_000_000,
        mtime=0.0,
        duration=119.5,
        width=1920,
        height=1080,
        container="mp4",
        vcodec="h264",
        overall_bitrate=7_900_000,
        video_bitrate=5_800_000,
    )
    result = scoring.score_metadata_candidate(
        reference=reference,
        candidate=candidate,
        tolerance=2.0,
        prefer_same_resolution=True,
        prefer_same_codec=True,
        prefer_same_container=True,
    )
    assert result.final > 0.7
    assert not result.negatives


def test_score_metadata_candidate_penalizes_mismatch() -> None:
    reference = VideoMeta(
        path=Path("ref.mp4"),
        size=1_000_000_000,
        mtime=0.0,
        duration=300.0,
        width=1920,
        height=1080,
        container="mp4",
        vcodec="h264",
        overall_bitrate=10_000_000,
    )
    candidate = VideoMeta(
        path=Path("different.mp4"),
        size=150_000_000,
        mtime=0.0,
        duration=40.0,
        width=854,
        height=480,
        container="mkv",
        vcodec="vp9",
        overall_bitrate=2_000_000,
    )
    result = scoring.score_metadata_candidate(
        reference=reference,
        candidate=candidate,
        tolerance=2.0,
        prefer_same_resolution=True,
        prefer_same_codec=True,
        prefer_same_container=True,
    )
    assert result.final < 0.3
    assert "duration_gap" in result.negatives or "resolution_gap" in result.negatives
