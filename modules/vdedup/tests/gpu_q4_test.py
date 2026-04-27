from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from vdedup import gpu_q4
from vdedup.gpu_q4 import (
    hamming64,
    match_video_signatures_by_hash,
    merge_duplicate_pairs,
    run_q4g,
    score_full_video_similarity,
)
from vdedup.models import FrameSignature, VideoSignature


def _signature(path: str, hashes: list[int], *, valid: list[bool] | None = None) -> VideoSignature:
    valid = valid or [True] * len(hashes)
    frames = [
        FrameSignature(Path(path), path, index, float(index + 1), value, 3.0, 0.5, valid[index])
        for index, value in enumerate(hashes)
    ]
    return VideoSignature(
        Path(path),
        path,
        float(len(hashes)),
        len(frames),
        sum(1 for frame in frames if frame.valid_for_matching),
        frames,
        "cpu_ffmpeg",
        "balanced",
    )


def _config(**overrides):
    values = {
        "gpu_mode": "auto",
        "gpu_device_id": 0,
        "gpu_q4_signature_profile": "balanced",
        "gpu_q4_hash_field": "phash64",
        "gpu_q4_max_hamming_distance": 8,
        "gpu_q4_weak_hamming_distance": 12,
        "gpu_q4_min_valid_frames": 8,
        "gpu_q4_min_band_votes": 3,
        "gpu_q4_full_duplicate_coverage": 0.90,
        "gpu_q4_full_duplicate_score": 0.88,
        "gpu_q4_candidate_score": 0.45,
        "gpu_q4_min_candidate_matches": 4,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_hamming64_zero_for_equal_hashes():
    assert hamming64(0x1234, 0x1234) == 0


def test_hamming64_counts_differing_bits():
    assert hamming64(0b1010, 0b0101) == 4


def test_match_video_signatures_by_hash_finds_close_frames():
    left = _signature("a.mp4", [0])
    right = _signature("b.mp4", [0b1111])

    matches = match_video_signatures_by_hash(left, right, max_hamming_distance=4)

    assert len(matches) == 1
    assert matches[0].distance == 4


def test_match_video_signatures_by_hash_rejects_far_frames():
    left = _signature("a.mp4", [0])
    right = _signature("b.mp4", [0xFFFF])

    assert match_video_signatures_by_hash(left, right, max_hamming_distance=4) == []


def test_match_video_signatures_by_hash_ignores_invalid_frames():
    left = _signature("a.mp4", [0], valid=[False])
    right = _signature("b.mp4", [0])

    assert match_video_signatures_by_hash(left, right, max_hamming_distance=0) == []


def test_score_full_video_similarity_high_for_full_match():
    left = _signature("a.mp4", list(range(8)))
    right = _signature("b.mp4", list(range(8)))
    matches = match_video_signatures_by_hash(left, right, max_hamming_distance=0)

    pair = score_full_video_similarity(left, right, matches, max_hamming_distance=8)

    assert pair.score == 1.0
    assert pair.coverage_left == 1.0
    assert pair.coverage_right == 1.0


def test_score_full_video_similarity_low_for_one_sided_partial_match():
    left = _signature("a.mp4", list(range(8)))
    right = _signature("b.mp4", list(range(4)) + [0xFFFF_0000_0000_0000 + i for i in range(4)])
    matches = match_video_signatures_by_hash(left, right, max_hamming_distance=0)

    pair = score_full_video_similarity(left, right, matches, max_hamming_distance=8)

    assert pair.coverage_left < 0.90
    assert pair.coverage_right < 0.90


def test_score_full_video_similarity_zero_for_no_matches():
    left = _signature("a.mp4", [0])
    right = _signature("b.mp4", [0xFFFF])

    pair = score_full_video_similarity(left, right, [], max_hamming_distance=8)

    assert pair.score == 0.0
    assert pair.matched_frame_count == 0


def test_subset_like_pattern_becomes_visual_candidate_not_group(monkeypatch):
    sigs = {
        Path("a.mp4"): _signature("a.mp4", list(range(8))),
        Path("b.mp4"): _signature("b.mp4", list(range(4)) + [0xFFFF_0000_0000_0000 + i for i in range(4)]),
    }
    metas = [SimpleNamespace(path=Path("a.mp4"), size=1, mtime=1.0, duration=8.0), SimpleNamespace(path=Path("b.mp4"), size=1, mtime=1.0, duration=8.0)]

    def fake_load(meta, *, config, signature_cache):
        return sigs[Path(meta.path)], False

    monkeypatch.setattr(gpu_q4, "_load_or_extract_signature", fake_load)

    result = run_q4g(metas, config=_config(gpu_q4_min_band_votes=1), signature_cache=None)

    assert result.duplicate_groups == {}
    assert len(result.candidate_groups) == 1
    assert next(iter(result.candidate_metadata.values()))["match_type"] == "visual_candidate"


def test_merge_duplicate_pairs_transitive():
    pairs = [
        gpu_q4.VisualCandidatePair(Path("a.mp4"), Path("b.mp4"), "x", 1.0, 8, 8, 8, 1.0, 1.0, 0.0, 0.0),
        gpu_q4.VisualCandidatePair(Path("b.mp4"), Path("c.mp4"), "x", 1.0, 8, 8, 8, 1.0, 1.0, 0.0, 0.0),
    ]

    assert merge_duplicate_pairs(pairs) == [{Path("a.mp4"), Path("b.mp4"), Path("c.mp4")}]


def test_visual_candidates_are_not_merged_into_large_components(monkeypatch):
    sigs = {
        Path("a.mp4"): _signature("a.mp4", list(range(4)) + [0xAAAA_0000_0000_0000 + i for i in range(4)]),
        Path("b.mp4"): _signature("b.mp4", list(range(4)) + [0xBBBB_0000_0000_0000 + i for i in range(4)]),
        Path("c.mp4"): _signature("c.mp4", [0xCCCC_0000_0000_0000 + i for i in range(4)] + [0xBBBB_0000_0000_0000 + i for i in range(4)]),
    }
    metas = [
        SimpleNamespace(path=Path("a.mp4"), size=1, mtime=1.0, duration=8.0),
        SimpleNamespace(path=Path("b.mp4"), size=1, mtime=1.0, duration=8.0),
        SimpleNamespace(path=Path("c.mp4"), size=1, mtime=1.0, duration=8.0),
    ]

    def fake_load(meta, *, config, signature_cache):
        return sigs[Path(meta.path)], False

    monkeypatch.setattr(gpu_q4, "_load_or_extract_signature", fake_load)

    # max_hamming_distance=2 ensures 0xAAAA... vs 0xBBBB... (4-bit diff) do NOT match,
    # so only the shared [0..3] frames pair up, giving 50% coverage — not a full duplicate.
    result = run_q4g(
        metas,
        config=_config(gpu_q4_min_band_votes=1, gpu_q4_max_hamming_distance=2, gpu_q4_weak_hamming_distance=2),
        signature_cache=None,
    )

    assert result.duplicate_groups == {}
    assert all(len(members) == 2 for members in result.candidate_groups.values())


def test_q3_candidate_without_visual_match_emits_no_group_or_candidate(monkeypatch):
    sigs = {
        Path("a.mp4"): _signature("a.mp4", [0] * 8),
        Path("b.mp4"): _signature("b.mp4", [0xFFFF_FFFF_FFFF_FFFF] * 8),
    }
    metas = [SimpleNamespace(path=Path("a.mp4"), size=1, mtime=1.0, duration=8.0), SimpleNamespace(path=Path("b.mp4"), size=1, mtime=1.0, duration=8.0)]

    def fake_load(meta, *, config, signature_cache):
        return sigs[Path(meta.path)], False

    monkeypatch.setattr(gpu_q4, "_load_or_extract_signature", fake_load)

    result = run_q4g(
        metas,
        config=_config(),
        q3_candidate_groups={"meta:0": metas},
        signature_cache=None,
    )

    assert result.duplicate_groups == {}
    assert result.candidate_groups == {}
    assert len(result.rejected_pairs) == 1


def test_q3_candidate_with_visual_match_records_source_not_metadata_score(monkeypatch):
    sigs = {
        Path("a.mp4"): _signature("a.mp4", list(range(8))),
        Path("b.mp4"): _signature("b.mp4", list(range(8))),
    }
    metas = [SimpleNamespace(path=Path("a.mp4"), size=1, mtime=1.0, duration=8.0), SimpleNamespace(path=Path("b.mp4"), size=1, mtime=1.0, duration=8.0)]

    def fake_load(meta, *, config, signature_cache):
        return sigs[Path(meta.path)], False

    monkeypatch.setattr(gpu_q4, "_load_or_extract_signature", fake_load)

    result = run_q4g(
        metas,
        config=_config(),
        q3_candidate_groups={"meta:0": metas},
        signature_cache=None,
    )

    metadata = next(iter(result.group_metadata.values()))
    edge = metadata["evidence"]["verified_edges"][0]  # type: ignore[index]
    assert "q3_candidate" in edge["source"]
    assert "metadata_score" not in edge


def test_transitive_component_group_preserves_pair_level_evidence(monkeypatch):
    sigs = {
        Path("a.mp4"): _signature("a.mp4", [0] * 8),
        Path("b.mp4"): _signature("b.mp4", [1] * 8),   # hamming(0,1)=1 → score=0.9375 ≥ 0.88
        Path("c.mp4"): _signature("c.mp4", [3] * 8),   # hamming(1,3)=1 (b↔c), hamming(0,3)=2 (a↔c, score=0.875<0.88)
    }
    metas = [
        SimpleNamespace(path=Path("a.mp4"), size=1, mtime=1.0, duration=8.0),
        SimpleNamespace(path=Path("b.mp4"), size=1, mtime=1.0, duration=8.0),
        SimpleNamespace(path=Path("c.mp4"), size=1, mtime=1.0, duration=8.0),
    ]

    def fake_load(meta, *, config, signature_cache):
        return sigs[Path(meta.path)], False

    monkeypatch.setattr(gpu_q4, "_load_or_extract_signature", fake_load)

    result = run_q4g(
        metas,
        config=_config(gpu_q4_max_hamming_distance=4, gpu_q4_weak_hamming_distance=4),
        signature_cache=None,
    )

    assert len(result.duplicate_groups) == 1
    metadata = next(iter(result.group_metadata.values()))
    edges = metadata["evidence"]["verified_edges"]  # type: ignore[index]
    assert len(edges) == 2
