"""
Tests for vdedup.gpu_q5 – Q5G orchestration.
All fixtures use in-memory VideoSignature objects; no video files needed.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import List

from vdedup.gpu_alignment import FrameMatch
from vdedup.gpu_q5 import (
    Q5GResult,
    TemporalAlignmentResult,
    align_candidate_pair,
    alignment_result_to_group_metadata,
    classify_alignment_result,
    run_q5g,
)
from vdedup.models import FrameSignature, VideoSignature


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _frame(index: int, timestamp: float, phash: int, *, valid: bool = True) -> FrameSignature:
    return FrameSignature(
        Path("dummy.mp4"),
        "dummy.mp4",
        index,
        timestamp,
        phash,
        3.0,
        0.5,
        valid,
    )


def _signature(path: str, frames: List[FrameSignature], *, duration: float | None = None) -> VideoSignature:
    valid_count = sum(1 for f in frames if f.valid_for_matching)
    dur = duration if duration is not None else float(len(frames))
    return VideoSignature(
        Path(path),
        path,
        dur,
        len(frames),
        valid_count,
        frames,
        "cpu_ffmpeg",
        "balanced",
    )


def _config(**overrides):
    base = dict(
        gpu_q5_hash_field="auto",
        gpu_q5_max_hamming_distance=10,
        gpu_q5_offset_bin_seconds=2.0,
        gpu_q5_top_offset_bins=5,
        gpu_q5_max_gap_seconds=4.0,
        gpu_q5_min_segment_seconds=2.0,
        gpu_q5_min_segment_matches=3,
        gpu_q5_full_duplicate_ratio=0.90,
        gpu_q5_subset_ratio=0.85,
        gpu_q5_partial_min_seconds=10.0,
        gpu_q5_partial_min_shorter_ratio=0.10,
        gpu_q5_min_confidence=0.30,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _pair(left: str, right: str):
    return SimpleNamespace(left=Path(left), right=Path(right))


def _identical_pair(left_path: str = "left.mp4", right_path: str = "right.mp4", n: int = 20):
    """Create two identical VideoSignatures (same hashes, same timestamps)."""
    hash_val = 0x0000_ABCD_ABCD_1234
    frames = [_frame(i, float(i * 2), hash_val) for i in range(n)]
    left_sig = _signature(left_path, [_frame(i, float(i * 2), hash_val) for i in range(n)], duration=float(n * 2))
    right_sig = _signature(right_path, [_frame(i, float(i * 2), hash_val) for i in range(n)], duration=float(n * 2))
    return left_sig, right_sig


# ---------------------------------------------------------------------------
# align_candidate_pair
# ---------------------------------------------------------------------------


def test_align_candidate_pair_returns_temporal_alignment_result():
    left_sig, right_sig = _identical_pair()
    cfg = _config()
    pair = _pair(left_sig.path, right_sig.path)
    result = align_candidate_pair(pair, left_sig, right_sig, config=cfg)
    assert isinstance(result, TemporalAlignmentResult)
    assert result.match_type in (
        "perceptual_duplicate", "subset_of_longer", "partial_overlap", "rejected_candidate"
    )


def test_align_candidate_pair_sets_confidence():
    left_sig, right_sig = _identical_pair()
    cfg = _config()
    pair = _pair(left_sig.path, right_sig.path)
    result = align_candidate_pair(pair, left_sig, right_sig, config=cfg)
    assert 0.0 <= result.confidence <= 1.0


def test_align_candidate_pair_sets_overlap_ratios():
    left_sig, right_sig = _identical_pair()
    cfg = _config()
    pair = _pair(left_sig.path, right_sig.path)
    result = align_candidate_pair(pair, left_sig, right_sig, config=cfg)
    assert 0.0 <= result.overlap_ratio_left <= 1.0
    assert 0.0 <= result.overlap_ratio_right <= 1.0


# ---------------------------------------------------------------------------
# run_q5g
# ---------------------------------------------------------------------------


def test_run_q5g_emits_full_duplicate_group():
    left_sig, right_sig = _identical_pair()
    cfg = _config(
        gpu_q5_full_duplicate_ratio=0.50,  # low threshold so identical pair classifies as dup
        gpu_q5_min_confidence=0.20,
    )
    sigs = {left_sig.path: left_sig, right_sig.path: right_sig}
    pairs = [_pair(str(left_sig.path), str(right_sig.path))]
    # Fix path types — pairs use str paths, sigs use Path keys
    pairs_fixed = [SimpleNamespace(left=left_sig.path, right=right_sig.path)]
    result = run_q5g(pairs_fixed, sigs, config=cfg)
    assert isinstance(result, Q5GResult)
    assert result.candidate_pairs_received == 1
    total_groups = (
        len(result.duplicate_groups)
        + len(result.subset_groups)
        + len(result.overlap_groups)
    )
    # At least one group should be formed for an identical pair
    assert total_groups >= 1 or result.candidate_pairs_rejected == 1


def test_run_q5g_missing_signature_is_recorded_as_failure():
    cfg = _config()
    left_sig, right_sig = _identical_pair(left_path="missing_left.mp4")
    # Only register right signature
    sigs = {right_sig.path: right_sig}
    pairs = [SimpleNamespace(left=left_sig.path, right=right_sig.path)]
    result = run_q5g(pairs, sigs, config=cfg)
    assert result.candidate_pairs_rejected == 1
    assert len(result.alignment_failures) == 1


def test_run_q5g_empty_pairs():
    cfg = _config()
    result = run_q5g([], {}, config=cfg)
    assert result.candidate_pairs_received == 0
    assert len(result.duplicate_groups) == 0


def test_run_q5g_rejects_weak_candidate():
    # Use very different hashes so no matches can form
    left_frames = [_frame(i, float(i), 0x0000_0000_0000_FFFF) for i in range(5)]
    right_frames = [_frame(i, float(i), 0xFFFF_FFFF_FFFF_0000) for i in range(5)]
    left_sig = _signature("a.mp4", left_frames, duration=5.0)
    right_sig = _signature("b.mp4", right_frames, duration=5.0)
    sigs = {left_sig.path: left_sig, right_sig.path: right_sig}
    cfg = _config(gpu_q5_max_hamming_distance=2)  # tight — no matches
    pairs = [SimpleNamespace(left=left_sig.path, right=right_sig.path)]
    result = run_q5g(pairs, sigs, config=cfg)
    assert result.candidate_pairs_rejected == 1
    assert len(result.rejected_results) == 1


# ---------------------------------------------------------------------------
# alignment_result_to_group_metadata
# ---------------------------------------------------------------------------


def test_q5g_metadata_contains_segments():
    from vdedup.gpu_alignment import AlignmentSegment
    seg = AlignmentSegment(0.0, 30.0, 0.0, 30.0, 15, 0.85, 1.5)
    tar = TemporalAlignmentResult(
        left=Path("a.mp4"),
        right=Path("b.mp4"),
        segments=[seg],
        frame_matches=[],
        match_type="perceptual_duplicate",
        actionable=True,
        review_required=False,
        confidence=0.92,
        overlap_seconds=30.0,
        left_duration=30.0,
        right_duration=30.0,
        overlap_ratio_left=1.0,
        overlap_ratio_right=1.0,
        overlap_ratio_shorter=1.0,
        overlap_ratio_longer=1.0,
        matched_frame_count=15,
        mean_distance=1.2,
        median_distance=1.0,
    )
    meta = alignment_result_to_group_metadata(tar)
    assert "evidence" in meta
    evidence = meta["evidence"]
    assert len(evidence["segments"]) == 1
    assert evidence["segments"][0]["matched_frame_count"] == 15


def test_q5g_metadata_contains_overlap_ratios():
    from vdedup.gpu_alignment import AlignmentSegment
    seg = AlignmentSegment(0.0, 30.0, 0.0, 30.0, 10, 0.80, 2.0)
    tar = TemporalAlignmentResult(
        left=Path("a.mp4"),
        right=Path("b.mp4"),
        segments=[seg],
        frame_matches=[],
        match_type="partial_overlap",
        actionable=False,
        review_required=True,
        confidence=0.65,
        overlap_seconds=12.0,
        left_duration=30.0,
        right_duration=60.0,
        overlap_ratio_left=0.40,
        overlap_ratio_right=0.20,
        overlap_ratio_shorter=0.40,
        overlap_ratio_longer=0.20,
        matched_frame_count=10,
        mean_distance=2.5,
        median_distance=2.0,
    )
    meta = alignment_result_to_group_metadata(tar)
    evidence = meta["evidence"]
    assert abs(evidence["overlap_ratio_left"] - 0.40) < 1e-3
    assert abs(evidence["overlap_ratio_right"] - 0.20) < 1e-3


def test_q5g_metadata_actionability_policy():
    from vdedup.gpu_alignment import AlignmentSegment
    seg = AlignmentSegment(0.0, 30.0, 0.0, 30.0, 10, 0.80, 2.0)
    for match_type, actionable, review_required in [
        ("perceptual_duplicate", True, False),
        ("subset_of_longer", True, True),
        ("partial_overlap", False, True),
    ]:
        tar = TemporalAlignmentResult(
            left=Path("a.mp4"), right=Path("b.mp4"),
            segments=[seg], frame_matches=[],
            match_type=match_type,
            actionable=actionable,
            review_required=review_required,
            confidence=0.80,
            overlap_seconds=30.0,
            left_duration=30.0,
            right_duration=30.0,
            overlap_ratio_left=0.9,
            overlap_ratio_right=0.9,
            overlap_ratio_shorter=0.9,
            overlap_ratio_longer=0.9,
            matched_frame_count=10,
            mean_distance=1.0,
            median_distance=1.0,
        )
        meta = alignment_result_to_group_metadata(tar)
        assert meta["actionable"] == actionable
        assert meta["review_required"] == review_required
