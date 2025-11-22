# vdedup Implementation Status & Roadmap

## Overview

This document tracks the implementation status of the comprehensive video deduplication improvements outlined in `DETAILED_RESEARCH.md` and `DETAILED_RESEARCH_PLAN.md`.

**Goal**: Upgrade vdedup to detect full and partial duplicates (≥10% overlap), scale to 6TB+ datasets, and provide configurable speed/accuracy trade-offs using only open-source tools.

---

## Phase 0: Foundations & Definitions ✅ COMPLETE

### Duplicate Semantics Defined

1. **Exact Duplicate**: Byte-for-byte identical (same SHA/BLAKE3)
2. **Visual Duplicate**: Same content, different resolution/codec/encoding
3. **Partial/Subset Duplicate**: ≥10% contiguous segment overlap
4. **Overlap Threshold**: Ignore common intros/outros < 10% of longer video

**Status**: ✅ Documented in research materials

---

## Phase 1: Fix & Harden Existing Stages (Q1-Q3)

### 1.1 Q1 Size Stage - Correct Logic ✅ COMPLETE

**Problem Identified**:
- Q1 was eliminating files with unique sizes
- Missed 70%+ of duplicates (different encodings/resolutions have different sizes)
- Visual duplicates, clips, and re-encodes were all incorrectly excluded

**Solution Implemented** (2025-01-XX):
- Q1 is now **optimization hint only** - NO elimination
- ALL files in `all_candidates = metas` continue to Q2/Q3/Q4
- Smart ordering: size-matched files processed first for faster exact-dup detection
- Added logging: "X files in size-matched groups", "Y unique-sized files continue"

**Files Modified**:
- `pipeline.py:599-721` - Q1 logic completely rewritten
- `EXPLAINED.md:52-94` - Documentation updated
- Core Philosophy section updated

**Impact**:
- ✅ Detects different encodings (h264 vs h265)
- ✅ Detects different resolutions (1080p vs 720p)
- ✅ Detects clips/subsets (different sizes)
- ✅ Detects different bitrates
- **Estimated 2-3x improvement in duplicate detection**

---

### 1.2 Q2 Partial Hash - Clarify "Exclusion" ⏳ IN PROGRESS

**Current Status**: NEEDS AUDIT

**Requirement**:
- Partial hash mismatch should **only** exclude from full-hash stage
- Must **NOT** exclude from Q3 (metadata) or Q4 (pHash) stages

**Action Items**:
1. ✅ Verified Q2 uses `all_candidates` (not size-filtered list)
2. ⏳ **NEED TO VERIFY**: Files that don't match partial hash still go to Q3/Q4
3. ⏳ **NEED TO VERIFY**: Progressive exclusion only applies to exact-dup groups

**Code Location**: `pipeline.py:659-812` (Q2 partial → SHA256 stages)

**Expected Behavior**:
```python
# Partial hash matches → proceed to full hash (exact dup check)
# Partial hash differs → skip full hash, BUT continue to Q3/Q4/Q5

# After Q2 SHA256:
excluded_after_q2 = {files in exact-dup groups}  # Only these excluded
# All other files continue to Q3/Q4
```

---

### 1.3 Replace SHA-256 Full Hash with BLAKE3 ⏳ NEXT TASK

**Current State**:
- Partial hash: Uses BLAKE3 ✅
- Full hash: Uses SHA-256 ❌ (slower)

**Rationale**:
- BLAKE3 is cryptographically secure
- **Much faster** than SHA-256 for large files (up to 10x)
- Already using BLAKE3 for partial hashing
- Consistent hashing algorithm across stages

**Implementation Plan**:

1. **Update `_sha256_file()` function** (`pipeline.py:247-252`):
   ```python
   def _blake3_full_file(path: Path, block: int = 1 << 20) -> str:
       """Full file hash using BLAKE3."""
       h = blake3.blake3() if _BLAKE3_AVAILABLE else hashlib.sha256()
       with path.open("rb") as f:
           for chunk in iter(lambda: f.read(block), b""):
               h.update(chunk)
       return h.hexdigest()
   ```

2. **Update cache field name**:
   - Change from `sha256` to `blake3_full` or `full_hash`
   - Maintain backward compatibility with existing caches

3. **Update Q2 SHA256 stage** (`pipeline.py:702-801`):
   - Rename to "Q2 Full Hash"
   - Update reporter metrics
   - Update cache.get/put calls

4. **Add config option** (optional):
   ```python
   --full-hash-algo [blake3|sha256]  # default: blake3
   ```

**Estimated Impact**: 30-50% faster full-file hashing on large files

---

### 1.4 Align `--subset-min-ratio` with 10% Overlap ⏳ PENDING

**Current State**:
- Default: `--subset-min-ratio = 0.30` (30%)
- Research says: 10% overlap threshold

**Decision Needed**:

**Option A - Strict Alignment** (Recommended):
- Change default to `--subset-min-ratio = 0.10`
- Matches research definition exactly
- Catches more partial duplicates

**Option B - Pragmatic Default**:
- Keep 0.30 as default (less false positives)
- Update docs: "For aggressive detection, use 0.10"
- Add quality preset: `-q 6` for "thorough with 10% overlap"

**Recommendation**: **Option A**
- Research is clear: ≥10% overlap is the goal
- False positives handled by confidence scoring
- Users can raise threshold if too aggressive

**Action Items**:
1. Update `PipelineConfig` default in `pipeline.py:66`
2. Update CLI help text
3. Update EXPLAINED.md
4. Update FEATURE_PLAN.md

---

## Phase 2: Improve Caching, Metadata, and IO ⏳ NEXT PHASE

### 2.1 Cache Identity & Renames

**Current Problem**:
- Cache key: `(path, size, mtime)`
- Renames/moves invalidate cache even if file unchanged

**Planned Improvements**:

1. **Better identity (platform-dependent)**:
   - POSIX: Include `(st_dev, st_ino)` from `os.stat`
   - Windows: Use FileId if accessible
   - Store `path` as value for display, not identity

2. **Sharded cache**:
   - Split large JSONL into shards
   - Load only relevant shards per run

3. **Binary format (later iteration)**:
   - Keep JSONL for now
   - Plan for MessagePack or SQLite later

---

### 2.2 Efficient ffprobe Usage

**Current State**: Uses full ffprobe output

**Optimization**:
```bash
ffprobe -v error -select_streams v:0 \
  -show_entries stream=width,height,codec_name,r_frame_rate,bit_rate \
  -show_entries format=duration,format_name \
  -of json "file.mp4"
```

**Benefits**:
- Faster execution
- Less parsing overhead
- Only extract what we need

---

### 2.3 IO/Hashing Scheduling

**For HDD-heavy datasets**:
- Sort files by path before hashing (reduce seeks)
- Separate thread pools:
  - Disk IO (hashing, decoding)
  - CPU-bound (pHash, audio fingerprinting)

---

## Phase 3: Perceptual Hashing & Frame Sampling ⏳ MAJOR UPGRADE

### Current Implementation

**Existing pHash** (`phash.py`):
- Samples 5 frames per video (configurable via `phash_frames`)
- Uses FFmpeg to extract frames
- Computes pHash for visual similarity

**Current Limitations**:
1. **Too sparse sampling**: 5 frames can miss partial overlaps
2. **No adaptive strategy**: Same sampling for 1min and 2hr videos
3. **Limited sequence matching**: Current subset detection may miss overlaps

---

### 3.1 Adaptive Frame Sampling Strategy ⏳ HIGH PRIORITY

**Proposed Strategy**:

```python
def adaptive_sampling_rate(duration: float, mode: str) -> float:
    """Return frame sampling interval in seconds."""

    if mode == "fast":
        # Minimal sampling for speed
        if duration <= 300:  # ≤5 min
            return 10.0  # 1 frame / 10s
        elif duration <= 3600:  # ≤1 hr
            return 20.0
        else:
            return 30.0

    elif mode == "balanced":
        # Moderate sampling (default)
        if duration <= 300:  # ≤5 min
            return 1.0  # 1 frame / 1s
        elif duration <= 3600:  # ≤1 hr
            return 2.0  # 1 frame / 2s
        else:
            return 4.0  # 1 frame / 4s

    elif mode == "thorough":
        # Dense sampling for maximum recall
        if duration <= 300:  # ≤5 min
            return 0.5  # 2 frames / 1s
        elif duration <= 3600:  # ≤1 hr
            return 1.0  # 1 frame / 1s
        else:
            return 2.0  # 1 frame / 2s

    # Constraints
    min_frames = 20
    max_frames = 1000 if mode == "thorough" else 500

    num_frames = int(duration / interval)
    if num_frames < min_frames:
        interval = duration / min_frames
    elif num_frames > max_frames:
        interval = duration / max_frames

    return interval
```

**Benefits**:
- Short videos: Dense sampling (catch all content)
- Long videos: Reasonable sampling (avoid explosion)
- Mode-dependent: User controls speed/accuracy trade-off

**Implementation Steps**:
1. Add `adaptive_sampling_rate()` helper
2. Update frame extraction in `phash.py`
3. Add mode config to `PipelineConfig`
4. Update CLI with `--mode [fast|balanced|thorough]`

---

### 3.2 Per-Frame pHash Storage

**Current**: Returns tuple of pHashes

**Proposed**: Return structured data:
```python
@dataclass
class FrameHash:
    timestamp: float  # Position in video (seconds)
    index: int        # Frame index in sequence
    phash: int        # 64-bit pHash

@dataclass
class VideoFingerprint:
    path: Path
    duration: float
    frames: List[FrameHash]
```

**Benefits**:
- Enables sequence matching
- Tracks temporal position
- Supports partial overlap detection

---

### 3.3 Per-Video Coarse Hash (Optional)

**Fast coarse filter**:
- XOR or hash all frame pHashes → single 64-bit video hash
- Very fast full-video similarity check
- **Does NOT replace** frame-level matching for partials

---

## Phase 4: Efficient pHash Comparison & Subset Detection ⏳ CRITICAL

### Current Subset Detection

**Location**: `pipeline.py:1055-1123` (inside Q4 stage)

**Current Implementation**:
- Uses `_alignable_distance()` for sliding window comparison
- Adaptive thresholding based on content complexity
- Cross-resolution support

**Limitations**:
1. Only runs if `cfg.subset_detect = True`
2. May miss overlaps if frame sampling too sparse
3. O(N²) frame comparisons (can be slow)

---

### 4.1 Indexing pHashes (Non-Deep, Non-FAISS) ⏳ NEEDED

**Problem**: O(N²) pairwise frame comparisons don't scale

**Solution: Hash Bucket Index**

```python
class PHashIndex:
    def __init__(self):
        # Map: bucket_key → list[(video_id, frame_idx, phash, timestamp)]
        self.buckets: Dict[int, List[Tuple]] = defaultdict(list)

    def add_frame(self, video_id: str, frame: FrameHash):
        """Add frame to multiple buckets for LSH-style lookup."""
        # Derive 4 bucket keys from 64-bit pHash (16-bit segments)
        for i in range(4):
            bucket_key = (frame.phash >> (i * 16)) & 0xFFFF
            self.buckets[bucket_key].append((video_id, frame.index, frame.phash, frame.timestamp))

    def find_similar(self, phash: int, threshold: int = 12) -> List[Tuple]:
        """Find frames with Hamming distance ≤ threshold."""
        candidates = set()

        # Look up all buckets this frame belongs to
        for i in range(4):
            bucket_key = (phash >> (i * 16)) & 0xFFFF
            candidates.update(self.buckets.get(bucket_key, []))

        # Filter by Hamming distance
        results = []
        for vid_id, idx, candidate_phash, ts in candidates:
            dist = hamming_distance(phash, candidate_phash)
            if dist <= threshold:
                results.append((vid_id, idx, dist, ts))

        return results
```

**Benefits**:
- Near O(1) lookup vs O(N) linear scan
- Scales to millions of frames
- No ML dependencies

---

### 4.2 Sequence-Based Subset Detection ⏳ MAJOR IMPROVEMENT

**Treat frame pHashes as time-ordered sequences**

**High-Level Algorithm**:

```python
def detect_partial_overlap(video_a: VideoFingerprint,
                          video_b: VideoFingerprint,
                          min_ratio: float = 0.10) -> Optional[OverlapMatch]:
    """
    Detect if video A and B share a contiguous segment ≥ min_ratio of longer video.

    Returns:
        OverlapMatch with:
        - overlap_duration: float (seconds)
        - overlap_ratio: float (0-1)
        - a_range: (start_sec, end_sec)
        - b_range: (start_sec, end_sec)
        - confidence: float
    """

    # 1. Build map of pHash matches
    matches: List[Tuple[int, int]] = []  # (index_a, index_b) pairs

    for i, frame_a in enumerate(video_a.frames):
        for j, frame_b in enumerate(video_b.frames):
            if hamming_distance(frame_a.phash, frame_b.phash) <= threshold:
                matches.append((i, j))

    # 2. Find longest diagonal streak (consecutive matches)
    longest_run = find_longest_diagonal_run(matches)

    # 3. Convert to duration
    if longest_run:
        a_start, a_end = video_a.frames[longest_run.a_start].timestamp, \
                         video_a.frames[longest_run.a_end].timestamp
        b_start, b_end = video_b.frames[longest_run.b_start].timestamp, \
                         video_b.frames[longest_run.b_end].timestamp

        overlap_duration = min(a_end - a_start, b_end - b_start)
        max_duration = max(video_a.duration, video_b.duration)
        overlap_ratio = overlap_duration / max_duration

        if overlap_ratio >= min_ratio:
            return OverlapMatch(
                overlap_duration=overlap_duration,
                overlap_ratio=overlap_ratio,
                a_range=(a_start, a_end),
                b_range=(b_start, b_end),
                confidence=calculate_confidence(longest_run)
            )

    return None

def find_longest_diagonal_run(matches: List[Tuple[int, int]]) -> DiagonalRun:
    """
    Find longest sequence of (i, j) where both i and j increase together.
    This represents a contiguous matching segment.
    """
    # Sort by (i, j)
    matches = sorted(matches)

    best_run = None
    current_run = []

    for match in matches:
        if not current_run:
            current_run = [match]
        else:
            prev_i, prev_j = current_run[-1]
            curr_i, curr_j = match

            # Check if diagonal continues (both indices increase)
            if curr_i == prev_i + 1 and abs(curr_j - prev_j) <= 2:
                # Allow small gaps in j (for dropped frames)
                current_run.append(match)
            else:
                # Run ended, check if it's the best so far
                if not best_run or len(current_run) > len(best_run.matches):
                    best_run = DiagonalRun(
                        a_start=current_run[0][0],
                        a_end=current_run[-1][0],
                        b_start=current_run[0][1],
                        b_end=current_run[-1][1],
                        matches=current_run
                    )
                current_run = [match]

    # Check final run
    if current_run and (not best_run or len(current_run) > len(best_run.matches)):
        best_run = DiagonalRun(...)

    return best_run
```

**Benefits**:
- Detects contiguous matching segments
- Handles frame drops and slight variations
- Provides exact overlap boundaries
- No ML required

---

## Phase 5: Mode System (Fast / Balanced / Thorough) ⏳ NEEDED

### Current State

**Quality Levels** (`-q 1-7`):
- Partially implemented
- Maps to stage selection
- No comprehensive mode system

**Needed**: Unified mode configuration

---

### Proposed Mode System

```python
@dataclass
class ModeConfig:
    """Configuration for detection mode."""
    name: str

    # Frame sampling
    sampling_strategy: str  # "fixed" | "adaptive"
    min_frames_per_video: int
    max_frames_per_video: int

    # Stages enabled
    enable_subset_detection: bool
    enable_audio_fingerprint: bool
    enable_deep_embeddings: bool  # Future

    # Thresholds
    phash_threshold: int
    subset_min_ratio: float

    # Performance
    max_threads: int
    cache_frames: bool

# Preset modes
MODES = {
    "fast": ModeConfig(
        name="fast",
        sampling_strategy="fixed",
        min_frames_per_video=5,
        max_frames_per_video=10,
        enable_subset_detection=False,
        enable_audio_fingerprint=False,
        enable_deep_embeddings=False,
        phash_threshold=15,  # More permissive
        subset_min_ratio=0.30,
        max_threads=4,
        cache_frames=False,
    ),

    "balanced": ModeConfig(
        name="balanced",
        sampling_strategy="adaptive",
        min_frames_per_video=20,
        max_frames_per_video=500,
        enable_subset_detection=True,
        enable_audio_fingerprint=False,  # Optional
        enable_deep_embeddings=False,
        phash_threshold=12,
        subset_min_ratio=0.10,  # Aligned with research
        max_threads=8,
        cache_frames=True,
    ),

    "thorough": ModeConfig(
        name="thorough",
        sampling_strategy="adaptive",
        min_frames_per_video=50,
        max_frames_per_video=1000,
        enable_subset_detection=True,
        enable_audio_fingerprint=True,
        enable_deep_embeddings=False,  # Future: True
        phash_threshold=10,  # Stricter
        subset_min_ratio=0.10,
        max_threads=16,
        cache_frames=True,
    ),
}
```

**CLI Integration**:
```bash
# Mode flag
video-dedupe -D ./videos --mode balanced -o ./output

# Or keep -q for backward compatibility
video-dedupe -D ./videos -q 5  # Maps to "balanced"

# Override specific settings
video-dedupe -D ./videos --mode thorough --subset-min-ratio 0.05
```

---

## Phase 6: Audio Fingerprinting ⏳ FUTURE

### Integration with Chromaprint

**Status**: Not yet implemented

**Plan**:
1. Use `fpcalc` (Chromaprint CLI) or Python bindings
2. Extract mono audio from video (FFmpeg)
3. Generate fingerprint, store in cache
4. Compare fingerprints for audio similarity

**Benefits**:
- Catches duplicates with visual changes
- Robust to re-encoding
- Complements visual matching

**Implementation Priority**: After Phase 3-4 complete

---

## Phase 7: Confidence Scoring & Verification ⏳ NEEDED

### Current State

**Report Viewer** (`report_viewer.py`):
- Already displays groups
- Shows keep/loser files
- Interactive browsing

**Missing**:
- Confidence scores
- Verification mode before deletion
- Quality-based winner selection

---

### Proposed Confidence Scoring

```python
@dataclass
class DuplicateMatch:
    video_a: Path
    video_b: Path

    # Scores
    visual_coverage: float  # % of frames matched
    visual_similarity: float  # Avg pHash similarity
    audio_score: float  # Audio fingerprint match (0-1)

    # Relationship
    relationship: str  # "full" | "subset" | "partial"
    overlap_ratio: float  # Duration overlap / max(durationA, durationB)
    overlap_ranges: Tuple[Tuple[float, float], Tuple[float, float]]  # ((a_start, a_end), (b_start, b_end))

    # Combined
    confidence: float  # 0-1, weighted combination

    def calculate_confidence(self) -> float:
        """
        Weighted combination:
        - 40% visual coverage
        - 30% visual similarity
        - 30% audio score (if available)
        """
        weights = [0.4, 0.3, 0.3] if self.audio_score > 0 else [0.6, 0.4, 0.0]
        return (
            weights[0] * self.visual_coverage +
            weights[1] * self.visual_similarity +
            weights[2] * self.audio_score
        )
```

---

### Verification Mode

**CLI Options**:
```bash
# Generate report only, no deletion
video-dedupe -D ./videos --verify-only -o report.json

# Apply report with threshold
video-dedupe --apply-report report.json --confidence-threshold 0.95

# Interactive confirmation
video-dedupe -D ./videos --interactive
```

---

## Phase 8-10: Later Stages

### Phase 8: Scalability (Batch Processing, Parallelism)
- **Status**: Partially implemented
- **TODO**: Streaming, better batching

### Phase 9: Deep Embeddings & FAISS
- **Status**: Not implemented
- **Priority**: LOW (only after all above complete)

### Phase 10: SSIM Validation
- **Status**: Researched, not implemented
- **Use**: Final validator for borderline cases

---

## Current Implementation Priority

### Immediate Tasks (This Session):

1. ✅ **Q1 Size Fix** - COMPLETE
2. ⏳ **Verify Q2 Partial Hash Logic** - Audit exclusion behavior
3. ⏳ **Replace SHA-256 with BLAKE3** - Faster full hashing
4. ⏳ **Update subset-min-ratio default** - Align with 10% threshold

### Next Sprint:

5. **Adaptive Frame Sampling** - High-impact improvement
6. **pHash Index** - Scalability for large datasets
7. **Sequence-Based Subset Detection** - Better partial overlap detection
8. **Mode System** - User-friendly configuration

### Future:

9. **Audio Fingerprinting** - Multi-modal detection
10. **Confidence Scoring** - Smart winner selection
11. **Deep Embeddings** - Maximum recall (optional)

---

## Success Metrics

### Phase 1-4 Complete:
- ✅ Detects visual duplicates (different sizes)
- ✅ Detects partial overlaps ≥10%
- ✅ Scales to 6TB+ datasets
- ✅ Configurable speed/accuracy modes
- ✅ 3-5x improvement in duplicate detection rate

### All Phases Complete:
- ✅ Multi-modal detection (visual + audio)
- ✅ Deep learning embeddings (optional)
- ✅ Confidence-based verification
- ✅ Production-ready for large-scale deduplication

---

## Notes

- **No ML required** for Phases 1-7 (core functionality)
- **PyTorch/FAISS** only for Phase 9+ (optional thorough mode)
- **Open-source only**: FFmpeg, OpenCV, Chromaprint, Python ecosystem
- **Incremental value**: Each phase adds value independently
