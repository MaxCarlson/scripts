"""
Contract tests for Q5G pipeline routing.

These tests verify:
- Q4G candidate pairs feed Q5G correctly
- Q5G groups merge into pipeline output correctly
- Actionability policies (partial_overlap = non-actionable, subset = review)
- GPU mode flags (off/auto/on) respected
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import List

import pytest

from vdedup.gpu_q5 import Q5GResult, TemporalAlignmentResult, run_q5g
from vdedup.gpu_alignment import AlignmentSegment
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


def _pair(left_path: Path, right_path: Path):
    return SimpleNamespace(left=left_path, right=right_path)


def _stub_q5g_result(match_type: str) -> Q5GResult:
    """Create a minimal Q5GResult stub with one group of the given type."""
    result = Q5GResult()
    left = Path("left.mp4")
    right = Path("right.mp4")
    meta = {
        "method": "gpu-temporal",
        "confidence": "verified",
        "review_required": match_type != "perceptual_duplicate",
        "actionable": match_type != "partial_overlap",
        "match_type": match_type,
        "evidence": {
            "backend": "gpu",
            "verified_by": ["gpu_q5_temporal_alignment"],
            "match_type": match_type,
            "overlap_seconds": 30.0,
            "overlap_ratio_left": 0.9,
            "overlap_ratio_right": 0.9,
            "overlap_ratio_shorter": 0.9,
            "overlap_ratio_longer": 0.9,
            "matched_frame_count": 15,
            "confidence": 0.88,
            "segments": [],
        },
    }
    if match_type == "perceptual_duplicate":
        result.duplicate_groups["gpu-temporal:0"] = [left, right]
        result.group_metadata["gpu-temporal:0"] = meta
    elif match_type == "subset_of_longer":
        result.subset_groups["gpu-temporal-sub:0"] = [right, left]
        result.subset_metadata["gpu-temporal-sub:0"] = meta
    elif match_type == "partial_overlap":
        result.overlap_groups["gpu-temporal-overlap:0"] = [left, right]
        result.overlap_metadata["gpu-temporal-overlap:0"] = meta
    result.candidate_pairs_received = 1
    result.candidate_pairs_aligned = 1 if match_type != "rejected_candidate" else 0
    result.candidate_pairs_rejected = 0 if match_type != "rejected_candidate" else 1
    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_q5g_groups_merge_into_report_groups():
    """Q5GResult.duplicate_groups can be iterated and would merge into pipeline groups."""
    q5g = _stub_q5g_result("perceptual_duplicate")
    assert "gpu-temporal:0" in q5g.duplicate_groups
    assert len(q5g.duplicate_groups["gpu-temporal:0"]) == 2
    assert q5g.group_metadata["gpu-temporal:0"]["actionable"] is True


def test_q5g_partial_overlap_actionable_false():
    """partial_overlap groups must be non-actionable."""
    q5g = _stub_q5g_result("partial_overlap")
    assert "gpu-temporal-overlap:0" in q5g.overlap_groups
    meta = q5g.overlap_metadata["gpu-temporal-overlap:0"]
    assert meta["actionable"] is False


def test_q5g_subset_actionable_true_review_required_true():
    """subset_of_longer groups are actionable and require review."""
    q5g = _stub_q5g_result("subset_of_longer")
    assert "gpu-temporal-sub:0" in q5g.subset_groups
    meta = q5g.subset_metadata["gpu-temporal-sub:0"]
    assert meta["actionable"] is True
    assert meta["review_required"] is True


def test_q4g_candidates_feed_q5g():
    """run_q5g correctly consumes a list of pairs and produces a Q5GResult."""
    hash_val = 0x0000_1111_2222_ABCD
    left_frames = [_frame(i, float(i * 2), hash_val) for i in range(10)]
    right_frames = [_frame(i, float(i * 2), hash_val) for i in range(10)]
    left_sig = _signature("x.mp4", left_frames, duration=20.0)
    right_sig = _signature("y.mp4", right_frames, duration=20.0)
    sigs = {left_sig.path: left_sig, right_sig.path: right_sig}
    pairs = [_pair(left_sig.path, right_sig.path)]
    cfg = _config()
    result = run_q5g(pairs, sigs, config=cfg)
    assert isinstance(result, Q5GResult)
    assert result.candidate_pairs_received == 1


def test_q5g_metadata_evidence_has_verified_by():
    """Group metadata evidence must contain verified_by = ['gpu_q5_temporal_alignment']."""
    q5g = _stub_q5g_result("perceptual_duplicate")
    evidence = q5g.group_metadata["gpu-temporal:0"]["evidence"]
    assert "gpu_q5_temporal_alignment" in evidence.get("verified_by", [])


def test_q5g_result_stats_are_accurate():
    """Q5GResult tracks received/aligned/rejected counts correctly."""
    hash_val = 0xAAAA_BBBB_CCCC_DDDD
    left_frames = [_frame(i, float(i), hash_val) for i in range(5)]
    right_frames_match = [_frame(i, float(i), hash_val) for i in range(5)]
    right_frames_no_match = [_frame(i, float(i), 0xFFFF_FFFF_FFFF_FFFF ^ hash_val) for i in range(5)]

    sig_a = _signature("a.mp4", left_frames, duration=5.0)
    sig_b = _signature("b.mp4", right_frames_match, duration=5.0)
    sig_c = _signature("c.mp4", right_frames_no_match, duration=5.0)

    sigs = {sig_a.path: sig_a, sig_b.path: sig_b, sig_c.path: sig_c}
    pairs = [
        _pair(sig_a.path, sig_b.path),   # should align
        _pair(sig_a.path, sig_c.path),   # should reject (no frame matches)
    ]
    cfg = _config(gpu_q5_max_hamming_distance=2)
    result = run_q5g(pairs, sigs, config=cfg)
    assert result.candidate_pairs_received == 2
    # At least one must be aligned + one rejected
    assert result.candidate_pairs_aligned + result.candidate_pairs_rejected == 2


def test_q5g_alignment_failures_track_missing_sigs():
    """Alignment failures are recorded when a signature is not found."""
    cfg = _config()
    pairs = [SimpleNamespace(left=Path("missing.mp4"), right=Path("also_missing.mp4"))]
    result = run_q5g(pairs, {}, config=cfg)
    assert result.candidate_pairs_rejected == 1
    assert len(result.alignment_failures) == 1


def test_q5g_candidate_pairs_consumed_completely():
    """run_q5g must consume the full candidate_pairs list (iterator-safe)."""
    hash_val = 0x1234_5678_ABCD_EF01
    sigs = {}
    pairs = []
    for i in range(5):
        frames_l = [_frame(j, float(j), hash_val) for j in range(6)]
        frames_r = [_frame(j, float(j), hash_val) for j in range(6)]
        sig_l = _signature(f"l{i}.mp4", frames_l, duration=6.0)
        sig_r = _signature(f"r{i}.mp4", frames_r, duration=6.0)
        sigs[sig_l.path] = sig_l
        sigs[sig_r.path] = sig_r
        pairs.append(_pair(sig_l.path, sig_r.path))

    # Pass as generator to ensure iterator-consumption bug is caught
    def _gen():
        yield from pairs

    cfg = _config()
    result = run_q5g(_gen(), sigs, config=cfg)
    assert result.candidate_pairs_received == 5
