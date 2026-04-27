# vdedup Implementation Plan: Plan #4 — Q5G Temporal Alignment

## Scope

This plan assumes the following are already implemented:

```text
P0/P1:
    safety semantics + GPU capability/routing foundation

P2:
    GPU sampling + decode + fingerprint extraction

P3:
    Q4G coarse duplicate detection
    VideoSignature / FrameSignature extraction
    VisualCandidatePair
    Q4GResult.candidate_pairs
    hash-band candidate generation
    high-confidence full-video perceptual duplicate grouping
    visual_candidate candidate_groups for uncertain/partial-looking matches
```

This plan implements:

```text
P4:
    Q5G temporal alignment
```

Q5G should consume candidate pairs from Q4G and classify localized visual relationships:

```text
1. full perceptual duplicate
2. subset_of_longer
3. partial_overlap
4. rejected_candidate
```

Q5G may emit:

```text
1. actionable full perceptual duplicate groups
2. actionable REVIEW subset_of_longer groups
3. non-actionable REVIEW partial_overlap groups
4. rejected candidates not serialized by default
```

Q5G must not implement:

```text
1. Q6G deep embeddings
2. semantic/CLIP/DINO matching
3. audio-only verification
4. video trimming/editing
5. deletion decisions based on metadata
```

Q5G is the stage where visual candidate pairs become temporally localized evidence.

---

## 1. High-Level Goal

Q4G answers:

```text
"These two videos have enough frame-level visual similarity to compare more carefully."
```

Q5G answers:

```text
"These two videos align over this timestamp range, for this many seconds, with this coverage ratio."
```

The expected post-P3/P4 flow:

```text
Q1:
    size candidates only

Q2:
    exact byte duplicate groups

Q3:
    metadata candidates only

Q4G:
    full visual duplicates
    visual candidates for Q5G

Q5G:
    temporal alignment over Q4G candidate pairs
    localized classification:
        full duplicate
        subset
        partial overlap
        reject
```

---

## 2. Safety Contract

## 2.1 Full Duplicate

```text
match_type=perceptual_duplicate
actionable=true
review_required=false
candidate_only=false
method=gpu-temporal
```

Reason:

```text
Both videos are substantially covered by the same temporally aligned content.
```

## 2.2 Subset of Longer

```text
match_type=subset_of_longer
actionable=true
review_required=true
candidate_only=false
method=gpu-temporal-subset
```

Reason:

```text
The shorter video is substantially covered by an aligned segment of the longer video.
This is likely delete-safe under a "keep longer/master" policy, but it deserves a REVIEW label.
```

Important:

```text
review_required=true is a report/viewer warning label only.
It does not block apply when actionable=true.
```

## 2.3 Partial Overlap

```text
match_type=partial_overlap
actionable=false
review_required=true
candidate_only=false
method=gpu-temporal-overlap
```

Reason:

```text
Both videos share some content but each may contain unique content.
Deleting either by default is unsafe.
```

Partial-overlap groups may have `keep`/`losers` only if the existing report schema requires it, but apply must treat `actionable=false` as non-applyable.

Preferred:

```text
Represent partial overlaps as groups only if the viewer/report UX can show them clearly as non-actionable REVIEW.
Otherwise serialize them as candidate_groups with rich evidence.
```

Recommended initial choice:

```text
Emit partial_overlap into groups with actionable=false and review_required=true,
so the report viewer can show timestamp evidence prominently,
but apply_report must skip them because actionable=false.
```

## 2.4 Rejected Candidate

```text
No report group by default.
Optional debug output only.
```

---

# 3. Files to Create or Modify

## New Files

```text
modules/vdedup/gpu_alignment.py
modules/vdedup/gpu_q5.py
modules/vdedup/tests/gpu_alignment_test.py
modules/vdedup/tests/gpu_q5_test.py
modules/vdedup/tests/gpu_q5_pipeline_contract_test.py
```

## Existing Files Likely Modified

```text
modules/vdedup/pipeline.py
modules/vdedup/video_dedupe.py
modules/vdedup/gpu_q4.py
modules/vdedup/report.py
modules/vdedup/report_models.py
modules/vdedup/report_viewer.py
```

Only modify `report.py`, `report_models.py`, or `report_viewer.py` if current schemas/views cannot represent timestamped temporal evidence cleanly.

Do not modify:

```text
Q1/Q2/Q3 behavior
Q4G coarse duplicate logic except to pass candidate_pairs forward
Q6G embedding code
apply safety semantics except to ensure actionable=false groups are skipped
```

---

# 4. Data Models

## 4.1 `FrameMatch`

File:

```text
modules/vdedup/gpu_alignment.py
```

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class FrameMatch:
    left_frame_index: int
    right_frame_index: int
    left_timestamp_seconds: float
    right_timestamp_seconds: float
    distance: float
    similarity: float
```

For hash-based Q5G:

```text
distance = Hamming distance
similarity = 1.0 - distance / max_hamming_distance
```

Later Q6G can reuse the same model with embedding distance/similarity.

---

## 4.2 `AlignmentSegment`

File:

```text
modules/vdedup/gpu_alignment.py
```

```python
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass(slots=True)
class AlignmentSegment:
    start_left_seconds: float
    end_left_seconds: float
    start_right_seconds: float
    end_right_seconds: float
    overlap_seconds_left: float
    overlap_seconds_right: float
    matched_frame_count: int
    mean_distance: float
    median_distance: float
    max_gap_seconds: float
    score: float
    matches: List[FrameMatch] = field(default_factory=list)
```

Notes:

```text
overlap_seconds_left and overlap_seconds_right may differ slightly if sample rates differ.
Use the smaller value as conservative overlap_seconds.
```

---

## 4.3 `TemporalAlignmentResult`

File:

```text
modules/vdedup/gpu_alignment.py
```

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass(slots=True)
class TemporalAlignmentResult:
    left: Path
    right: Path
    segments: List[AlignmentSegment]
    best_segment: Optional[AlignmentSegment]
    total_aligned_seconds_left: float
    total_aligned_seconds_right: float
    overlap_seconds: float
    overlap_ratio_left: float
    overlap_ratio_right: float
    overlap_ratio_shorter: float
    overlap_ratio_longer: float
    matched_frame_count: int
    mean_distance: Optional[float]
    median_distance: Optional[float]
    low_entropy_fraction: float
    confidence: float
    match_type: str
    actionable: bool
    review_required: bool
    rejected_reason: Optional[str] = None
    evidence: Dict[str, object] = field(default_factory=dict)
```

---

## 4.4 `Q5GResult`

File:

```text
modules/vdedup/gpu_q5.py
```

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from .gpu_alignment import TemporalAlignmentResult


@dataclass(slots=True)
class Q5GResult:
    duplicate_groups: Dict[str, List[Path]] = field(default_factory=dict)
    group_metadata: Dict[str, Dict[str, object]] = field(default_factory=dict)
    candidate_groups: Dict[str, List[Path]] = field(default_factory=dict)
    candidate_metadata: Dict[str, Dict[str, object]] = field(default_factory=dict)
    alignment_results: List[TemporalAlignmentResult] = field(default_factory=list)
    rejected_results: List[TemporalAlignmentResult] = field(default_factory=list)
```

---

# 5. Q5G Inputs

Q5G should consume explicit pair-level candidates.

Primary input:

```python
Q4GResult.candidate_pairs
```

Candidate source examples:

```text
gpu_hash_band
q3_candidate+gpu_hash
manual
```

Q5G also may consume Q4G duplicate pairs if desired for stronger evidence, but that is optional.

Recommended initial input:

```text
Q5G runs only on Q4G visual candidates, not on Q4G already-verified full duplicates.
```

Reason:

```text
Q4G full duplicates are already high-confidence.
Q5G should focus compute on unresolved/partial-looking pairs.
```

Optional later:

```text
Run Q5G on Q4G full duplicates in thorough mode to add timestamp evidence.
```

---

# 6. Frame Match Generation

Q5G starts from two `VideoSignature` objects.

## 6.1 Extract Valid Hashes

Use valid frames only:

```text
FrameSignature.valid_for_matching == true
hash field exists
```

Hash field:

```text
auto:
    prefer phash64
    fallback to dhash64

phash64:
    require phash64

dhash64:
    require dhash64
```

## 6.2 Match Function

File:

```text
modules/vdedup/gpu_alignment.py
```

```python
def build_frame_matches(
    left_signature,
    right_signature,
    *,
    hash_field: str = "auto",
    max_hamming_distance: int = 10,
) -> list[FrameMatch]:
    ...
```

Rules:

```text
1. Compare valid sampled frames between the candidate pair.
2. Compute Hamming distance.
3. Convert distance to similarity.
4. Keep matches where distance <= max_hamming_distance.
5. Return sorted matches by left_timestamp_seconds, then right_timestamp_seconds.
```

Initial Q5G matching can be O(n*m) per candidate pair because Q4G already narrowed candidates.

For each match:

```text
offset_seconds = right_timestamp_seconds - left_timestamp_seconds
```

---

# 7. Offset Voting / Temporal Hough Prefilter

Q5G needs to find candidate diagonal bands.

## 7.1 Offset Bin Model

File:

```text
modules/vdedup/gpu_alignment.py
```

```python
from dataclasses import dataclass


@dataclass(slots=True)
class OffsetBin:
    bin_index: int
    offset_seconds: float
    match_count: int
    score: float
```

## 7.2 Offset Voting Function

```python
def vote_offsets(
    matches: list[FrameMatch],
    *,
    bin_size_seconds: float,
) -> list[OffsetBin]:
    ...
```

Rules:

```text
1. For each match, compute offset = right_timestamp - left_timestamp.
2. Bin offset by round(offset / bin_size_seconds).
3. Accumulate:
       match_count
       sum_similarity
       optional distance penalty
4. Return bins sorted by score descending.
```

Suggested bin size:

```text
bin_size_seconds = max(1.0, median_sample_interval_seconds)
```

If sample interval is unknown:

```text
bin_size_seconds = 2.0
```

Initial config:

```python
gpu_q5_offset_bin_seconds: float = 2.0
gpu_q5_top_offset_bins: int = 5
```

Reason:

```text
Subset/overlap copies should form a dominant offset band where time in both videos progresses together.
```

---

# 8. Diagonal Streak Extraction

Q5G should find monotonic temporally consistent match streaks.

## 8.1 Core Function

```python
def extract_alignment_segments(
    matches: list[FrameMatch],
    *,
    offset_bins: list[OffsetBin],
    bin_size_seconds: float,
    max_gap_seconds: float,
    min_segment_seconds: float,
    min_segment_matches: int,
) -> list[AlignmentSegment]:
    ...
```

Algorithm:

```text
1. Select top K offset bins.
2. For each selected bin:
       keep matches whose offset falls within that bin window.
3. Sort filtered matches by left_timestamp, then right_timestamp.
4. Build monotonic streaks:
       next.left_timestamp > current.left_timestamp
       next.right_timestamp > current.right_timestamp
       gap_left <= max_gap_seconds
       gap_right <= max_gap_seconds
5. Allow small jumps/dropped frames.
6. End current streak when monotonicity or gap limits fail.
7. Score each streak.
8. Keep streaks satisfying:
       matched_frame_count >= min_segment_matches
       duration >= min_segment_seconds
9. Deduplicate highly overlapping streaks.
```

## 8.2 Segment Duration

For a streak:

```text
duration_left = end_left_seconds - start_left_seconds
duration_right = end_right_seconds - start_right_seconds
overlap_seconds = min(duration_left, duration_right)
```

If only one or two frames:

```text
duration may be near zero
do not accept as segment unless min_segment_matches and duration thresholds pass
```

## 8.3 Segment Score

Suggested:

```text
length_score = min(1.0, overlap_seconds / target_segment_seconds)
match_score = min(1.0, matched_frame_count / target_match_count)
distance_score = 1.0 - median_distance / max_hamming_distance
gap_score = max(0.0, 1.0 - max_gap_seconds_observed / max_gap_seconds_allowed)

score = 0.35 * length_score
      + 0.30 * match_score
      + 0.25 * distance_score
      + 0.10 * gap_score
```

Use config-driven weights only if helpful; otherwise keep formula internal and tested.

## 8.4 Deduping Segments

Two segments are duplicates if their timestamp ranges substantially overlap on both videos.

Initial simple rule:

```text
If segment A and B overlap by >= 70% on both left and right:
    keep the higher-score segment
```

Do not overbuild segment merging in P4.

---

# 9. Multi-Segment Handling

A video pair can share multiple copied segments.

Q5G should support multiple `AlignmentSegment` objects per pair.

Initial behavior:

```text
1. Extract multiple segments.
2. Compute total aligned coverage using union of segment intervals separately on left and right.
3. Use best segment for display summary.
4. Include all accepted segments in evidence.
```

Union coverage helper:

```python
def union_interval_seconds(intervals: list[tuple[float, float]]) -> float:
    ...
```

This avoids double-counting overlapping/adjacent segments.

---

# 10. Classification Rules

## 10.1 Config Fields

Add to `PipelineConfig` or a Q5G config dataclass:

```python
gpu_q5_hash_field: str = "auto"
gpu_q5_max_hamming_distance: int = 10
gpu_q5_offset_bin_seconds: float = 2.0
gpu_q5_top_offset_bins: int = 5
gpu_q5_max_gap_seconds: float = 4.0
gpu_q5_min_segment_seconds: float = 5.0
gpu_q5_min_segment_matches: int = 4
gpu_q5_full_duplicate_ratio: float = 0.90
gpu_q5_subset_ratio: float = 0.85
gpu_q5_partial_min_seconds: float = 10.0
gpu_q5_partial_min_shorter_ratio: float = 0.10
gpu_q5_min_confidence: float = 0.50
```

If only dHash64 is available from P2/P3, use stricter matching:

```python
gpu_q5_max_hamming_distance: int = 8
```

## 10.2 Compute Ratios

Given accepted segments:

```text
left_covered_seconds = union of left segment intervals
right_covered_seconds = union of right segment intervals

overlap_seconds = min(left_covered_seconds, right_covered_seconds)

overlap_ratio_left = left_covered_seconds / left_duration
overlap_ratio_right = right_covered_seconds / right_duration

overlap_ratio_shorter = overlap_seconds / min(left_duration, right_duration)
overlap_ratio_longer = overlap_seconds / max(left_duration, right_duration)
```

If duration is unknown:

```text
Use sampled span as fallback.
Reduce confidence.
Do not emit actionable subset/full duplicate without duration if coverage cannot be estimated.
```

## 10.3 Full Duplicate Classification

Classify as `perceptual_duplicate` when:

```text
overlap_ratio_left >= gpu_q5_full_duplicate_ratio
and overlap_ratio_right >= gpu_q5_full_duplicate_ratio
and confidence >= gpu_q5_min_confidence
```

Output:

```text
method="gpu-temporal"
match_type="perceptual_duplicate"
actionable=true
review_required=false
```

## 10.4 Subset Classification

Classify as `subset_of_longer` when:

```text
overlap_ratio_shorter >= gpu_q5_subset_ratio
and overlap_ratio_longer < gpu_q5_full_duplicate_ratio
and confidence >= gpu_q5_min_confidence
```

Output:

```text
method="gpu-temporal-subset"
match_type="subset_of_longer"
actionable=true
review_required=true
```

Viewer should show:

```text
[REVIEW] subset_of_longer
short video coverage: 93%
long video coverage: 18%
timestamps:
    short: 00:00:00–00:02:10
    long:  00:34:12–00:36:22
```

## 10.5 Partial Overlap Classification

Classify as `partial_overlap` when:

```text
overlap_seconds >= gpu_q5_partial_min_seconds
or overlap_ratio_shorter >= gpu_q5_partial_min_shorter_ratio
```

but it does not satisfy full duplicate or subset.

Output:

```text
method="gpu-temporal-overlap"
match_type="partial_overlap"
actionable=false
review_required=true
```

Reason:

```text
Both files may contain unique content. Do not delete either by default.
```

## 10.6 Rejection

Reject when:

```text
no accepted segments
or confidence < gpu_q5_min_confidence
or overlap below partial thresholds
```

Default:

```text
Do not serialize rejected pairs.
```

Optional debug:

```text
Store rejected results in Q5GResult.rejected_results.
```

---

# 11. Confidence Scoring

Add:

```python
def compute_alignment_confidence(result_inputs...) -> float:
    ...
```

Suggested factors:

```text
segment_score:
    max or weighted average of segment scores

coverage_score:
    min(1.0, overlap_ratio_shorter)

distance_score:
    1.0 - median_distance / max_hamming_distance

entropy_quality:
    1.0 - low_entropy_fraction

gap_quality:
    1.0 - observed_max_gap / allowed_max_gap
```

Initial formula:

```text
confidence = 0.35 * best_segment_score
           + 0.25 * coverage_score
           + 0.20 * distance_score
           + 0.10 * entropy_quality
           + 0.10 * gap_quality
```

Clamp:

```text
0.0 <= confidence <= 1.0
```

Do not overfit confidence in P4. It mainly helps report evidence and rejection thresholds.

---

# 12. Report Evidence Contract

Every Q5G group should include rich timestamp evidence.

## 12.1 Full Duplicate Evidence

```json
{
    "backend": "gpu",
    "verified_by": ["gpu_q5_temporal_alignment"],
    "hash_field": "phash64",
    "match_type": "perceptual_duplicate",
    "overlap_seconds": 316.2,
    "overlap_ratio_left": 0.98,
    "overlap_ratio_right": 0.97,
    "overlap_ratio_shorter": 0.98,
    "overlap_ratio_longer": 0.97,
    "matched_frame_count": 128,
    "mean_hamming_distance": 5.4,
    "median_hamming_distance": 5.0,
    "confidence": 0.94,
    "segments": [
        {
            "start_left_seconds": 0.0,
            "end_left_seconds": 316.2,
            "start_right_seconds": 0.0,
            "end_right_seconds": 316.8,
            "matched_frame_count": 128,
            "score": 0.94
        }
    ]
}
```

## 12.2 Subset Evidence

```json
{
    "backend": "gpu",
    "verified_by": ["gpu_q5_temporal_alignment"],
    "hash_field": "phash64",
    "match_type": "subset_of_longer",
    "overlap_seconds": 132.0,
    "overlap_ratio_left": 0.96,
    "overlap_ratio_right": 0.18,
    "overlap_ratio_shorter": 0.96,
    "overlap_ratio_longer": 0.18,
    "shorter_path": "clip.mp4",
    "longer_path": "master.mp4",
    "confidence": 0.89,
    "segments": [
        {
            "start_left_seconds": 0.0,
            "end_left_seconds": 132.0,
            "start_right_seconds": 2052.0,
            "end_right_seconds": 2184.0,
            "matched_frame_count": 66,
            "score": 0.91
        }
    ]
}
```

## 12.3 Partial Overlap Evidence

```json
{
    "backend": "gpu",
    "verified_by": ["gpu_q5_temporal_alignment"],
    "hash_field": "phash64",
    "match_type": "partial_overlap",
    "overlap_seconds": 47.0,
    "overlap_ratio_left": 0.23,
    "overlap_ratio_right": 0.31,
    "confidence": 0.74,
    "actionable": false,
    "review_required": true,
    "segments": [
        {
            "start_left_seconds": 88.0,
            "end_left_seconds": 135.0,
            "start_right_seconds": 12.0,
            "end_right_seconds": 59.0,
            "matched_frame_count": 21,
            "score": 0.76
        }
    ]
}
```

---

# 13. Group Emission Policy

## 13.1 Full Duplicate Groups

```text
groups["gpu-temporal:<id>"] = [left, right]
metadata:
    actionable=true
    review_required=false
    match_type=perceptual_duplicate
```

## 13.2 Subset Groups

```text
groups["gpu-temporal-sub:<id>"] = [longer, shorter]
metadata:
    actionable=true
    review_required=true
    match_type=subset_of_longer
```

Ordering recommendation:

```text
Put longer/master candidate first if existing keep policy respects group order.
Otherwise let existing keep policy decide.
```

## 13.3 Partial Overlap Groups

Recommended initial option:

```text
groups["gpu-temporal-overlap:<id>"] = [left, right]
metadata:
    actionable=false
    review_required=true
    match_type=partial_overlap
```

Reason:

```text
The viewer should surface partial overlaps with timestamp evidence.
apply_report must skip actionable=false groups.
```

Alternative if existing apply/report stack assumes every group has losers:

```text
candidate_groups["temporal_overlap_candidate:<id>"] = [left, right]
candidate_only=true
actionable=false
match_type=partial_overlap
```

Preferred if feasible:

```text
Use groups with actionable=false so overlap reports show in "REVIEW / non-actionable findings" section.
```

---

# 14. Pipeline Integration

## 14.1 Routing

In `pipeline.py`, after Q4G:

```text
if 5 in selected_stages and GPU route is enabled:
    run Q5G on Q4GResult.candidate_pairs
else:
    run existing CPU Q5 if selected
```

If the old CPU Q5 is still present:

```text
--gpu off:
    old CPU Q5

--gpu auto:
    Q5G if Q4G produced candidate_pairs and GPU route is usable
    otherwise CPU Q5 or skip according to existing behavior

--gpu on:
    Q5G required for Q5; fail clearly if unavailable
```

## 14.2 Q4G Dependency

Q5G needs candidate pairs.

If user runs:

```text
-q 5
```

without Q4:

Option A:

```text
Run Q4G candidate generation internally as prerequisite but only emit Q5G results.
```

Option B:

```text
Fail with a clear message requiring Q4 or Q4G candidate input.
```

Recommended:

```text
For `-q 5` standalone, run minimal Q4G candidate generation internally.
```

Reason:

```text
The user's expectation is that each quality level can run independently.
Q5G cannot align all pairs globally, so it needs internal candidate generation.
```

Implementation rule:

```text
-q 5:
    internally call Q4G in candidate-generation mode
    do not emit Q4G full duplicate groups unless Q4 is selected
    use Q4G candidate_pairs as Q5G input
```

If this is too much for P4, implement:

```text
-q 4-5 works
-q 5 standalone raises clear NotImplementedError with TODO
```

But the better target is independent `-q 5`.

## 14.3 Merge Results

For Q5G duplicate groups:

```python
groups[group_id] = members
groups.metadata[group_id] = metadata
```

For Q5G candidate groups if any:

```python
groups.candidate_groups[candidate_id] = members
groups.candidate_metadata[candidate_id] = metadata
```

For partial overlaps as non-actionable groups:

```python
groups[group_id] = members
groups.metadata[group_id]["actionable"] = False
```

---

# 15. Public API

File:

```text
modules/vdedup/gpu_q5.py
```

Add:

```python
def run_q5g(
    candidate_pairs: Sequence[object],
    signatures_by_path: Mapping[Path, object],
    *,
    config: object,
    reporter: Optional[object] = None,
) -> Q5GResult:
    ...
```

Recommended helpers:

```python
def align_candidate_pair(
    pair: object,
    left_signature: object,
    right_signature: object,
    *,
    config: object,
) -> TemporalAlignmentResult:
    ...

def classify_alignment_result(
    result: TemporalAlignmentResult,
    *,
    config: object,
) -> TemporalAlignmentResult:
    ...

def alignment_result_to_group_metadata(
    result: TemporalAlignmentResult,
) -> Dict[str, object]:
    ...
```

Keep orchestration small and unit-test helpers.

---

# 16. Viewer Updates

If not already supported, update report viewer to show timestamp evidence for Q5G.

For Q5G groups, viewer should show:

```text
[SAFE] gpu-temporal:0 perceptual_duplicate
    overlap: 98% / 97%, 316.2s
    segment:
        left:  00:00:00–00:05:16
        right: 00:00:00–00:05:16

[REVIEW] gpu-temporal-sub:0 subset_of_longer
    shorter coverage: 96%
    longer coverage: 18%
    segment:
        clip:   00:00:00–00:02:12
        master: 00:34:12–00:36:24

[REVIEW] gpu-temporal-overlap:0 partial_overlap NON-ACTIONABLE
    overlap: 47.0s
    segment:
        left:  00:01:28–00:02:15
        right: 00:00:12–00:00:59
```

Add helper:

```python
def format_seconds_as_timestamp(seconds: float) -> str:
    ...
```

Format:

```text
HH:MM:SS
or
HH:MM:SS.mmm if subsecond precision is useful
```

---

# 17. Tests

## 17.1 `gpu_alignment_test.py`

Required tests:

```text
test_build_frame_matches_keeps_close_hashes
test_build_frame_matches_rejects_far_hashes
test_build_frame_matches_ignores_invalid_frames
test_vote_offsets_finds_dominant_offset
test_vote_offsets_handles_empty_matches
test_extract_alignment_segments_finds_simple_diagonal
test_extract_alignment_segments_allows_small_gaps
test_extract_alignment_segments_breaks_on_large_gap
test_extract_alignment_segments_rejects_short_segment
test_extract_alignment_segments_handles_multiple_segments
test_union_interval_seconds_merges_overlapping_intervals
test_union_interval_seconds_sums_disjoint_intervals
test_classify_full_duplicate
test_classify_subset_of_longer
test_classify_partial_overlap
test_classify_rejected_candidate
```

---

## 17.2 Synthetic Match Fixtures

Use in-memory signatures, no video files required.

Fixture: full duplicate

```text
left timestamps:  0, 1, 2, 3, 4, 5
right timestamps: 0, 1, 2, 3, 4, 5
matching hashes throughout
expected: perceptual_duplicate
```

Fixture: subset

```text
short timestamps: 0, 1, 2, 3, 4
long timestamps:  50, 51, 52, 53, 54
expected: subset_of_longer
```

Fixture: partial overlap

```text
left:  shared segment covers 20%
right: shared segment covers 25%
expected: partial_overlap, actionable=false
```

Fixture: intro-only

```text
shared first 5 seconds only
long videos otherwise different
expected: partial_overlap or rejected, not full duplicate
```

Fixture: repeated low-entropy frames

```text
matches from invalid frames only
expected: rejected
```

---

## 17.3 `gpu_q5_test.py`

Required tests:

```text
test_align_candidate_pair_returns_temporal_alignment_result
test_run_q5g_emits_full_duplicate_group
test_run_q5g_emits_subset_review_group
test_run_q5g_emits_partial_overlap_non_actionable_group
test_run_q5g_rejects_weak_candidate
test_q5g_metadata_contains_segments
test_q5g_metadata_contains_overlap_ratios
test_q5g_metadata_actionability_policy
```

---

## 17.4 Pipeline Contract Tests

File:

```text
modules/vdedup/tests/gpu_q5_pipeline_contract_test.py
```

Required tests:

```text
test_q4g_candidates_feed_q5g
test_q5g_groups_merge_into_report_groups
test_q5g_partial_overlap_actionable_false
test_q5g_subset_actionable_true_review_required_true
test_gpu_off_uses_existing_cpu_q5
test_gpu_auto_falls_back_cleanly_if_q5g_unavailable
test_gpu_on_fails_if_q5g_unavailable
test_q5_standalone_runs_candidate_generation_or_fails_clearly
```

---

## 17.5 Optional Real Video Integration Tests

Use generated synthetic videos if repo already has media fixture generation.

Scenarios:

```text
1. full re-encode
2. short clip inside longer video
3. same intro different body
4. shared middle segment
5. black frames/title cards
```

Expected:

```text
full re-encode:
    perceptual_duplicate

short clip inside longer:
    subset_of_longer REVIEW

same intro different body:
    partial_overlap REVIEW or rejected

shared middle segment:
    partial_overlap REVIEW non-actionable

black/title-card-only:
    rejected
```

Mark real GPU tests:

```python
@pytest.mark.gpu
```

Normal CI should rely on synthetic in-memory signatures.

---

# 18. Failure Modes and Mitigations

## 18.1 Repeated Scenes

Problem:

```text
A video may repeat the same visual scene many times, creating false diagonal paths.
```

Mitigation:

```text
Use monotonicity.
Require minimum segment duration.
Use offset voting.
Use distance/confidence.
Prefer longer, cleaner segment over many tiny repeated matches.
```

## 18.2 Intros / Outros / Logos

Problem:

```text
Shared intros/outros cause false duplicate groups.
```

Mitigation:

```text
They should become partial_overlap or rejected unless coverage ratios are high.
```

## 18.3 Low-Entropy Frames

Problem:

```text
Black frames/title cards match unrelated videos.
```

Mitigation:

```text
Use only valid_for_matching frames from P2.
Track low_entropy_fraction in evidence.
Reduce confidence if low_entropy_fraction is high.
```

## 18.4 Different Frame Rates / Dropped Frames

Problem:

```text
Matching timestamps may drift slightly.
```

Mitigation:

```text
Allow max_gap_seconds.
Use offset bins.
Do not require exact frame index differences.
Use timestamp monotonicity rather than frame-index equality.
```

## 18.5 Speed Changes

Problem:

```text
A clip may be sped up/slowed down.
```

Initial P4 behavior:

```text
May miss or weaken alignment.
Do not solve fully now.
```

Future:

```text
Support diagonal slope ranges, not only near-1:1 offset bands.
```

Do not implement slope search in initial P4 unless easy.

---

# 19. Performance Targets

Q5G should run only on Q4G candidate pairs.

Expected complexity:

```text
per candidate pair:
    frame match generation O(n*m)
    offset voting O(r)
    segment extraction O(r log r)

where:
    n = valid sampled frames in left
    m = valid sampled frames in right
    r = frame matches under threshold
```

Log:

```text
candidate_pairs_received
candidate_pairs_aligned
candidate_pairs_rejected
full_duplicates
subsets
partial_overlaps
alignment_seconds_total
average_alignment_seconds_per_pair
```

Do not optimize with CUDA kernels yet.

Reason:

```text
At this stage, the GPU has already accelerated decode/fingerprint extraction.
Q5G alignment over sparse sampled signatures is likely CPU-cheap enough.
```

Later optimization:

```text
vectorized NumPy/PyTorch Hamming
FAISS binary range search
CUDA kernels
```

---

# 20. Acceptance Criteria

Plan #4 is complete when:

```text
1. Q5G consumes Q4G VisualCandidatePair objects.
2. Q5G builds frame matches from valid FrameSignatures.
3. Q5G performs offset voting.
4. Q5G extracts monotonic diagonal alignment segments.
5. Q5G supports multiple copied segments per pair.
6. Q5G computes overlap seconds and coverage ratios.
7. Q5G classifies full duplicate vs subset vs partial overlap vs reject.
8. Q5G emits timestamped evidence in report metadata.
9. subset_of_longer is actionable=true and review_required=true.
10. partial_overlap is actionable=false and review_required=true.
11. Q5G does not rely on metadata as evidence.
12. Q5G has unit tests for full/subset/partial/reject cases.
13. Q5G integrates with pipeline routing after Q4G.
14. CPU fallback behavior remains intact.
```

Minimum viable P4:

```text
- gpu_alignment.py
- gpu_q5.py
- in-memory signature tests
- Q4G candidate pair consumption
- full/subset/partial/reject classification
- report metadata with timestamp evidence
```

Defer if necessary:

```text
- real video GPU integration tests
- multi-slope speed-change handling
- advanced segment deduping
- visual timeline rendering
- FAISS/binary index acceleration
```

---

# 21. Suggested Claude Code Plan Mode Prompt

Use this prompt:

```text
Enter Plan Mode.

Use this document as the implementation spec for Plan #4 only.

Assume Plans 0, 1, 2, and 3 have already been implemented:
- REVIEW is a label/warning, not an apply gate.
- Candidate-only groups are never applyable.
- GPU capability/routing foundation exists.
- GPU sampling/decode/fingerprint extraction exists.
- VideoSignature and FrameSignature models exist.
- Q4G coarse duplicate detection exists.
- Q4GResult.candidate_pairs exists.

Do not edit files yet.

Inspect the current repo files relevant to:
- Q4G candidate pair output
- VideoSignature / FrameSignature models
- pipeline stage orchestration
- report metadata serialization
- report viewer display
- existing subset/timeline CPU logic if any
- tests and pytest style

Generate a repo-local implementation plan for Q5G temporal alignment.

The plan must include:
1. exact files to create/modify
2. exact public functions/classes to add
3. how Q4G VisualCandidatePair objects will feed Q5G
4. how frame matches will be generated
5. how offset voting will work
6. how diagonal streak extraction will work
7. how multiple segments will be represented
8. how full duplicate/subset/partial overlap/reject classification will work
9. report metadata/evidence schema
10. viewer changes for timestamp evidence
11. tests to add/update
12. risks and implementation uncertainties

Do not plan Q6G embeddings.
Do not change Q1/Q2/Q3 behavior.
Do not make metadata evidence.
Do not change apply safety semantics except to ensure partial_overlap actionable=false is skipped.
Stop after producing the plan. Wait for approval before editing.
```

After approving the repo-local plan, use:

```text
Switch to implementation mode.

Implement the approved Plan #4 only.
Run the targeted tests:
- gpu_alignment_test.py
- gpu_q5_test.py
- gpu_q5_pipeline_contract_test.py
- existing Q1/Q3/report safety tests
- existing Q4G tests

Do not start Q6G deep embeddings.
Do not alter existing CPU Q4/Q5 behavior except for routing fallback.
```

---

# 22. Notes for Future Plan #5

Plan #5 should implement Q6G deep embeddings.

Q6G should consume:

```text
Q5G rejected or weak candidates
Q4G visual candidates with insufficient hash alignment
hard transformed cases
```

Q6G should not make semantic-only matches apply-safe.

Q6G should only emit groups when deep embeddings also produce temporal alignment evidence.
