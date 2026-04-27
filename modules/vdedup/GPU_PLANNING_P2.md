# vdedup Implementation Plan: Plan #2 — GPU Sampling + Decode + Fingerprint Extraction

## Scope

This plan assumes the following have already been implemented:

```text
0. Safety semantics cleanup
1. GPU capability/routing foundation
```

This plan implements:

```text
2. GPU sampling + decode + fingerprint extraction
```

This plan must **not** implement:

```text
3. Q4G coarse duplicate detection
4. Q5G temporal alignment
5. Q6G deep embeddings
```

In this plan, GPU code should be able to:

```text
1. Choose deterministic frame sample points for a video.
2. Decode those sampled frames using GPU decode when available.
3. Fall back to the existing CPU path when GPU decode is unavailable and --gpu auto is used.
4. Convert decoded frames into CUDA tensors where possible.
5. Compute compact frame fingerprints in batches.
6. Compute low-entropy / low-information frame stats.
7. Return structured VideoSignature / FrameSignature objects.
8. Optionally serialize and reload signatures from a simple cache.
```

This plan should **not** yet use the signatures to emit duplicate groups. It only creates the extraction substrate that later Q4G will consume.

---

## Design Goal

The goal is to introduce a new GPU-backed extraction path without disrupting the existing CPU-only route.

The final architecture after this plan should look like:

```text
scan command
    -> existing Q1/Q2/Q3
    -> if stages include Q4+:
        -> GPU capability already detected by Plan #1
        -> Plan #2 can extract GPU VideoSignature objects
        -> existing CPU Q4+ still remains the active detector until Plan #3
```

This means Plan #2 can expose functions and maybe a debug/developer path, but should not yet replace Q4.

---

## Core Principles

```text
1. CPU-only installs must continue to work.
2. GPU imports must be lazy.
3. PyNvVideoCodec and torch must not be imported at package import time.
4. GPU decode failures should be structured and recoverable in --gpu auto.
5. --gpu on should fail clearly if GPU extraction cannot run.
6. Sampling must be deterministic.
7. Fingerprinting must be deterministic for the same input frames.
8. Low-entropy frames must be marked invalid, not removed.
9. The output data model must be usable by future Q4G/Q5G.
10. No deletion/report grouping behavior should change in this plan.
```

---

# 1. New Files

Add the following files:

```text
modules/vdedup/gpu_sampling.py
modules/vdedup/gpu_decode.py
modules/vdedup/gpu_fingerprint.py
modules/vdedup/gpu_signature.py
modules/vdedup/gpu_cache.py
modules/vdedup/tests/gpu_sampling_test.py
modules/vdedup/tests/gpu_fingerprint_test.py
modules/vdedup/tests/gpu_signature_test.py
modules/vdedup/tests/gpu_decode_test.py
modules/vdedup/tests/gpu_cache_test.py
```

Optional if the repo prefers fewer files:

```text
gpu_signature.py and gpu_cache.py may be merged into gpu_fingerprint.py initially.
```

Preferred separation:

```text
gpu_sampling.py:
    deterministic sampling policy only

gpu_decode.py:
    PyNvVideoCodec wrapper and CPU fallback decode wrapper

gpu_fingerprint.py:
    tensor preprocessing, dHash64/pHash64, entropy/luma stats

gpu_signature.py:
    FrameSignature, VideoSignature, extraction orchestration

gpu_cache.py:
    simple JSONL or JSON cache for signatures
```

---

# 2. Data Models

## 2.1 Add `FrameSignature`

File:

```text
modules/vdedup/gpu_signature.py
```

Model:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


@dataclass(slots=True)
class FrameSignature:
    path: Path
    video_id: str
    frame_index: int
    timestamp_seconds: float
    phash64: Optional[int]
    dhash64: Optional[int]
    entropy: float
    mean_luma: float
    std_luma: float
    valid_for_matching: bool
    invalid_reason: Optional[str] = None

    def to_json_dict(self) -> Dict[str, object]:
        ...

    @classmethod
    def from_json_dict(cls, payload: Dict[str, object]) -> "FrameSignature":
        ...
```

Notes:

```text
phash64 may be None if only dHash is implemented first.
dhash64 may be None if pHash is implemented first.
At least one of phash64 or dhash64 should exist for a successfully processed valid frame.
Invalid frames can still have hashes, but should have valid_for_matching=false.
```

## 2.2 Add `VideoSignature`

File:

```text
modules/vdedup/gpu_signature.py
```

Model:

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass(slots=True)
class VideoSignature:
    path: Path
    video_id: str
    duration_seconds: Optional[float]
    sampled_frame_count: int
    valid_frame_count: int
    signatures: List[FrameSignature] = field(default_factory=list)
    extraction_backend: str = "unknown"
    sampling_profile: str = "balanced"
    hash_type: str = "phash64"
    decode_backend: str = "unknown"
    error: Optional[str] = None

    def to_json_dict(self) -> Dict[str, object]:
        ...

    @classmethod
    def from_json_dict(cls, payload: Dict[str, object]) -> "VideoSignature":
        ...
```

Recommended `video_id`:

```text
stable hash of normalized path + size + mtime_ns
```

For now, a helper can generate it:

```python
def make_video_id(path: Path) -> str:
    ...
```

Do not use the content hash as `video_id`; that would defeat the purpose and require full-file reading.

---

# 3. Sampling Policy

## 3.1 Add Sampling Model

File:

```text
modules/vdedup/gpu_sampling.py
```

Add:

```python
from dataclasses import dataclass
from typing import List, Optional


@dataclass(slots=True)
class SamplingPlan:
    frame_indices: List[int]
    timestamps_seconds: List[float]
    profile: str
    target_frame_count: int
    duration_seconds: Optional[float]
    fps: Optional[float]
    total_frames: Optional[int]
    exclude_edges_seconds: float
```

## 3.2 Add Sampling Profiles

Define profiles:

```python
SAMPLING_PROFILES = {
    "fast": {
        "target_frames": 32,
        "max_frames": 48,
        "exclude_edges_seconds": 2.0,
    },
    "balanced": {
        "target_frames": 96,
        "max_frames": 128,
        "exclude_edges_seconds": 3.0,
    },
    "thorough": {
        "target_frames": 192,
        "max_frames": 256,
        "exclude_edges_seconds": 3.0,
    },
}
```

Use `balanced` as default.

## 3.3 Sampling Rules

Implement:

```python
def build_sampling_plan(
    *,
    duration_seconds: Optional[float],
    fps: Optional[float],
    total_frames: Optional[int],
    profile: str = "balanced",
) -> SamplingPlan:
    ...
```

Rules:

```text
1. If total_frames and fps are known:
       choose frame indices directly.

2. If duration and fps are known:
       total_frames = round(duration * fps).

3. If duration is known but fps is unknown:
       generate timestamps only and leave frame_indices empty.

4. If neither duration nor total_frames are known:
       return an empty or minimal plan and let decoder/backend decide.
```

Deterministic frame selection:

```text
- Avoid first/last N seconds for videos longer than 60s.
- Do not exclude edges for very short videos if exclusion would remove too much content.
- Uniformly sample across the usable interval.
- Always sort and deduplicate frame indices/timestamps.
```

Edge exclusion rule:

```text
if duration_seconds is not None and duration_seconds > 60:
    start_time = exclude_edges_seconds
    end_time = duration_seconds - exclude_edges_seconds
else:
    start_time = 0
    end_time = duration_seconds
```

If usable interval becomes too small:

```text
fallback to full interval
```

## 3.4 Sampling Tests

File:

```text
modules/vdedup/tests/gpu_sampling_test.py
```

Required tests:

```text
test_sampling_plan_is_deterministic
test_sampling_plan_short_video_does_not_exclude_all_edges
test_sampling_plan_long_video_excludes_edges
test_sampling_plan_respects_max_frames
test_sampling_plan_sorted_unique_indices
test_sampling_plan_invalid_profile_raises
test_sampling_plan_duration_without_fps_returns_timestamps
test_sampling_plan_total_frames_without_duration_returns_indices
```

---

# 4. GPU Decode Wrapper

## 4.1 Decode Result Model

File:

```text
modules/vdedup/gpu_decode.py
```

Add:

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional


@dataclass(slots=True)
class DecodedFrameBatch:
    path: Path
    backend: str
    frames: Any
    frame_indices: List[int]
    timestamps_seconds: List[float]
    device: str
    color_format: str
    error: Optional[str] = None
```

`frames` should be:

```text
GPU route:
    torch.Tensor on CUDA, shape [N, C, H, W] or [N, H, W, C]

CPU fallback:
    torch.Tensor on CPU or list of PIL/numpy frames, but prefer torch.Tensor for shared fingerprint code
```

Preferred normalized output:

```text
torch.Tensor with shape [N, 3, H, W], dtype uint8 or float32
```

## 4.2 Lazy Import Helpers

Add:

```python
def _import_torch():
    ...

def _import_pynvcodec():
    ...
```

Do not import torch or PyNvVideoCodec at module import time.

## 4.3 GPU Decode Function

Add:

```python
def decode_sampled_frames_gpu(
    path: Path,
    sampling_plan: SamplingPlan,
    *,
    device_id: int = 0,
    output_rgb: bool = True,
) -> DecodedFrameBatch:
    ...
```

Implementation target:

```text
Use PyNvVideoCodec SimpleDecoder for sparse/random access.
Construct SimpleDecoder with:
    gpu_id=device_id
    use_device_memory=True
    output_color_type=RGBP if available
```

Important:

```text
PyNvVideoCodec APIs may vary slightly by installed version.
Use defensive getattr checks for OutputColorType.RGBP.
If RGBP is unavailable, decode native format and either:
    fail clearly for now
    or convert using available PyNvVideoCodec conversion API if straightforward
```

DLPack handoff:

```python
tensor = torch.from_dlpack(frame)
```

If frame comes as one frame at a time:

```text
collect tensors and stack into batch
```

If PyNvVideoCodec exposes batch frame retrieval returning frames:

```text
prefer batch API, but keep a simple per-frame fallback
```

## 4.4 CPU Fallback Decode Function

Add:

```python
def decode_sampled_frames_cpu(
    path: Path,
    sampling_plan: SamplingPlan,
) -> DecodedFrameBatch:
    ...
```

Use existing repo frame extraction utilities if available. If not, use the current CPU pHash extraction path rather than introducing a new heavy dependency.

Rules:

```text
Do not require OpenCV if the repo does not already require it.
Prefer existing ffmpeg/PIL helpers.
Return a torch.Tensor on CPU if torch is available.
If torch is unavailable, return a structured error unless CPU fingerprint path supports non-torch frames.
```

Because Plan #2 is GPU-focused, CPU fallback can be minimal as long as it does not break existing CPU route.

## 4.5 Unified Decode Function

Add:

```python
def decode_sampled_frames(
    path: Path,
    sampling_plan: SamplingPlan,
    *,
    gpu_mode: str,
    device_id: int,
    allow_cpu_fallback: bool,
) -> DecodedFrameBatch:
    ...
```

Rules:

```text
gpu_mode == "off":
    use CPU fallback

gpu_mode == "auto":
    try GPU decode
    if GPU decode fails:
        use CPU fallback
        include error/fallback reason in DecodedFrameBatch

gpu_mode == "on":
    try GPU decode
    if GPU decode fails:
        raise RuntimeError or return error depending existing style
```

## 4.6 Decode Tests

File:

```text
modules/vdedup/tests/gpu_decode_test.py
```

Most tests should not require a real GPU.

Required tests:

```text
test_decode_gpu_lazy_imports
test_decode_auto_falls_back_to_cpu_on_gpu_import_error
test_decode_on_raises_on_gpu_import_error
test_decode_off_uses_cpu_backend
test_decode_result_shape_contract_with_mock_frames
```

GPU smoke test:

```python
@pytest.mark.gpu
def test_decode_sample_video_on_gpu(...):
    ...
```

Skip if:

```text
torch unavailable
CUDA unavailable
PyNvVideoCodec unavailable
small fixture video unavailable
```

Do not make GPU smoke tests required for normal CI.

---

# 5. GPU Fingerprint Extraction

## 5.1 Fingerprint Batch Result

File:

```text
modules/vdedup/gpu_fingerprint.py
```

Add:

```python
from dataclasses import dataclass
from typing import List, Optional


@dataclass(slots=True)
class FingerprintBatch:
    phash64: List[Optional[int]]
    dhash64: List[Optional[int]]
    entropy: List[float]
    mean_luma: List[float]
    std_luma: List[float]
    valid_for_matching: List[bool]
    invalid_reasons: List[Optional[str]]
    backend: str
```

## 5.2 Tensor Normalization

Add:

```python
def normalize_frame_tensor(frames):
    ...
```

Input accepted:

```text
[N, H, W, C]
[N, C, H, W]
single frame variants if easy
uint8 or float32
CPU or CUDA tensor
```

Output:

```text
[N, 3, H, W]
float32
range [0, 1]
same device as input
```

Use PyTorch operations so CPU fallback and CUDA path share code.

## 5.3 Grayscale Conversion

Add:

```python
def rgb_to_luma(frames):
    ...
```

Formula:

```text
Y = 0.299 R + 0.587 G + 0.114 B
```

Output:

```text
[N, 1, H, W]
```

## 5.4 Low-Entropy Statistics

Add:

```python
def compute_frame_stats(luma) -> Tuple[mean_luma, std_luma, entropy]:
    ...
```

Initial entropy implementation:

```text
Use histogram with 32 or 64 bins per frame.
Compute Shannon entropy.
```

If efficient per-frame histograms are cumbersome in PyTorch, acceptable initial fallback:

```text
Use std_luma and mean_luma only for invalid filtering.
Set entropy = 0.0 or approximate entropy.
```

Preferred initial thresholds:

```python
DEFAULT_LOW_ENTROPY_CONFIG = {
    "min_mean_luma": 4.0 / 255.0,
    "max_mean_luma": 251.0 / 255.0,
    "min_std_luma": 2.0 / 255.0,
    "min_entropy": 1.0,
}
```

Invalid reasons:

```text
black_frame
white_frame
low_variance
low_entropy
```

## 5.5 dHash64 First

Implement dHash64 first because it is simpler and gives a complete Plan #2 quickly.

Add:

```python
def compute_dhash64(frames) -> List[int]:
    ...
```

Algorithm:

```text
1. normalize frames to [N, 3, H, W] float32
2. convert to luma [N, 1, H, W]
3. resize to [N, 1, 8, 9]
4. compare adjacent columns:
       bits = luma[:, :, :, :-1] > luma[:, :, :, 1:]
5. flatten 8x8 bits
6. pack into uint64 Python ints
```

Use:

```text
torch.nn.functional.interpolate
```

for resizing.

Packing can happen on CPU after moving only a tiny boolean tensor back:

```python
bits_cpu = bits.reshape(n, 64).to("cpu")
```

This transfer is tiny and acceptable.

## 5.6 pHash64 Target

Implement pHash64 in the same plan if feasible, but do not let it block dHash64.

Add:

```python
def compute_phash64(frames) -> List[int]:
    ...
```

Algorithm:

```text
1. normalize frames
2. convert to luma
3. resize to [N, 1, 32, 32]
4. compute 2D DCT using precomputed DCT basis matrix:
       coeff = D @ image @ D.T
5. take top-left 8x8 block
6. exclude DC coefficient if desired
7. threshold coefficients by median
8. pack 64 bits
```

DCT matrix helper:

```python
def create_dct_matrix(size: int, device, dtype) -> Tensor:
    ...
```

pHash bit choice:

```text
Option A:
    use 8x8 including DC = 64 bits

Option B:
    use 8x8 excluding DC and include next coefficient = 64 bits

Initial acceptable:
    use 8x8 including DC but document it

Better:
    exclude DC and use a stable 64-coefficient selection from low-frequency area
```

Given implementation simplicity, initial acceptable pHash:

```text
top-left 8x8
median over all 64 coefficients
pack 64 bits
```

The later Q4G threshold can be calibrated around this implementation.

## 5.7 Unified Fingerprint Function

Add:

```python
def compute_frame_fingerprints(
    frames,
    *,
    hash_type: str = "dhash64",
    low_entropy_config: Optional[Dict[str, float]] = None,
) -> FingerprintBatch:
    ...
```

Supported hash types:

```text
dhash64
phash64
both
```

For Plan #2, default can be:

```text
dhash64
```

But if pHash64 is implemented, default should be:

```text
phash64
```

## 5.8 Fingerprint Tests

File:

```text
modules/vdedup/tests/gpu_fingerprint_test.py
```

Required tests:

```text
test_normalize_frame_tensor_accepts_nchw_uint8
test_normalize_frame_tensor_accepts_nhwc_uint8
test_rgb_to_luma_shape
test_dhash64_returns_ints
test_dhash64_identical_frames_identical_hash
test_dhash64_different_frames_can_differ
test_low_entropy_black_frame_invalid
test_low_entropy_white_frame_invalid
test_low_variance_frame_invalid
test_fingerprint_batch_lengths_match_input_count
```

If pHash64 implemented:

```text
test_phash64_returns_ints
test_phash64_identical_frames_identical_hash
test_dct_matrix_shape
test_phash64_deterministic
```

CUDA optional test:

```python
@pytest.mark.gpu
def test_compute_fingerprint_on_cuda_tensor():
    ...
```

Skip if CUDA unavailable.

---

# 6. Signature Extraction Orchestration

## 6.1 Extract Function

File:

```text
modules/vdedup/gpu_signature.py
```

Add:

```python
def extract_video_signature(
    path: Path,
    *,
    duration_seconds: Optional[float],
    fps: Optional[float],
    total_frames: Optional[int],
    gpu_mode: str = "auto",
    device_id: int = 0,
    sampling_profile: str = "balanced",
    hash_type: str = "dhash64",
    allow_cpu_fallback: bool = True,
) -> VideoSignature:
    ...
```

Flow:

```text
1. Build SamplingPlan.
2. Decode sampled frames via decode_sampled_frames.
3. Compute fingerprints via compute_frame_fingerprints.
4. Build FrameSignature objects.
5. Build VideoSignature object.
6. Return VideoSignature, never groups.
```

If decode fails:

```text
return VideoSignature(error=...)
```

or raise if existing project style prefers raising. For pipeline use, structured error is preferred.

## 6.2 Metadata Inputs

This function should accept duration/fps/total_frames from the existing `VideoMeta` if available.

Do not run ffprobe inside this function if the pipeline already has metadata.

Optional helper:

```python
def extract_video_signature_from_meta(
    video_meta: VideoMeta,
    *,
    cfg: PipelineConfig,
) -> VideoSignature:
    ...
```

Be careful importing `VideoMeta` to avoid circular imports.

## 6.3 Signature Tests

File:

```text
modules/vdedup/tests/gpu_signature_test.py
```

Use monkeypatch to mock decode and fingerprint functions.

Required tests:

```text
test_extract_video_signature_builds_sampling_plan
test_extract_video_signature_returns_expected_frame_signatures
test_extract_video_signature_counts_valid_frames
test_extract_video_signature_records_backend
test_extract_video_signature_records_error_on_decode_failure
test_video_signature_json_round_trip
test_frame_signature_json_round_trip
```

---

# 7. Simple Cache

## 7.1 Cache Key

File:

```text
modules/vdedup/gpu_cache.py
```

Add:

```python
@dataclass(slots=True)
class SignatureCacheKey:
    path: Path
    size_bytes: int
    mtime_ns: int
    sampling_profile: str
    hash_type: str
    decode_backend: str
    schema_version: int = 1
```

Helper:

```python
def make_signature_cache_key(
    path: Path,
    *,
    sampling_profile: str,
    hash_type: str,
    decode_backend: str,
) -> str:
    ...
```

Suggested key:

```text
sha256 of:
    resolved path string
    size_bytes
    mtime_ns
    sampling_profile
    hash_type
    decode_backend
    schema_version
```

## 7.2 Cache Store

Use JSON files or JSONL.

Simplest:

```text
cache_dir/
    <cache_key>.json
```

Add:

```python
class SignatureCache:
    def __init__(self, cache_dir: Path) -> None:
        ...

    def get(self, key: str) -> Optional[VideoSignature]:
        ...

    def put(self, key: str, signature: VideoSignature) -> None:
        ...
```

Atomic write:

```text
write temp file
replace target
```

## 7.3 Cache Tests

File:

```text
modules/vdedup/tests/gpu_cache_test.py
```

Required tests:

```text
test_cache_key_changes_when_mtime_changes
test_cache_key_changes_when_hash_type_changes
test_cache_put_get_round_trip
test_cache_missing_returns_none
test_cache_corrupt_entry_returns_none_or_raises_clear_error
```

---

# 8. Pipeline Integration for Plan #2

This plan should integrate minimally.

## 8.1 PipelineConfig Additions

If not already present from Plan #1, add only what is needed:

```python
gpu_sampling_profile: str = "balanced"
gpu_hash_type: str = "dhash64"
gpu_signature_cache_dir: Optional[Path] = None
```

If Plan #1 intentionally kept config minimal, add these now.

Do not add Q4G thresholds yet.

## 8.2 CLI Additions

Likely file:

```text
modules/vdedup/video_dedupe.py
```

Add optional scan args:

```text
--gpu-sampling-profile {fast,balanced,thorough}
-s maybe only if free; otherwise no short flag

--gpu-hash-type {dhash64,phash64,both}
-H if free

--gpu-signature-cache PATH
-C if free
```

Given CLI flag constraints and collision risk, it is acceptable to add only long flags if short flags conflict. If adding short flags, ensure they do not conflict with existing CLI args.

Recommended:

```text
--gpu-sampling-profile
--gpu-hash-type
--gpu-signature-cache
```

No short flags unless obvious and free.

## 8.3 Developer/Debug Extraction Path

Do not replace Q4 yet.

Options:

### Option A: Internal only

Plan #2 functions are called only by tests. No CLI behavior changes beyond flags/config.

### Option B: Add hidden/debug CLI

Add a developer command:

```text
video-dedupe debug-signature <video-path> --gpu auto --gpu-hash-type dhash64
```

Only do this if consistent with existing CLI style.

### Option C: Log-only dry integration

If selected stages include Q4+ and GPU route is available, extract signatures for a small limited set only when a debug flag is enabled.

Recommended for this plan:

```text
Option A: internal only.
```

Then Plan #3 will consume these functions.

## 8.4 Do Not Change Detection Output

After Plan #2:

```text
Running normal scans should produce the same duplicate groups as before.
```

Only differences allowed:

```text
new CLI args accepted
new logs about GPU capability/config
new tests
```

---

# 9. Error Handling

Define clear exceptions:

```python
class GpuDecodeError(RuntimeError):
    ...

class GpuFingerprintError(RuntimeError):
    ...

class SignatureExtractionError(RuntimeError):
    ...
```

Use exceptions internally, but return structured errors from top-level extraction if that is more pipeline-friendly.

Recommended:

```text
low-level decode/fingerprint functions raise clear exceptions
extract_video_signature catches and stores error unless gpu_mode == "on"
```

For `--gpu on`:

```text
failure should be loud
```

For `--gpu auto`:

```text
fallback or structured error should be used
```

---

# 10. Performance Logging Hooks

Do not overbuild metrics, but add simple timing data where easy.

Add optional result fields or log payload:

```text
decode_seconds
fingerprint_seconds
frame_count
backend
device
```

If adding fields to `VideoSignature` feels too intrusive, just return them in debug logs later.

Do not let performance logging complicate correctness.

---

# 11. Acceptance Criteria

Plan #2 is complete when:

```text
1. CPU-only import still works without torch or PyNvVideoCodec.
2. Sampling plan generation is deterministic and tested.
3. GPU decode wrapper exists with lazy PyNvVideoCodec import.
4. CPU fallback wrapper exists or gracefully reports unavailable fallback.
5. Frame tensor normalization works for NCHW and NHWC.
6. dHash64 is implemented and tested.
7. pHash64 is implemented if feasible; otherwise explicit TODO remains.
8. Low-information frames are marked invalid with reasons.
9. FrameSignature and VideoSignature round-trip through JSON.
10. Signature extraction orchestration returns VideoSignature objects.
11. Cache put/get works if cache is implemented in this plan.
12. Normal vdedup scan behavior is unchanged.
13. No duplicate groups are emitted by this new GPU signature code yet.
```

Minimum acceptable Plan #2 if time is limited:

```text
- gpu_sampling.py
- gpu_decode.py with lazy import and mocked tests
- gpu_fingerprint.py with dHash64
- gpu_signature.py with VideoSignature extraction
- unit tests for all pure logic
```

Defer to later if necessary:

```text
- pHash64
- cache
- debug CLI command
```

---

# 12. Suggested Claude Code Plan Mode Prompt

Use this prompt:

```text
Enter Plan Mode.

Use this document as the implementation spec for Plan #2 only.

Assume Plan 0 and Plan 1 have already been implemented:
- REVIEW is a label/warning, not an apply gate.
- Candidate-only groups are never applyable.
- GPU capability/routing foundation exists.

Do not edit files yet.

Inspect the current repo files relevant to:
- PipelineConfig and scan CLI args
- GPU capability module from Plan #1
- existing video metadata models
- existing CPU pHash / frame extraction utilities
- existing cache conventions
- existing tests and pytest style

Generate a repo-local implementation plan for GPU sampling + decode + fingerprint extraction.

The plan must include:
1. exact files to create/modify
2. exact public functions/classes to add
3. how lazy imports will preserve CPU-only installs
4. how sampling plans will be deterministic
5. how GPU decode will use PyNvVideoCodec when available
6. how CPU fallback will behave
7. how dHash64 and optionally pHash64 will be computed
8. how low-entropy frames will be marked invalid
9. how VideoSignature / FrameSignature JSON round-tripping will work
10. tests to add/update
11. risks and implementation uncertainties

Do not plan Q4G duplicate detection.
Do not plan Q5G temporal alignment.
Do not plan Q6G embeddings.
Do not change report/apply behavior.
Stop after producing the plan. Wait for approval before editing.
```

After approving the repo-local plan, use:

```text
Switch to implementation mode.

Implement the approved Plan #2 only.
Run the targeted tests:
- gpu_sampling_test.py
- gpu_fingerprint_test.py
- gpu_signature_test.py
- gpu_decode_test.py
- gpu_cache_test.py if cache is implemented

Do not start Q4G duplicate detection.
Do not alter existing scan output semantics.
```

---

# 13. Notes for Future Plan #3

Plan #3 will consume `VideoSignature` objects and implement:

```text
Q4G coarse duplicate detection
hash-band candidate indexing
full-video visual duplicate grouping
visual candidate forwarding to Q5G
```

Therefore, Plan #2 should focus on making the signature extraction API clean and testable.

The most important future-facing API is:

```python
def extract_video_signature(...) -> VideoSignature:
    ...
```

If that API is correct, Plan #3 becomes much easier.
