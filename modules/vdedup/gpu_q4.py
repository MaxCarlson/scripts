from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, median
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence, Tuple

from vdedup.gpu_index import HashBandIndex
from vdedup.models import VideoSignature


class VideoMetaLike(Protocol):
    path: Path
    size: int
    mtime: float
    duration: Optional[float]


@dataclass(slots=True)
class FrameHashMatch:
    left_frame_index: int
    right_frame_index: int
    left_timestamp_seconds: float
    right_timestamp_seconds: float
    distance: int


@dataclass(slots=True)
class VisualCandidatePair:
    left: Path
    right: Path
    source: str
    score: float
    matched_frame_count: int
    left_valid_frame_count: int
    right_valid_frame_count: int
    coverage_left: float
    coverage_right: float
    median_distance: Optional[float]
    mean_distance: Optional[float]
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Q4GResult:
    duplicate_groups: Dict[str, List[Path]] = field(default_factory=dict)
    group_metadata: Dict[str, Dict[str, object]] = field(default_factory=dict)
    candidate_groups: Dict[str, List[Path]] = field(default_factory=dict)
    candidate_metadata: Dict[str, Dict[str, object]] = field(default_factory=dict)
    candidate_pairs: List[VisualCandidatePair] = field(default_factory=list)
    rejected_pairs: List[VisualCandidatePair] = field(default_factory=list)
    signature_count: int = 0
    extraction_failures: Dict[str, str] = field(default_factory=dict)
    cache_hits: int = 0
    cache_misses: int = 0


def hamming64(a: int, b: int) -> int:
    return int((int(a) ^ int(b)).bit_count())


def _normal_path(path: Path) -> Path:
    try:
        return Path(path).expanduser().resolve()
    except Exception:
        return Path(path)


def normalize_pair(left: Path, right: Path) -> Tuple[Path, Path]:
    a = _normal_path(left)
    b = _normal_path(right)
    return (a, b) if str(a).casefold() <= str(b).casefold() else (b, a)


def _frame_hash(frame: object, hash_field: str) -> Optional[int]:
    field = "phash64" if hash_field == "auto" else hash_field
    value = getattr(frame, field, None)
    if value is None:
        return None
    try:
        return int(value) & ((1 << 64) - 1)
    except (TypeError, ValueError):
        return None


def _valid_frame_hashes(signature: VideoSignature, hash_field: str) -> List[Tuple[int, float, int]]:
    values: List[Tuple[int, float, int]] = []
    for frame in signature.signatures:
        if not frame.valid_for_matching:
            continue
        hash_value = _frame_hash(frame, hash_field)
        if hash_value is None:
            continue
        values.append((int(frame.frame_index), float(frame.timestamp_seconds), hash_value))
    return values


def match_video_signatures_by_hash(
    left: VideoSignature,
    right: VideoSignature,
    *,
    hash_field: str = "phash64",
    max_hamming_distance: int = 8,
) -> List[FrameHashMatch]:
    left_hashes = _valid_frame_hashes(left, hash_field)
    right_hashes = _valid_frame_hashes(right, hash_field)
    matches: List[FrameHashMatch] = []
    for left_index, left_ts, left_hash in left_hashes:
        for right_index, right_ts, right_hash in right_hashes:
            distance = hamming64(left_hash, right_hash)
            if distance <= max_hamming_distance:
                matches.append(
                    FrameHashMatch(
                        left_frame_index=left_index,
                        right_frame_index=right_index,
                        left_timestamp_seconds=left_ts,
                        right_timestamp_seconds=right_ts,
                        distance=distance,
                    )
                )
    matches.sort(key=lambda match: (match.left_frame_index, match.right_frame_index, match.distance))
    return matches


def score_full_video_similarity(
    left: VideoSignature,
    right: VideoSignature,
    matches: Sequence[FrameHashMatch],
    *,
    max_hamming_distance: int,
    hash_field: str = "phash64",
    source: str = "gpu_hash_band",
) -> VisualCandidatePair:
    left_valid = len(_valid_frame_hashes(left, hash_field))
    right_valid = len(_valid_frame_hashes(right, hash_field))
    if left_valid <= 0 or right_valid <= 0 or not matches:
        return VisualCandidatePair(
            left=left.path,
            right=right.path,
            source=source,
            score=0.0,
            matched_frame_count=0,
            left_valid_frame_count=left_valid,
            right_valid_frame_count=right_valid,
            coverage_left=0.0,
            coverage_right=0.0,
            median_distance=None,
            mean_distance=None,
            evidence={},
        )

    best_left: Dict[int, int] = {}
    best_right: Dict[int, int] = {}
    for match in matches:
        best_left[match.left_frame_index] = min(best_left.get(match.left_frame_index, match.distance), match.distance)
        best_right[match.right_frame_index] = min(best_right.get(match.right_frame_index, match.distance), match.distance)

    coverage_left = len(best_left) / left_valid if left_valid else 0.0
    coverage_right = len(best_right) / right_valid if right_valid else 0.0
    coverage_f1 = (
        0.0
        if coverage_left + coverage_right <= 0.0
        else 2.0 * coverage_left * coverage_right / (coverage_left + coverage_right)
    )
    distances = list(best_left.values()) + list(best_right.values())
    median_distance = float(median(distances)) if distances else None
    mean_distance = float(mean(distances)) if distances else None
    distance_quality = (
        0.0
        if median_distance is None or max_hamming_distance <= 0
        else max(0.0, 1.0 - float(median_distance) / float(max_hamming_distance))
    )
    score = 0.75 * coverage_f1 + 0.25 * distance_quality
    return VisualCandidatePair(
        left=left.path,
        right=right.path,
        source=source,
        score=max(0.0, min(1.0, score)),
        matched_frame_count=max(len(best_left), len(best_right)),
        left_valid_frame_count=left_valid,
        right_valid_frame_count=right_valid,
        coverage_left=coverage_left,
        coverage_right=coverage_right,
        median_distance=median_distance,
        mean_distance=mean_distance,
        evidence={},
    )


def merge_duplicate_pairs(pairs: Sequence[VisualCandidatePair]) -> List[set[Path]]:
    parent: Dict[Path, Path] = {}

    def find(path: Path) -> Path:
        parent.setdefault(path, path)
        while parent[path] != path:
            parent[path] = parent[parent[path]]
            path = parent[path]
        return path

    def union(left: Path, right: Path) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for pair in pairs:
        left, right = normalize_pair(pair.left, pair.right)
        union(left, right)

    components: Dict[Path, set[Path]] = {}
    for path in list(parent):
        components.setdefault(find(path), set()).add(path)
    return [components[root] for root in sorted(components, key=lambda item: str(item).casefold())]


def _pair_evidence(pair: VisualCandidatePair, *, hash_field: str, sampling_profile: str) -> Dict[str, Any]:
    evidence = {
        "backend": "gpu",
        "source": pair.source,
        "verified_by": ["gpu_q4_visual_hash"],
        "hash_field": hash_field,
        "sampling_profile": sampling_profile,
        "score": pair.score,
        "coverage_left": pair.coverage_left,
        "coverage_right": pair.coverage_right,
        "matched_frame_count": pair.matched_frame_count,
        "left_valid_frame_count": pair.left_valid_frame_count,
        "right_valid_frame_count": pair.right_valid_frame_count,
        "median_hamming_distance": pair.median_distance,
        "mean_hamming_distance": pair.mean_distance,
        "left": str(pair.left),
        "right": str(pair.right),
    }
    evidence.update(pair.evidence)
    return evidence


def _is_full_duplicate(pair: VisualCandidatePair, config: object) -> bool:
    min_valid = int(getattr(config, "gpu_q4_min_valid_frames", 8))
    max_dist = int(getattr(config, "gpu_q4_max_hamming_distance", 8))
    return (
        pair.left_valid_frame_count >= min_valid
        and pair.right_valid_frame_count >= min_valid
        and pair.coverage_left >= float(getattr(config, "gpu_q4_full_duplicate_coverage", 0.90))
        and pair.coverage_right >= float(getattr(config, "gpu_q4_full_duplicate_coverage", 0.90))
        and pair.score >= float(getattr(config, "gpu_q4_full_duplicate_score", 0.88))
        and pair.median_distance is not None
        and pair.median_distance <= max_dist
    )


def _is_visual_candidate(pair: VisualCandidatePair, config: object) -> bool:
    return (
        pair.score >= float(getattr(config, "gpu_q4_candidate_score", 0.45))
        or pair.matched_frame_count >= int(getattr(config, "gpu_q4_min_candidate_matches", 4))
        or max(pair.coverage_left, pair.coverage_right) >= 0.70
    )


def _stat_values(meta: VideoMetaLike) -> Tuple[int, int]:
    try:
        stat = Path(meta.path).stat()
        return int(stat.st_size), int(stat.st_mtime_ns)
    except Exception:
        return int(getattr(meta, "size", 0)), int(float(getattr(meta, "mtime", 0.0)) * 1_000_000_000)


def _load_or_extract_signature(
    meta: VideoMetaLike,
    *,
    config: object,
    signature_cache: object | None,
) -> Tuple[Optional[VideoSignature], bool]:
    from vdedup.gpu_fingerprint import extract_video_signature  # noqa: PLC0415

    path = Path(meta.path)
    profile = str(getattr(config, "gpu_q4_signature_profile", "balanced"))
    size, mtime_ns = _stat_values(meta)
    if signature_cache is not None:
        for backend in ("gpu_pynvcodec", "cpu_ffmpeg"):
            try:
                cached = signature_cache.get(path, size, mtime_ns, profile, backend)
            except Exception:
                cached = None
            if cached is not None:
                return cached, True

    signature = extract_video_signature(
        path,
        profile=profile,
        device_id=int(getattr(config, "gpu_device_id", 0)),
        use_gpu=True,
        duration_seconds=getattr(meta, "duration", None),
    )
    if signature is not None and signature_cache is not None:
        try:
            signature_cache.put(signature, size=size, mtime_ns=mtime_ns)
        except Exception:
            pass
    return signature, False


def _q3_pairs(q3_candidate_groups: Optional[Dict[str, Sequence[VideoMetaLike]]]) -> Dict[Tuple[Path, Path], str]:
    pairs: Dict[Tuple[Path, Path], str] = {}
    if not q3_candidate_groups:
        return pairs
    for group_id, members in q3_candidate_groups.items():
        member_list = list(members)
        for i, left in enumerate(member_list):
            for right in member_list[i + 1 :]:
                pair = normalize_pair(Path(left.path), Path(right.path))
                if pair[0] != pair[1]:
                    pairs[pair] = f"q3_candidate:{group_id}"
    return pairs


def _classify_pairs(
    signatures: Dict[Path, VideoSignature],
    pair_sources: Dict[Tuple[Path, Path], str],
    *,
    config: object,
) -> Tuple[List[VisualCandidatePair], List[VisualCandidatePair], List[VisualCandidatePair]]:
    hash_field = str(getattr(config, "gpu_q4_hash_field", "phash64"))
    strong_distance = int(getattr(config, "gpu_q4_max_hamming_distance", 8))
    weak_distance = int(getattr(config, "gpu_q4_weak_hamming_distance", 12))
    verified: List[VisualCandidatePair] = []
    candidates: List[VisualCandidatePair] = []
    rejected: List[VisualCandidatePair] = []

    for pair, source in sorted(pair_sources.items(), key=lambda item: (str(item[0][0]).casefold(), str(item[0][1]).casefold())):
        left_sig = signatures.get(pair[0])
        right_sig = signatures.get(pair[1])
        if left_sig is None or right_sig is None:
            continue
        strong_matches = match_video_signatures_by_hash(
            left_sig,
            right_sig,
            hash_field=hash_field,
            max_hamming_distance=strong_distance,
        )
        scored = score_full_video_similarity(
            left_sig,
            right_sig,
            strong_matches,
            max_hamming_distance=strong_distance,
            hash_field=hash_field,
            source=source,
        )
        if _is_full_duplicate(scored, config):
            verified.append(scored)
            continue

        weak_matches = strong_matches
        if weak_distance > strong_distance:
            weak_matches = match_video_signatures_by_hash(
                left_sig,
                right_sig,
                hash_field=hash_field,
                max_hamming_distance=weak_distance,
            )
            scored = score_full_video_similarity(
                left_sig,
                right_sig,
                weak_matches,
                max_hamming_distance=weak_distance,
                hash_field=hash_field,
                source=source,
            )
        if _is_visual_candidate(scored, config):
            candidates.append(scored)
        else:
            rejected.append(scored)
    return verified, candidates, rejected


def run_q4g(
    video_metas: Sequence[VideoMetaLike],
    *,
    config: object,
    q3_candidate_groups: Optional[Dict[str, Sequence[VideoMetaLike]]] = None,
    signature_cache: object | None = None,
    reporter: object | None = None,
) -> Q4GResult:
    result = Q4GResult()
    profile = str(getattr(config, "gpu_q4_signature_profile", "balanced"))
    hash_field = str(getattr(config, "gpu_q4_hash_field", "phash64"))
    signatures: Dict[Path, VideoSignature] = {}
    by_video_id: Dict[str, VideoSignature] = {}

    for index, meta in enumerate(video_metas, start=1):
        if reporter is not None:
            try:
                reporter.wait_if_paused()
                if reporter.should_quit():
                    break
                reporter.update_progress_periodically(index - 1, len(video_metas) or 1)
            except Exception:
                pass
        try:
            signature, cache_hit = _load_or_extract_signature(meta, config=config, signature_cache=signature_cache)
        except Exception as exc:
            result.extraction_failures[str(meta.path)] = str(exc)
            continue
        if signature is None:
            result.extraction_failures[str(meta.path)] = "no decodable frames"
            continue
        norm = _normal_path(signature.path)
        signatures[norm] = signature
        by_video_id[signature.video_id] = signature
        result.cache_hits += 1 if cache_hit else 0
        result.cache_misses += 0 if cache_hit else 1
        try:
            if reporter is not None:
                reporter.inc_hashed(1, cache_hit=cache_hit)
        except Exception:
            pass

    result.signature_count = len(signatures)
    if len(video_metas) >= 2 and result.signature_count == 0:
        raise RuntimeError("Q4G could not extract any video signatures")

    if reporter is not None:
        try:
            reporter.update_progress_periodically(len(video_metas), len(video_metas) or 1, force_update=True)
        except Exception:
            pass

    q3_pair_sources = _q3_pairs(q3_candidate_groups)
    pair_sources: Dict[Tuple[Path, Path], str] = {}
    for pair, source in q3_pair_sources.items():
        if pair[0] in signatures and pair[1] in signatures:
            pair_sources[pair] = source

    index = HashBandIndex()
    for signature in signatures.values():
        index.add_video(signature, hash_field=hash_field)
    band_votes = index.candidate_video_pairs()
    min_votes = int(getattr(config, "gpu_q4_min_band_votes", 3))
    for (left_video_id, right_video_id), votes in band_votes.items():
        if votes < min_votes:
            continue
        left_sig = by_video_id.get(left_video_id)
        right_sig = by_video_id.get(right_video_id)
        if left_sig is None or right_sig is None:
            continue
        pair = normalize_pair(left_sig.path, right_sig.path)
        prior = pair_sources.get(pair)
        if prior:
            pair_sources[pair] = f"{prior}+gpu_hash"
        else:
            pair_sources[pair] = "gpu_hash_band"

    verified_pairs, candidate_pairs, rejected_pairs = _classify_pairs(signatures, pair_sources, config=config)
    result.candidate_pairs = candidate_pairs
    result.rejected_pairs = rejected_pairs

    components = merge_duplicate_pairs(verified_pairs)
    verified_by_pair = {normalize_pair(pair.left, pair.right): pair for pair in verified_pairs}
    for group_index, component in enumerate(components):
        members = sorted(component, key=lambda path: str(path).casefold())
        group_id = f"gpu-phash:{group_index}"
        result.duplicate_groups[group_id] = members
        edges = []
        edge_scores = []
        for i, left in enumerate(members):
            for right in members[i + 1 :]:
                edge_pair = verified_by_pair.get(normalize_pair(left, right))
                if edge_pair is None:
                    continue
                evidence = _pair_evidence(edge_pair, hash_field=hash_field, sampling_profile=profile)
                edges.append(evidence)
                edge_scores.append(edge_pair.score)
        best_edge = max(edges, key=lambda edge: float(edge.get("score") or 0.0), default={})
        result.group_metadata[group_id] = {
            "method": "gpu-phash",
            "confidence": "verified",
            "review_required": False,
            "actionable": True,
            "match_type": "perceptual_duplicate",
            "evidence": {
                "backend": "gpu",
                "verified_by": ["gpu_q4_visual_hash"],
                "hash_field": hash_field,
                "sampling_profile": profile,
                "score": max(edge_scores) if edge_scores else None,
                "coverage_left": best_edge.get("coverage_left"),
                "coverage_right": best_edge.get("coverage_right"),
                "matched_frame_count": best_edge.get("matched_frame_count"),
                "left_valid_frame_count": best_edge.get("left_valid_frame_count"),
                "right_valid_frame_count": best_edge.get("right_valid_frame_count"),
                "median_hamming_distance": best_edge.get("median_hamming_distance"),
                "mean_hamming_distance": best_edge.get("mean_hamming_distance"),
                "verified_edges": edges,
            },
        }

    for index, pair in enumerate(candidate_pairs):
        candidate_id = f"visual_candidate:{index}"
        result.candidate_groups[candidate_id] = list(normalize_pair(pair.left, pair.right))
        result.candidate_metadata[candidate_id] = {
            "method": "gpu-visual-candidate",
            "candidate_only": True,
            "actionable": False,
            "review_required": True,
            "match_type": "visual_candidate",
            "recommended_next_stage": "q5",
            "evidence": _pair_evidence(pair, hash_field=hash_field, sampling_profile=profile),
        }

    return result
