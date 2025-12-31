from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Optional

from .models import VideoMeta

if TYPE_CHECKING:
    from .pipeline import AlignmentResult


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _safe_ratio(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    try:
        a_f = float(a)
        b_f = float(b)
    except (TypeError, ValueError):
        return None
    denom = max(abs(a_f), abs(b_f), 1e-9)
    return abs(a_f - b_f) / denom


@dataclass(slots=True)
class ScoreCard:
    """Stores per-detector scoring details for duplicate confidence."""

    final: float
    positives: Dict[str, float] = field(default_factory=dict)
    negatives: Dict[str, float] = field(default_factory=dict)
    rationale: str = ""

    def to_payload(self) -> Dict[str, Any]:
        return {
            "final": round(self.final, 4),
            "positives": {k: round(v, 4) for k, v in self.positives.items()},
            "negatives": {k: round(v, 4) for k, v in self.negatives.items()},
            "rationale": self.rationale,
        }


def score_subset_candidate(
    *,
    subset: VideoMeta,
    superset: VideoMeta,
    match: "AlignmentResult",
    detector: str,
) -> ScoreCard:
    """
    Build a score for a subset-style duplicate detection (scene/pHash/audio/timeline).

    Positive evidence:
      * visual signal (inverse average pHash distance)
      * duration ratio (short over long)
      * temporal overlap coverage (frames matched vs longer clip)
      * detector confidence (scene/audio/timeline get a slight boost)

    Negative evidence:
      * suspiciously tiny duration ratios (<5%)
      * poor visual alignment (distance too high)
    """

    positives: Dict[str, float] = {}
    negatives: Dict[str, float] = {}

    # Visual alignment (lower distance == better)
    max_distance = 32.0  # empirically safe with 64-bit hashes
    visual_score = _clamp(1.0 - (match.distance / max_distance))
    positives[f"{detector}:visual"] = visual_score
    if match.distance > max_distance * 0.8:
        negatives["visual_noise"] = _clamp((match.distance - (max_distance * 0.8)) / max_distance)

    # Duration ratio (subset / superset)
    duration_ratio = 0.0
    if subset.duration and superset.duration and superset.duration > 0:
        duration_ratio = _clamp(subset.duration / superset.duration)
        positives["duration_ratio"] = duration_ratio
        if duration_ratio < 0.05:
            negatives["duration_mismatch"] = _clamp(0.2 - duration_ratio, 0.0, 0.2)
    else:
        positives["duration_ratio"] = 0.5  # neutral if we lack metadata

    # Temporal coverage using alignment lengths
    coverage = 0.0
    if match.shorter_len and match.longer_len:
        coverage = _clamp(match.shorter_len / max(1, match.longer_len))
        positives["temporal_overlap"] = coverage

    # Detector confidence bump
    detector_bonus = {
        "subset-phash": 0.15,
        "subset-scene": 0.1,
        "subset-audio": 0.2,
        "subset-timeline": 0.25,
    }.get(detector, 0.05)
    positives[f"{detector}:signal"] = detector_bonus

    pos_total = sum(positives.values())
    neg_total = sum(negatives.values())
    avg_pos = pos_total / max(1, len(positives))
    final = _clamp(avg_pos - neg_total)
    rationale = (
        " | ".join(f"{k}:{positives[k]:.2f}" for k in sorted(positives))
        or "insufficient evidence"
    )
    if negatives:
        rationale += " | penalties: " + ", ".join(f"{k}:{v:.2f}" for k, v in negatives.items())

    return ScoreCard(final=final, positives=positives, negatives=negatives, rationale=rationale)


def score_metadata_candidate(
    *,
    reference: VideoMeta,
    candidate: VideoMeta,
    tolerance: float,
    prefer_same_resolution: bool,
    prefer_same_codec: bool,
    prefer_same_container: bool,
) -> ScoreCard:
    """
    Score a pair of videos matched by metadata.

    Emphasizes duration proximity, size similarity, resolution, codecs, containers,
    and bitrate alignment. Penalizes large deviations even if tolerances allow grouping.
    """

    positives: Dict[str, float] = {}
    weights: Dict[str, float] = {}
    negatives: Dict[str, float] = {}

    def _add_positive(key: str, value: float, weight: float) -> None:
        positives[key] = value
        weights[key] = weight

    # Duration proximity (dominant signal)
    ref_duration = reference.duration
    cand_duration = candidate.duration
    if ref_duration and cand_duration:
        diff = abs(ref_duration - cand_duration)
        baseline = max(tolerance, 0.05 * min(ref_duration, cand_duration), 1.0)
        score = _clamp(1.0 - (diff / max(baseline, 1e-3)))
        _add_positive("duration", score, 2.5)
        if diff > max(tolerance, 1.0):
            negatives["duration_gap"] = _clamp(diff / max(ref_duration, cand_duration, 1.0))
    else:
        _add_positive("duration", 0.4, 1.5)

    # File size similarity
    size_ratio = _safe_ratio(reference.size or 0, candidate.size or 0)
    if size_ratio is not None:
        _add_positive("size", _clamp(1.0 - size_ratio), 2.0)
        if size_ratio > 0.35:
            negatives["size_mismatch"] = min(1.0, size_ratio)
    else:
        _add_positive("size", 0.3, 1.0)

    # Resolution match
    if reference.resolution_area and candidate.resolution_area:
        res_ratio = _safe_ratio(reference.resolution_area, candidate.resolution_area) or 0.0
        _add_positive("resolution", _clamp(1.0 - res_ratio), 1.0)
        if prefer_same_resolution and res_ratio > 0.15:
            negatives["resolution_gap"] = min(1.0, res_ratio * 1.5)
    else:
        _add_positive("resolution", 0.25, 0.6)

    # Codec/container similarity
    ref_codec = (reference.vcodec or "").lower()
    cand_codec = (candidate.vcodec or "").lower()
    if ref_codec and cand_codec and prefer_same_codec:
        if ref_codec == cand_codec:
            _add_positive("video_codec", 0.2, 0.5)
        else:
            negatives["codec_mismatch"] = 0.3
    else:
        _add_positive("video_codec", 0.05, 0.2)

    ref_container = (reference.container or "").lower()
    cand_container = (candidate.container or "").lower()
    if ref_container and cand_container and prefer_same_container:
        if ref_container == cand_container:
            _add_positive("container", 0.15, 0.3)
        else:
            negatives["container_mismatch"] = 0.2
    else:
        _add_positive("container", 0.05, 0.2)

    # Bitrate alignment (use video bitrate first, fallback to overall)
    ref_bitrate = reference.video_bitrate or reference.overall_bitrate
    cand_bitrate = candidate.video_bitrate or candidate.overall_bitrate
    bitrate_ratio = _safe_ratio(ref_bitrate, cand_bitrate)
    if bitrate_ratio is not None:
        _add_positive("bitrate", _clamp(1.0 - bitrate_ratio), 1.2)
        if bitrate_ratio > 0.75:
            negatives["bitrate_gap"] = min(1.0, bitrate_ratio * 0.8)
    else:
        _add_positive("bitrate", 0.2, 0.8)

    pos_total = sum(positives[key] * weights.get(key, 1.0) for key in positives)
    weight_total = sum(weights.values())
    neg_total = sum(negatives.values())
    avg_pos = pos_total / max(weight_total, 1e-6)
    final = _clamp(avg_pos - neg_total)
    rationale = (
        " | ".join(f"{k}:{positives[k]:.2f}" for k in sorted(positives))
        or "insufficient metadata"
    )
    if negatives:
        rationale += " | penalties: " + ", ".join(f"{k}:{v:.2f}" for k, v in negatives.items())
    return ScoreCard(final=final, positives=positives, negatives=negatives, rationale=rationale)
