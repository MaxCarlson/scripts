# vdedup Implementation Plan: Plan #3 — Q4G Coarse Duplicate Detection

## Scope

This plan assumes the following are already implemented:

```text
0. Safety semantics cleanup
1. GPU capability/routing foundation
2. GPU sampling + decode + fingerprint extraction
```

This plan implements:

```text
3. Q4G coarse duplicate detection
```

This plan must **not** implement:

```text
4. Q5G temporal alignment
5. Q6G deep embeddings
```

Q4G should consume `VideoSignature` / `FrameSignature` objects from Plan #2 and use them to detect **high-confidence full-video perceptual duplicates**.

Q4G may emit:

```text
1. actionable full-video perceptual duplicate groups
2. non-actionable visual candidate pairs/groups for future Q5G temporal alignment
```

Q4G must not emit:

```text
1. subset_of_longer groups
2. partial_overlap groups
3. semantic/cropped/watermarked duplicate groups
4. apply-safe groups based on metadata, duration, size, or Q3 membership
```

Q4G is a coarse visual verifier. It is not the temporal alignment layer.

---

## 1. Architectural Goal

The post-Q3 GPU route should become:

```text
Q1:
    size candidates only

Q2:
    exact byte duplicate groups

Q3:
    metadata candidates only

Q4G:
    extract/load visual signatures
    index frame-level perceptual hashes
    generate visual candidate pairs
    verify only high-confidence full-video perceptual duplicates
    forward uncertain visual matches to Q5G as candidates
```

Q4G should be able to say:

```text
"These two videos are very likely full perceptual duplicates."
```

Q4G should also be able to say:

```text
"These two videos share enough visual content to deserve temporal alignment."
```

Q4G should not say:

```text
"This short video is a subset of that longer video."
```

Subset/overlap classification belongs to Plan #4 / Q5G.

---

## 2. Safety Contract

### Verified Q4G Full Duplicate

```text
candidate_only=false
actionable=true
review_required=false
match_type=perceptual_duplicate
method=gpu-phash or gpu-dhash
```

### Q4G Visual Candidate

```text
candidate_only=true
actionable=false
review_required=true
match_type=visual_candidate
method=gpu-visual-candidate
recommended_next_stage=q5
```

### Hard Invariants

```text
1. Q4G must never treat Q3 metadata as evidence.
2. Q4G may use Q3 candidates only as priority work queues.
3. Q4G must never place visual candidates in `groups`.
4. Q4G visual candidates must go under `candidate_groups`.
5. Q4G full-duplicate groups must include visual evidence sufficient without metadata.
6. Existing CPU Q4 route must remain available.
```

---

## 3. Files to Create or Modify

### New Files

```text
modules/vdedup/gpu_index.py
modules/vdedup/gpu_q4.py
modules/vdedup/tests/gpu_index_test.py
modules/vdedup/tests/gpu_q4_test.py
modules/vdedup/tests/gpu_q4_pipeline_contract_test.py
```

### Existing Files Likely Modified

```text
modules/vdedup/pipeline.py
modules/vdedup/video_dedupe.py
modules/vdedup/gpu_signature.py
modules/vdedup/gpu_cache.py
modules/vdedup/report.py
modules/vdedup/report_models.py
```

Only modify report/report model code if existing report serialization cannot represent Q4G evidence/candidates.

Do not modify:

```text
Q5/Q6 logic
deep embedding code
apply_report safety semantics
Q1/Q3 candidate-only semantics
```

---

## 4. New Data Models

## 4.1 `FrameHashMatch`

File:

```text
modules/vdedup/gpu_q4.py
```

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class FrameHashMatch:
    left_frame_index: int
    right_frame_index: int
    left_timestamp_seconds: float
    right_timestamp_seconds: float
    distance: int
```

---

## 4.2 `VisualCandidatePair`

File:

```text
modules/vdedup/gpu_q4.py
```

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


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
```

Field meanings:

```text
source:
    q3_candidate
    gpu_hash_band
    gpu_global_scan
    manual

score:
    normalized coarse score in [0, 1]

coverage_left:
    fraction of valid sampled frames in left video with a close visual match

coverage_right:
    fraction of valid sampled frames in right video with a close visual match

median_distance / mean_distance:
    Hamming distance statistics over matched frame pairs
```

---

## 4.3 `Q4GResult`

File:

```text
modules/vdedup/gpu_q4.py
```

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List


@dataclass(slots=True)
class Q4GResult:
    duplicate_groups: Dict[str, List[Path]] = field(default_factory=dict)
    group_metadata: Dict[str, Dict[str, object]] = field(default_factory=dict)
    candidate_groups: Dict[str, List[Path]] = field(default_factory=dict)
    candidate_metadata: Dict[str, Dict[str, object]] = field(default_factory=dict)
    candidate_pairs: List[VisualCandidatePair] = field(default_factory=list)
    rejected_pairs: List[VisualCandidatePair] = field(default_factory=list)
```

`candidate_pairs` should exist even if not serialized, because Q5G will consume it later.

---

# 5. Hash-Band Index

Q4G needs a cheap way to avoid global all-pairs video comparison.

Use a simple in-repo frame-hash band index first. Do not add FAISS yet.

Reason:

```text
FAISS binary indexes support Hamming-distance search, but adding FAISS now increases dependency and packaging complexity. Q4G can first use compact 64-bit hash bands and only move to FAISS if benchmark data proves it is needed.
```

## 5.1 `gpu_index.py`

Add imports:

```python
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import DefaultDict, Dict, Iterable, List, Sequence, Tuple

from .gpu_signature import FrameSignature, VideoSignature
```

---

## 5.2 `HashBandKey`

```python
@dataclass(frozen=True, slots=True)
class HashBandKey:
    band_index: int
    band_value: int
```

---

## 5.3 `FrameHashRef`

```python
@dataclass(frozen=True, slots=True)
class FrameHashRef:
    video_id: str
    path: Path
    frame_index: int
    timestamp_seconds: float
    hash_value: int
```

---

## 5.4 `HashBandIndex`

```python
class HashBandIndex:
    def __init__(self, *, bands: int = 4, bits_per_band: int = 16) -> None:
        ...

    def add_video(self, signature: VideoSignature, *, hash_field: str = "phash64") -> None:
        ...

    def candidate_video_pairs(self) -> Dict[Tuple[str, str], int]:
        ...

    def frame_refs_for_video(self, video_id: str) -> List[FrameHashRef]:
        ...
```

Default index parameters:

```text
bands = 4
bits_per_band = 16
```

For a 64-bit hash:

```text
band 0 = bits 0..15
band 1 = bits 16..31
band 2 = bits 32..47
band 3 = bits 48..63
```

Alternative later:

```text
8 bands x 8 bits:
    higher recall
    more candidate noise

4 bands x 16 bits:
    conservative
    good first Q4G default
```

Start with:

```text
4 bands x 16 bits
```

---

## 5.5 Indexing Rules

When adding a video:

```text
1. Use only FrameSignature.valid_for_matching == true.
2. Use the configured hash field:
       phash64 if available
       otherwise dhash64 if configured
3. Skip frames with missing hash values.
4. Store FrameHashRef in each band bucket.
```

For candidate pair generation:

```text
1. For each band bucket, consider cross-video frame refs.
2. Normalize pair ordering by video_id or path string.
3. Increment a vote count per video pair.
4. Do not generate self-pairs.
5. Return pair -> vote_count.
```

Candidate thresholding happens in Q4G, not inside the index, unless a helper is useful.

---

## 5.6 Hash Index Tests

File:

```text
modules/vdedup/tests/gpu_index_test.py
```

Required tests:

```text
test_hash_band_index_empty
test_hash_band_index_adds_valid_frames_only
test_hash_band_index_ignores_invalid_frames
test_hash_band_index_uses_selected_hash_field
test_hash_band_index_skips_missing_hash
test_hash_band_index_generates_pair_for_shared_band
test_hash_band_index_does_not_generate_self_pair
test_hash_band_index_pair_order_is_stable
test_hash_band_index_frame_refs_for_video
test_hash_band_index_raises_for_invalid_band_config
```

---

# 6. Hamming Distance and Frame Matching

## 6.1 Hamming Helper

File:

```text
modules/vdedup/gpu_q4.py
```

```python
def hamming64(a: int, b: int) -> int:
    return int((a ^ b).bit_count())
```

Add:

```python
def hamming64_many(left: Sequence[int], right: Sequence[int]) -> List[int]:
    ...
```

Do not over-optimize. Q4G should verify only candidate pairs.

---

## 6.2 Signature Hash Extraction Helper

```python
def _frame_hash(frame: FrameSignature, hash_field: str) -> Optional[int]:
    ...
```

Rules:

```text
hash_field == "phash64":
    return frame.phash64

hash_field == "dhash64":
    return frame.dhash64

hash_field == "auto":
    prefer phash64, fallback to dhash64
```

---

## 6.3 Frame Match Extraction

```python
def match_video_signatures_by_hash(
    left: VideoSignature,
    right: VideoSignature,
    *,
    hash_field: str = "auto",
    max_hamming_distance: int = 8,
) -> List[FrameHashMatch]:
    ...
```

Algorithm:

```text
1. Extract valid frame hashes from left and right.
2. Compare each valid left frame to each valid right frame.
3. Emit FrameHashMatch for every pair where Hamming distance <= threshold.
4. Sort by left_frame_index, then right_frame_index, then distance.
```

Complexity:

```text
O(n*m) per candidate pair
```

Acceptable because:

```text
n and m are sampled frame counts, normally <= 128
candidate pairs have already been reduced by hash-band indexing
```

This function does **not** perform temporal alignment.

---

# 7. Full-Video Similarity Scoring

Q4G should score full-video similarity using bidirectional sampled-frame coverage.

## 7.1 Scoring Function

```python
def score_full_video_similarity(
    left: VideoSignature,
    right: VideoSignature,
    matches: Sequence[FrameHashMatch],
    *,
    max_hamming_distance: int,
) -> VisualCandidatePair:
    ...
```

Algorithm:

```text
1. Count valid frames in left and right.
2. For each left frame, keep its best right match by lowest distance.
3. For each right frame, keep its best left match by lowest distance.
4. coverage_left = distinct matched left frames / left_valid_frame_count
5. coverage_right = distinct matched right frames / right_valid_frame_count
6. matched_frame_count = number of unique matched frame pairs or max of distinct counts
7. median_distance = median over selected/best matches
8. mean_distance = mean over selected/best matches
```

Score formula:

```text
coverage_f1 = 2 * coverage_left * coverage_right / (coverage_left + coverage_right)

distance_quality = max(0.0, 1.0 - median_distance / max_hamming_distance)

score = 0.75 * coverage_f1 + 0.25 * distance_quality
```

If no matches:

```text
score = 0.0
coverage_left = 0.0
coverage_right = 0.0
median_distance = None
mean_distance = None
```

Important:

```text
High score requires high bidirectional coverage.
A short clip matching a small part of a long video should not become a full duplicate.
```

That case becomes a candidate for Q5G.

---

# 8. Q4G Classification Rules

## 8.1 Config Fields

Add to `PipelineConfig` or a Q4G config dataclass.

Recommended `PipelineConfig` additions:

```python
gpu_q4_hash_field: str = "auto"
gpu_q4_max_hamming_distance: int = 8
gpu_q4_weak_hamming_distance: int = 12
gpu_q4_min_valid_frames: int = 8
gpu_q4_min_band_votes: int = 3
gpu_q4_full_duplicate_coverage: float = 0.90
gpu_q4_full_duplicate_score: float = 0.88
gpu_q4_candidate_score: float = 0.45
gpu_q4_min_candidate_matches: int = 4
```

If Plan #2 only implemented dHash64:

```text
Set gpu_q4_hash_field="dhash64"
Set gpu_q4_max_hamming_distance=6
Set gpu_q4_full_duplicate_coverage=0.92
Set gpu_q4_full_duplicate_score=0.90
```

If Plan #2 implemented pHash64:

```text
Set gpu_q4_hash_field="phash64" or "auto"
Set gpu_q4_max_hamming_distance=8
Set gpu_q4_full_duplicate_coverage=0.90
Set gpu_q4_full_duplicate_score=0.88
```

All thresholds must be config-driven.

---

## 8.2 Full Duplicate Rule

A pair becomes an actionable full duplicate only if:

```text
left_valid_frame_count >= gpu_q4_min_valid_frames
right_valid_frame_count >= gpu_q4_min_valid_frames

coverage_left >= gpu_q4_full_duplicate_coverage
coverage_right >= gpu_q4_full_duplicate_coverage

score >= gpu_q4_full_duplicate_score

median_distance is not None
median_distance <= gpu_q4_max_hamming_distance
```

Output:

```text
groups["gpu-phash:<id>"] or groups["gpu-dhash:<id>"]
```

Metadata:

```json
{
    "method": "gpu-phash",
    "confidence": "verified",
    "review_required": false,
    "actionable": true,
    "match_type": "perceptual_duplicate",
    "evidence": {
        "backend": "gpu",
        "verified_by": ["gpu_q4_visual_hash"],
        "hash_field": "phash64",
        "coverage_left": 0.96,
        "coverage_right": 0.94,
        "score": 0.93,
        "matched_frame_count": 92,
        "left_valid_frame_count": 96,
        "right_valid_frame_count": 98,
        "median_hamming_distance": 5.0,
        "mean_hamming_distance": 5.7,
        "sampling_profile": "balanced"
    }
}
```

---

## 8.3 Visual Candidate Rule

A pair becomes a Q5 candidate if it fails full-duplicate requirements but satisfies:

```text
score >= gpu_q4_candidate_score
or matched_frame_count >= gpu_q4_min_candidate_matches
or max(coverage_left, coverage_right) >= 0.70
```

Candidate output:

```text
candidate_groups["visual_candidate:<id>"]
```

Candidate metadata:

```json
{
    "method": "gpu-visual-candidate",
    "candidate_only": true,
    "actionable": false,
    "review_required": true,
    "match_type": "visual_candidate",
    "recommended_next_stage": "q5",
    "evidence": {
        "backend": "gpu",
        "source": "gpu_hash_band",
        "hash_field": "phash64",
        "score": 0.61,
        "coverage_left": 0.82,
        "coverage_right": 0.24,
        "matched_frame_count": 19,
        "median_hamming_distance": 7.0
    }
}
```

Potential subset-like pattern:

```text
coverage_left high, coverage_right low
or
coverage_right high, coverage_left low
```

Q4G should **not** classify it as subset. It should be a `visual_candidate`.

---

## 8.4 Rejection Rule

Reject if:

```text
score < gpu_q4_candidate_score
and matched_frame_count < gpu_q4_min_candidate_matches
and max(coverage_left, coverage_right) < 0.70
```

Rejected pairs should not be serialized by default.

Optionally store rejected pairs only in verbose/debug mode.

---

# 9. Q3 Candidate Integration

Q3 metadata candidates should prioritize Q4G pair comparisons.

## 9.1 Input Support

Add to `run_q4g`:

```python
def run_q4g(
    video_metas: Sequence[object],
    *,
    config: object,
    q3_candidate_groups: Optional[Dict[str, Sequence[object]]] = None,
    signature_cache: Optional[object] = None,
    reporter: Optional[object] = None,
) -> Q4GResult:
    ...
```

## 9.2 Processing Order

```text
1. Extract/load signatures for all eligible videos.
2. Compare explicit pairs inside Q3 candidate groups first.
3. Build hash-band index over all eligible signatures.
4. Generate global visual candidate pairs from index votes.
5. Deduplicate pair list.
6. Score/classify each pair.
```

## 9.3 Evidence Rule

If a pair came from Q3:

```json
{
    "source": "q3_candidate+gpu_hash",
    "q3_candidate_id": "meta_candidate:3"
}
```

But Q3 must never contribute to score or actionability.

Visual evidence alone must be sufficient.

---

# 10. Pair Deduplication

Add:

```python
def normalize_pair(left: Path, right: Path) -> Tuple[Path, Path]:
    ...
```

Rules:

```text
Resolve or normalize paths consistently with existing repo path normalization.
Pair order is stable.
Same path pair is ignored.
```

If both Q3 and hash-band index propose the same pair:

```text
Merge evidence source:
    q3_candidate+gpu_hash
```

---

# 11. Pair-to-Group Merging

Q4G verified full-duplicate pairs should become groups.

Add:

```python
def merge_duplicate_pairs(
    pairs: Sequence[VisualCandidatePair],
) -> List[set[Path]]:
    ...
```

Use union-find.

Rules:

```text
A-B and B-C => {A, B, C}
A-B and C-D => two groups
```

Candidate pairs should not be aggressively merged.

Recommendation:

```text
Verified duplicates:
    merge into connected components

Visual candidates:
    one candidate_group per pair
```

Reason:

```text
Candidate connected components can become huge and misleading.
Q5G should evaluate explicit pairs.
```

---

# 12. Keep/Losers Selection

Q4G should avoid inventing a new keep policy.

Preferred integration:

```text
Q4G returns duplicate groups as lists of VideoMeta or Path.
Existing report/scoring layer chooses keep/losers.
```

If Q4G must return group members:

```text
Use the same member type as existing pipeline groups.
Do not precompute keep/losers inside Q4G.
```

If a keep decision is unavoidable:

```text
prefer existing scoring.choose_winner / keep-policy helper
```

Do not use metadata as duplicate evidence. Metadata may only affect keeper choice after visual duplication is proven.

---

# 13. Pipeline Integration

## 13.1 Routing

In `pipeline.py`, around current Q4:

```text
if 4 in selected_stages and GPU route is enabled:
    try run Q4G
    if success:
        merge Q4G groups and candidates
        skip CPU Q4
    if failure and gpu_mode == "auto":
        log warning
        run CPU Q4
    if failure and gpu_mode == "on":
        raise/fail scan
else:
    run CPU Q4
```

## 13.2 Do Not Break CPU Route

```text
--gpu off:
    existing CPU Q4

--gpu auto:
    Q4G when possible, CPU fallback when not

--gpu on:
    Q4G required for Q4
```

If Q4G is behind an additional flag from Plan #1:

```text
Respect that flag.
```

## 13.3 Merge into `GroupResults`

For each Q4G duplicate group:

```python
groups[group_id] = members
groups.metadata[group_id] = metadata
```

For each Q4G candidate:

```python
groups.candidate_groups[candidate_id] = members
groups.candidate_metadata[candidate_id] = metadata
```

No candidate should appear in `groups`.

---

# 14. Public API

File:

```text
modules/vdedup/gpu_q4.py
```

Add:

```python
def run_q4g(
    video_metas: Sequence[object],
    *,
    config: object,
    q3_candidate_groups: Optional[Dict[str, Sequence[object]]] = None,
    signature_cache: Optional[object] = None,
    reporter: Optional[object] = None,
) -> Q4GResult:
    ...
```

Recommended helper APIs:

```python
def build_q4g_signatures(...) -> Dict[Path, VideoSignature]:
    ...

def generate_q4g_candidate_pairs(...) -> List[VisualCandidatePair]:
    ...

def classify_q4g_pairs(...) -> Q4GResult:
    ...

def merge_duplicate_pairs(...) -> List[set[Path]]:
    ...
```

Keep `run_q4g` orchestration small. Test helpers independently.

If importing `PipelineConfig` or `VideoMeta` creates circular imports:

```text
Use Protocols or loose object typing.
```

Example Protocol:

```python
from typing import Optional, Protocol
from pathlib import Path


class VideoMetaLike(Protocol):
    path: Path
    duration: Optional[float]
```

---

# 15. Cache Use

Use Plan #2 signature cache if present.

Q4G should:

```text
1. Make cache key based on path/mtime/size/profile/hash type/backend.
2. Load signature from cache if valid.
3. Extract signature if missing.
4. Save signature after extraction.
5. Continue on per-file errors unless gpu_mode=on requires failure.
```

Report/log:

```text
cache hits
cache misses
extraction failures
```

If cache is absent:

```text
Q4G still works by extracting signatures directly.
```

---

# 16. Logging and Progress

Reporter stages:

```text
Q4G: loading/extracting visual signatures
Q4G: building hash-band index
Q4G: scoring candidate pairs
Q4G: emitting verified duplicates/candidates
```

Log counts:

```text
signatures_loaded
cache_hits
cache_misses
signature_failures
hash_index_buckets
candidate_pairs_from_q3
candidate_pairs_from_hash_index
candidate_pairs_scored
verified_duplicate_pairs
verified_duplicate_groups
visual_candidate_pairs
rejected_pairs
```

Avoid logging every pair unless verbose/debug mode.

---

# 17. Tests

## 17.1 `gpu_index_test.py`

Required tests:

```text
test_hash_band_index_empty
test_hash_band_index_adds_valid_frames_only
test_hash_band_index_ignores_invalid_frames
test_hash_band_index_uses_selected_hash_field
test_hash_band_index_skips_missing_hash
test_hash_band_index_generates_pair_for_shared_band
test_hash_band_index_does_not_generate_self_pair
test_hash_band_index_pair_order_is_stable
test_hash_band_index_frame_refs_for_video
test_hash_band_index_raises_for_invalid_band_config
```

---

## 17.2 `gpu_q4_test.py`

Required tests:

```text
test_hamming64_zero_for_equal_hashes
test_hamming64_counts_differing_bits
test_frame_hash_helper_prefers_phash_in_auto_mode
test_frame_hash_helper_falls_back_to_dhash_in_auto_mode
test_match_video_signatures_by_hash_finds_close_frames
test_match_video_signatures_by_hash_rejects_far_frames
test_match_video_signatures_by_hash_ignores_invalid_frames
test_score_full_video_similarity_high_for_full_match
test_score_full_video_similarity_low_for_one_sided_partial_match
test_score_full_video_similarity_zero_for_no_matches
test_full_duplicate_rule_requires_bidirectional_coverage
test_subset_like_pattern_becomes_visual_candidate_not_group
test_merge_duplicate_pairs_transitive
test_merge_duplicate_pairs_disjoint
test_visual_candidates_are_not_merged_into_large_components
```

---

## 17.3 Q3 Candidate Integration Tests

```text
test_q3_candidate_without_visual_match_emits_no_group
test_q3_candidate_with_visual_match_emits_gpu_duplicate_group
test_q3_candidate_source_is_recorded_but_not_scored_as_evidence
```

Construct mock signatures:

```text
Case A:
    Q3 says A/B candidate
    visual hashes do not match
    expected no duplicate group

Case B:
    Q3 says A/B candidate
    visual hashes match with high bidirectional coverage
    expected gpu perceptual duplicate group
```

---

## 17.4 Pipeline Contract Tests

File:

```text
modules/vdedup/tests/gpu_q4_pipeline_contract_test.py
```

Required tests:

```text
test_gpu_off_uses_cpu_q4
test_gpu_auto_falls_back_to_cpu_q4_when_q4g_unavailable
test_gpu_on_fails_when_q4g_unavailable
test_gpu_q4g_groups_merge_into_report_groups
test_gpu_q4g_candidates_merge_into_candidate_groups
test_q4g_does_not_change_q1_q3_candidate_safety
test_q4g_does_not_emit_subset_groups
test_q4g_report_metadata_contains_backend_and_match_type
```

Use monkeypatching; normal tests must not require real CUDA.

---

## 17.5 Optional Real GPU Smoke Test

```python
@pytest.mark.gpu
def test_q4g_detects_reencoded_fixture_with_real_gpu(...):
    ...
```

Skip unless:

```text
torch available
CUDA available
PyNvVideoCodec available
small fixture videos available
```

Expected:

```text
Q4G detects a re-encoded duplicate as perceptual_duplicate.
```

Do not make this required in normal CI.

---

# 18. Threshold Defaults

Initial conservative defaults:

```text
gpu_q4_hash_field = "auto"
gpu_q4_max_hamming_distance = 8
gpu_q4_weak_hamming_distance = 12
gpu_q4_min_valid_frames = 8
gpu_q4_min_band_votes = 3
gpu_q4_full_duplicate_coverage = 0.90
gpu_q4_full_duplicate_score = 0.88
gpu_q4_candidate_score = 0.45
gpu_q4_min_candidate_matches = 4
```

If only dHash64 is available:

```text
gpu_q4_hash_field = "dhash64"
gpu_q4_max_hamming_distance = 6
gpu_q4_full_duplicate_coverage = 0.92
gpu_q4_full_duplicate_score = 0.90
```

Do not hardcode thresholds in inner functions.

---

# 19. Failure Modes and Mitigations

## 19.1 Shared Intro/Outro

Problem:

```text
Unrelated videos share intro/outro/logos.
```

Q4G mitigation:

```text
Require high bidirectional coverage across valid sampled frames.
Partial coverage becomes visual_candidate only.
```

## 19.2 Black Frames / Title Cards

Problem:

```text
Low-entropy frames match everything.
```

Q4G mitigation:

```text
Only index valid_for_matching frames.
Do not count invalid frames as matched coverage.
```

## 19.3 Short Videos

Problem:

```text
Too few valid frames for robust full-duplicate evidence.
```

Q4G mitigation:

```text
If valid frame count < gpu_q4_min_valid_frames:
    do not emit actionable duplicate
    optionally emit visual candidate if evidence is enough
```

## 19.4 Same Show / Different Episode

Problem:

```text
Same title sequence, similar structure, same codec/duration.
```

Q4G mitigation:

```text
Q3 metadata does not count.
Require high sampled visual coverage.
```

## 19.5 Crops / Watermarks / Heavy Transformations

Problem:

```text
pHash/dHash may miss transformed duplicates.
```

Q4G mitigation:

```text
Do not overfit Q4G.
Leave hard transformed cases for Q6G.
```

---

# 20. Performance Targets

Q4G should avoid global all-pairs video comparison.

Expected broad complexity:

```text
signature extraction:
    O(total sampled frames)

hash-band indexing:
    O(total valid sampled frames * bands)

candidate verification:
    O(candidate pairs * sampled_frames_per_video^2)
```

Log:

```text
signature extraction seconds
index build seconds
candidate generation seconds
candidate scoring seconds
candidate pair count
verified duplicate group count
visual candidate count
fallback count
```

Do not introduce FAISS or vector DB in this plan.

---

# 21. Report Contract

## 21.1 Verified Q4G Group

```json
{
    "method": "gpu-phash",
    "confidence": "verified",
    "review_required": false,
    "actionable": true,
    "match_type": "perceptual_duplicate",
    "evidence": {
        "backend": "gpu",
        "verified_by": ["gpu_q4_visual_hash"],
        "hash_field": "phash64",
        "coverage_left": 0.96,
        "coverage_right": 0.94,
        "score": 0.93,
        "matched_frame_count": 92,
        "left_valid_frame_count": 96,
        "right_valid_frame_count": 98,
        "median_hamming_distance": 5.0,
        "mean_hamming_distance": 5.7,
        "sampling_profile": "balanced"
    }
}
```

## 21.2 Visual Candidate Group

```json
{
    "method": "gpu-visual-candidate",
    "candidate_only": true,
    "actionable": false,
    "review_required": true,
    "match_type": "visual_candidate",
    "members": [
        "a.mp4",
        "b.mp4"
    ],
    "recommended_next_stage": "q5",
    "evidence": {
        "backend": "gpu",
        "source": "gpu_hash_band",
        "hash_field": "phash64",
        "score": 0.61,
        "coverage_left": 0.82,
        "coverage_right": 0.24,
        "matched_frame_count": 19,
        "median_hamming_distance": 7.0
    }
}
```

---

# 22. Acceptance Criteria

Plan #3 is complete when:

```text
1. Q4G can load/extract VideoSignature objects from Plan #2.
2. Q4G builds a hash-band index over valid frame hashes.
3. Q4G generates candidate video pairs without global all-pairs comparison.
4. Q4G verifies high-confidence full-video perceptual duplicates.
5. Q4G emits full duplicates as actionable perceptual_duplicate groups.
6. Q4G emits weak/partial/subset-like matches as candidate_groups only.
7. Q4G never uses Q3 metadata as evidence.
8. Q4G can prioritize Q3 candidates without trusting them.
9. Q4G integrates into pipeline routing when GPU route is selected.
10. CPU Q4 route remains available and unchanged when GPU is off/unavailable.
11. Existing Q1/Q3 candidate safety remains intact.
12. Tests cover scoring, indexing, grouping, candidate behavior, and pipeline integration.
```

Minimum viable Plan #3:

```text
- gpu_index.py
- gpu_q4.py
- unit tests for hash index and Q4 scoring
- pipeline integration behind --gpu auto/on/off
- Q4G full duplicate groups
- Q4G candidate_groups for uncertain pairs
```

Defer if necessary:

```text
- advanced candidate scoring
- real GPU smoke fixture
- threshold calibration
- debug visualization
- FAISS/cuvs/vector DB
```

---

# 23. Suggested Claude Code Plan Mode Prompt

Use this prompt:

```text
Enter Plan Mode.

Use this document as the implementation spec for Plan #3 only.

Assume Plans 0, 1, and 2 have already been implemented:
- REVIEW is a label/warning, not an apply gate.
- Candidate-only groups are never applyable.
- GPU capability/routing foundation exists.
- GPU sampling/decode/fingerprint extraction exists.
- VideoSignature and FrameSignature models exist.

Do not edit files yet.

Inspect the current repo files relevant to:
- pipeline stage orchestration
- GPU capability/routing from Plan #1
- GPU signature extraction from Plan #2
- GroupResults / candidate_groups report contract
- existing CPU Q4 behavior
- existing tests and pytest style

Generate a repo-local implementation plan for Q4G coarse duplicate detection.

The plan must include:
1. exact files to create/modify
2. exact public functions/classes to add
3. how VideoSignature objects will be loaded/extracted
4. how hash-band indexing will work
5. how candidate pairs will be generated
6. how candidate pairs will be scored
7. exact thresholds and config fields
8. how full-video duplicate groups will be emitted
9. how uncertain matches will become candidate_groups
10. how Q3 candidates will prioritize but not prove matches
11. how CPU Q4 fallback remains unchanged
12. tests to add/update
13. risks and implementation uncertainties

Do not plan Q5G temporal alignment.
Do not plan Q6G embeddings.
Do not change apply safety semantics.
Do not make metadata evidence.
Stop after producing the plan. Wait for approval before editing.
```

After approving the repo-local plan, use:

```text
Switch to implementation mode.

Implement the approved Plan #3 only.
Run the targeted tests:
- gpu_index_test.py
- gpu_q4_test.py
- gpu_q4_pipeline_contract_test.py
- existing Q1/Q3/report safety tests
- existing pipeline stage-selection tests

Do not start Q5G temporal alignment.
Do not start Q6G embeddings.
Do not alter existing CPU Q4 behavior except for routing fallback.
```

---

# 24. Notes for Future Plan #4

Plan #4 will consume Q4G `VisualCandidatePair` objects and implement:

```text
Q5G temporal alignment
offset voting
diagonal streak extraction
full/subset/partial-overlap classification
timestamped evidence
```

Therefore, Plan #3 should preserve candidate pair details:

```text
left path
right path
matched frame count
coverage ratios
distance stats
source
score
evidence
```

The most important future-facing API is:

```python
def run_q4g(...) -> Q4GResult:
    ...
```

The most important future-facing field is:

```python
Q4GResult.candidate_pairs
```
