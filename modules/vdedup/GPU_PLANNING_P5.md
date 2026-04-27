# vdedup Implementation Plan: Plan #5 — Q6G Deep Embeddings for Hard Visual Matches

## Scope

This plan assumes the following are already implemented:

```text
P0/P1:
    safety semantics + GPU capability/routing foundation

P2:
    GPU sampling + decode + fingerprint extraction
    FrameSignature / VideoSignature
    optional signature cache

P3:
    Q4G coarse duplicate detection
    hash-band indexing
    full-video perceptual duplicate groups
    visual_candidate groups/pairs for uncertain matches

P4:
    Q5G temporal alignment
    offset voting
    diagonal streak extraction
    full/subset/partial/reject classification
    timestamped evidence
```

This plan implements:

```text
P5:
    Q6G deep visual embedding fallback
```

Q6G should improve recall for hard transformed cases where pHash/dHash and Q5G temporal alignment are too brittle.

Target hard cases:

```text
crop
resize
aspect-ratio conversion
watermark / overlay
border / pillarbox / letterbox
color grading
compression artifacts
mild blur
mild rotation
picture-in-picture-like edits
transcodes where pHash is unstable
```

Q6G must not become a broad semantic duplicate finder. Its purpose is still copy/same-footage detection.

---

## 1. High-Level Goal

Q4G answers:

```text
"Do these videos share enough perceptual-hash evidence to compare?"
```

Q5G answers:

```text
"Do these videos temporally align using hash-based frame matches?"
```

Q6G answers:

```text
"Do these videos temporally align when using stronger deep visual features instead of pHash/dHash?"
```

Q6G should consume difficult candidates from Q4G/Q5G and produce temporal evidence only when deep frame embeddings align over time.

---

## 2. Non-Goals

Q6G must not implement:

```text
1. Semantic-only deletion.
2. Text search.
3. CLIP prompt classification.
4. Audio matching.
5. Video trimming/editing.
6. Fine-tuning models.
7. Global average embedding deletion decisions.
8. Vector database infrastructure unless absolutely required.
```

Important rule:

```text
A high average embedding similarity is candidate evidence only.
It is not duplicate evidence.
```

Apply-safe/review-visible groups require temporal alignment evidence.

---

## 3. Model Strategy

## 3.1 Default Model: DINOv2

Recommended default:

```text
facebook/dinov2-small
```

or if GPU memory/performance is comfortable:

```text
facebook/dinov2-base
```

Reason:

```text
DINOv2 is image-only and visual-feature-oriented.
It is less likely than CLIP to overmatch two conceptually similar but visually different scenes.
It exposes whole-image CLS embeddings and patch/local embeddings through Transformers.
```

Initial Q6G should use:

```text
CLS embedding first
optional patch embeddings later
```

## 3.2 Optional Model: CLIP / OpenCLIP / SigLIP

CLIP-like models can be optional for later recall expansion.

Use only as:

```text
candidate recall signal
secondary evidence
debug/experimental backend
```

Do not make CLIP semantic similarity apply-safe by itself.

Reason:

```text
CLIP is semantic/text-aligned and may consider different footage of the same object/event too similar.
```

## 3.3 Model Backend Config

Add config fields:

```python
gpu_q6_enabled: bool = False
gpu_q6_model_backend: str = "dinov2"  # "dinov2" | "clip" | "openclip"
gpu_q6_model_name: str = "facebook/dinov2-small"
gpu_q6_batch_size: int = 32
gpu_q6_embedding_dtype: str = "float16"  # "float16" | "float32"
gpu_q6_max_frames_per_video: int = 64
gpu_q6_use_patch_embeddings: bool = False
gpu_q6_cache_embeddings: bool = True
```

Default:

```text
Q6G disabled unless Q6 is selected or thorough GPU mode requests it.
```

Do not run Q6G on every pair globally.

---

## 4. Safety Contract

## 4.1 Deep Embedding Candidate Only

If Q6G finds strong embedding similarity but no temporal alignment:

```text
candidate_only=true
actionable=false
review_required=true
match_type=deep_visual_candidate
method=gpu-deep-candidate
recommended_next_stage=q5 or q6-temporal
```

## 4.2 Deep Embedding + Temporal Full Duplicate

If Q6G finds embedding-based temporal alignment covering both videos:

```text
candidate_only=false
actionable=true
review_required=false
match_type=transformed_duplicate or perceptual_duplicate
method=gpu-deep-temporal
```

## 4.3 Deep Embedding + Temporal Subset

If Q6G finds shorter video mostly contained in longer video:

```text
candidate_only=false
actionable=true
review_required=true
match_type=subset_of_longer
method=gpu-deep-temporal-subset
```

## 4.4 Deep Embedding + Partial Overlap

If Q6G finds a meaningful aligned segment but both videos have unique content:

```text
candidate_only=false
actionable=false
review_required=true
match_type=partial_overlap
method=gpu-deep-temporal-overlap
```

## 4.5 Hard Invariant

```text
Deep semantic similarity alone must never create keep/losers.
Only temporally aligned deep visual evidence can create a verified group.
```

---

# 5. Files to Create or Modify

## New Files

```text
modules/vdedup/gpu_embeddings.py
modules/vdedup/gpu_q6.py
modules/vdedup/gpu_embedding_cache.py
modules/vdedup/tests/gpu_embeddings_test.py
modules/vdedup/tests/gpu_q6_test.py
modules/vdedup/tests/gpu_embedding_cache_test.py
modules/vdedup/tests/gpu_q6_pipeline_contract_test.py
```

## Existing Files Likely Modified

```text
modules/vdedup/pipeline.py
modules/vdedup/video_dedupe.py
modules/vdedup/gpu_signature.py
modules/vdedup/gpu_alignment.py
modules/vdedup/gpu_q5.py
modules/vdedup/report.py
modules/vdedup/report_models.py
modules/vdedup/report_viewer.py
pyproject.toml
```

Do not modify:

```text
Q1/Q2/Q3 safety behavior
Q4G hash-band logic except to pass unresolved candidates forward
Q5G alignment semantics except to reuse alignment utilities for embeddings
apply_report safety semantics
```

---

# 6. Optional Dependencies

Q6G should live under `gpu-deep` extras.

Example optional extras:

```toml
[project.optional-dependencies]
gpu-deep = [
    "transformers>=4.45",
    "accelerate>=1.0",
    "safetensors>=0.4",
]
```

If `torch` is already in `gpu`, do not duplicate it unless needed.

Rules:

```text
1. No top-level transformers imports.
2. CPU-only installs must still import vdedup.
3. Missing transformers/model dependencies should disable Q6G in --gpu auto.
4. --gpu on + selected Q6 should fail clearly if Q6G dependencies are missing.
```

---

# 7. Data Models

## 7.1 `FrameEmbedding`

File:

```text
modules/vdedup/gpu_embeddings.py
```

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass(slots=True)
class FrameEmbedding:
    path: Path
    video_id: str
    frame_index: int
    timestamp_seconds: float
    embedding: List[float]
    embedding_dim: int
    model_backend: str
    model_name: str
    normalized: bool = True
    valid_for_matching: bool = True
    invalid_reason: Optional[str] = None
    evidence: Dict[str, object] = field(default_factory=dict)
```

For memory efficiency, do not store Python lists internally during inference if tensors are available. Lists are for serialization only.

## 7.2 `VideoEmbeddingSignature`

File:

```text
modules/vdedup/gpu_embeddings.py
```

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass(slots=True)
class VideoEmbeddingSignature:
    path: Path
    video_id: str
    duration_seconds: Optional[float]
    model_backend: str
    model_name: str
    embedding_dim: int
    sampled_frame_count: int
    valid_frame_count: int
    frame_embeddings: List[FrameEmbedding] = field(default_factory=list)
    extraction_backend: str = "gpu"
    error: Optional[str] = None
    evidence: Dict[str, object] = field(default_factory=dict)
```

## 7.3 `DeepFrameMatch`

File:

```text
modules/vdedup/gpu_embeddings.py` or `gpu_alignment.py`
```

```python
from dataclasses import dataclass


@dataclass(slots=True)
class DeepFrameMatch:
    left_frame_index: int
    right_frame_index: int
    left_timestamp_seconds: float
    right_timestamp_seconds: float
    cosine_similarity: float
    distance: float
```

This can be converted into the existing `FrameMatch` model from P4:

```text
distance = 1.0 - cosine_similarity
similarity = cosine_similarity
```

---

# 8. Embedding Extraction

## 8.1 Model Loader

File:

```text
modules/vdedup/gpu_embeddings.py
```

Add:

```python
def load_embedding_model(
    *,
    backend: str,
    model_name: str,
    device: str,
    dtype: str = "float16",
):
    ...
```

Rules:

```text
1. Lazy import transformers/torch.
2. Cache loaded model/processors in-process.
3. Put model in eval mode.
4. Use torch.no_grad() or torch.inference_mode().
5. Move model to requested CUDA device when available.
6. Use float16 on CUDA if configured.
7. Use float32 on CPU fallback.
```

For DINOv2 with Transformers:

```text
AutoImageProcessor.from_pretrained(model_name)
AutoModel.from_pretrained(model_name)
CLS token = last_hidden_state[:, 0, :]
L2 normalize embedding
```

## 8.2 Input Frame Source

Q6G should reuse Plan #2 decode/sampling where possible.

Two modes:

```text
1. Whole-video sampled frames:
       use balanced/thorough sampled frames from VideoSignature.

2. Candidate-segment focused frames:
       if Q5G found weak/rejected tentative segments,
       resample frames around those timestamp ranges more densely.
```

Initial P5 implementation:

```text
Use sampled frames already selected by P2.
Do not implement segment-focused resampling yet unless easy.
```

Future improvement:

```text
Densify around Q5G weak diagonal hints.
```

## 8.3 Preprocessing

For DINOv2/Transformers:

```text
Use AutoImageProcessor if starting from PIL/numpy frames.
If starting from torch tensors, either:
    convert to expected tensor format manually,
    or use processor carefully.
```

Preferred initial path:

```text
Accept torch tensors or CPU arrays from P2.
Normalize/resize with the model processor or a dedicated preprocessing helper.
```

Be careful:

```text
Do not move frames GPU -> CPU -> GPU unnecessarily if avoidable.
```

However, initial correctness is more important than perfect zero-copy. If processor requires CPU PIL/numpy, accept a performance hit only for P5 initial implementation and mark a TODO.

## 8.4 Embedding Function

Add:

```python
def extract_video_embeddings(
    video_signature,
    *,
    backend: str = "dinov2",
    model_name: str = "facebook/dinov2-small",
    device_id: int = 0,
    batch_size: int = 32,
    dtype: str = "float16",
    max_frames: int = 64,
) -> VideoEmbeddingSignature:
    ...
```

Rules:

```text
1. Use only frames that are valid_for_matching unless configured otherwise.
2. Cap frames to max_frames.
3. Preserve timestamps.
4. Batch inference.
5. L2-normalize embeddings.
6. Return structured error if model load/inference fails.
```

---

# 9. Embedding Cache

Deep embeddings are expensive. Add cache unless implementation cost is excessive.

## 9.1 Cache Key

File:

```text
modules/vdedup/gpu_embedding_cache.py
```

Key components:

```text
path
size_bytes
mtime_ns
video_id
sampling_profile
model_backend
model_name
embedding_dtype
max_frames
schema_version
```

Do not key only by path.

## 9.2 Cache Storage

Preferred simple cache:

```text
cache_dir/
    <embedding_cache_key>.json
```

If embeddings are large, JSON is not ideal but acceptable for P5 if frame count is capped.

Better optional later:

```text
npz
safetensors
sqlite blob
```

Initial implementation:

```text
JSON per video embedding signature
```

If JSON file sizes are too large:

```text
store embeddings as float16 lists or rounded float32
```

But do not quantize in a way that breaks tests silently.

## 9.3 Cache API

```python
class EmbeddingCache:
    def __init__(self, cache_dir: Path) -> None:
        ...

    def get(self, key: str) -> Optional[VideoEmbeddingSignature]:
        ...

    def put(self, key: str, signature: VideoEmbeddingSignature) -> None:
        ...
```

Use atomic writes.

---

# 10. Candidate Selection

Q6G should run only on hard candidates.

## 10.1 Inputs

Candidate sources:

```text
1. Q5G rejected_results with enough weak evidence.
2. Q5G partial_overlap or low-confidence candidates if additional verification is requested.
3. Q4G visual_candidate pairs not resolved by Q5G.
4. Q3 candidates only if Q4G/Q5G found some weak visual evidence.
```

Do not run Q6G over all videos.

## 10.2 Eligibility Rule

A pair is eligible for Q6G if any of:

```text
Q4G candidate score >= gpu_q6_min_q4_score
Q4G max one-sided coverage >= gpu_q6_min_one_sided_coverage
Q5G rejected_reason indicates weak_hash_alignment but enough matches
Q5G confidence between low and medium thresholds
user selected thorough/deep mode
```

Suggested config:

```python
gpu_q6_min_q4_score: float = 0.30
gpu_q6_min_one_sided_coverage: float = 0.35
gpu_q6_max_pairs: int = 500
```

If too many pairs:

```text
rank by Q4G/Q5G score and process top N
```

---

# 11. Deep Similarity Matching

## 11.1 Cosine Similarity Matrix

Given two `VideoEmbeddingSignature` objects:

```text
A: [n, d]
B: [m, d]
```

Compute:

```text
similarity = A @ B.T
```

Embeddings should already be L2-normalized.

## 11.2 Deep Frame Match Extraction

Add:

```python
def build_deep_frame_matches(
    left_embeddings: VideoEmbeddingSignature,
    right_embeddings: VideoEmbeddingSignature,
    *,
    min_cosine_similarity: float = 0.82,
) -> list[FrameMatch]:
    ...
```

Rules:

```text
1. Compute cosine similarity matrix.
2. For each frame pair with similarity >= threshold, emit FrameMatch.
3. distance = 1.0 - similarity.
4. similarity = cosine similarity.
5. Sort by timestamps.
```

Suggested initial thresholds:

```python
gpu_q6_min_cosine_similarity: float = 0.82
gpu_q6_strong_cosine_similarity: float = 0.88
```

These must be config-driven and calibrated later.

## 11.3 Top-K Sparsification

To prevent too many matches:

```text
For each left frame, keep top K right frames above threshold.
For each right frame, optionally keep top K left frames.
```

Config:

```python
gpu_q6_top_k_per_frame: int = 5
```

Reason:

```text
Dense semantic matrices can create many spurious matches.
Sparse top-K keeps temporal alignment tractable.
```

---

# 12. Reuse Q5G Temporal Alignment

Q6G should not invent a new alignment algorithm.

Use P4/Q5G alignment functions with deep frame matches:

```text
vote_offsets
extract_alignment_segments
classify_alignment_result
union_interval_seconds
```

Q6G-specific differences:

```text
distance range is 0..1 instead of Hamming distance
similarity is cosine similarity
thresholds differ
```

Add a metric abstraction if needed:

```python
@dataclass(slots=True)
class MatchDistanceConfig:
    distance_kind: str  # "hamming" | "cosine_distance"
    max_distance: float
    min_similarity: float
```

But avoid overengineering. It is acceptable to convert deep matches into the existing `FrameMatch` type and pass Q6-specific config values.

---

# 13. Q6G Classification

Q6G classification should mirror Q5G:

```text
full duplicate
subset_of_longer
partial_overlap
rejected_candidate
```

## 13.1 Full Transformed Duplicate

```text
match_type=transformed_duplicate
method=gpu-deep-temporal
actionable=true
review_required=false
```

Conditions:

```text
overlap_ratio_left >= gpu_q6_full_duplicate_ratio
overlap_ratio_right >= gpu_q6_full_duplicate_ratio
confidence >= gpu_q6_min_confidence
median_cosine_similarity >= gpu_q6_median_similarity_threshold
```

Defaults:

```python
gpu_q6_full_duplicate_ratio: float = 0.90
gpu_q6_min_confidence: float = 0.60
gpu_q6_median_similarity_threshold: float = 0.84
```

## 13.2 Deep Subset

```text
match_type=subset_of_longer
method=gpu-deep-temporal-subset
actionable=true
review_required=true
```

Conditions:

```text
overlap_ratio_shorter >= gpu_q6_subset_ratio
overlap_ratio_longer < gpu_q6_full_duplicate_ratio
confidence >= gpu_q6_min_confidence
```

Defaults:

```python
gpu_q6_subset_ratio: float = 0.85
```

## 13.3 Deep Partial Overlap

```text
match_type=partial_overlap
method=gpu-deep-temporal-overlap
actionable=false
review_required=true
```

Conditions:

```text
overlap_seconds >= gpu_q6_partial_min_seconds
or overlap_ratio_shorter >= gpu_q6_partial_min_shorter_ratio
```

Defaults:

```python
gpu_q6_partial_min_seconds: float = 10.0
gpu_q6_partial_min_shorter_ratio: float = 0.10
```

## 13.4 Rejected

No report output by default.

---

# 14. Q6G Evidence Schema

Every Q6G result should include:

```json
{
    "backend": "gpu",
    "verified_by": ["gpu_q6_deep_embeddings", "gpu_temporal_alignment"],
    "model_backend": "dinov2",
    "model_name": "facebook/dinov2-small",
    "embedding_dim": 384,
    "min_cosine_similarity": 0.82,
    "median_cosine_similarity": 0.87,
    "mean_cosine_similarity": 0.85,
    "overlap_seconds": 132.0,
    "overlap_ratio_left": 0.96,
    "overlap_ratio_right": 0.18,
    "overlap_ratio_shorter": 0.96,
    "overlap_ratio_longer": 0.18,
    "confidence": 0.88,
    "segments": [
        {
            "start_left_seconds": 0.0,
            "end_left_seconds": 132.0,
            "start_right_seconds": 2052.0,
            "end_right_seconds": 2184.0,
            "matched_frame_count": 42,
            "median_cosine_similarity": 0.87,
            "score": 0.89
        }
    ]
}
```

For transformed duplicates, include:

```json
{
    "match_type": "transformed_duplicate",
    "transformation_resilience": "deep_visual_embedding"
}
```

Do not claim exact transformation type unless explicitly detected.

---

# 15. Q6G Public API

File:

```text
modules/vdedup/gpu_q6.py
```

Add:

```python
def run_q6g(
    candidate_pairs: Sequence[object],
    video_signatures_by_path: Mapping[Path, object],
    *,
    q4g_result: Optional[object] = None,
    q5g_result: Optional[object] = None,
    config: object,
    reporter: Optional[object] = None,
) -> Q6GResult:
    ...
```

Add result model:

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from .gpu_alignment import TemporalAlignmentResult


@dataclass(slots=True)
class Q6GResult:
    duplicate_groups: Dict[str, List[Path]] = field(default_factory=dict)
    group_metadata: Dict[str, Dict[str, object]] = field(default_factory=dict)
    candidate_groups: Dict[str, List[Path]] = field(default_factory=dict)
    candidate_metadata: Dict[str, Dict[str, object]] = field(default_factory=dict)
    alignment_results: List[TemporalAlignmentResult] = field(default_factory=list)
    rejected_results: List[TemporalAlignmentResult] = field(default_factory=list)
```

Recommended helpers:

```python
def select_q6g_candidates(...) -> list[object]:
    ...

def extract_or_load_embeddings(...) -> VideoEmbeddingSignature:
    ...

def build_deep_frame_matches(...) -> list[FrameMatch]:
    ...

def align_deep_candidate_pair(...) -> TemporalAlignmentResult:
    ...

def q6_alignment_result_to_metadata(...) -> Dict[str, object]:
    ...
```

---

# 16. Pipeline Integration

## 16.1 Stage Routing

In `pipeline.py`, after Q5G:

```text
if 6 in selected_stages and GPU route is enabled:
    run Q6G on unresolved/hard candidates
else:
    run existing CPU Q6 if selected
```

If old CPU Q6 audio stage exists, avoid name collision.

Important:

```text
If current Q6 is audio fingerprinting, do not silently replace it.
Either:
    map Q6G behind GPU route only, or
    use internal stage label "Q6G deep visual" while preserving CPU Q6 audio behavior.
```

Recommended:

```text
--gpu on/auto + selected Q6:
    run Q6G deep visual after Q5G if GPU/deep deps available

--gpu off + selected Q6:
    run existing CPU Q6 audio behavior
```

If both CPU audio Q6 and GPU deep Q6 should run:

```text
run CPU audio as Q6A
run GPU deep as Q6G
```

But avoid too much restructuring in P5.

## 16.2 Standalone `-q 6`

If user runs:

```text
-q 6
```

Q6G needs candidates.

Recommended behavior:

```text
-q 6:
    internally run minimal Q4G candidate generation
    internally run Q5G hash temporal alignment
    run Q6G only on unresolved candidates
    emit only Q6G results unless existing stage semantics expect cumulative output
```

If too much for initial P5:

```text
-q 4-6 works
-q 6 standalone fails clearly:
    "Q6G requires Q4G/Q5G candidates; run -q 4-6 or enable internal candidate generation."
```

Preferred long-term:

```text
Each q-level can run independently, so implement internal candidate generation.
```

---

# 17. Viewer Updates

Report viewer should distinguish Q6G from Q5G:

```text
[SAFE] gpu-deep-temporal:0 transformed_duplicate
    model: dinov2 facebook/dinov2-small
    overlap: 96% / 95%, 132.0s
    median cosine: 0.87
    segment:
        left:  00:00:00–00:02:12
        right: 00:34:12–00:36:24

[REVIEW] gpu-deep-temporal-sub:0 subset_of_longer
    model: dinov2 facebook/dinov2-small
    shorter coverage: 96%
    longer coverage: 18%
    median cosine: 0.87

[REVIEW] gpu-deep-temporal-overlap:0 partial_overlap NON-ACTIONABLE
    model: dinov2 facebook/dinov2-small
    overlap: 47.0s
    median cosine: 0.84
```

For semantic-only candidates:

```text
[CANDIDATE] gpu-deep-candidate:0
    model: dinov2 facebook/dinov2-small
    reason: high embedding similarity but no temporal alignment
```

---

# 18. Tests

## 18.1 `gpu_embeddings_test.py`

Required tests:

```text
test_embedding_model_imports_are_lazy
test_missing_transformers_disables_q6g_cleanly
test_frame_embedding_json_round_trip
test_video_embedding_signature_json_round_trip
test_l2_normalize_embeddings
test_build_deep_frame_matches_threshold
test_build_deep_frame_matches_top_k
test_build_deep_frame_matches_returns_frame_match_compatible_objects
```

Use mocked model/processor. Do not require internet/model download.

## 18.2 `gpu_embedding_cache_test.py`

Required tests:

```text
test_embedding_cache_key_changes_with_model_name
test_embedding_cache_key_changes_with_mtime
test_embedding_cache_put_get_round_trip
test_embedding_cache_corrupt_file_tolerated
test_embedding_cache_missing_returns_none
```

## 18.3 `gpu_q6_test.py`

Use in-memory embeddings and timestamps.

Required tests:

```text
test_q6g_rejects_semantic_similarity_without_temporal_alignment
test_q6g_full_transformed_duplicate
test_q6g_subset_review_group
test_q6g_partial_overlap_non_actionable
test_q6g_uses_q5_alignment_helpers
test_q6g_metadata_contains_model_name_and_similarity
test_q6g_does_not_emit_groups_for_embedding_only_candidate
test_q6g_limits_max_candidate_pairs
```

## 18.4 Pipeline Contract Tests

File:

```text
modules/vdedup/tests/gpu_q6_pipeline_contract_test.py
```

Required tests:

```text
test_q6g_consumes_q5g_unresolved_candidates
test_q6g_groups_merge_into_report_groups
test_q6g_candidates_merge_into_candidate_groups
test_gpu_off_preserves_existing_cpu_q6_behavior
test_gpu_auto_skips_q6g_when_deep_deps_missing
test_gpu_on_fails_when_deep_deps_missing
test_q6g_does_not_change_q1_q3_safety
test_q6g_does_not_make_semantic_only_matches_actionable
```

## 18.5 Optional Real GPU Smoke Test

Mark:

```python
@pytest.mark.gpu
@pytest.mark.deep
```

Scenarios:

```text
cropped duplicate
watermarked duplicate
color-graded duplicate
pHash-failing but visually same clip
```

Expected:

```text
Q6G recovers temporal alignment.
```

Normal CI should not require these.

---

# 19. Failure Modes and Mitigations

## 19.1 Semantic Overmatching

Problem:

```text
Different footage of similar objects/scenes may have high CLIP/DINO similarity.
```

Mitigation:

```text
Require temporal alignment.
Use DINOv2 default before CLIP.
Keep semantic-only results as candidates.
Use top-K sparsification and offset voting.
```

## 19.2 Model Download / Offline Environments

Problem:

```text
Transformers may try to download model weights.
```

Mitigation:

```text
Allow local model path.
Expose config for model cache dir if needed.
Fail clearly if model not available.
Do not download in tests.
```

Config:

```python
gpu_q6_model_cache_dir: Optional[Path] = None
gpu_q6_local_files_only: bool = False
```

## 19.3 VRAM Pressure

Problem:

```text
Deep models can use significant VRAM.
```

Mitigation:

```text
Batch size config.
float16 on CUDA.
small model default.
max frames per video cap.
clear model cache if needed.
```

## 19.4 Slow Throughput

Problem:

```text
Q6G can be much slower than Q4G/Q5G.
```

Mitigation:

```text
Run only on unresolved hard candidates.
Limit max pairs.
Cache embeddings.
Log timing.
```

## 19.5 License / Commercial Use

Problem:

```text
Some model weights may have non-commercial or research-only terms.
```

Mitigation:

```text
Document model license caveat.
Allow user-provided local model.
Keep backend/model configurable.
Do not hardcode a legally problematic model as the only option.
```

Important implementation note:

```text
The code should not hide model license implications.
README/help should say the user is responsible for model license compatibility.
```

---

# 20. Performance Metrics

Log:

```text
q6_candidate_pairs_received
q6_candidate_pairs_selected
q6_embeddings_cache_hits
q6_embeddings_cache_misses
q6_model_load_seconds
q6_embedding_seconds
q6_alignment_seconds
q6_full_duplicates
q6_subsets
q6_partial_overlaps
q6_rejected
q6_peak_vram_if_available
```

Do not optimize prematurely.

Expected P5 behavior:

```text
Q6G is slower but high-recall.
Q6G should run on a small candidate set only.
```

---

# 21. Acceptance Criteria

Plan #5 is complete when:

```text
1. Q6G optional dependencies are isolated behind gpu-deep.
2. CPU-only installs still import vdedup.
3. Q6G can load/mock a deep visual embedding model.
4. Q6G can extract/cache per-frame embeddings.
5. Q6G can compute sparse cosine-similarity frame matches.
6. Q6G reuses Q5G temporal alignment logic.
7. Q6G rejects embedding-only matches without temporal alignment.
8. Q6G classifies transformed full duplicate/subset/partial/reject cases.
9. Q6G emits timestamped evidence with model/backend/similarity metadata.
10. Q6G never makes semantic-only matches apply-safe.
11. Q6G integrates with pipeline routing after Q5G.
12. GPU-off behavior preserves existing CPU Q6 behavior.
13. Tests pass without CUDA/model downloads using mocks.
```

Minimum viable P5:

```text
- gpu_embeddings.py
- gpu_q6.py
- mocked model tests
- in-memory embedding alignment tests
- Q6G candidate selection from Q5G unresolved results
- report metadata for deep temporal groups
```

Defer if necessary:

```text
- CLIP/OpenCLIP backend
- patch-level local embeddings
- real model smoke tests
- FAISS/ANN embedding retrieval
- local model management UI
- advanced crop/geometric verification
```

---

# 22. Suggested Claude Code Plan Mode Prompt

Use this prompt:

```text
Enter Plan Mode.

Use this document as the implementation spec for Plan #5 only.

Assume Plans 0 through 4 have already been implemented:
- REVIEW is a label/warning, not an apply gate.
- Candidate-only groups are never applyable.
- GPU capability/routing foundation exists.
- GPU sampling/decode/fingerprint extraction exists.
- Q4G coarse duplicate detection exists.
- Q5G temporal alignment exists.
- VideoSignature, FrameSignature, VisualCandidatePair, and TemporalAlignmentResult exist.

Do not edit files yet.

Inspect the current repo files relevant to:
- Q4G candidate pair output
- Q5G unresolved/rejected results
- VideoSignature / FrameSignature models
- GPU routing/capability detection
- optional dependency handling
- report metadata serialization
- report viewer display
- existing CPU Q6 behavior if any
- tests and pytest style

Generate a repo-local implementation plan for Q6G deep visual embeddings.

The plan must include:
1. exact files to create/modify
2. exact public functions/classes to add
3. how optional transformers/model dependencies stay lazy
4. default model/backend choice and configuration
5. how per-frame embeddings will be extracted and cached
6. how candidate pairs are selected for Q6G
7. how cosine frame matches are generated
8. how Q5G temporal alignment logic is reused
9. how transformed full duplicate/subset/partial/reject classification works
10. report metadata/evidence schema
11. viewer changes for deep temporal evidence
12. tests to add/update
13. risks and implementation uncertainties

Do not make semantic-only matches apply-safe.
Do not implement audio matching.
Do not implement model fine-tuning.
Do not change Q1/Q2/Q3 behavior.
Do not make metadata evidence.
Stop after producing the plan. Wait for approval before editing.
```

After approving the repo-local plan, use:

```text
Switch to implementation mode.

Implement the approved Plan #5 only.
Run the targeted tests:
- gpu_embeddings_test.py
- gpu_embedding_cache_test.py
- gpu_q6_test.py
- gpu_q6_pipeline_contract_test.py
- existing Q4G/Q5G tests
- existing Q1/Q3/report safety tests

Do not start unrelated architecture work.
Do not alter existing CPU Q6 behavior except for explicit GPU routing integration.
```

---

# 23. Final Safety Reminder

Q6G is a recall-expansion stage, not a license to delete semantically similar videos.

The only safe Q6G deletion-capable cases are:

```text
deep visual embedding similarity
+ temporal alignment
+ sufficient coverage ratio
+ clear match_type
+ actionable=true
```

Everything else remains:

```text
candidate_only
or
actionable=false REVIEW
```
