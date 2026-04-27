# vdedup Research Brief for Partial-Overlap Video Deduplication

## Purpose and Desired Outcome

`modules/vdedup` is a Python video and file deduplication module. Its practical goal is to scan one or more folders, identify duplicate or overlapping media, choose a preferred keeper, write a JSON report, and optionally apply that report by deleting or moving losers.

The user goal for future research is narrower and stricter than the current implementation: find videos that partially overlap and keep the longer, more complete, higher-quality video. Exact byte duplicates are useful, but the research priority is robust detection of partial video overlap, clips, re-encodes, and subsets without producing false-positive groups of unrelated videos.

The research LLM should assume it has source access and should read the module directly. This document is a guide to the architecture, current detection methods, known weaknesses, and research tasks.

## Repository Location and Shape

The module lives at:

`modules/vdedup`

The package is flat rather than nested under `modules/vdedup/vdedup`. Important files:

- `video_dedupe.py`: CLI entry point and top-level scan/apply orchestration.
- `pipeline.py`: staged detection pipeline and most duplicate/subset detection logic.
- `models.py`: `FileMeta` and `VideoMeta` data classes.
- `grouping.py`: winner selection from detected groups.
- `report.py`: report JSON writing, printing, collapsing, and apply-report operations.
- `report_models.py`: typed report loading for UI/report tools.
- `phash.py`: pHash extraction, adaptive sampling helpers, and visual fingerprints.
- `sequence_matcher.py`: diagonal-streak partial-overlap matcher concept, not currently integrated into the main pipeline.
- `scoring.py`: metadata/subset score cards and confidence payloads.
- `audio.py`: experimental audio fingerprint support.
- `tests/`: pytest coverage for pipeline stages, scoring, report handling, CLI validation, viewer behavior, and some media dataset workflows.

Existing research/design notes also exist in this folder, including `DETAILED_RESEARCH.md`, `DETAILED_RESEARCH_PLAN.md`, `VideoDeduplicationResearch.md`, and related planning docs. Treat them as context, not as proof that the implementation is correct.

## CLI and High-Level Flow

The CLI entry point is `video_dedupe.py`.

Typical scan flow:

1. Parse CLI args in `parse_args`.
2. Convert a quality setting to pipeline stages using `_quality_to_pipeline`.
3. Apply quality-dependent defaults with `_apply_quality_defaults`.
4. Build `PipelineConfig`.
5. Call `run_pipeline` from `pipeline.py`.
6. Merge groups if multiple root/depth scans are involved.
7. Choose winners with `choose_winners` from `grouping.py`.
8. Write a JSON report with `write_report` from `report.py`.

Typical apply flow:

1. Load a report with `apply_report`.
2. For each report group, keep the `keep` path and process `losers`.
3. Delete losers by default, or backup-move losers with `-b/--backup`.
4. Recent code also supports `-M/--folder-priority` in apply-report mode, which can move kept files into a priority folder tree before loser processing when safe.

The CLI quality mapping is:

- `1` -> stage `1`
- `2` -> stages `1-2`
- `3` -> stages `1-3`
- `4` -> stages `1-4`
- `5` -> stages `1-4`, with subset detection enabled by config
- `6` -> stages `1-6`
- `7` -> stages `1-7`

Important nuance: quality `5` does not map to an explicit stage 5. It maps to `1-4` and enables `subset_detect=True` based on inferred quality level.

## Data Model

`models.py` defines two core metadata objects:

- `FileMeta`: path, size, mtime, optional full hash and partial-hash fields.
- `VideoMeta`: extends `FileMeta` with duration, dimensions, container, codecs, bitrate fields, and optional pHash signature.

Pipeline outputs are group maps:

`{group_id: [members]}`

`pipeline.GroupResults` is a dict subclass that also carries:

`groups.metadata[group_id] = {...}`

Winner selection converts groups to:

`{group_id: (keep, losers)}`

Report JSON structure from `write_report`:

```json
{
  "summary": {
    "groups": 1,
    "losers": 1,
    "size_bytes": 1234,
    "by_method": {"unknown": 1}
  },
  "groups": {
    "hash:...": {
      "keep": "path",
      "losers": ["path"],
      "method": "unknown",
      "evidence": {},
      "keep_meta": {},
      "loser_meta": {}
    }
  }
}
```

Important weakness: report `method` is currently set via `getattr(keep, "method", "unknown")`. `FileMeta` and `VideoMeta` do not define `method`, so detector identity may be lost unless the consumer reads the group ID prefix or evidence metadata. This should be fixed or accounted for in any research/UX redesign.

## Winner Selection Policy

`grouping.py` chooses a keeper by sorting members with a configurable keep order. The current CLI uses:

```python
["longer", "resolution", "video-bitrate", "newer", "smaller", "deeper"]
```

This matches the user's desired direction: prefer longer, higher-resolution, higher-bitrate, newer, smaller, deeper-path files. For partial-overlap workflows, this is only safe if the detected group is truly an overlap/subset. Bad grouping will cause bad keep/delete decisions.

## Pipeline Stages

### Q1: Size Bucketing

Implemented in `pipeline.py`.

Q1 scans files and groups them by exact byte size. The code comments correctly state that size buckets are an optimization hint, not proof. Unique-size files still continue to later visual stages.

Usefulness:

- Good for prioritizing exact duplicate candidates.
- Not evidence of duplicate content by itself.

Risk:

- If ever exposed as final duplicate evidence, it would be unsafe. Current pipeline appears to use it as an optimization for Q2.

### Q2: Partial Hash to Full Hash

Implemented in `pipeline.py`.

Q2 first computes bounded partial hashes using BLAKE3 where available. It reads head and tail slices, currently with no middle slice. Partial-hash collisions are escalated to full-file BLAKE3 or SHA-256. Only full-hash collisions form report groups.

Usefulness:

- High confidence for exact byte duplicates.
- Q1-2 output is expected to be reliable because a final group requires full-file hash equality.

Limitations:

- Cannot detect re-encoded duplicates.
- Cannot detect clips/subsets.
- Cannot detect partial overlaps unless the files are byte-identical and same length, which is not the target use case.

### Q3: ffprobe Metadata Clustering

Implemented in `pipeline.py`.

Q3 probes videos and clusters them by metadata. The current clustering starts with duration buckets based on `duration_tolerance`. `_similar()` requires:

- Both videos have duration.
- Absolute duration difference is no greater than tolerance.
- Resolution equality only if `cfg.same_res` is true.
- Codec equality only if `cfg.same_codec` is true.
- Container equality only if `cfg.same_container` is true.

The CLI currently builds:

```python
PipelineConfig(
    same_res=False,
    same_codec=False,
    same_container=False,
    ...
)
```

So in normal CLI use, Q3 grouping is primarily duration-based. `_score_metadata_cluster` then scores duration, size, resolution, codec, container, and bitrate, but this score is still metadata-only. It is not visual or audio proof.

Usefulness:

- Candidate generation.
- Useful for narrowing expensive visual/audio comparisons.
- Useful as a low-confidence review signal.

Major risk:

- Unsafe as a final duplicate detector. Similar duration and encoding metadata do not prove shared content.
- This is the likely reason quality `3` produces reports full of unrelated videos.

### Q4: pHash Visual Similarity and Optional Subset Detection

Implemented in `pipeline.py` and `phash.py`.

Q4 computes pHash signatures by extracting a small number of frames and comparing Hamming distances. Same-length visual grouping compares signatures in aligned order. Optional subset detection is enabled by config, not directly by stage 5.

Current pHash signature extraction:

- `compute_phash_signature(path, frames=cfg.phash_frames, gpu=cfg.gpu)`
- Uses ffprobe duration.
- Samples multiple frames.
- Batch extraction attempts are in `phash.py`.

Current subset detection:

- Sort videos by duration.
- Compare shorter to longer.
- Gate by `subset_min_ratio` and skip ratios above `0.95`.
- Use `_alignable_distance` over pHash signatures.
- Record subset metadata through `_record_subset_metadata`.

Weaknesses:

- Sparse, fixed-size pHash signatures are weak for arbitrary partial overlaps.
- A 5-frame or 12-frame signature is too low-resolution for reliable temporal localization.
- `_alignable_distance` compares short sequences of sampled frames, not dense temporal fingerprints.
- Matching can be sensitive to intros/outros, black frames, repeated scenes, overlays, cuts, and frame extraction choices.
- Current Q3 groups are excluded from Q4, so metadata false positives may prevent visual verification in higher-quality pipelines.

### Q5: Scene-Aware Matching

Implemented as an experimental stage in `pipeline.py`, using `compute_scene_fingerprint` from `phash.py`.

It compares scene fingerprints for near duplicates and subset-like matches. It uses `_alignable_distance` and subset metadata recording. This is promising but still appears heuristic and not clearly calibrated.

### Q6: Audio Matching

Implemented as an experimental stage in `pipeline.py`, using `compute_audio_fingerprint` from `audio.py`.

This may be valuable for partial-overlap detection, especially where visuals differ due to crop/resolution/re-encode but audio is shared. It also has risks: music, silence, repeated intros, and dubbed/edited audio.

### Q7: Timeline Matching

Implemented as an experimental stage in `pipeline.py`, using `compute_timeline_signature` from `phash.py`.

This is closer to a robust temporal method because it samples more frames over time. It still needs careful indexing, alignment, confidence scoring, and false-positive control.

## Current Partial-Overlap Strategy

The current pipeline contains several partial-overlap concepts:

- Duration-ratio gating: a short video must be a minimum fraction of the long video.
- `_alignable_distance`: slides a shorter pHash signature over a longer one and accepts if average per-frame Hamming distance is below an adaptive threshold.
- `_record_subset_metadata`: records shorter, longer, overlap seconds, overlap ratio, pHash distance, frame offset, and scoring details.
- Report overlap hints: `write_report` can store overlap hints into `keep_meta` and `loser_meta`.
- `sequence_matcher.py`: implements a diagonal-streak approach over frame-level pHash matches, but it is not integrated into `run_pipeline`.

The most important research direction is to separate candidate retrieval from verification. Metadata and coarse hashes can propose candidate pairs. A real partial-overlap verifier should then prove temporal alignment with enough evidence before a report group is eligible for deletion.

## Existing Sequence Matcher Concept

`sequence_matcher.py` describes a better direction:

1. Build frame-level fingerprints for videos.
2. Find matching frame pairs using a pHash index.
3. Search for diagonal streaks where frame indices in both videos increase together.
4. Convert the best streak to overlap duration and timestamps.
5. Accept only if overlap duration or ratio passes a threshold.

This is a better conceptual fit than Q3 metadata clustering or sparse fixed-frame pHash tuples. The research LLM should inspect whether `PHashIndex`, `VideoFingerprint`, and `SequenceMatcher` can be integrated into `run_pipeline` as a verifier.

## Key Known Gaps

- Q3 is content-free and unsafe as a report-producing final detector.
- Q3 accepted groups are excluded from Q4, so false positives can block visual verification.
- Report `method` often becomes `unknown` because group detector identity is not attached to `FileMeta` or `VideoMeta`.
- Metadata score is not calibrated as a probability of duplicate content.
- There is no clear distinction between candidate groups, verified duplicate groups, and review-only groups.
- Partial-overlap matching does not appear to use dense enough temporal evidence for reliable deletion decisions.
- Existing tests validate mechanics but do not appear to include enough hard negative media cases: unrelated same-duration videos, repeated intros, same show episodes, common black frames, same resolution/bitrate unrelated exports, and short clips from different source videos.

## Research Instructions for Another LLM

Read the source code and propose a safer architecture for partial-overlap detection. Prioritize low false positives over recall, because this tool can delete files.

Treat these as confidence levels:

- Q2 full-file hash equality: high confidence exact duplicate.
- Q3 metadata similarity: candidate only, not proof.
- Q4 sparse pHash similarity: candidate or moderate evidence depending on sampling density and alignment proof.
- Q5-Q7 scene/audio/timeline: experimental; evaluate empirically before deletion use.

Research and propose improvements in these areas:

- Candidate generation:
  - Use metadata, duration, resolution, file size, and coarse pHash only to reduce pair counts.
  - Avoid emitting final deletion groups from candidate-only signals.
- Visual verification:
  - Dense temporal frame fingerprints.
  - Diagonal sequence alignment/streak detection.
  - Robust frame hashes, crop-resistant hashes, or embeddings.
  - Scene-boundary-aware fingerprints.
  - SSIM or perceptual similarity checks on aligned candidate frames.
  - CLIP or modern vision embeddings for harder re-encodes, if practical.
- Audio verification:
  - Chromaprint/AcoustID-style fingerprints.
  - Robust audio alignment as a second independent signal.
  - Handling silence, intros, music, and dubbed/edited audio.
- Indexing:
  - LSH/FAISS/Annoy or similar nearest-neighbor indexing for frame or scene descriptors.
  - Avoid all-pairs comparison for large libraries.
- Confidence scoring:
  - Require multiple independent matching frames in temporal order.
  - Require minimum overlap duration and ratio.
  - Record start/end timestamps and confidence.
  - Calibrate thresholds against real positive and negative datasets.
- Report/apply safety:
  - Add detector identity, confidence, review-required status, and evidence summary to reports.
  - Prevent `apply_report` from deleting low-confidence or review-only groups unless explicitly forced.
  - Prefer dry-run and viewer workflows for non-exact duplicates.

## Suggested Future Acceptance Criteria

A safer future version should satisfy:

- Q1-2 exact duplicate reports remain high confidence.
- Q1-3 does not produce deletion-ready groups from metadata alone.
- Partial-overlap reports include actual overlap timestamps and evidence.
- The tool can identify a short clip inside a longer source while keeping the longer source.
- The tool rejects unrelated videos with same duration, same resolution, similar bitrate, same codec, and similar file size.
- Report consumers can distinguish exact hash duplicates, visual near-duplicates, subset overlaps, and low-confidence candidates.

