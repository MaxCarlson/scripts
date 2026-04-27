# GPU Plan 2 Handoff — vdedup GPU Sampling, Decode, and Fingerprint Extraction

## Your Job

Implement **Plan 2: GPU frame sampling, decode, and fingerprint extraction** for the `vdedup` module.

This is a focused, self-contained implementation task. Do **not** implement Q4G duplicate detection, Q5G temporal alignment, Q6G embeddings, or any pipeline integration beyond a detection stub. Your job ends when GPU signatures can be extracted and cached reliably, independently of the existing CPU detection pipeline.

All tests must pass (`285 passed` baseline) when you are done.

---

## Repository Location

```
c:\Users\mcarls\src\scripts\modules\vdedup\
```

This is a Python package installed as `vdedup`. The entry point CLI is `video_dedupe.py` (not inside the `vdedup/` package dir — it's a sibling module, `py-modules = ["video_dedupe"]` in pyproject.toml).

---

## Current Test Baseline

```
285 passed, 1-2 skipped, 1 warning
```

Run tests from the module root:
```bash
cd modules/vdedup
pytest --tb=short -q
```

The 1 warning is a PyNvVideoCodec `ast.Str` deprecation — not from this codebase. Ignore it.

---

## What Has Already Been Done (Do Not Redo)

### Completed in prior sessions

**Safety refactor (Q1/Q3 candidate split):**
- Q1 standalone emits `size_candidate:*` into `GroupResults.candidate_groups` (not verified groups)
- Q3 standalone emits `meta_candidate:*` into `GroupResults.candidate_groups`
- `GroupResults` has `.candidate_groups: Dict[str, List[VideoMeta]]` and `.candidate_metadata`
- Report JSON has top-level `"candidate_groups"` and `"groups"` as separate keys
- `apply_report()` refuses `candidate_only=True` groups unconditionally
- `apply_report()` applies `review_required=True` groups with a warning (REVIEW is a label, not a gate)
- `-F/--force-review-required` flag is deprecated no-op
- `DuplicateGroup` has `.actionable`, `.match_type`, `.review_required`, `.confidence`
- `CandidateGroup` dataclass has `.members` list (no keep/losers)
- Report viewer (`render_reports_to_text`) shows `[SAFE]`/`[REVIEW]`/`[CANDIDATE]` labels

**GPU foundation (Plan 1):**
- `gpu_capabilities.py` — `GpuCapabilities` dataclass + `detect_gpu_capabilities()` with lazy imports
- `validate_gpu_mode()` — normalises `auto/on/off` with aliases
- `-g/--gpu {auto,on,off}` on `scan` subcommand (not `store_true` bool anymore)
- `--gpu-device-id` arg on `scan` subcommand (default 0)
- `PipelineConfig` has `gpu_mode: str = "auto"` and `gpu_device_id: int = 0`
- `run_pipeline()` runs `detect_gpu_capabilities()` before Q4+ stages and logs result
- On `--gpu on` with no GPU: raises `RuntimeError`
- Existing CPU Q4+ algorithm is untouched — GPU detection only logs, does not change behavior yet

---

## Existing Relevant Modules You Must Understand

### `phash.py` — existing CPU fingerprint module
Key classes already present:
```python
@dataclass(frozen=True)
class FrameHash:
    timestamp: float
    index: int
    phash: int        # 64-bit perceptual hash as integer

@dataclass(frozen=True)
class VideoFingerprint:
    path: Path
    duration: float
    frames: Tuple[FrameHash, ...]
    def get_phash_tuple(self) -> Tuple[int, ...]: ...  # backward compat

class AdaptiveSamplingParams(NamedTuple):
    sampling_interval: float
    min_frames: int
    max_frames: int

def adaptive_sampling_params(duration: float, mode: str = "balanced") -> AdaptiveSamplingParams: ...
def compute_video_fingerprint(path: Path, mode: str = "balanced") -> Optional[VideoFingerprint]: ...
def compute_phash_signature(path: Path, frames: int = 5, gpu: bool = False) -> Optional[Tuple[int, ...]]: ...
def phash_distance(sig_a, sig_b) -> int: ...
```

`compute_video_fingerprint` is the existing CPU path. It uses ffmpeg subprocess to extract frames as PNGs, then PIL + imagehash to compute pHash. The new GPU path should produce compatible `VideoFingerprint` objects or a new `GpuVideoSignature` type.

### `phash_index.py` — existing index for pHash lookup
```python
class PHashIndex:
    def add(self, video_id: str, fingerprint: VideoFingerprint) -> None: ...
    def search(self, query: VideoFingerprint, threshold: int = 10) -> List[Tuple[str, float]]: ...
```

### `sequence_matcher.py` — existing diagonal streak matching
Used by Q7 conceptually. Already has diagonal-streak overlap detection logic.

### `models.py` — core data types
```python
@dataclass(frozen=True)
class FileMeta:
    path: Path; size: int; mtime: float; sha256: Optional[str]; ...

@dataclass(frozen=True)
class VideoMeta(FileMeta):
    duration: Optional[float]; width: Optional[int]; height: Optional[int]
    container: Optional[str]; vcodec: Optional[str]; acodec: Optional[str]
    overall_bitrate: Optional[int]; video_bitrate: Optional[int]
    phash_signature: Optional[Tuple[int, ...]]  # existing CPU pHash storage
    resolution_area: int  # property = width * height
```

### `pipeline.py` — stage orchestrator
`PipelineConfig` current fields (relevant subset):
```python
@dataclass
class PipelineConfig:
    threads: int = 8
    phash_frames: int = 5
    phash_threshold: int = 12
    gpu: bool = False            # set True by run_pipeline if GPU available
    gpu_mode: str = "auto"       # "auto"|"on"|"off"
    gpu_device_id: int = 0
    sample_ratio: Optional[float] = None
    sample_seed: Optional[int] = None
    ...
```

`GroupResults` class:
```python
class GroupResults(dict):
    metadata: Dict[str, Dict[str, Any]]
    candidate_groups: Dict[str, List[VideoMeta]]
    candidate_metadata: Dict[str, Dict[str, Any]]
```

### `gpu_capabilities.py` — what you already have
```python
@dataclass(slots=True)
class GpuCapabilities:
    requested_mode: str
    gpu_available: bool
    route_enabled: bool
    torch_available: bool
    cuda_available: bool
    pynvcodec_available: bool
    device_id: int
    device_name: Optional[str]
    compute_capability: Optional[Tuple[int, int]]
    free_vram_bytes: Optional[int]
    total_vram_bytes: Optional[int]
    reason_unavailable: Optional[str]

def detect_gpu_capabilities(requested_mode, device_id, require_pynvcodec) -> GpuCapabilities: ...
def validate_gpu_mode(value: str) -> str: ...
```

### `cache.py` — existing JSONL hash cache
The existing `HashCache` stores per-file hash fields keyed by `(path, size, mtime)`. You may build on this pattern for GPU signature caching or write a new JSONL cache following the same conventions.

---

## What You Must Implement (Plan 2)

### New files to create

```
modules/vdedup/gpu_sampling.py       — deterministic frame index selection
modules/vdedup/gpu_decode.py         — PyNvVideoCodec decode wrapper + CPU fallback
modules/vdedup/gpu_fingerprint.py    — batched GPU pHash/dHash + entropy/luma filtering
modules/vdedup/tests/gpu_sampling_test.py
modules/vdedup/tests/gpu_decode_test.py
modules/vdedup/tests/gpu_fingerprint_test.py
```

Optionally (if scope permits):
```
modules/vdedup/gpu_signature_cache.py  — JSONL cache for VideoSignature objects
```

### Data models to add

Add to `models.py` (or to a new `gpu_models.py` if you prefer isolation):

```python
@dataclass(slots=True)
class FrameSignature:
    path: Path
    video_id: str           # canonical str(path)
    frame_index: int        # index in sampled sequence
    timestamp_seconds: float
    phash64: int            # 64-bit pHash
    entropy: float
    mean_luma: float
    valid_for_matching: bool  # False for black/blank/low-entropy frames

@dataclass(slots=True)
class VideoSignature:
    path: Path
    video_id: str
    duration_seconds: Optional[float]
    sampled_frame_count: int        # total frames attempted
    valid_frame_count: int          # frames where valid_for_matching=True
    signatures: List[FrameSignature]
    extraction_backend: str         # "gpu_pynvcodec" | "cpu_ffmpeg"
    sampling_profile: str           # "fast" | "balanced" | "thorough"
```

`VideoSignature` is the GPU equivalent of `VideoFingerprint`. Both can coexist. The existing CPU pipeline uses `VideoFingerprint`; the GPU pipeline uses `VideoSignature`.

### `gpu_sampling.py` — frame index selection

Purpose: given a video duration and sampling profile, return the list of frame timestamps (or indices) to extract. Must be deterministic (same inputs → same outputs).

```python
PROFILES = {
    "fast":      {"target_frames": 24},
    "balanced":  {"target_frames": 64},
    "thorough":  {"target_frames": 128},
}

def select_frame_timestamps(
    duration_seconds: float,
    profile: str = "balanced",
    avoid_first_seconds: float = 3.0,
    avoid_last_seconds: float = 3.0,
) -> List[float]:
    """
    Return sorted list of timestamp positions (seconds) to sample.
    For videos > 60s, skips the first/last N seconds for coarse scoring
    (those frames are still in raw signatures for debugging/evidence).
    """
```

Rules from the spec:
- `duration <= 60s`: sample every 1s, cap at `target_frames`
- `60s < duration <= 10min`: sample every 2s, cap at `target_frames`
- `duration > 10min`: sample uniformly up to `target_frames`
- For videos > 60s, avoid first/last 3s in the *valid_for_matching* flag (still extract the frames)
- Must be deterministic — no randomness

### `gpu_decode.py` — decoder backend

Purpose: decode video frames at specific timestamps and return them as tensors (GPU) or numpy arrays (CPU fallback).

```python
def decode_frames_at_timestamps(
    path: Path,
    timestamps: List[float],
    device_id: int = 0,
    use_gpu: bool = True,
) -> List[Any]:
    """
    Decode frames at the given timestamps.
    Returns list of CHW RGB tensors (torch.Tensor on CUDA) when use_gpu=True and PyNvVideoCodec available.
    Returns list of HWC uint8 numpy arrays when use_gpu=False or fallback triggered.
    Returns empty list on unrecoverable error.
    """
```

Decoder selection logic:
1. If `use_gpu=True` and PyNvVideoCodec is importable: use `PyNvVideoCodec.SimpleDecoder` with `use_device_memory=True`
2. Otherwise: CPU fallback using ffmpeg subprocess (same approach as existing `phash.py`)

CPU fallback must not crash the whole scan if one video fails decode. Wrap in try/except, log the error, return empty list for that video.

**PyNvVideoCodec usage pattern** (for your reference):
```python
import PyNvVideoCodec as nvc
decoder = nvc.SimpleDecoder(str(path), gpu_id=device_id)
# seek to timestamp and decode
```

The frames returned by PyNvVideoCodec implement `__dlpack__` so they can be converted to PyTorch tensors:
```python
import torch
frame_tensor = torch.from_dlpack(frame)   # zero-copy, stays on GPU
```

### `gpu_fingerprint.py` — batched pHash + filtering

Purpose: take decoded frames (tensors or numpy arrays), compute 64-bit pHash signatures, and filter low-quality frames.

```python
def compute_phash64_batch(
    frames: List[Any],   # list of CHW tensors or HWC numpy arrays
    use_gpu: bool = True,
) -> List[int]:
    """
    Compute 64-bit pHash for each frame. Returns list of ints same length as input.
    """

def compute_frame_quality(
    frames: List[Any],
    use_gpu: bool = True,
) -> List[Tuple[float, float]]:
    """
    Returns list of (entropy, mean_luma) for each frame.
    """

def is_valid_for_matching(entropy: float, mean_luma: float) -> bool:
    """
    Returns False for black/blank/low-entropy frames.
    Thresholds (configurable):
        mean_luma < 4/255  → invalid (nearly black)
        std_luma < 2/255   → invalid (nearly flat)
        entropy < 1.0      → invalid
    """
```

**GPU pHash implementation** (DCT-based, Torch):
```python
# Resize to 32x32, grayscale, DCT via matrix multiply, threshold top-left 8x8 coefficients
D = _precompute_dct_matrix(32, device="cuda")
gray = rgb_to_gray(frame_32x32)            # (N, 32, 32)
coeff = D @ gray @ D.T                     # (N, 32, 32)
low_freq = coeff[:, :8, :8]               # top-left 8x8 excluding DC
bits = (low_freq > low_freq.median())      # threshold by median
phash = pack_bits_to_int64(bits)           # → int
```

**CPU fallback**: use existing `imagehash.phash()` from `phash.py` (PIL-based).

### Top-level extraction function

Add to `gpu_fingerprint.py`:
```python
def extract_video_signature(
    path: Path,
    profile: str = "balanced",
    device_id: int = 0,
    use_gpu: bool = True,
) -> Optional[VideoSignature]:
    """
    Main entry point: sample frame timestamps → decode → compute pHash + quality.
    Returns None if the video cannot be decoded at all.
    """
```

### Optional: `gpu_signature_cache.py`

JSONL cache following the same pattern as `cache.py`. Cache key: `(path, size, mtime_ns, profile, backend)`.

Cache record shape:
```json
{
    "schema_version": 1,
    "path": "/abs/path/to/video.mp4",
    "size": 123456789,
    "mtime_ns": 1714000000000000000,
    "backend": "gpu_pynvcodec",
    "profile": "balanced",
    "duration_seconds": 123.4,
    "frames": [
        {"frame_index": 0, "timestamp_seconds": 1.5, "phash64": 12345678901234,
         "entropy": 3.2, "mean_luma": 0.42, "valid_for_matching": true},
        ...
    ]
}
```

---

## Coding Conventions for This Repository

1. **Short + long flags**: CLI args must always have `-x` short form and `--long-form` long form.
2. **Test file naming**: `*_test.py` suffix (e.g. `gpu_sampling_test.py`), not `test_*.py`.
3. **Imports**: absolute imports (`from vdedup.module import X`). CPU-only installs must never fail at import time due to `torch` or `PyNvVideoCodec` being absent — use lazy imports inside functions.
4. **No top-level GPU imports**: `import torch` and `import PyNvVideoCodec` must only appear inside functions, wrapped in `try/except ImportError`.
5. **Type hints**: use them everywhere. `from __future__ import annotations` at the top of every file.
6. **Dataclasses**: prefer `@dataclass(slots=True)` for new data types (matches existing `GpuCapabilities`, `CandidateGroup` style).
7. **Line length**: 120 chars (black-formatted).
8. **No comments unless the WHY is non-obvious**: don't add comments explaining WHAT the code does.
9. **conftest.py**: `modules/vdedup/tests/conftest.py` patches the temp directory to stay inside the repo to avoid Windows ACL issues — all tests that need files should use `tmp_path` pytest fixture and this will be handled automatically.
10. **pyproject.toml**: test runner config is `pytest` with `testpaths = ["tests"]`. Do not add `real_media_test.py` to the run (it's already excluded by convention, not by config).

---

## Test Patterns

All tests in this codebase use monkeypatching for expensive operations. GPU tests must:
1. Not require CUDA to run (mock torch and PyNvVideoCodec).
2. Use `@pytest.mark.gpu` mark if they do require a real GPU (these will be skipped in CI).
3. Test the pure-Python logic (sampling calculations, hash packing, quality thresholds) without mocking.

Example pattern from existing `gpu_capabilities_test.py`:
```python
def test_auto_all_available():
    torch_mock = _make_torch_mock(cuda_available=True, device_name="NVIDIA RTX 5090")
    pynvc_mock = MagicMock()
    with patch.dict(sys.modules, {"torch": torch_mock, "PyNvVideoCodec": pynvc_mock}):
        caps = detect_gpu_capabilities("auto")
    assert caps.route_enabled is True
```

The `sys.modules` patch approach is necessary because `gpu_capabilities.py` uses lazy imports — you must patch `sys.modules` BEFORE the lazy import fires.

---

## pyproject.toml Dependencies

Current optional GPU extras (already in `pyproject.toml`):
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

These are already defined. Do not add `torch` to base `dependencies` — it must stay optional.

---

## Current Module File Map

```
modules/vdedup/
├── __init__.py
├── audio.py                    — Q6 audio fingerprinting
├── cache.py                    — JSONL hash cache (HashCache class)
├── gpu_capabilities.py         — GPU detection (DONE — do not modify)
├── grouping.py                 — choose_winners() keep/loser selection
├── hashers.py                  — hash utilities
├── models.py                   — FileMeta, VideoMeta (add FrameSignature, VideoSignature here)
├── phash.py                    — CPU pHash: FrameHash, VideoFingerprint, compute_video_fingerprint
├── phash_index.py              — PHashIndex for fast lookup
├── pipeline.py                 — run_pipeline(), PipelineConfig, GroupResults
├── probe.py                    — ffprobe wrappers (run_ffprobe_json, probe_video)
├── progress.py                 — ProgressReporter (live UI)
├── report.py                   — write_report, apply_report, pretty_print_reports
├── report_models.py            — DuplicateGroup, CandidateGroup, ReportDocument
├── report_viewer.py            — render_reports_to_text (TUI viewer)
├── scoring.py                  — ScoreCard, score_metadata_candidate, score_subset_candidate
├── sequence_matcher.py         — diagonal streak overlap matching
├── video_dedupe.py             — CLI entry point (main, parse_args)
│
├── gpu_sampling.py             ← YOU CREATE THIS
├── gpu_decode.py               ← YOU CREATE THIS
├── gpu_fingerprint.py          ← YOU CREATE THIS
├── gpu_signature_cache.py      ← YOU CREATE THIS (optional)
│
└── tests/
    ├── conftest.py             — temp dir patching (Windows-safe)
    ├── gpu_capabilities_test.py — GPU detection tests (DONE)
    ├── gpu_sampling_test.py    ← YOU CREATE THIS
    ├── gpu_decode_test.py      ← YOU CREATE THIS
    ├── gpu_fingerprint_test.py ← YOU CREATE THIS
    └── ... (many existing test files — do not break them)
```

---

## Report JSON Contract (Must Be Preserved)

Any groups emitted by GPU code must follow this schema. This is already enforced by `write_report()`:

```json
{
  "group_id": {
    "keep": "/abs/path/to/winner.mp4",
    "losers": ["/abs/path/to/loser.mp4"],
    "method": "gpu-phash",
    "confidence": "verified",
    "review_required": false,
    "actionable": true,
    "match_type": "perceptual_duplicate",
    "evidence": {
      "backend": "gpu",
      "verified_by": ["gpu_phash"],
      "extraction_profile": "balanced"
    },
    "keep_meta": {"size": 0, "duration": null, ...},
    "loser_meta": {"/abs/path/to/loser.mp4": {...}}
  }
}
```

For candidate-only GPU results (e.g. visual candidates pending temporal alignment):
```json
{
  "candidate_id": {
    "method": "gpu-phash-candidate",
    "candidate_only": true,
    "actionable": false,
    "review_required": true,
    "match_type": "visual_candidate",
    "members": ["/abs/path/a.mp4", "/abs/path/b.mp4"],
    "recommended_next_stage": "q5g",
    "evidence": {"backend": "gpu", "candidate_score": 0.73}
  }
}
```

---

## What Plan 2 Must NOT Do

- Do not implement Q4G duplicate detection or candidate pair generation — that is Plan 3.
- Do not modify the existing CPU Q4/Q5/Q6/Q7 pipeline logic in `pipeline.py`.
- Do not add Q4G stage routing to `run_pipeline()` — Plan 2 is infrastructure only.
- Do not implement Q5G temporal alignment or Q6G embeddings — those are Plans 4 and 5.
- Do not make GPU extras mandatory in base `dependencies`.
- Do not change the existing `phash.py` CPU path — it must continue to work.

---

## Acceptance Criteria for Plan 2

```
1. CPU-only install imports all new modules without error (torch/PyNvVideoCodec absent → no crash).
2. select_frame_timestamps() is deterministic and respects all three profiles.
3. decode_frames_at_timestamps() returns tensors on GPU when available, numpy arrays on CPU.
4. Single-video decode failure is caught and returns empty list (does not abort scan).
5. compute_phash64_batch() produces 64-bit integers compatible with existing phash_distance().
6. is_valid_for_matching() correctly rejects black/blank/low-entropy frames.
7. extract_video_signature() returns a VideoSignature for any decodable video.
8. All new tests pass without CUDA via monkeypatching.
9. Full test suite still passes (285+ tests, 0 failures).
10. If gpu_signature_cache.py is implemented: serialise/deserialise round-trip works correctly.
```

---

## Hardware Context

The user has an **RTX 5090** (Blackwell architecture, 32 GB GDDR7). PyNvVideoCodec supports Blackwell. NVDEC on Blackwell has increased H.264 throughput. The 32 GB VRAM is more than enough for aggressive batched frame extraction. Optimise for batched throughput, not single-frame latency.

---

## Summary of Recent Changes (Session History)

| Session | What Changed |
|---|---|
| Session 1 | Added subcommands `scan`/`view`/`apply` to CLI; replaced flat argparse with subparsers |
| Session 2 | Fixed Q3 false positives: Q3 standalone → `candidate_groups` only; Q4 Pass 1 verifies Q3 candidates via pHash; `_annotate_group()` annotates every group with `match_type`/`actionable`/`review_required` |
| Session 3 | Full candidate/verified split: `CandidateGroup`, `DuplicateGroup.actionable`, `DuplicateGroup.match_type`, `candidate_groups` top-level JSON, `apply_report` hard-refuses candidates, Q1 demoted to candidate output |
| Session 4 | Safety semantics cleanup (Plan 0): REVIEW is label+warning only, not apply gate; `-F` deprecated to no-op; viewer labels `[SAFE]`/`[REVIEW]`/`[CANDIDATE]`; `pretty_print_reports` section separation |
| Session 4 | GPU foundation (Plan 1): `gpu_capabilities.py`, `-g auto/on/off`, `PipelineConfig.gpu_mode/gpu_device_id`, capability detection + logging in `run_pipeline` |
