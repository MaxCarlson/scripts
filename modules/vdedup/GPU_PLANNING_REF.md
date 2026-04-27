The diff now has the right safety direction for Q1/Q3: both emit `candidate_groups`, Q2 exact hashes are annotated as actionable, and Q3 standalone metadata output is explicitly non-apply-safe.  One correction based on your clarification: **`REVIEW` should be a viewer/report label, not an apply gate**. Candidate-only groups should remain impossible to apply, but verified groups marked `REVIEW` should not require `-F`; they should simply be visibly labeled.

For GPU work, the best scope is **three new GPU-backed levels** rather than trying to design all future Q stages at once:

```text
Q4G = GPU visual fingerprint extraction + coarse visual duplicate detection
Q5G = GPU-assisted temporal alignment for full/subset/overlap classification
Q6G = deep embedding fallback for transformed/cropped/watermarked hard cases
```

This aligns with the literature: VCDB-style systems use frame-level matching followed by temporal alignment for partial copies, not metadata inference; VCSL evaluates whole video pairs and localized copied segment overlap; NVIDIA’s current PyNvVideoCodec supports GPU decode, `SimpleDecoder`, `ThreadedDecoder`, `use_device_memory=True`, and DLPack handoff to PyTorch; and NVIDIA’s Video Codec SDK emphasizes direct decoder-to-GPU-compute paths without extra memory/PCIe copies.  ([NVIDIA Docs][1])

````markdown
# vdedup GPU Acceleration Implementation Plan

## 0. Immediate Safety Clarification Before GPU Work

The current Q1/Q3/Q4 safety refactor is mostly correct, but one semantic change is required before continuing.

### Required Change: `REVIEW` Is a Label, Not an Apply Gate

`review_required` should not actually block applying a verified group. It should mean:

- Display an all-caps `REVIEW` label next to the group in `video-dedupe view`.
- Include the label in report JSON.
- Include the count in report summary.
- Warn during apply that review-labeled groups exist.
- Do not require `-F` / `--force-review-required`.

Candidate-only groups are different:

- `candidate_only=true` must remain impossible to apply.
- Q1 size candidates and Q3 metadata candidates must never have `keep` / `losers`.
- Candidate groups should remain members-only.
- Candidate groups should never be affected by `--force`, `-F`, or any prompt-skipping flag.

Recommended updated apply semantics:

```text
candidate_only=true:
    never applyable

actionable=false:
    never applyable

actionable=true and review_required=false:
    applyable normally

actionable=true and review_required=true:
    applyable normally, but display REVIEW warning/label
````

Recommended CLI cleanup:

```text
--force / -f:
    skip interactive prompt for actionable groups

--force-review-required / -F:
    remove this flag, ignore it with a deprecation warning, or leave it accepted as a no-op for compatibility
```

Recommended viewer display:

```text
[SAFE]   hash:...
[SAFE]   phash:...
[REVIEW] subset:...
[REVIEW] timeline-sub:...
[CANDIDATE] size_candidate:...
[CANDIDATE] meta_candidate:...
```

Hard invariant:

```text
Only groups with keep/losers and actionable=true are applyable.
Candidate groups are never applyable.
REVIEW is visual/report labeling, not an execution blocker.
```

---

# 1. Strategic Direction

The current CPU Q4+ path can remain as the portable fallback. The GPU path should diverge substantially after Q3.

The existing Q1/Q2/Q3 architecture is now a good front-end:

* Q1: file-size candidates only.
* Q2: exact hash verification.
* Q3: metadata candidates only.
* Q4+: content verification.

The GPU work should not try to preserve the existing Q4/Q5/Q6/Q7 internals. Treat the existing CPU logic as:

```text
legacy_cpu_visual_route
```

and add a new GPU route:

```text
gpu_visual_route
```

The GPU route should start with three focused quality levels:

```text
Q4G: GPU visual fingerprint extraction and coarse visual duplicate detection.
Q5G: GPU-assisted temporal alignment and duplicate/subset/overlap classification.
Q6G: deep embedding fallback for hard transformed cases.
```

Do not implement every future quality level at once. Q4G/Q5G/Q6G are enough to create a coherent, benchmarkable GPU architecture.

---

# 2. Quality-Level Redesign

## Q4G: GPU Visual Fingerprint Extraction + Coarse Duplicate Detection

Purpose:

* Decode sampled video frames on GPU.
* Compute compact frame-level perceptual signatures.
* Produce full-video duplicate groups only when evidence is strong.
* Produce candidate pairs for Q5G temporal alignment when evidence is promising but not sufficient.

Primary outputs:

```text
groups:
    perceptual full-video duplicates only

candidate_groups:
    possible subset/overlap/transformed pairs requiring Q5G/Q6G
```

Default safety:

```text
full-video duplicate:
    actionable=true
    review_required=false
    match_type=perceptual_duplicate

possible subset/overlap:
    candidate_only=true OR actionable=false
    recommended_next_stage=q5g
```

## Q5G: Temporal Alignment + Subset/Overlap Classification

Purpose:

* Given candidate pairs from Q4G, compute localized temporal alignment.
* Classify:

  * full duplicate
  * subset_of_longer
  * partial_overlap
  * rejected_candidate

Primary outputs:

```text
groups:
    full duplicate
    subset_of_longer
    partial_overlap

candidate_groups:
    rejected or weak candidates, optionally only in debug reports
```

Default safety:

```text
full duplicate:
    actionable=true
    review_required=false

subset_of_longer:
    actionable=true
    review_required=true
    display REVIEW label

partial_overlap:
    actionable=true only if the planned apply behavior is non-destructive or user explicitly chooses overlap policy
    otherwise actionable=false or review_required=true depending existing report policy

rejected_candidate:
    not a group
```

Important policy:

A `partial_overlap` is not equivalent to a duplicate. If both files contain unique content, deleting either is wrong by default. The report should still show it, but apply should not delete overlap-only groups unless a later policy explicitly supports trimming, archiving, or manual action.

Recommended initial choice:

```text
subset_of_longer:
    actionable=true
    review_required=true

partial_overlap:
    actionable=false
    review_required=true
```

## Q6G: Deep Embedding Fallback

Purpose:

* Verify hard cases where pHash-like signatures are too brittle:

  * crop
  * resize
  * watermark
  * color transform
  * strong compression
  * format transcode
  * aspect ratio conversion
  * picture-in-picture / border edits

Primary outputs:

```text
groups:
    transformed duplicates or transformed subsets only when Q6G + Q5G temporal evidence agrees

candidate_groups:
    semantic-only matches without temporal alignment
```

Default safety:

```text
semantic-only:
    not apply-safe

semantic + temporal alignment:
    actionable depends on match_type
```

---

# 3. GPU Dependencies and Optional Install Strategy

Keep the default install CPU-only. Add GPU extras.

## pyproject.toml

Add optional dependencies:

```toml
[project.optional-dependencies]
gpu = [
    "torch>=2.5",
    "torchvision>=0.20",
    "numpy>=1.26",
    "PyNvVideoCodec>=2.1",
]

gpu-deep = [
    "transformers>=4.45",
    "accelerate>=1.0",
    "safetensors>=0.4",
]
```

Do not make GPU dependencies mandatory.

## Runtime Detection

Add a GPU capability module:

```text
gpu_capabilities.py
```

Responsibilities:

```text
detect torch
detect CUDA
detect PyNvVideoCodec
detect GPU name
detect available VRAM
detect whether NVDEC decode is usable
select fallback route if any required component is missing
```

Suggested public API:

```python
@dataclass(slots=True)
class GpuCapabilities:
    gpu_available: bool
    torch_available: bool
    cuda_available: bool
    pynvcodec_available: bool
    device_name: Optional[str]
    total_vram_bytes: Optional[int]
    reason_unavailable: Optional[str]

def detect_gpu_capabilities() -> GpuCapabilities:
    ...
```

CLI behavior:

```text
--gpu auto:
    use GPU route if available, otherwise CPU route

--gpu on:
    require GPU route; fail if unavailable

--gpu off:
    force CPU route
```

If changing CLI surface now is too large, start with config fields only and internal auto-detection.

---

# 4. New Module Layout

Keep the current repository structure, but add GPU-specific modules beside existing CPU modules.

Recommended new files:

```text
modules/vdedup/gpu_capabilities.py
modules/vdedup/gpu_decode.py
modules/vdedup/gpu_sampling.py
modules/vdedup/gpu_fingerprint.py
modules/vdedup/gpu_index.py
modules/vdedup/gpu_alignment.py
modules/vdedup/gpu_pipeline.py
modules/vdedup/tests/gpu_capabilities_test.py
modules/vdedup/tests/gpu_sampling_test.py
modules/vdedup/tests/gpu_alignment_test.py
modules/vdedup/tests/gpu_report_contract_test.py
```

Do not rewrite `pipeline.py` around GPU code initially. Instead:

```text
pipeline.py:
    orchestrates stage selection
    delegates Q4G+ to gpu_pipeline.py when GPU route is selected
```

---

# 5. Core Data Models

Add these models in a new file or in existing `models.py` if that is the repo convention.

## FrameSignature

```python
@dataclass(slots=True)
class FrameSignature:
    path: Path
    video_id: str
    frame_index: int
    timestamp_seconds: float
    phash64: int
    entropy: float
    mean_luma: float
    valid_for_matching: bool
```

## VideoSignature

```python
@dataclass(slots=True)
class VideoSignature:
    path: Path
    video_id: str
    duration_seconds: Optional[float]
    sampled_frame_count: int
    valid_frame_count: int
    signatures: List[FrameSignature]
    extraction_backend: str
    sampling_profile: str
```

## CandidatePair

```python
@dataclass(slots=True)
class CandidatePair:
    left: Path
    right: Path
    source: str
    score: float
    evidence: Dict[str, Any]
```

## TemporalAlignmentResult

```python
@dataclass(slots=True)
class TemporalAlignmentResult:
    left: Path
    right: Path
    start_left_seconds: float
    end_left_seconds: float
    start_right_seconds: float
    end_right_seconds: float
    overlap_seconds: float
    overlap_ratio_left: float
    overlap_ratio_right: float
    matched_frame_count: int
    mean_distance: float
    median_distance: float
    max_gap_seconds: float
    low_entropy_fraction: float
    confidence: float
    match_type: str
    review_required: bool
    actionable: bool
```

The report layer should consume `TemporalAlignmentResult` to create `groups` with evidence.

---

# 6. Q4G Detailed Plan: GPU Visual Fingerprint Extraction

## 6.1 Decoder Backend

Use PyNvVideoCodec as the preferred backend.

Two decode modes:

```text
SimpleDecoder:
    Use for sparse/random sampling.
    Best for Q4G where only selected frame indices are needed.

ThreadedDecoder:
    Use for dense sequential sampling.
    Best for Q5G/Q6G if doing contiguous clip analysis or heavy model inference.
```

Q4G should start with `SimpleDecoder`.

Required decoder settings:

```text
use_device_memory=True
output_color_type=RGBP or equivalent RGB planar output
gpu_id=0 by default
```

Fallbacks:

```text
PyNvVideoCodec unavailable:
    use existing CPU ffmpeg/Pillow path

decode failure for a file:
    record error
    fallback to CPU for that file if --gpu auto
    fail if --gpu on
```

## 6.2 Sampling Strategy

Add `gpu_sampling.py`.

Sampling should be deterministic and duration-aware.

Recommended profiles:

```text
fast:
    target_frames = 16 to 32

balanced:
    target_frames = 48 to 96

thorough:
    target_frames = 128 to 256
```

Initial Q4G default:

```text
balanced
```

Sampling logic:

```text
if duration unknown:
    use container frame count if available
    otherwise sample by frame indices from decoder length if available

if duration <= 60s:
    sample every 1s, capped at 96 frames

if duration <= 10min:
    sample every 2s, capped at 128 frames

if duration > 10min:
    sample uniformly up to target_frames
```

Important:

Sampling must include early, middle, and late content, but avoid relying only on intro/outro.

Recommended exclusion:

```text
For videos longer than 60s:
    avoid first 3s and last 3s in coarse duplicate scoring
    still keep these frames in raw signatures for evidence/debugging
```

## 6.3 GPU pHash Implementation

Implement a batched pHash-like signature in PyTorch.

Input:

```text
N x C x H x W RGB tensor on CUDA
```

Pipeline:

```text
resize to 32x32 or 64x64 on GPU
convert to grayscale on GPU
optionally blur/downsample
compute DCT or approximate low-frequency transform
extract top-left 8x8 coefficients excluding DC
threshold by median
pack into uint64
```

Initial implementation options:

### Option A: Torch DCT via Matrix Multiplication

Precompute DCT basis matrix on CUDA:

```python
D = create_dct_matrix(32, device="cuda")
coeff = D @ image @ D.T
```

Pros:

```text
simple
deterministic
no extra dependencies
fast enough for sampled frames
```

Cons:

```text
not as fast as custom CUDA/CuPy
```

Use this first.

### Option B: average/difference hash fallback

If DCT is annoying initially, implement GPU dHash first:

```text
resize grayscale to 9x8
compare adjacent pixels
pack 64-bit hash
```

This is less robust than pHash but much easier. However, pHash/DCT should be the target.

## 6.4 Low-Entropy Filtering

Each frame gets:

```text
mean_luma
std_luma
entropy estimate
valid_for_matching
```

Invalid frames:

```text
nearly black
nearly white
very low variance
very low entropy
```

Suggested initial thresholds:

```text
mean_luma < 4/255:
    invalid

std_luma < 2/255:
    invalid

entropy < 1.0:
    invalid
```

Keep these configurable. Do not delete the frame record; just mark it invalid for matching.

## 6.5 Q4G Candidate Generation

For each video:

```text
extract VideoSignature
store frame signatures in memory for this scan
optionally cache to JSONL/SQLite later
```

Generate candidate pairs by hash buckets:

```text
Split 64-bit hash into bands:
    4 bands of 16 bits
or
    8 bands of 8 bits

For each valid frame hash:
    add (band_value, video_id, frame_index) to bucket

Candidate video pair score:
    count matching/similar buckets across videos
```

Then verify candidates with true Hamming distance:

```text
candidate frame match if hamming(phash_a, phash_b) <= threshold
```

Suggested initial threshold:

```text
hamming <= 8:
    strong frame match

hamming <= 12:
    weak frame match
```

Q4G full duplicate grouping:

```text
If videos have similar duration and high bidirectional sampled-frame coverage:
    emit perceptual_duplicate

Suggested thresholds:
    overlap_ratio_left >= 0.90
    overlap_ratio_right >= 0.90
    median_hamming <= 8
    valid matched frames >= 8
```

Q4G should not emit subset groups yet unless the current CPU subset logic already does this well. Prefer Q5G for subset/overlap classification.

---

# 7. Q5G Detailed Plan: Temporal Alignment

Q5G is the most important stage for correctness.

It should consume candidate pairs from:

```text
Q3 metadata candidates
Q4G visual candidates
existing CPU pHash candidate groups if GPU route is mixed
```

## 7.1 Frame Match Matrix

Given two `VideoSignature` objects:

```text
A signatures: a_0 ... a_n
B signatures: b_0 ... b_m
```

Build sparse frame matches:

```text
for each valid frame a_i:
    find b_j where hamming(a_i.phash64, b_j.phash64) <= threshold
```

Do not materialize a dense matrix for large videos unless needed.

Represent matches as:

```python
@dataclass(slots=True)
class FrameMatch:
    i: int
    j: int
    t_left: float
    t_right: float
    distance: int
```

## 7.2 Diagonal Offset Voting

For each frame match:

```text
offset = t_right - t_left
```

Bin offsets:

```text
bin_size = max(sample_interval_seconds, 1.0)
offset_bin = round(offset / bin_size)
```

Strong candidate alignments are bins with many matches.

This is a temporal Hough-style prefilter.

## 7.3 Diagonal Streak Extraction

For top offset bins:

```text
sort matches by i then j
walk monotonic paths where both i and j increase
allow small gaps
score path by:
    matched_frame_count
    overlap_seconds
    median distance
    gap penalty
    entropy quality
```

Suggested gap tolerance:

```text
fast:
    max_gap_frames = 2

balanced:
    max_gap_frames = 3

thorough:
    max_gap_frames = 5
```

Suggested minimums:

```text
min_matched_frames = 6
min_overlap_seconds = 5.0
```

For long videos, raise minimum overlap:

```text
min_overlap_seconds = max(5.0, 0.02 * min(duration_left, duration_right))
cap at maybe 30s for initial implementation
```

## 7.4 Classification

Given best alignment:

```text
ratio_left = overlap_seconds / duration_left
ratio_right = overlap_seconds / duration_right
ratio_shorter = overlap_seconds / min(duration_left, duration_right)
ratio_longer = overlap_seconds / max(duration_left, duration_right)
```

Classification:

```text
if ratio_left >= 0.90 and ratio_right >= 0.90:
    match_type = perceptual_duplicate
    actionable = true
    review_required = false

elif ratio_shorter >= 0.85 and ratio_longer < 0.85:
    match_type = subset_of_longer
    actionable = true
    review_required = true

elif overlap_seconds >= min_partial_overlap_seconds:
    match_type = partial_overlap
    actionable = false
    review_required = true

else:
    rejected_candidate
```

Initial `min_partial_overlap_seconds`:

```text
10s for short videos
30s for longer videos
```

Configurable:

```text
--min-overlap-seconds
--subset-ratio
--full-duplicate-ratio
```

If the CLI already has equivalent flags, reuse them.

## 7.5 Report Evidence

Every Q5G emitted group should include:

```json
{
    "verified_by": "gpu_temporal_alignment",
    "match_type": "subset_of_longer",
    "overlap_seconds": 42.0,
    "overlap_ratio_left": 0.95,
    "overlap_ratio_right": 0.18,
    "start_left_seconds": 0.0,
    "end_left_seconds": 42.0,
    "start_right_seconds": 391.0,
    "end_right_seconds": 433.0,
    "matched_frame_count": 37,
    "mean_hamming_distance": 5.8,
    "median_hamming_distance": 5.0,
    "max_gap_seconds": 3.0,
    "low_entropy_fraction": 0.04,
    "backend": "gpu"
}
```

The report viewer should show timestamp ranges prominently.

---

# 8. Q6G Detailed Plan: Deep Embedding Fallback

Q6G should not run globally at first. It should run only on candidates that Q4G/Q5G cannot confidently decide.

Candidate sources:

```text
Q4G high visual bucket overlap but weak pHash distance
Q5G weak diagonal but enough hints
Q3 metadata candidates that Q4G did not confirm but user requested thorough mode
manual candidate groups from report
```

## 8.1 Model Choice

Start with one image embedding model, not a video model.

Recommended initial options:

```text
DINOv2 small/base:
    strong visual retrieval features
    good for transformed/cropped visuals
    no text semantics needed

CLIP/SigLIP:
    more semantic
    may overmatch conceptually similar but non-duplicate scenes
```

Initial recommendation:

```text
Use DINOv2 or a retrieval-oriented vision embedding before CLIP.
```

Reason:

`vdedup` needs copy/same-footage detection, not broad semantic similarity. CLIP may consider two different videos of the same object/event too close.

## 8.2 Sampling for Embeddings

Use Q5G alignment hints:

```text
If Q5G found weak candidate segment:
    embed frames around candidate segment

Else:
    embed balanced sampled frames
```

Do not embed every frame.

Suggested limits:

```text
fast:
    16 frames/video

balanced:
    32 frames/video

thorough:
    64 frames/video
```

## 8.3 Embedding Similarity

For each pair:

```text
normalize embeddings
compute similarity matrix: A @ B.T
find diagonal/temporal alignments using the same Q5G alignment code
```

Do not use average pooled video embedding for deletion decisions. Average embedding is acceptable for candidate generation only.

## 8.4 Q6G Classification

Only emit groups when temporal alignment exists.

```text
semantic similarity without temporal alignment:
    candidate only

semantic similarity + temporal alignment:
    classify with same Q5G rules
```

Suggested thresholds need calibration, but initial rough values:

```text
cosine >= 0.82:
    possible frame match

cosine >= 0.88:
    strong frame match
```

Keep these config-driven and report the actual score distribution.

---

# 9. Pipeline Integration

## 9.1 PipelineConfig Additions

Add fields:

```python
use_gpu: str = "auto"  # "auto" | "on" | "off"
gpu_device_id: int = 0
gpu_quality_profile: str = "balanced"  # "fast" | "balanced" | "thorough"
gpu_q4_enabled: bool = True
gpu_q5_enabled: bool = True
gpu_q6_enabled: bool = False
gpu_batch_size: int = 32
gpu_max_frames_per_video: int = 128
gpu_hash_type: str = "phash64"  # "phash64" | "dhash64"
gpu_decode_backend: str = "pynvcodec"  # future: "decord", "cpu"
```

## 9.2 Stage Selection

Keep user-facing `-q`.

Add internal routing:

```text
if stages include 4+ and gpu route available:
    Q4 -> Q4G
    Q5 -> Q5G
    Q6 -> Q6G if enabled/requested
else:
    existing CPU Q4/Q5/Q6/Q7
```

Optionally add:

```text
--visual-backend cpu|gpu|auto
```

If not desired yet, use `--gpu`.

## 9.3 Candidate Flow

Current safe flow:

```text
Q1 candidates -> Q2 verification
Q3 candidates -> Q4 verification
```

GPU flow:

```text
Q1 size candidates:
    Q2 exact hash only

Q3 metadata candidates:
    Q4G priority candidate pairs
    not evidence by themselves

Q4G:
    emits full perceptual duplicates
    emits visual candidates for Q5G

Q5G:
    emits full/subset/partial overlap groups
    rejects weak candidates

Q6G:
    only processes unresolved Q5G candidates
```

## 9.4 Do Not Let Q3 Exclude Q5G/Q6G

Do not reuse old `excluded_after_q3` semantics.

Q3 candidates should prioritize Q4G, but Q3 should not permanently remove a video from later content verification.

---

# 10. Caching

GPU extraction is expensive. Add cache before optimizing further.

## 10.1 Cache Key

Cache key should include:

```text
path
size
mtime_ns
duration
decoder backend
sampling profile
hash type
vdedup version or cache schema version
```

## 10.2 Cache Format

Initial simple cache:

```text
JSONL
```

Later better cache:

```text
SQLite
```

For now, JSONL is easier and consistent with existing repo style.

Cache record:

```json
{
    "schema_version": 1,
    "path": "...",
    "size": 123,
    "mtime_ns": 123456789,
    "backend": "pynvcodec",
    "sampling_profile": "balanced",
    "hash_type": "phash64",
    "duration_seconds": 123.4,
    "frames": [
        {
            "frame_index": 123,
            "timestamp_seconds": 4.1,
            "phash64": "0x1234abcd...",
            "entropy": 3.2,
            "mean_luma": 0.42,
            "valid_for_matching": true
        }
    ]
}
```

---

# 11. Performance Targets

Initial measurable goals:

```text
Q4G extraction:
    5x faster than CPU pHash path on RTX 5090 for sampled frames

GPU utilization:
    NVDEC active during extraction
    CUDA active during pHash batch computation

CPU utilization:
    CPU should remain available for file I/O, hashing, report generation

Accuracy:
    no Q1/Q3 candidate-only false positives become groups
    full re-encodes detected
    subset clips detected by Q5G
    intro/outro-only matches labeled REVIEW or rejected
```

Do not optimize until these metrics are recorded.

Add timing logs:

```text
videos/sec
frames decoded/sec
frames hashed/sec
candidate pairs generated
candidate pairs aligned
groups emitted by match_type
GPU backend used
fallback count
decode errors
cache hits/misses
```

---

# 12. Testing Plan

## 12.1 Unit Tests Without GPU

GPU code should have pure-Python testable units:

```text
sampling policy
hash packing/unpacking
Hamming distance
candidate pair generation
diagonal alignment
classification
report safety fields
```

These must run in normal CI without CUDA.

## 12.2 GPU Smoke Tests

Mark tests:

```python
@pytest.mark.gpu
```

Skip if CUDA/PyNvVideoCodec unavailable.

Tests:

```text
decode small mp4 on GPU
extract sampled frames
compute pHash64
cache and reload signature
Q4G emits no candidates for unrelated files
Q4G emits duplicate for exact visual duplicate
Q5G detects short clip inside long video
```

## 12.3 Synthetic Fixtures

Generate videos with ffmpeg:

```text
exact copy
re-encode
resolution change
bitrate change
container change
short subset from longer
subset with black padding
same intro different body
same outro different body
black frames only
same audio different video
cropped video
watermarked video
```

Expected results:

```text
exact copy:
    Q2 exact_byte_duplicate

re-encode:
    Q4G/Q5G perceptual_duplicate

short subset:
    Q5G subset_of_longer REVIEW

same intro different body:
    rejected or partial_overlap REVIEW, not full duplicate

same audio different video:
    no visual group; audio-only REVIEW/candidate only

cropped/watermarked:
    Q6G transformed duplicate/subset only if temporal alignment confirms
```

---

# 13. Implementation Phases

## Phase 1: Fix REVIEW Semantics

Files likely touched:

```text
report.py
report_models.py
report_viewer.py
video_dedupe.py
tests/q3_verification_test.py
tests/report_apply_test.py
```

Tasks:

```text
1. Keep candidate-only refusal.
2. Stop skipping review_required groups in apply_report.
3. Remove or deprecate -F behavior.
4. Make report viewer show all-caps REVIEW next to review_required groups.
5. Add tests proving REVIEW groups are applyable when actionable=true.
6. Add tests proving candidate-only groups are never applyable.
```

## Phase 2: GPU Capability Detection

Files:

```text
gpu_capabilities.py
tests/gpu_capabilities_test.py
```

Tasks:

```text
1. Detect torch.
2. Detect CUDA.
3. Detect PyNvVideoCodec.
4. Detect GPU name and memory.
5. Return structured capability object.
6. Add --gpu auto|on|off if desired.
```

## Phase 3: GPU Sampling and Decode

Files:

```text
gpu_sampling.py
gpu_decode.py
tests/gpu_sampling_test.py
```

Tasks:

```text
1. Implement deterministic frame index selection.
2. Implement PyNvVideoCodec SimpleDecoder wrapper.
3. Add CPU fallback wrapper.
4. Return CUDA tensors when GPU decode works.
5. Return structured decode errors.
```

## Phase 4: GPU pHash / dHash

Files:

```text
gpu_fingerprint.py
tests/gpu_fingerprint_test.py
```

Tasks:

```text
1. Implement batched grayscale conversion.
2. Implement batched resize.
3. Implement dHash64 first if needed.
4. Implement pHash64 via DCT matrix multiplication.
5. Add entropy/luma filtering.
6. Pack hashes into Python ints.
```

## Phase 5: Q4G Pipeline

Files:

```text
gpu_pipeline.py
gpu_index.py
pipeline.py
tests/gpu_pipeline_contract_test.py
```

Tasks:

```text
1. Extract VideoSignature for all eligible videos.
2. Build hash-band candidate index.
3. Generate candidate pairs.
4. Emit high-confidence full duplicates.
5. Forward uncertain candidates to Q5G.
6. Preserve report contract.
```

## Phase 6: Q5G Temporal Alignment

Files:

```text
gpu_alignment.py
tests/gpu_alignment_test.py
```

Tasks:

```text
1. Implement sparse frame match generation.
2. Implement offset voting.
3. Implement diagonal streak extraction.
4. Implement classification rules.
5. Emit TemporalAlignmentResult.
6. Convert results into report groups with evidence.
```

## Phase 7: Q6G Deep Embeddings

Files:

```text
gpu_embeddings.py
gpu_pipeline.py
tests/gpu_embeddings_test.py
```

Tasks:

```text
1. Add optional model loader.
2. Extract embeddings for candidate pairs only.
3. Reuse Q5G alignment over embedding similarity.
4. Emit groups only with temporal alignment.
5. Keep semantic-only matches as candidates/review.
```

---

# 14. Report Contract for GPU Groups

Every GPU group must include:

```json
{
    "method": "gpu-phash" ,
    "confidence": "verified",
    "review_required": false,
    "actionable": true,
    "match_type": "perceptual_duplicate",
    "evidence": {
        "backend": "gpu",
        "gpu_name": "NVIDIA GeForce RTX 5090",
        "verified_by": ["gpu_phash", "gpu_temporal_alignment"],
        "overlap_seconds": 123.4,
        "overlap_ratio_left": 0.99,
        "overlap_ratio_right": 0.98,
        "matched_frame_count": 80,
        "median_hamming_distance": 4,
        "low_entropy_fraction": 0.02
    }
}
```

Candidate-only GPU results:

```json
{
    "method": "gpu-phash-candidate",
    "candidate_only": true,
    "actionable": false,
    "review_required": true,
    "match_type": "visual_candidate",
    "members": ["a.mp4", "b.mp4"],
    "recommended_next_stage": "q5",
    "evidence": {
        "backend": "gpu",
        "candidate_score": 0.73
    }
}
```

---

# 15. Things Not To Do Yet

Do not start by integrating FAISS, cuVS, sqlite-vec, or a large vector DB.

Do not start by replacing every Q4+ stage.

Do not make CLIP global average embeddings deletion-safe.

Do not use metadata as evidence.

Do not let Q3 candidates exclude videos from later stages.

Do not optimize for maximum GPU utilization before correctness metrics exist.

Do not make Q6G semantic similarity apply-safe without temporal alignment.

---

# 16. First Milestone Definition of Done

Milestone 1 is complete when:

```text
1. REVIEW is display/report labeling only.
2. Candidate-only groups are still impossible to apply.
3. `--gpu auto|on|off` or equivalent config exists.
4. GPU capability detection works.
5. Q4G can decode sampled frames on GPU when available.
6. Q4G computes dHash64 or pHash64 on GPU.
7. Q4G emits high-confidence full visual duplicates.
8. Q5G detects a synthetic short clip inside a longer video.
9. Reports include backend/evidence/match_type/actionable/review_required.
10. CPU route still works unchanged when GPU is unavailable.
```

Suggested first implementation target:

```text
Implement Q4G + Q5G only.
Defer Q6G deep embeddings until pHash + temporal alignment is working and benchmarked.
```

```
::contentReference[oaicite:3]{index=3}
```

[1]: https://docs.nvidia.com/video-technologies/pynvvideocodec/pynvc-api-reference/index.html?utm_source=chatgpt.com "PyNvVideoCodec API Reference - NVIDIA Docs"

