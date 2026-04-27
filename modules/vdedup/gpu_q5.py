"""
vdedup.gpu_q5

Q5G – Temporal Alignment Orchestrator.

Consumes Q4G candidate pairs (VisualCandidatePair objects) together with the
extracted VideoSignature objects and classifies each pair via temporal alignment
into one of:

  perceptual_duplicate  – actionable=True,  review_required=False
  subset_of_longer      – actionable=True,  review_required=True
  partial_overlap       – actionable=False, review_required=True
  rejected_candidate    – not serialised

Public API:
  run_q5g(candidate_pairs, signatures_by_path, *, config, reporter=None) -> Q5GResult
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, median
from typing import Any, Dict, List, Optional, Sequence, Tuple

from vdedup.gpu_alignment import (
    AlignmentSegment,
    FrameMatch,
    build_frame_matches,
    compute_alignment_confidence,
    extract_alignment_segments,
    union_interval_seconds,
    vote_offsets,
)
from vdedup.models import VideoSignature


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class TemporalAlignmentResult:
    left: Path
    right: Path
    segments: List[AlignmentSegment]
    frame_matches: List[FrameMatch]
    match_type: str         # "perceptual_duplicate" | "subset_of_longer" | "partial_overlap" | "rejected_candidate"
    actionable: bool
    review_required: bool
    confidence: float
    overlap_seconds: float
    left_duration: Optional[float]
    right_duration: Optional[float]
    overlap_ratio_left: float
    overlap_ratio_right: float
    overlap_ratio_shorter: float
    overlap_ratio_longer: float
    matched_frame_count: int
    mean_distance: Optional[float]
    median_distance: Optional[float]


@dataclass(slots=True)
class Q5GResult:
    # Groups keyed by group_id
    duplicate_groups: Dict[str, List[Path]] = field(default_factory=dict)
    group_metadata: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    subset_groups: Dict[str, List[Path]] = field(default_factory=dict)
    subset_metadata: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    overlap_groups: Dict[str, List[Path]] = field(default_factory=dict)
    overlap_metadata: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    rejected_results: List[TemporalAlignmentResult] = field(default_factory=list)
    # Stats
    candidate_pairs_received: int = 0
    candidate_pairs_aligned: int = 0
    candidate_pairs_rejected: int = 0
    alignment_seconds_total: float = 0.0
    alignment_failures: Dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sampled_span(sig: VideoSignature) -> Optional[float]:
    """
    Estimate video duration from sampled frame timestamps when
    VideoSignature.duration_seconds is unavailable.
    """
    ts = [f.timestamp_seconds for f in sig.signatures if f.valid_for_matching]
    if len(ts) < 2:
        return None
    return max(ts) - min(ts)


def _low_entropy_fraction(sig: VideoSignature) -> float:
    """Fraction of frames with low entropy (potential black/solid frames)."""
    valid = [f for f in sig.signatures if f.valid_for_matching]
    if not valid:
        return 0.0
    low = sum(1 for f in valid if getattr(f, "entropy", 1.0) < 0.5)
    return low / len(valid)


def _segment_to_dict(seg: AlignmentSegment) -> Dict[str, Any]:
    return {
        "start_left_seconds": seg.start_left_seconds,
        "end_left_seconds": seg.end_left_seconds,
        "start_right_seconds": seg.start_right_seconds,
        "end_right_seconds": seg.end_right_seconds,
        "matched_frame_count": seg.matched_frame_count,
        "score": round(seg.score, 4),
        "median_distance": round(seg.median_distance, 2),
    }


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def align_candidate_pair(
    pair: object,
    left_sig: VideoSignature,
    right_sig: VideoSignature,
    *,
    config: object,
) -> TemporalAlignmentResult:
    """
    Run temporal alignment on a single candidate pair.

    Returns a classified TemporalAlignmentResult.
    """
    hash_field = str(getattr(config, "gpu_q5_hash_field", "auto"))
    max_hamming = int(getattr(config, "gpu_q5_max_hamming_distance", 10))
    bin_seconds = float(getattr(config, "gpu_q5_offset_bin_seconds", 2.0))
    top_k = int(getattr(config, "gpu_q5_top_offset_bins", 5))
    max_gap = float(getattr(config, "gpu_q5_max_gap_seconds", 4.0))
    min_seg_secs = float(getattr(config, "gpu_q5_min_segment_seconds", 5.0))
    min_seg_matches = int(getattr(config, "gpu_q5_min_segment_matches", 4))

    left_path = getattr(pair, "left", left_sig.path)
    right_path = getattr(pair, "right", right_sig.path)

    # Step 1: frame matches
    frame_matches = build_frame_matches(
        left_sig,
        right_sig,
        hash_field=hash_field,
        max_hamming_distance=max_hamming,
    )

    # Step 2: offset voting
    offset_bins = vote_offsets(frame_matches, bin_size_seconds=bin_seconds)

    # Step 3: segment extraction
    segments = extract_alignment_segments(
        frame_matches,
        offset_bins=offset_bins,
        bin_size_seconds=bin_seconds,
        max_gap_seconds=max_gap,
        min_segment_seconds=min_seg_secs,
        min_segment_matches=min_seg_matches,
        top_k_bins=top_k,
    )

    # Step 4: compute coverage
    left_dur = left_sig.duration_seconds or _sampled_span(left_sig)
    right_dur = right_sig.duration_seconds or _sampled_span(right_sig)

    left_intervals = [(s.start_left_seconds, s.end_left_seconds) for s in segments]
    right_intervals = [(s.start_right_seconds, s.end_right_seconds) for s in segments]
    left_covered = union_interval_seconds(left_intervals)
    right_covered = union_interval_seconds(right_intervals)
    overlap_seconds = min(left_covered, right_covered)

    def _ratio(covered: float, total: Optional[float]) -> float:
        if total is None or total <= 0:
            return 0.0
        return min(1.0, covered / total)

    ratio_left = _ratio(left_covered, left_dur)
    ratio_right = _ratio(right_covered, right_dur)

    if left_dur is not None and right_dur is not None:
        shorter_dur = min(left_dur, right_dur)
        longer_dur = max(left_dur, right_dur)
        ratio_shorter = _ratio(overlap_seconds, shorter_dur)
        ratio_longer = _ratio(overlap_seconds, longer_dur)
    else:
        ratio_shorter = max(ratio_left, ratio_right)
        ratio_longer = min(ratio_left, ratio_right)

    # Step 5: distance stats
    all_dists = [m.distance for m in frame_matches if any(
        s.start_left_seconds <= m.left_timestamp_seconds <= s.end_left_seconds
        for s in segments
    )]
    mean_dist = mean(all_dists) if all_dists else None
    med_dist = median(all_dists) if all_dists else None
    matched_count = sum(s.matched_frame_count for s in segments)

    # Step 6: confidence
    lef = _low_entropy_fraction(left_sig)
    ref = _low_entropy_fraction(right_sig)
    low_entropy_frac = max(lef, ref)
    confidence = compute_alignment_confidence(
        segments,
        overlap_ratio_shorter=ratio_shorter,
        max_hamming_distance=max_hamming,
        low_entropy_fraction=low_entropy_frac,
        allowed_max_gap=max_gap,
    )

    # Step 7: classification
    result = TemporalAlignmentResult(
        left=left_path,
        right=right_path,
        segments=segments,
        frame_matches=frame_matches,
        match_type="rejected_candidate",
        actionable=False,
        review_required=False,
        confidence=confidence,
        overlap_seconds=overlap_seconds,
        left_duration=left_dur,
        right_duration=right_dur,
        overlap_ratio_left=ratio_left,
        overlap_ratio_right=ratio_right,
        overlap_ratio_shorter=ratio_shorter,
        overlap_ratio_longer=ratio_longer,
        matched_frame_count=matched_count,
        mean_distance=mean_dist,
        median_distance=med_dist,
    )
    return classify_alignment_result(result, config=config)


def classify_alignment_result(
    result: TemporalAlignmentResult,
    *,
    config: object,
) -> TemporalAlignmentResult:
    """
    Apply classification rules and return a new result with match_type,
    actionable, and review_required set.
    """
    full_dup_ratio = float(getattr(config, "gpu_q5_full_duplicate_ratio", 0.90))
    subset_ratio = float(getattr(config, "gpu_q5_subset_ratio", 0.85))
    partial_min_secs = float(getattr(config, "gpu_q5_partial_min_seconds", 10.0))
    partial_min_shorter = float(getattr(config, "gpu_q5_partial_min_shorter_ratio", 0.10))
    min_confidence = float(getattr(config, "gpu_q5_min_confidence", 0.50))

    if not result.segments:
        # No valid alignment segments — reject
        result.match_type = "rejected_candidate"
        result.actionable = False
        result.review_required = False
        return result

    if (result.confidence >= min_confidence
            and result.overlap_ratio_left >= full_dup_ratio
            and result.overlap_ratio_right >= full_dup_ratio):
        result.match_type = "perceptual_duplicate"
        result.actionable = True
        result.review_required = False
    elif (result.confidence >= min_confidence
            and result.overlap_ratio_shorter >= subset_ratio
            and result.overlap_ratio_longer < full_dup_ratio):
        result.match_type = "subset_of_longer"
        result.actionable = True
        result.review_required = True
    elif (result.overlap_seconds >= partial_min_secs
            or result.overlap_ratio_shorter >= partial_min_shorter):
        result.match_type = "partial_overlap"
        result.actionable = False
        result.review_required = True
    else:
        result.match_type = "rejected_candidate"
        result.actionable = False
        result.review_required = False

    return result


def alignment_result_to_group_metadata(
    result: TemporalAlignmentResult,
    *,
    hash_field: str = "auto",
) -> Dict[str, Any]:
    """Serialise a TemporalAlignmentResult into the report group metadata dict."""
    segments_payload = [_segment_to_dict(s) for s in result.segments]
    evidence: Dict[str, Any] = {
        "backend": "gpu",
        "verified_by": ["gpu_q5_temporal_alignment"],
        "hash_field": hash_field,
        "match_type": result.match_type,
        "overlap_seconds": round(result.overlap_seconds, 3),
        "overlap_ratio_left": round(result.overlap_ratio_left, 4),
        "overlap_ratio_right": round(result.overlap_ratio_right, 4),
        "overlap_ratio_shorter": round(result.overlap_ratio_shorter, 4),
        "overlap_ratio_longer": round(result.overlap_ratio_longer, 4),
        "matched_frame_count": result.matched_frame_count,
        "confidence": round(result.confidence, 4),
        "segments": segments_payload,
    }
    if result.mean_distance is not None:
        evidence["mean_hamming_distance"] = round(result.mean_distance, 3)
    if result.median_distance is not None:
        evidence["median_hamming_distance"] = round(result.median_distance, 3)
    if result.match_type == "subset_of_longer":
        if result.left_duration is not None and result.right_duration is not None:
            if result.right_duration > result.left_duration:
                evidence["shorter_path"] = str(result.left)
                evidence["longer_path"] = str(result.right)
            else:
                evidence["shorter_path"] = str(result.right)
                evidence["longer_path"] = str(result.left)

    method_map = {
        "perceptual_duplicate": "gpu-temporal",
        "subset_of_longer":     "gpu-temporal-subset",
        "partial_overlap":      "gpu-temporal-overlap",
    }
    method = method_map.get(result.match_type, "gpu-temporal")

    return {
        "method": method,
        "confidence": "verified" if result.confidence >= 0.80 else "low",
        "review_required": result.review_required,
        "actionable": result.actionable,
        "match_type": result.match_type,
        "evidence": evidence,
    }


def run_q5g(
    candidate_pairs: Sequence[object],
    signatures_by_path: Dict[Path, VideoSignature],
    *,
    config: object,
    reporter: Optional[object] = None,
) -> Q5GResult:
    """
    Run Q5G temporal alignment on a sequence of VisualCandidatePair objects.

    Requires VideoSignature objects for each pair member, passed via
    signatures_by_path (keyed by normalised Path).

    Returns a Q5GResult with classified groups.
    """
    result = Q5GResult()
    pairs = list(candidate_pairs)
    result.candidate_pairs_received = len(pairs)

    hash_field = str(getattr(config, "gpu_q5_hash_field", "auto"))

    dup_index = 0
    sub_index = 0
    overlap_index = 0
    t_total = 0.0

    for pair in pairs:
        left_path: Path = getattr(pair, "left")
        right_path: Path = getattr(pair, "right")
        pair_key = f"{left_path}|{right_path}"

        left_sig = signatures_by_path.get(left_path)
        right_sig = signatures_by_path.get(right_path)

        if left_sig is None or right_sig is None:
            result.alignment_failures[pair_key] = (
                "signature not found for "
                + ("left" if left_sig is None else "right")
            )
            result.candidate_pairs_rejected += 1
            continue

        try:
            t0 = time.monotonic()
            aligned = align_candidate_pair(pair, left_sig, right_sig, config=config)
            t_total += time.monotonic() - t0
        except Exception as exc:
            result.alignment_failures[pair_key] = str(exc)
            result.candidate_pairs_rejected += 1
            continue

        if aligned.match_type == "rejected_candidate":
            result.rejected_results.append(aligned)
            result.candidate_pairs_rejected += 1
            continue

        result.candidate_pairs_aligned += 1
        meta = alignment_result_to_group_metadata(aligned, hash_field=hash_field)

        if aligned.match_type == "perceptual_duplicate":
            gid = f"gpu-temporal:{dup_index}"
            dup_index += 1
            result.duplicate_groups[gid] = [left_path, right_path]
            result.group_metadata[gid] = meta

        elif aligned.match_type == "subset_of_longer":
            gid = f"gpu-temporal-sub:{sub_index}"
            sub_index += 1
            # Put longer/master first if durations known
            if (aligned.left_duration is not None and aligned.right_duration is not None
                    and aligned.right_duration > aligned.left_duration):
                members = [right_path, left_path]
            else:
                members = [left_path, right_path]
            result.subset_groups[gid] = members
            result.subset_metadata[gid] = meta

        elif aligned.match_type == "partial_overlap":
            gid = f"gpu-temporal-overlap:{overlap_index}"
            overlap_index += 1
            result.overlap_groups[gid] = [left_path, right_path]
            result.overlap_metadata[gid] = meta

        if reporter is not None:
            try:
                reporter.inc_hashed(1, cache_hit=False)
            except Exception:
                pass

    result.alignment_seconds_total = t_total
    return result
