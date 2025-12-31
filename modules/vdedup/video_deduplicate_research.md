# Maximizing vdedup performance: A technical blueprint for 10TB+ video deduplication

Your RTX 5090 and AMD 9950x3D are severely underutilized at **2% GPU and 10% CPU** because of architectural bottlenecks—not hardware limitations. This report provides a comprehensive roadmap to achieve **80%+ GPU utilization** and **10-20x throughput improvement** by implementing GPU-accelerated decoding, efficient similarity indexing, and proper pipeline parallelization. The priority order of detection quality, then throughput, then efficiency guides all recommendations.

## The root cause: Pipeline serialization starves your hardware

Your current bottleneck is almost certainly **I/O and decoding blocking compute**. When video frames decode sequentially on CPU while the GPU sits idle waiting for work, utilization collapses. The solution requires three simultaneous changes: hardware video decoding via NVDEC, bounded producer-consumer queues between pipeline stages, and batched GPU operations for hashing.

The RTX 5090 contains **2 sixth-generation NVDEC decoders** capable of processing 8× 4K@60fps streams simultaneously, plus **32GB VRAM** sufficient to hold ~500M compressed vectors or thousands of decoded frames. Your 9950x3D's 16 cores should handle parallel file I/O and hash comparisons while the GPU handles decoding and perceptual hash computation.

Expected performance after optimization: **10-20 videos/second** versus the likely current rate of ~1 video/second, completing a 10TB library (~500K videos) in **7-14 hours** rather than days.

---

## Perceptual hashing: pHash and dHash dominate for quality and speed

For video deduplication prioritizing recall, **DCT-based pHash (64-bit)** delivers the best accuracy while **dHash (64-128 bit)** offers nearly equivalent quality at faster speeds. The algorithm choice significantly impacts both detection quality and computational overhead.

**pHash implementation details**: The algorithm resizes frames to 32×32 pixels, converts to grayscale, applies a 2D DCT transform, extracts the top-left 8×8 low-frequency coefficients (excluding DC), computes the median, and generates a 64-bit binary hash where bits indicate above/below median. This captures dominant visual structure while ignoring high-frequency noise from compression or minor edits.

**Hamming distance thresholds** determine the precision-recall tradeoff:
- Distance 0: Identical frames
- Distance 1-5: Very similar (high-confidence duplicates)
- Distance 5-10: Similar content (likely duplicates with transformations)
- Distance >10: Probably different content

For **high recall** (your priority), start with threshold ≤10-12 for 64-bit hashes, then tune downward based on false positive rates. Research from the PHASER framework (2024) and Tech Coalition benchmarks confirms this range balances sensitivity with specificity.

**Video-specific hashing** requires temporal aggregation. The **videohash** library extracts 1 frame/second, creates a 144×144 collage, and applies wavelet hashing—robust against transcoding, watermarks, and aspect ratio changes. However, it cannot detect **partial copies** (clips within longer videos), a critical limitation for comprehensive deduplication.

For clip detection, extract per-frame hashes and use sequence matching algorithms (covered in subset detection section). The **MPEG-7 Video Signature** standard achieves 96% detection rate with only 5 false alarms per million comparisons through temporal fingerprinting.

---

## Similarity search must avoid O(N²) complexity for billion-frame scale

A 10TB library with millions of frames requires **sub-linear search algorithms**. Linear comparison of all frame pairs is computationally infeasible—FAISS binary indexes and multi-index hashing provide the solution.

**FAISS IndexBinaryMultiHash** implements the Norouzi et al. (2012) algorithm optimal for binary codes: split each hash into m disjoint substrings, build m hash tables indexed by substrings, query by looking up matching buckets across tables, then verify candidates with full Hamming distance. On 1 billion 64-bit codes, this achieves **hundreds of times faster** lookups than linear scan.

For your setup, the recommended index configuration:
```
Primary: FAISS IndexBinaryMultiHash (CPU)
  - 256-bit binary codes (32 bytes per frame)
  - Multi-index with ~16 substrings
  - Memory: ~5GB for 100M frames
  - Query: 10,000-50,000 QPS single-threaded
```

**Critical limitation**: FAISS GPU acceleration only supports floating-point vectors, not binary indexes. Binary hash search remains CPU-bound. However, **cuVS** (NVIDIA RAPIDS) provides GPU-accelerated search for dense embeddings—useful for deep learning features in later pipeline stages.

**Hierarchical indexing** improves efficiency for video-level deduplication:
1. **Video-level**: Aggregate frame hashes into single signature via mean or majority voting
2. **Scene-level**: Group frames by shot boundaries, hash per scene
3. **Frame-level**: Individual frame comparison for verification

This hierarchy reduces candidate pairs by 99%+ before expensive frame-by-frame comparison.

---

## Subset and clip detection requires temporal sequence algorithms

Detecting when one video contains a clip from another—rather than being an exact duplicate—requires **temporal sequence matching**. Standard perceptual hashing alone cannot solve this.

**Longest Common Subsequence (LCS)** identifies matching frame sequences between videos. The Hunt-Szymanski algorithm achieves O((r + n) log n) complexity where r = number of matching frame pairs, making it efficient when matches are sparse (typical for clip-within-video detection). Frame hashes "match" if Hamming distance falls below threshold.

**Dynamic Time Warping (DTW)** handles temporal distortion—videos playing at different speeds or with inserted/deleted frames. Standard DTW requires O(N²) time and space; **FastDTW** (Salvador & Chan) reduces this to O(N) through multi-resolution coarsening, making it practical for long videos.

**ViSiL** (Video Similarity Learning, ICCV 2019) represents the deep learning state-of-the-art: it constructs frame-to-frame similarity matrices using CNN features, then applies a 4-layer CNN to detect temporal patterns indicating partial copies. It achieves leading results on FIVR-200K and VCDB benchmarks. The **VSAL** (2021) extension adds explicit alignment prediction.

**False positive control** is essential. Common intros, outros, and black frames trigger false matches. Solutions include:
- Whitelist known common segments (studio logos, disclaimers)
- Detect and exclude black frames (mean luminance < threshold)
- Require minimum matched segment length (e.g., 5+ seconds)
- Weight matches by position (content matches vs. intro matches)

---

## GPU acceleration through NVDEC and PyNvVideoCodec transforms throughput

The primary cause of your 2% GPU utilization is **CPU-based video decoding**. The RTX 5090's dual NVDEC decoders can handle 2500+ fps for 1080p content—but only if you use them.

**PyNvVideoCodec** (NVIDIA's official Python library) provides the optimal path:

```python
import PyNvVideoCodec as nvc

decoder = nvc.ThreadedDecoder(
    video_path,
    buffer_size=24,           # Prefetch frames in background
    use_device_memory=True,   # Keep frames in VRAM (critical!)
    output_color_type=nvc.OutputColorType.RGBP
)

# Frames decoded in background, ready when needed
frames = decoder.get_batch_frames(32)

# Zero-copy conversion to PyTorch
import torch
tensors = [torch.from_dlpack(f) for f in frames]
```

**Key optimizations that unlock performance**:
- `use_device_memory=True`: Frames remain in VRAM, eliminating CPU-GPU transfer overhead
- `ThreadedDecoder`: Background decoding overlaps with processing
- `decoder_cache_size`: Reuse decoder contexts across similar videos (3.8× speedup for 360p)
- DLPack protocol enables zero-copy tensor sharing between PyNvVideoCodec, PyTorch, and CuPy

**Expected throughput improvements**:
| Operation | CPU (current) | GPU (optimized) | Speedup |
|-----------|---------------|-----------------|---------|
| 4K decode | ~30 fps | 800+ fps | 26× |
| 1080p decode | ~100 fps | 2500+ fps | 25× |
| Hash compute | ~50 frames/s | 5000+ frames/s | 100× |

**GPU perceptual hashing** via PyTorch or CuPy performs DCT on batched frames entirely on GPU. Pre-compute the DCT basis matrix once, then matrix multiply against grayscale frames—avoiding per-frame overhead.

---

## BLAKE3 and parallel processing maximize CPU utilization

Your 10% CPU utilization indicates sequential processing without proper parallelization. **BLAKE3** and **ProcessPoolExecutor** together can saturate the 9950x3D.

**BLAKE3** achieves ~1GB/s per core through built-in parallelism—its Merkle tree structure enables unlimited parallel chunk hashing. The Python `blake3` package (official PyO3/Rust bindings) supports:
- `max_threads=blake3.AUTO`: Automatically uses all cores
- `update_mmap()`: Memory-mapped file hashing without loading entire video
- SIMD auto-detection: Exploits AVX-512 on your 9950x3D

For **file identification** (detecting exact byte-identical copies before perceptual comparison), BLAKE3 processes faster than any competitor while providing cryptographic strength.

**xxHash/XXH3** reaches ~31GB/s with AVX-512—useful for quick content-addressable storage keys but without cryptographic guarantees.

**Parallel processing architecture** for the 9950x3D:
```python
from concurrent.futures import ProcessPoolExecutor
from blake3 import blake3

def process_video(path):
    hasher = blake3(max_threads=4)  # 4 threads per worker
    hasher.update_mmap(path)
    return path, hasher.hexdigest()

# 8 workers × 4 threads = 32 total (matches 9950x3D thread count)
with ProcessPoolExecutor(max_workers=8) as executor:
    results = dict(executor.map(process_video, video_paths, chunksize=10))
```

**Rust bindings via PyO3/maturin** provide maximum performance for custom hot paths. The `blake3-py`, `ruff`, and `tiktoken` projects demonstrate Python extensions achieving native Rust speed.

---

## Audio fingerprinting validates visual matches and catches re-encodes

Audio fingerprinting complements visual hashing by catching duplicates where video was re-encoded but audio remained identical—common in piracy and content redistribution.

**Chromaprint/AcoustID** generates compact fingerprints from audio waveforms. The algorithm extracts at 11025 Hz, computes FFT-based features, and produces binary fingerprints where **cross-correlation >0.5 indicates likely match**, >0.7 indicates high confidence.

Integration pattern for multi-modal deduplication:
```
Video → Visual fingerprint (pHash)  ─┬─→ Match if BOTH match (high confidence)
                                     │
      → Audio fingerprint (Chromaprint) ─→ Flag for review if only ONE matches
```

**Computational cost**: Chromaprint fingerprints 1 minute of audio in ~2-3 seconds on CPU. For the first 60-120 seconds of each video (sufficient for matching), audio fingerprinting adds minimal overhead while significantly improving recall for re-encoded content.

**librosa** provides deeper audio analysis via MFCCs, chroma features, and spectral descriptors—useful for edge cases where Chromaprint produces ambiguous results.

---

## Deep learning refines candidates from perceptual hashing

Deep learning models like **CLIP** and **VideoMAE** provide semantic understanding that perceptual hashes cannot—distinguishing "similar looking" from "same content." Deploy these for **verification of candidates** identified by faster hashing methods, not initial screening.

**CLIP ViT-L/14** (768-dimensional embeddings) excels at semantic frame matching. Process keyframes through CLIP, compute cosine similarity, threshold at 0.85-0.95 for duplicate confirmation. With TensorRT FP16 optimization, expect **200+ frames/second** on RTX 5090.

**VideoMAE** and **I3D/SlowFast** capture temporal patterns—useful for detecting clips even when visual similarity is borderline. SlowFast's dual-pathway architecture (slow spatial semantics + fast motion) produces 2304-dimensional features capturing both appearance and action.

**Deep hashing** learns compact binary codes optimized for similarity search. Architectures like DSVH (Deep Supervised Video Hashing) train end-to-end to map video features to 128-bit codes searchable via Hamming distance—combining deep learning quality with hash-based efficiency.

**Two-stage architecture** for your pipeline:
1. Coarse filtering: pHash/dHash + FAISS binary index (100K+ QPS)
2. Fine verification: CLIP/I3D embeddings + cuVS search (validated candidates only)

This achieves high recall from hashing with high precision from deep features.

---

## Frame sampling balances coverage with speed

Processing every frame of every video is computationally wasteful—intelligent sampling achieves 95%+ recall with 10-50× speedup.

**I-frame extraction** (keyframe-only) provides the biggest single optimization: decode only intra-coded frames, skipping inter-frame dependencies. FFmpeg with `-skip_frame nokey` achieves **10-100× faster** extraction since most decoding work involves reconstructing P/B frames from I-frames.

```bash
ffmpeg -skip_frame nokey -i video.mp4 -vsync vfr keyframe_%03d.jpg
```

I-frame spacing varies by codec: H.264 typically every 10 seconds, H.265 every 4-10 seconds, MPEG-2 every 0.5 seconds. This means I-frame-only extraction yields **5-15 frames per minute** automatically placed at scene boundaries.

**PySceneDetect ContentDetector** identifies scene changes for content-aware sampling:
```python
from scenedetect import detect, ContentDetector
scenes = detect('video.mp4', ContentDetector(threshold=27.0))
# Sample 1-2 frames per detected scene
```

**Adaptive sampling formula** based on video duration:
- <30 seconds: 5 frames minimum
- 30s-5min: 5 + duration/20 frames (up to 20)
- 5-30min: 15 + duration/60 frames (up to 35)
- >30min: 30 + duration/120 frames (up to 50)

Research shows accuracy plateaus around 32-50 frames regardless of video length—additional samples provide diminishing returns.

---

## Pipeline architecture with bounded queues maximizes parallelism

The optimal architecture decomposes processing into **four decoupled stages** connected by bounded queues:

```
File Scanner → [Queue 1000] → Video Decoder → [Queue 50] → Hash Compute → [Queue 5000] → Compare
   (4 threads)                 (8 processes)               (2 GPU streams)              (4 threads)
```

**Bounded queues implement backpressure** automatically: when a queue fills, upstream producers block. This prevents memory exhaustion and keeps all stages running at the pace of the slowest.

**Queue sizing rationale**:
- File queue (1000): Paths are tiny (~100 bytes each)
- Frame queue (50): Decoded frames are huge (~6MB each for 1080p)
- Hash queue (5000): Hashes are tiny (8-64 bytes each)

**LMDB for hash storage** (not SQLite) provides 10×+ faster reads through memory mapping:
```python
import lmdb
env = lmdb.open('/path/to/hashes.lmdb', map_size=10**10)  # 10GB
with env.begin(write=True) as txn:
    txn.put(video_id.encode(), hash_bytes)
```

**Ray or Dask** enable distributed processing across multiple machines for libraries exceeding single-node capacity. Ray's work-stealing scheduler dynamically balances load when video processing times vary.

---

## Existing tools and benchmarking infrastructure

**videohash** provides a working baseline but cannot detect partial copies and shows limited maintenance. **imagehash** offers robust implementations of pHash/dHash/wHash with active development. **Decord** outperforms alternatives for GPU-accelerated batch video reading with its `get_batch()` API.

**Czkawka** (Rust) represents the current state-of-the-art in open-source duplicate detection—13,000+ GitHub stars, actively maintained, supports video content comparison with multi-threading. Its `czkawka_core` crate could be wrapped via PyO3 for Python integration.

**Benchmarking infrastructure** should capture:
- Throughput: videos/hour, frames/second
- Latency: p50, p95, p99 per-video processing time
- Resource utilization: CPU%, GPU%, memory
- Detection quality: precision, recall, F1 against ground truth

**pytest-benchmark** enables regression testing with `--benchmark-compare-fail min:5%` to catch performance degradations. **MLflow** (self-hosted) or **Weights & Biases** (cloud) track experiments across algorithm variations.

Ground truth datasets require **synthetic duplicate generation**: apply resolution changes (0.5×-2×), codec transcoding, bitrate variations, cropping (5-15%), color adjustments, and watermarks to create labeled positive pairs alongside negative pairs.

---

## Implementation roadmap prioritizing detection quality

**Phase 1 (Immediate)**: Fix GPU underutilization
- Replace CPU decoding with PyNvVideoCodec + NVDEC
- Implement bounded producer-consumer queues
- Add BLAKE3 parallel file hashing
- Expected: 10× throughput improvement, 70%+ GPU utilization

**Phase 2 (Core deduplication)**:
- Implement pHash/dHash with GPU batch processing
- Build FAISS IndexBinaryMultiHash for sub-linear search
- Add Chromaprint audio fingerprinting for validation
- Integrate I-frame extraction and adaptive sampling

**Phase 3 (Clip detection)**:
- Implement LCS with Hunt-Szymanski for temporal matching
- Add FastDTW for variable-speed alignment
- Deploy false positive filtering (intro/outro detection)

**Phase 4 (Deep learning refinement)**:
- Add CLIP/I3D verification for borderline candidates
- Optimize with TensorRT FP16
- Consider deep hashing for learned binary codes

**Metrics targets**:
- Detection recall: >95% (verified against ground truth)
- Processing throughput: 10+ videos/second sustained
- GPU utilization: 70-90% during active processing
- Memory footprint: <40GB working set

Your hardware is capable of processing the entire 10TB library in under 24 hours with these optimizations—the current multi-day timeline reflects software architecture problems, not hardware limitations.