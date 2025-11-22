# vdedup: How It Works

## Overview

**vdedup** (Video Deduplication) is a multi-stage pipeline system that identifies duplicate and similar video files using progressive filtering techniques. It uses a "fastest-first" approach where cheap operations filter out obvious non-duplicates before expensive operations run on candidates.

## Core Philosophy

1. **Progressive Exclusion**: Each stage eliminates confirmed non-duplicates after analysis
   - Q1 (Size): Optimization hint only - ALL files continue
   - Q2 (Hash): Exact duplicates excluded from visual stages
   - Q3 (Metadata): Metadata-matched groups excluded from pHash
   - Q4+ (Visual): Perceptual matching across different sizes/encodings
2. **Fastest First**: Size optimization → partial hash → full hash → metadata → visual analysis
3. **Caching**: All expensive operations (hashing, ffprobe, pHash) are cached to disk
4. **Parallel Processing**: Multi-threaded for I/O-bound operations (hashing, probing)

---

## Pipeline Stages

### Stage 1: Discovering Files
**Purpose**: Find all video files in specified directories

**Process**:
1. Recursively traverse directory tree (respects `--recursive` and depth limits)
2. Filter by file patterns (default: `*.mp4`, configurable with `-p`)
3. Skip artifacts (`.part`, `.tmp`, `.download`, etc.) unless `--include-partials`
4. Track statistics: total files, bytes, artifacts skipped

**Output**: List of `Path` objects for all candidate files

**Performance**: Fast (filesystem metadata only, no file reads)

---

### Stage 2: Scanning Files
**Purpose**: Gather basic file metadata for all candidates

**Process**:
1. `stat()` each file to get size and modification time
2. Create `FileMeta` objects: `{path, size, mtime}`
3. Group files by size into buckets: `Dict[size, List[FileMeta]]`
4. Track total bytes and video bytes

**Output**:
- List of `FileMeta` objects
- Size-bucketed dictionary for Q1 stage

**Performance**: Fast (metadata only, parallel execution)

**Cache**: No caching (cheap operation)

---

### Stage 3: Q1 Size Bucketing
**Purpose**: Identify size-matched groups for exact duplicate optimization

**Process**:
1. Group files by exact size
2. Identify buckets with 2+ files (potential exact duplicates)
3. **ALL files continue to next stages** (size is just an optimization hint)

**Logic**:
```python
by_size: Dict[int, List[FileMeta]] = defaultdict(list)
# Populate from scanning stage

# Identify size-matched groups for Q2 optimization
size_buckets_for_q2 = {size: bucket for size, bucket in by_size.items() if len(bucket) >= 2}

# CRITICAL: ALL files continue (nothing eliminated!)
all_candidates = metas  # Every file proceeds to Q2/Q3/Q4
```

**Output**:
- Size-grouped buckets for Q2 optimization (priority queue)
- ALL files proceed to Q2/Q3/Q4 (nothing eliminated)

**Rationale**:
Size matching only finds **exact binary duplicates**. Visual duplicates (different encodings, resolutions, clips) have **different sizes** and MUST be processed through metadata and pHash stages.

**Example**:
```
video_original.mp4   - 1.20 GB  ✅ Continues to Q2/Q3/Q4
video_720p.mp4       - 800 MB   ✅ Continues to Q2/Q3/Q4 (different size!)
video_h265.mp4       - 950 MB   ✅ Continues to Q2/Q3/Q4 (different size!)
video_clip.mp4       - 120 MB   ✅ Continues to Q2/Q3/Q4 (subset!)
```

All 4 files will be matched in Q4 (pHash visual similarity) despite having different sizes. This is **CORRECT** behavior.

**Performance**: Instant (already computed in stage 2)

**Smart Ordering in Q2**:
Q2 processes size-matched groups first for faster exact-duplicate detection, but unique-sized files are still fully processed for visual similarity.

**Elimination**: None (Q1 is optimization, not elimination)

---

### Stage 4: Q2 Partial Hash
**Purpose**: Fast preliminary hash to detect likely duplicates without reading entire files

**Algorithm**:
1. **BLAKE3 Partial Hash** (preferred, if available):
   - Read first 4 MB of file (head)
   - Read last 4 MB of file (tail)
   - Read middle 4 MB of file (if file > 12 MB)
   - Compute BLAKE3 hash of each chunk
   - Combine hashes: `{algo: "blake3", head: hash, tail: hash, mid: hash}`

2. **Fallback to SHA-256** (if BLAKE3 unavailable):
   - Same chunk-based approach with SHA-256

**Cache Key**: `(path, size, mtime)` → `partial` object

**Collision Handling**:
- If partial hashes match → group them
- If partial hashes differ → exclude from further processing
- Partial hash collisions proceed to Q2 SHA256 stage

**Output**: Groups of files with matching partial hashes

**Performance**:
- Reads ~12 MB per file (vs full file)
- ~50-100x faster than full hash for large files
- Parallel execution across `--threads`

**Typical Elimination**: 40-70% of remaining candidates

---

### Stage 5: Q2 SHA256 (Full Hash)
**Purpose**: Compute cryptographically-strong hash of entire file to confirm exact duplicates

**When Run**: Only on files that had partial hash collisions in Q4

**Algorithm**:
1. Read entire file in chunks
2. Compute SHA-256 hash of complete content
3. Group files by SHA-256 hash
4. Files with matching SHA-256 are **exact binary duplicates**

**Cache Key**: `(path, size, mtime)` → `sha256` hash string

**Output**:
- Groups of **exact duplicate** files (same SHA-256)
- These groups are excluded from Q3/Q4 (no need for metadata/visual analysis)

**Performance**:
- Must read entire file
- Bottleneck for large datasets
- Shows throughput (GiB/s) in UI

**Cache Hit Benefits**:
- If file hasn't changed (same path/size/mtime), use cached hash
- Skips re-reading entire file
- Typical cache hit rate on repeat runs: 80-95%

---

### Stage 6: Q3 Metadata Clustering
**Purpose**: Group visually similar files by video metadata (duration, resolution, codec, etc.)

**When Run**: Only on files that are NOT exact duplicates (different SHA-256)

**Algorithm**:
1. Run `ffprobe` on each file to extract metadata:
   - Duration (seconds)
   - Resolution (width × height)
   - Video codec (h264, h265, vp9, etc.)
   - Container format (mp4, mkv, etc.)
   - Bitrate
   - Frame rate

2. Normalize metadata for comparison:
   - Duration tolerance: ±2 seconds (configurable with `--duration-tolerance`)
   - Resolution: exact match or tolerance
   - Codec/container: optional exact match (`--same-codec`, `--same-container`)

3. Group files that match metadata criteria

**Cache Key**: `(path, size, mtime)` → `video_meta` object

**Output**: Metadata-based groups (candidates for visual similarity analysis)

**Performance**:
- `ffprobe` is fast (~10-50ms per file)
- Parallel execution
- Cache makes repeat runs instant

**Typical Behavior**:
- Groups re-encoded versions of same video
- Groups different resolutions of same content
- Passes groups to Q4 for visual verification

---

### Stage 7: Q4 pHash (Perceptual Hash)
**Purpose**: Detect visually similar files using perceptual hashing

**When Run**: Only on files grouped by Q3 metadata (not exact duplicates)

**Algorithm**:
1. **Frame Extraction**:
   - Extract N evenly-spaced frames from video (default: 5 frames)
   - Use `ffmpeg` to decode frames as images
   - Configurable with `--phash-frames`

2. **Perceptual Hashing**:
   - Compute pHash (perceptual hash) for each frame
   - pHash converts image to 8×8 grayscale, computes DCT, produces 64-bit hash
   - Each frame → 64-bit integer

3. **Similarity Comparison**:
   - Compare pHash arrays between files using Hamming distance
   - Hamming distance = number of differing bits
   - Threshold (default: 12 bits) configurable with `--phash-threshold`
   - Lower threshold = stricter matching

4. **Grouping**:
   - Files with average Hamming distance ≤ threshold → considered similar
   - Group visually similar files together

**Cache Key**: `(path, size, mtime)` → `phash` array (list of 64-bit ints)

**Output**: Groups of visually similar files

**Performance**:
- Frame extraction is expensive (depends on video length/codec)
- GPU acceleration available with `--gpu` flag
- Most time-consuming stage for large videos

**Use Cases**:
- Different quality encodings of same video
- Different resolutions (720p vs 1080p)
- Different codecs (h264 vs h265)
- Minor edits/cuts

**Optional: Subset Detection**:
- Enabled with quality level 5 (`-q 5`)
- Detects when one video is a subset of another (e.g., clip from full video)
- Uses sliding window comparison of pHash frames
- Configurable min ratio: `--subset-min-ratio` (default: 0.30 = 30%)

---

### Stage 8: Q6 Audio Fingerprinting (Future)
**Status**: Planned (stage exists but not fully implemented)

**Purpose**: Detect audio similarity independent of video

**Planned Algorithm**:
- Extract audio fingerprint using Chromaprint/AcoustID
- Compare audio signatures
- Detect:
  - Same video with different audio tracks
  - Dubbed versions
  - Videos with added commentary

---

### Stage 9: Q7 Advanced Content Analysis (Future)
**Status**: Planned (stage exists but not fully implemented)

**Purpose**: Deep content analysis using ML/AI techniques

**Planned Features**:
- Scene detection (shot boundaries)
- Motion vector analysis
- Keyframe extraction and comparison
- Object detection
- Face recognition (for matching similar scenes)

---

## Data Structures

### FileMeta
Basic file metadata from `stat()`:
```python
@dataclass
class FileMeta:
    path: Path
    size: int        # bytes
    mtime: float     # modification time (Unix timestamp)
```

### VideoMeta
Extended metadata from `ffprobe`:
```python
@dataclass
class VideoMeta:
    duration: float         # seconds
    width: int             # pixels
    height: int            # pixels
    codec: str             # h264, h265, vp9, etc.
    container: str         # mp4, mkv, etc.
    bitrate: Optional[int] # bits/sec
    fps: Optional[float]   # frames/sec
```

### Hash Cache Entry
JSONL format (one per line):
```json
{
  "path": "/path/to/video.mp4",
  "size": 1234567890,
  "mtime": 1234567890.123,
  "partial": {
    "algo": "blake3",
    "head": "abc123...",
    "tail": "def456...",
    "mid": "ghi789...",
    "head_bytes": 4194304,
    "tail_bytes": 4194304,
    "mid_bytes": 4194304
  },
  "sha256": "full_file_hash...",
  "video_meta": {
    "duration": 3600.5,
    "width": 1920,
    "height": 1080,
    "codec": "h264",
    "container": "mp4"
  },
  "phash": [12345678901234, 98765432109876, ...]
}
```

**Cache Lookup**:
- Key: `(path, size, mtime)`
- mtime tolerance: ±1.0 second (handles filesystem time precision differences)
- If file modified → cache miss → recompute

---

## Progressive Exclusion Flow

```
1956 total files
    ↓ [Scan] → 1956 files with metadata
    ↓ [Q1 Size] → 892 files (1064 eliminated: unique sizes)
    ↓ [Q2 Partial Hash] → 618 files (274 eliminated: different partial hashes)
    ↓ [Q2 SHA256] → 331 files (287 eliminated: exact duplicates found)
    ↓ [Q3 Metadata] → 84 groups (files clustered by metadata)
    ↓ [Q4 pHash] → Final duplicate groups
```

**Key Insight**: Each stage eliminates non-candidates, making subsequent expensive stages faster.

---

## Grouping & Winner Selection

### Group Types

**Hash Groups (Q2)**: Files with identical SHA-256
- These are **exact binary duplicates**
- Winner selection: Keep oldest file by default

**Metadata Groups (Q3)**: Files with similar metadata
- Not necessarily duplicates (might be different quality versions)
- Passed to Q4 for visual verification

**pHash Groups (Q4)**: Files with similar visual content
- Likely duplicates or different encodings
- Winner selection based on quality heuristics:
  - Higher resolution preferred
  - Higher bitrate preferred
  - Longer duration preferred (if subset detection off)
  - Configurable with keep policy

### Winner Selection (from `grouping.py`)

```python
def choose_winners(groups, policy="best_quality"):
    """
    For each group, select one file to keep (winner)
    and mark others as losers (candidates for deletion)
    """
    for group_id, members in groups.items():
        winner = select_best(members, policy)
        losers = [m for m in members if m != winner]
        yield (group_id, winner, losers)
```

**Default Policy** ("best_quality"):
1. Prefer higher resolution (1080p > 720p > 480p)
2. If tied, prefer higher bitrate
3. If tied, prefer longer duration
4. If tied, prefer older file (original)

**Alternative Policies**:
- `oldest`: Keep oldest file
- `newest`: Keep newest file
- `smallest`: Keep smallest file (lower quality)
- `largest`: Keep largest file (higher quality)

---

## Cache System

### Cache File Format
**Current**: JSONL (JSON Lines)
- One JSON object per line
- Append-only for atomic writes
- Human-readable for debugging

**Future** (planned): MessagePack binary format
- Smaller file size (~50-70% reduction)
- Faster parsing
- Better compression

### Cache Behavior

**On Startup**:
1. Load cache file into memory: `Dict[(path, size, mtime), record]`
2. Validate entries (skip malformed JSON)
3. Build lookup index

**During Processing**:
1. Before expensive operation (hash/probe/phash):
   - Check cache: `cache.get_sha256(path, size, mtime)`
   - If hit → use cached value, skip operation
   - If miss → compute value, write to cache

2. Write to cache:
   - Append JSON line to cache file
   - `flush()` after write
   - Update in-memory index

**On Shutdown**:
- Close cache file handle
- All writes already flushed
- Cache remains valid for next run

### Cache Invalidation

Cache entry is invalid if:
- File path changed (renamed/moved)
- File size changed (content modified)
- File mtime changed (beyond ±1.0s tolerance)

**Implication**: Renaming/moving files invalidates cache (by design, ensures correctness)

---

## Performance Characteristics

### Bottlenecks (in order of impact)

1. **Q2 SHA256 (Full Hash)**:
   - Must read entire file
   - I/O bound (limited by disk speed)
   - Mitigation: Partial hash eliminates most files, cache hits skip re-hashing

2. **Q4 pHash (Frame Extraction)**:
   - Video decoding is CPU-intensive
   - Depends on codec complexity and video length
   - Mitigation: GPU acceleration (`--gpu`), fewer frames (`--phash-frames 3`)

3. **Q3 ffprobe (Metadata)**:
   - Fast per-file but scales linearly
   - Mitigation: Parallel execution, caching

4. **File Discovery**:
   - Fast unless scanning millions of files
   - Mitigation: Depth limits, pattern filtering

### Optimization Strategies

**For Speed**:
- Use cached results (run on same dataset multiple times)
- Lower quality level: `-q 2` (skip pHash)
- Increase threads: `-t 16`
- Use fast storage (SSD > HDD)

**For Thoroughness**:
- Higher quality level: `-q 5` (enable subset detection)
- More pHash frames: `--phash-frames 9`
- Stricter pHash threshold: `--phash-threshold 8`

**For Large Datasets**:
- Limit depth: `-d 2` (don't recurse deeply)
- Filter patterns: `-p *.mp4` (skip other formats)
- Run incrementally (cache persists between runs)

---

## Report Generation

### Report Structure

JSON file containing:
```json
{
  "groups": [
    {
      "group_id": "sha256:abc123...",
      "type": "exact",
      "winner": {
        "path": "/keep/this.mp4",
        "size": 123456,
        "reason": "highest_quality"
      },
      "losers": [
        {
          "path": "/delete/this.mp4",
          "size": 123450,
          "reason": "duplicate"
        }
      ],
      "metadata": {...}
    }
  ],
  "summary": {
    "total_groups": 331,
    "total_losers": 892,
    "bytes_reclaimable": 1234567890,
    "scan_time": 3408.5
  }
}
```

### Applying Reports

**Dry Run Mode** (`-d` or `--dry-run`):
- Read report
- Print what would be deleted
- No actual file operations

**Live Mode** (no `-d`):
- Read report
- Prompt for confirmation (unless `--force`)
- Delete or move losers:
  - Delete: `unlink()` the file
  - Backup: `move()` to `--backup` directory (preserves structure)

**Backup Directory Structure**:
```
backup_dir/
├── original_path_1/
│   └── video.mp4
└── original_path_2/
    └── video.mp4
```

---

## Error Handling

### Graceful Degradation

**File Read Errors**:
- Skip file, log warning
- Continue processing other files

**ffprobe Errors**:
- Mark file as having no metadata
- Exclude from Q3/Q4 stages

**pHash Errors**:
- Skip frame extraction for that file
- Log error, continue with other files

**Cache Write Errors**:
- Log warning
- Continue without caching (slower but functional)

### Signal Handling

**SIGINT (Ctrl+C)**:
- First press: Graceful shutdown (flush cache, close files)
- Second press: Force quit immediately

**SIGTERM**:
- Graceful shutdown (flush cache, close files)

---

## UI/Progress Reporting

### Dashboard Layout

```
┌─ Header ──────────────────────────────────┐
│ Current stage, progress bar, ETA, status  │
└──────────────────────────────────────────┘
┌─ Timeline ─┐ ┌─ Stats ────────────────────┐
│ Stage list  │ │ Counters, throughput,     │
│ with times  │ │ cache hit rate, groups    │
└─────────────┘ └───────────────────────────┘
┌─ Recent Activity ─────────────────────────┐
│ Last N log messages with timestamps       │
└──────────────────────────────────────────┘
```

### Progress Updates

**Frequency**:
- UI refreshes: 4 times per second (every 0.25s)
- Progress updates: Every 50 files
- Log entries: Major events only

**Metrics Tracked**:
- Files scanned / total
- Bytes processed / total
- Throughput (MB/s or files/s)
- Cache hit rate (%)
- Duplicates found (count and %)
- ETA (estimated time remaining)

---

## Common Use Cases

### 1. Quick Exact Duplicate Scan
```bash
video-dedupe -D ~/Videos -q 2 -r -L
```
- Quality 2: Size + hash only (skip metadata/pHash)
- Fast results for exact duplicates

### 2. Thorough Visual Similarity Scan
```bash
video-dedupe -D ~/Videos -q 5 -r -L --phash-frames 7
```
- Quality 5: Full pipeline including subset detection
- 7 frames for better accuracy

### 3. Apply Report (Dry Run)
```bash
video-dedupe -a ~/report.json -d
```
- Show what would be deleted without actually deleting

### 4. Apply Report (Live with Backup)
```bash
video-dedupe -a ~/report.json -b ~/backup -f
```
- Move duplicates to backup directory instead of deleting

### 5. Resume Interrupted Scan
```bash
video-dedupe -D ~/Videos -q 5 -r -L -o ~/output
```
- Cache in `~/output/` persists between runs
- Re-running uses cached results (much faster)

---

## Future Enhancements

See `FEATURE_PLAN.md` for detailed feature requests and implementation plans.

**Key Improvements Planned**:
1. Binary cache format (faster, smaller)
2. Audio fingerprinting (Q6 stage)
3. Crash recovery with `--resume` flag
4. Real-time duplicate counter updates
5. Recent Activity log population
6. Stage-specific stats views (keyboard navigation)

---

## Glossary

**Exact Duplicate**: Files with identical SHA-256 hash (byte-for-byte same)

**Visual Duplicate**: Files with similar pHash (visually similar but different encoding)

**Subset**: One video is a portion of another (e.g., clip from full video)

**Partial Hash**: Hash computed from file chunks (head/tail/mid) instead of full file

**pHash (Perceptual Hash)**: Hash that produces similar values for visually similar images

**Hamming Distance**: Number of differing bits between two hashes

**Winner**: File selected to keep from a duplicate group

**Loser**: Files marked for deletion from a duplicate group

**Cache Hit**: Found precomputed result in cache (skip expensive operation)

**Cache Miss**: No cached result, must compute fresh

**mtime**: File modification time (Unix timestamp)

**JSONL**: JSON Lines format (one JSON object per line, newline-separated)
