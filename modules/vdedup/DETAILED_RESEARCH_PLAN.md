# vdedup – Implementation Plan for Advanced Duplicate & Partial-Overlap Detection

> **Goal:** Upgrade `vdedup` from “exact/rough duplicates” to a scalable system that:
> - Detects **full and partial** duplicates (≥ 10% of the longer video’s content overlaps).
> - Handles **6+ TB** of mixed-resolution video (240p–4K, 60 fps).
> - Offers **fast / balanced / thorough** modes.
> - Uses **open-source** tools only.
> - Adds **confidence scoring** and **verification** before deletions.
> - Defers heavy ML / PyTorch work to the final stages.

The sections below are ordered in **recommended implementation order**. You can implement them as stages or iterations over the existing codebase.

---

## 0. Foundations & Definitions

### 0.1 Clarify “Duplicate” Semantics

1. **Exact Duplicate**  
   Byte-for-byte identical file (same SHA/BLAKE3).  
   Typically: same resolution, same content, same duration.

2. **Visual Duplicate**  
   Same content but possibly:
   - Different resolution (480p vs 1080p)
   - Different codec (H.264 vs H.265)
   - Different container
   - Slight edits (re-encoded, small logo, etc.)

3. **Partial / Subset Duplicate**  
   One video contains a **contiguous segment** of another, with:
   - Overlap length  
     
     \[
     \text{overlap} \ge 0.10 \times \max(\text{duration}_A, \text{duration}_B)
     \]

4. **Overlap vs Shared Intro/Outro**  
   - Ignore very short common sections if they are **< 10%** of the longer video.
   - This avoids tagging different episodes with a common 30s intro as duplicates.

These definitions drive thresholds and decisions in later stages.

---

## 1. Fix & Harden Existing Stages (Q1–Q3)

### 1.1 Q1 Size Stage – Correct Logic

**Current documentation inconsistency:**

- One place says Q1 is **only an optimization**, all files continue.
- The example flow shows Q1 **eliminating unique sizes**.

**Required behavior:**

- **Do not eliminate** unique-sized files from downstream stages.
- Q1 is only used to:
  - Group files by size for **fast exact-dup detection**.
  - Prioritize same-size groups for hashing.

**Action items:**

- Ensure code does **not** filter out unique sizes before metadata/pHash.
- Update docs & internal comments:
  - “Q1 is a hint for Q2 exact duplicates only; all files continue to Q3/Q4.”

---

### 1.2 Q2 Partial Hash – Clarify “Exclusion”

Partial hash logic must **only control the full-hash path**, not the whole pipeline.

**Desired behavior:**

- Partial hash equal → candidates for **full file hash** (exact dup).
- Partial hash unequal → **skip full hash**, but **still go to Q3/Q4**.

**Action items:**

- Audit the code path that uses partial hash:
  - Confirm that a partial hash mismatch **does not** remove the file from visual/metadata analysis.
- Update comments/docs to say explicitly:
  - “Partial hash mismatch excludes from **exact-dup (full hash)** stage only.”

---

### 1.3 Replace SHA-256 Full Hash with BLAKE3 (Optional but Recommended)

You are already using **BLAKE3** for partial hashing. It is:

- Cryptographically secure.
- Much faster than SHA-256 for large files.

**Change:**

- For the “full hash” stage, compute **BLAKE3** hashes instead of SHA-256.
- Keep the same caching structure:
  - `{"algo": "blake3", "full": "..."}` vs `sha256`.

**Action items:**

- Introduce a `FullFileHasher` that:
  - Uses BLAKE3 as default.
  - Optional: config flag `--full-hash algo` if you want SHA-256 for compatibility.

---

### 1.4 Align `--subset-min-ratio` with 10% Overlap Definition

Current default: `--subset-min-ratio = 0.30` (30%).  
Stated conceptual definition: **10% of the longer video**.

Pick one of these strategies:

1. **Strict alignment:** default `--subset-min-ratio = 0.10`.  
2. **Pragmatic default:** keep 0.30 but update docs to say:
   - “By default we use 30% overlap; for truly aggressive detection, set 0.10.”

**Action items:**

- Decide on default and update:
  - CLI defaults.
  - Docs (EXPLAINED, README).
  - Any quality-level presets (`-q 5`, etc.).

---

## 2. Improve Caching, Metadata, and IO

### 2.1 Cache Identity & Renames

Current cache key: `(path, size, mtime)`.

Problems:

- Renames/moves invalidate cache even if file unchanged.
- Big JSONL file can grow very large.

**Improvements:**

1. **Better identity (platform-dependent):**
   - On POSIX: include `(st_dev, st_ino)` from `os.stat`.
   - On Windows: consider FileId if accessible.
   - Store `path` as value for display, not as identity.

2. **Sharded cache:**
   - Split one huge JSONL into shards (e.g., per dir or per day).
   - Load only shards relevant to the current run.

3. **Binary format later:**
   - Keep JSONL for now; plan for MsgPack or SQLite in a later iteration.

---

### 2.2 Efficient ffprobe Usage

- Use `ffprobe` with **minimal fields** for speed.
- Only extract what you need:
  - Duration, width, height, codec, bitrate, fps, container.

Example CLI pattern:

```bash
ffprobe -v error -select_streams v:0 -show_entries stream=width,height,codec_name,r_frame_rate,bit_rate -show_entries format=duration,format_name -of json "file.mp4"
```

**Action items:**

- Ensure ffprobe calls:
  - Are parallelized but not so many that they thrash the disk.
  - Use `-show_entries` to restrict output.

---

### 2.3 IO/Hashing Scheduling

For HDD-heavy datasets:

- Sort files by `path` or `size` before hashing to reduce seeks.
- Use a thread pool sized appropriately for:
  - Disk IO (hashing).
  - CPU-bound work (later, pHash/SSIM).

---

## 3. Perceptual Hashing & Frame Sampling (Non-Deep)

This is a **major accuracy upgrade** and does not require ML yet.

### 3.1 Adaptive Frame Sampling Strategy

Goal: avoid missing overlaps by sampling too sparsely.

**Proposed strategy:**

1. **Sampling based on duration:**

   - Duration ≤ 5 min → 1 frame / 0.5–1 s.
   - 5–60 min → 1 frame / 1–2 s.
   - > 60 min → 1 frame / 2–4 s.

2. **Minimum & maximum frame counts:**

   - Ensure at least ~20–50 frames per video.
   - Cap at, e.g., 500–1000 frames (balanced mode) to avoid explosion.

3. **Scene-change-aware sampling (optional now, later improved):**

   - Use keyframes (I-frames) or a simple histogram diff to detect scenes.
   - Always sample at scene boundaries plus midpoints for long scenes.

**Implementation notes:**

- Use FFmpeg to extract frames directly to memory or temp files.
- For now: start with fixed-interval timestamps; add scene-change later.

---

### 3.2 Per-Frame pHash

Each sampled frame:

1. Convert to grayscale, resize to small fixed size (e.g., 32×32 or 64×64).
2. Compute pHash (DCT-based, 64-bit).
3. Store as list:  

   ```python
   VideoFingerprint(
       path=...,
       duration=...,
       frames=[
           FrameHash(timestamp=..., phash=..., index=...),
           ...
       ],
   )
   ```

**Action items:**

- Implement a `phash_frame(frame_image)` helper using:
  - Your existing pHash implementation, or
  - OpenCV `img_hash` / Python `imagehash` library.

---

### 3.3 Per-Video Coarse Hash (Optional)

For a fast coarse filter:

- Derive a **single 64-bit hash per video** from:
  - A subset of frame pHashes (e.g., XOR or hash of concatenation).
- Use this for **very fast** near-dup detection:
  - Exact/near-equal video-level hash = strong candidate.

Do **not** rely on this for partial overlaps; it is just a coarse filter.

---

## 4. Efficient pHash Comparison & Subset Detection

### 4.1 Indexing pHashes (Non-Deep, Non-FAISS)

Avoid naive O(N²) pairwise comparisons of frames.

**Approach:**

1. **Hash bucket index:**

   - For each 64-bit pHash, derive a few bucket keys (e.g., 4 × 16-bit segments).
   - Map `bucket_key → list[(video_id, frame_idx, phash)]`.

2. **Near neighbor search:**

   - For a given frame, look up neighbors in buckets using its segment keys.
   - Optionally check Hamming distance ≤ `phash_threshold`.

This yields candidate matching frames quickly.

---

### 4.2 Detecting Partial Overlaps via Sequence Matching

Treat frame pHashes as a time-ordered sequence.

**High-level idea:**

1. For each video A, and candidate video B:
   - Find all pairs of frames `(i, j)` where pHash(A[i]) ~ pHash(B[j]).
2. We’re looking for **diagonal streaks** in `(timeA, timeB)`:
   - That is, sequences where `i` and `j` both increase together.

**Concrete plan:**

1. Build a mapping from pHash to approximate “cluster ID”:
   - Optionally cluster similar pHashes and assign IDs.
2. Convert each video to a sequence of IDs: `id_seq_A`, `id_seq_B`.
3. Use subsequence search:
   - Choose a small k (e.g., 3–5) and treat each k-length window as a “shingle”.
   - Create a rolling hash for each k-window of IDs for each video.
   - Build a map from rolling-hash → positions.
   - For every k-window in A, see if it appears in B.
   - When equal k-windows found, extend match forward/backward to find longest run.
4. Convert “longest run length in seconds” into overlap ratio:
   - If `run_duration >= subset_min_ratio * max(durationA, durationB)`, flag as partial duplicate.

**Key points:**

- This does **not** require ML.
- You can add an LSH/MinHash-style approximation later if needed.

---

## 5. Mode System: Fast / Balanced / Thorough

Introduce a central configuration object controlling:

- Sampling rate.
- Whether to run:
  - Subset detection.
  - Audio analysis.
  - Deep embedding stages (later).
- pHash thresholds.
- Number of frames to process.

### 5.1 Suggested Modes

1. **Fast mode (`-q 1` or `--mode fast`):**
   - Use:
     - Q1 size.
     - Partial+full BLAKE3 hash.
     - Optional single coarse video-level hash or a handful of frame pHashes.
   - No subset detection.
   - No deep embeddings.
   - No audio fingerprints.
   - Goal: find obvious full duplicates quickly.

2. **Balanced mode (default):**
   - Moderate frame sampling (as in §3.1).
   - Per-frame pHash + sequence-based subset detection.
   - Candidate grouping via pHash index.
   - Optional audio fingerprint for confirmation of strong candidates.
   - No deep embeddings yet (or only light use).
   - Good mix of recall and performance.

3. **Thorough mode (`--mode thorough`):**
   - Higher sampling rate (more frames per video).
   - Full subset detection.
   - Audio fingerprints enabled.
   - Later: deep embeddings + FAISS (see §9).
   - Best recall; slowest.

**Action items:**

- Refactor existing pipeline to run under a `Config` / `Settings` object.
- Tie CLI flags (`-q`, `--mode`, etc.) to these modes.

---

## 6. Audio Fingerprinting Stage

Add a new stage **before** any deep-learning work.

### 6.1 Chromaprint Integration

Use **Chromaprint/AcoustID** (via `fpcalc` or Python bindings):

1. Extract mono audio track from video (FFmpeg).
2. Run Chromaprint to generate fingerprint.
3. Store fingerprint in cache.

Chromaprint is robust to:

- Re-encoding.
- Quality changes.
- Minor noise.

### 6.2 Matching Logic

For each pair of videos:

1. Compare fingerprints:
   - If using `fpcalc`, parse the fingerprint (e.g., integer sequences).
   - Define a similarity metric:
     - Hamming distance.
     - Overlap in aligned sequences.
2. Mark:
   - **High audio similarity:** strong evidence of duplication.
   - **Partial audio overlap:** audio subset condition.

**Use in pipeline:**

- Balanced mode:
  - Use audio as *double-check* for high-confidence visual candidates.
- Thorough mode:
  - Use audio to generate **additional** candidates:
    - Videos that share a big audio segment might be partial duplicates even if visuals changed.

---

## 7. Confidence Scoring & Verification Mode

Before doing any deep ML work, implement:

- A **scoring system**.
- A **verification/report** step where no files are deleted directly.

### 7.1 Per-Pair / Per-Group Score

For each matched pair `(A, B)`:

Compute components:

1. **Visual coverage score:**
   - Percentage of frames in A that found near-matches in B.
   - Percentage in B that found matches in A.
   - Or: overlap duration / min(durationA, durationB).

2. **Visual similarity score:**
   - Average pHash similarity across overlapping region.
   - Later: SSIM or deep feature similarity.

3. **Audio score (if available):**
   - Binary (match / no match), or scaled based on fingerprint comparison.

Combine:

- Example heuristic:
  - `score = 0.4 * visual_coverage + 0.3 * visual_similarity + 0.3 * audio_score`.

Store:

```json
{
  "video_a": "...",
  "video_b": "...",
  "overlap_ratio": 0.42,
  "visual_score": 0.95,
  "audio_score": 1.0,
  "confidence": 0.90,
  "relationship": "full" | "subset" | "partial"
}
```

(Structure for the CLI to parse; actual schema is up to you.)

---

### 7.2 Winner Selection & Metadata-Based “Best Copy”

Once groups are formed, decide which file to keep.

Policy examples:

- **best_quality (default):**
  1. Higher resolution.
  2. Higher bitrate.
  3. Longer duration (when subset detection off).
  4. Larger file size (proxy for quality).
  5. Tie-breaker: oldest or newest based on user preference.

- Other policies:
  - `oldest`, `newest`, `smallest`, `largest`.

You already have this concept; just be sure it considers partial/subset relationships properly.

---

### 7.3 Verification Mode & Report

Introduce an explicit **verification mode** (even for non-dry runs):

1. Instead of directly deleting:
   - Generate a **report file** (JSON + optional Markdown).
   - Example structure:

     ```json
     {
       "groups": [
         {
           "group_id": "g1",
           "relationship": "full",
           "confidence": 0.98,
           "winner": { "path": "...", "reason": "best_quality" },
           "losers": [
             { "path": "...", "reason": "duplicate_lower_quality" }
           ]
         }
       ]
     }
     ```

2. CLI options:
   - `--verify-only`: produce report, do not delete.
   - `--apply-report path.json`: read report and apply deletions/moves.
   - `--threshold 0.95`: auto-apply only for confidence ≥ threshold; print others.

3. Optional interactive mode:
   - Iterate groups, ask:
     - “Keep [1] pathA or [2] pathB (confidence 0.97)? [1/2/s=skip]”

---

## 8. Scalability Tuning for Large Datasets (6 TB)

At this point, you have:

- Improved hashing and subset detection.
- Audio fingerprints.
- Confidence and reports.

Now ensure it scales.

### 8.1 Batch Processing & Streaming

- Do **not** load all frames of all videos in RAM.
- Process in batches:
  - E.g., process 100 videos at a time:
    - Extract frames → compute pHashes → update on-disk indices.
- Use streaming or pipes from FFmpeg to your process where possible (avoid dumping thousands of JPGs to disk unless necessary).

### 8.2 Parallelism

- Separate thread pools or process pools for:
  - IO-bound tasks (hashing, ffprobe).
  - CPU-bound tasks (pHash, Chromaprint).
- In CLI config:
  - `--threads` for CPU-bound.
  - `--io-threads` for IO-bound (if needed).

### 8.3 Index Persistence

Even before deep embeddings/FAISS:

- Persist your pHash indexes (hash buckets) for reuse.
- Potentially store them in:
  - Simple key-value store.
  - SQLite + custom Hamming search (later replaced by FAISS or BK-tree).

---

## 9. (Later Stage) Deep Visual Embeddings & FAISS

Only add this after all previous stages are stable. This is the **ML-heavy** part.

### 9.1 Deep Frame Embeddings

Use PyTorch with a pre-trained CNN (e.g., ResNet50):

1. Preprocess frames:
   - Resize to 224×224.
   - Normalize with ImageNet mean/std.
2. Run them through the model in evaluation mode:
   - Extract features from last pooling layer (e.g., 2048-D).
3. Optionally apply:
   - PCA to reduce to 128–256 dims.
   - L2 normalization.

Store per-frame embeddings (or aggregated per-video embeddings for coarse search).

---

### 9.2 FAISS Indexing

Use FAISS to index embeddings:

1. Build an index for **video-level** embeddings:
   - For quick, coarse matching of entire videos.
2. Optionally, a second index for **frame-level** embeddings:
   - For more accurate partial overlap detection.
3. Use approximate search (IVF, HNSW, PQ depending on scale).

Workflow:

- Balanced mode:
  - Use video-level index only.
- Thorough mode:
  - Combine:
    - Frame-level embedding search.
    - pHash sequence + embedding similarity for very robust detection.

---

### 9.3 SSIM as Final Validator

For borderline cases or high-value cleanup:

- Decode a handful of frames in overlapping regions.
- Compute **SSIM** between those frames using OpenCV.
- Reject pairs where SSIM is consistently low, even if embeddings/pHashes say “similar”.

This helps avoid weird false positives in extreme edge cases.

---

## 10. Summary of Implementation Order

**Recommended order of implementation:**

1. **Fix & clarify existing Q1/Q2 semantics** (no incorrect eliminations; BLAKE3 full hash).
2. **Align subset thresholds** with your 10% definition (or document divergence).
3. **Improve caching and ffprobe usage** for robustness and speed.
4. **Implement adaptive frame sampling** and a solid per-frame pHash system.
5. **Add pHash indexing & sequence-based subset detection** (non-ML).
6. **Introduce mode system (fast / balanced / thorough)** with proper config plumbing.
7. **Integrate Chromaprint for audio fingerprints** and combine with visual scores.
8. **Add confidence scoring, group-level decision logic, and verification/report mode.**
9. **Scale up batching, streaming, and parallelism** for large libraries.
10. **Finally, add deep CNN embeddings and FAISS indexing** for maximum recall in thorough mode.

Each step is useful on its own; you don’t need to finish all to get value. The CLI agent that reads this document should:

- Start by enforcing correctness and improving the current non-ML pipeline.
- Only then introduce audio and, lastly, PyTorch/FAISS-based enhancements.
`
