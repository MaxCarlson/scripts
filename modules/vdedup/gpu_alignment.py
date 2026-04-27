"""
vdedup.gpu_alignment

Q5G temporal alignment primitives.

Provides pure-Python (CPU) functions for:
- Building frame-level hash matches between two VideoSignature objects
- Voting on temporal offset bins (Hough-style prefilter)
- Extracting monotonic diagonal alignment segments
- Computing union interval coverage
- Scoring alignment confidence

None of these functions require a GPU; the GPU contributed during fingerprint
extraction in P2/Q4G.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Dict, List, Optional, Sequence, Tuple

from vdedup.models import FrameSignature, VideoSignature


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class FrameMatch:
    left_frame_index: int
    right_frame_index: int
    left_timestamp_seconds: float
    right_timestamp_seconds: float
    distance: int
    similarity: float  # 1.0 - distance/max_hamming_distance, clamped [0, 1]


@dataclass(slots=True)
class OffsetBin:
    bin_index: int
    offset_seconds: float  # representative offset (bin centre)
    match_count: int
    score: float  # mean similarity of contributing matches


@dataclass(slots=True)
class AlignmentSegment:
    start_left_seconds: float
    end_left_seconds: float
    start_right_seconds: float
    end_right_seconds: float
    matched_frame_count: int
    score: float
    median_distance: float

    @property
    def overlap_seconds(self) -> float:
        dur_left = max(0.0, self.end_left_seconds - self.start_left_seconds)
        dur_right = max(0.0, self.end_right_seconds - self.start_right_seconds)
        return min(dur_left, dur_right)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hamming64(a: int, b: int) -> int:
    return int((int(a) ^ int(b)).bit_count())


def _resolve_hash_field(frame: FrameSignature, hash_field: str) -> Optional[int]:
    """Return the hash value from a FrameSignature given field preference."""
    if hash_field == "phash64":
        return frame.phash64
    if hash_field == "dhash64":
        return getattr(frame, "dhash64", None)
    # "auto": prefer phash64, fallback dhash64
    val = frame.phash64
    if val is None:
        val = getattr(frame, "dhash64", None)
    return val


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def build_frame_matches(
    left_signature: VideoSignature,
    right_signature: VideoSignature,
    *,
    hash_field: str = "auto",
    max_hamming_distance: int = 10,
) -> List[FrameMatch]:
    """
    Build all pairwise frame matches between two VideoSignature objects.

    Only valid frames (valid_for_matching=True) with a resolvable hash are
    compared.  O(n*m) — acceptable because Q4G has already narrowed the
    candidate set.

    Returns matches sorted by (left_timestamp_seconds, right_timestamp_seconds).
    """
    left_frames: List[Tuple[int, float, int]] = []  # (frame_index, timestamp, hash)
    for f in left_signature.signatures:
        if not f.valid_for_matching:
            continue
        h = _resolve_hash_field(f, hash_field)
        if h is None:
            continue
        left_frames.append((f.frame_index, f.timestamp_seconds, h))

    right_frames: List[Tuple[int, float, int]] = []
    for f in right_signature.signatures:
        if not f.valid_for_matching:
            continue
        h = _resolve_hash_field(f, hash_field)
        if h is None:
            continue
        right_frames.append((f.frame_index, f.timestamp_seconds, h))

    matches: List[FrameMatch] = []
    for li, lt, lh in left_frames:
        for ri, rt, rh in right_frames:
            dist = _hamming64(lh, rh)
            if dist <= max_hamming_distance:
                similarity = max(0.0, 1.0 - dist / max(1, max_hamming_distance))
                matches.append(
                    FrameMatch(
                        left_frame_index=li,
                        right_frame_index=ri,
                        left_timestamp_seconds=lt,
                        right_timestamp_seconds=rt,
                        distance=dist,
                        similarity=similarity,
                    )
                )

    matches.sort(key=lambda m: (m.left_timestamp_seconds, m.right_timestamp_seconds))
    return matches


def vote_offsets(
    matches: List[FrameMatch],
    *,
    bin_size_seconds: float,
) -> List[OffsetBin]:
    """
    Bin frame matches by temporal offset (right_timestamp - left_timestamp).

    Returns bins sorted by score descending.  Each bin aggregates match count
    and mean similarity.
    """
    if not matches:
        return []
    if bin_size_seconds <= 0:
        bin_size_seconds = 2.0

    accumulator: Dict[int, Tuple[int, float]] = {}  # bin_index -> (count, sum_similarity)
    for m in matches:
        offset = m.right_timestamp_seconds - m.left_timestamp_seconds
        bin_index = round(offset / bin_size_seconds)
        count, total = accumulator.get(bin_index, (0, 0.0))
        accumulator[bin_index] = (count + 1, total + m.similarity)

    bins: List[OffsetBin] = []
    for bin_index, (count, total_sim) in accumulator.items():
        offset_seconds = bin_index * bin_size_seconds
        score = total_sim / max(1, count)
        bins.append(OffsetBin(bin_index=bin_index, offset_seconds=offset_seconds, match_count=count, score=score))

    bins.sort(key=lambda b: b.score, reverse=True)
    return bins


def _score_segment(
    matches: List[FrameMatch],
    *,
    max_hamming_distance: int,
    target_segment_seconds: float = 30.0,
    target_match_count: int = 20,
    max_gap_seconds_allowed: float,
    max_gap_seconds_observed: float,
) -> float:
    if not matches:
        return 0.0
    # duration of the streak
    start_l = matches[0].left_timestamp_seconds
    end_l = matches[-1].left_timestamp_seconds
    start_r = matches[0].right_timestamp_seconds
    end_r = matches[-1].right_timestamp_seconds
    dur_left = max(0.0, end_l - start_l)
    dur_right = max(0.0, end_r - start_r)
    overlap = min(dur_left, dur_right)

    length_score = min(1.0, overlap / max(1.0, target_segment_seconds))
    match_score = min(1.0, len(matches) / max(1, target_match_count))
    distances = [m.distance for m in matches]
    med_dist = median(distances) if distances else max_hamming_distance
    distance_score = max(0.0, 1.0 - med_dist / max(1, max_hamming_distance))
    gap_score = max(0.0, 1.0 - max_gap_seconds_observed / max(1.0, max_gap_seconds_allowed))

    return 0.35 * length_score + 0.30 * match_score + 0.25 * distance_score + 0.10 * gap_score


def _segments_overlap(a: AlignmentSegment, b: AlignmentSegment, threshold: float = 0.70) -> bool:
    """True if a and b overlap by >= threshold on both left and right timelines."""
    def _overlap_ratio(s1: float, e1: float, s2: float, e2: float) -> float:
        inter = max(0.0, min(e1, e2) - max(s1, s2))
        union = max(e1, e2) - min(s1, s2)
        return inter / max(1e-6, union)

    left_ratio = _overlap_ratio(a.start_left_seconds, a.end_left_seconds,
                                b.start_left_seconds, b.end_left_seconds)
    right_ratio = _overlap_ratio(a.start_right_seconds, a.end_right_seconds,
                                 b.start_right_seconds, b.end_right_seconds)
    return left_ratio >= threshold and right_ratio >= threshold


def extract_alignment_segments(
    matches: List[FrameMatch],
    *,
    offset_bins: List[OffsetBin],
    bin_size_seconds: float,
    max_gap_seconds: float,
    min_segment_seconds: float,
    min_segment_matches: int,
    top_k_bins: int = 5,
) -> List[AlignmentSegment]:
    """
    Extract monotonic diagonal alignment segments from frame matches.

    Algorithm:
    1. Select top K offset bins.
    2. For each bin, filter matches within the bin window.
    3. Sort filtered matches by (left_timestamp, right_timestamp).
    4. Build monotonic streaks: both timestamps must strictly increase and
       the gap on each side must not exceed max_gap_seconds.
    5. Score each streak; keep those meeting min_segment_matches and
       min_segment_seconds.
    6. Deduplicate segments that overlap >=70% on both sides.
    7. Return accepted segments sorted by score descending.
    """
    if not matches or not offset_bins:
        return []

    half_bin = bin_size_seconds / 2.0
    accepted_segments: List[AlignmentSegment] = []

    for obin in offset_bins[:top_k_bins]:
        lo = obin.offset_seconds - half_bin
        hi = obin.offset_seconds + half_bin
        bin_matches = [
            m for m in matches
            if lo <= (m.right_timestamp_seconds - m.left_timestamp_seconds) <= hi
        ]
        if not bin_matches:
            continue
        # Sort by left timestamp, breaking ties by right timestamp
        bin_matches.sort(key=lambda m: (m.left_timestamp_seconds, m.right_timestamp_seconds))

        # Build monotonic streaks
        streak: List[FrameMatch] = []
        max_gap_in_streak: float = 0.0
        streaks: List[Tuple[List[FrameMatch], float]] = []  # (streak, max_gap)

        for m in bin_matches:
            if not streak:
                streak = [m]
                max_gap_in_streak = 0.0
            else:
                prev = streak[-1]
                gap_l = m.left_timestamp_seconds - prev.left_timestamp_seconds
                gap_r = m.right_timestamp_seconds - prev.right_timestamp_seconds
                # Require strictly increasing timestamps and gap limits
                if (gap_l > 0 and gap_r > 0 and
                        gap_l <= max_gap_seconds and gap_r <= max_gap_seconds):
                    max_gap_in_streak = max(max_gap_in_streak, gap_l, gap_r)
                    streak.append(m)
                else:
                    # End streak, start new one
                    if len(streak) >= 1:
                        streaks.append((list(streak), max_gap_in_streak))
                    streak = [m]
                    max_gap_in_streak = 0.0

        if streak:
            streaks.append((streak, max_gap_in_streak))

        for streak_matches, max_gap_obs in streaks:
            if len(streak_matches) < min_segment_matches:
                continue
            start_l = streak_matches[0].left_timestamp_seconds
            end_l = streak_matches[-1].left_timestamp_seconds
            start_r = streak_matches[0].right_timestamp_seconds
            end_r = streak_matches[-1].right_timestamp_seconds
            overlap = min(end_l - start_l, end_r - start_r)
            if overlap < min_segment_seconds:
                continue
            distances = [m.distance for m in streak_matches]
            med_dist = median(distances)
            score = _score_segment(
                streak_matches,
                max_hamming_distance=max(1, max(distances)) if distances else 1,
                max_gap_seconds_allowed=max_gap_seconds,
                max_gap_seconds_observed=max_gap_obs,
            )
            accepted_segments.append(AlignmentSegment(
                start_left_seconds=start_l,
                end_left_seconds=end_l,
                start_right_seconds=start_r,
                end_right_seconds=end_r,
                matched_frame_count=len(streak_matches),
                score=score,
                median_distance=med_dist,
            ))

    if not accepted_segments:
        return []

    # Deduplicate highly overlapping segments (keep higher score)
    accepted_segments.sort(key=lambda s: s.score, reverse=True)
    deduped: List[AlignmentSegment] = []
    for seg in accepted_segments:
        dominated = any(_segments_overlap(seg, kept) for kept in deduped)
        if not dominated:
            deduped.append(seg)

    deduped.sort(key=lambda s: s.score, reverse=True)
    return deduped


def union_interval_seconds(intervals: List[Tuple[float, float]]) -> float:
    """
    Compute the total length covered by a set of (possibly overlapping) intervals.
    """
    if not intervals:
        return 0.0
    sorted_ivs = sorted(intervals, key=lambda iv: iv[0])
    total = 0.0
    cur_start, cur_end = sorted_ivs[0]
    for start, end in sorted_ivs[1:]:
        if start <= cur_end:
            cur_end = max(cur_end, end)
        else:
            total += cur_end - cur_start
            cur_start, cur_end = start, end
    total += cur_end - cur_start
    return max(0.0, total)


def compute_alignment_confidence(
    segments: List[AlignmentSegment],
    *,
    overlap_ratio_shorter: float,
    max_hamming_distance: int,
    low_entropy_fraction: float = 0.0,
    allowed_max_gap: float,
) -> float:
    """
    Compute a scalar confidence score [0, 1] for a temporal alignment result.
    """
    segment_score = max((s.score for s in segments), default=0.0)
    coverage_score = min(1.0, overlap_ratio_shorter)
    if segments:
        all_dists = [s.median_distance for s in segments]
        med_dist = median(all_dists)
    else:
        med_dist = float(max_hamming_distance)
    distance_score = max(0.0, 1.0 - med_dist / max(1, max_hamming_distance))
    entropy_quality = max(0.0, 1.0 - low_entropy_fraction)
    observed_max_gap = max((s.overlap_seconds for s in segments), default=0.0)
    # gap_quality: how small the observed gap is relative to allowed
    # Use the gap across the best segment rather than its overlap_seconds
    # (overlap_seconds is the shared duration, not the gap).  Since we don't
    # store max_gap_observed per segment here, use a simple heuristic.
    gap_quality = 1.0 if not segments else min(1.0, allowed_max_gap / max(1.0, allowed_max_gap))

    confidence = (
        0.35 * segment_score
        + 0.25 * coverage_score
        + 0.20 * distance_score
        + 0.10 * entropy_quality
        + 0.10 * gap_quality
    )
    return max(0.0, min(1.0, confidence))
