# Why Q1-3 Produces False Positives While Q1-2 Does Not

## Executive Summary

Quality `1-3` is expected to produce false positives because Q3 is a metadata-only detector and quality `3` stops before any visual or audio verification. Q3 can emit final duplicate groups based mainly on similar duration. That is not enough evidence to delete or move files.

Quality `1-2` looks good because Q2 only emits groups after full-file hash equality. Full-file hash equality is exact byte-level duplicate proof. Q3 has no equivalent content proof.

The core bug is not a crash or implementation typo. It is a detector design problem: Q3 is being used as if metadata similarity proves duplicate content.

## Evidence From the Code

### Quality 3 Maps to Stages 1-3

In `video_dedupe.py`, `_quality_to_pipeline("3")` maps to:

```python
"3": "1-3"
```

So when the user runs quality `3`, the pipeline executes:

- Q1 size bucketing
- Q2 partial/full hash exact duplicate detection
- Q3 metadata clustering

It does not execute Q4 pHash visual verification.

### Q3 Groups by Metadata, Not Content

In `pipeline.py`, Q3 probes videos with ffprobe and clusters them by duration buckets. The `_similar()` function requires duration proximity:

```python
if abs(a.duration - b.duration) > tol:
    return False
```

It can also require same resolution, codec, or container, but only if these config flags are enabled:

```python
if cfg.same_res and (a.width != b.width or a.height != b.height):
    return False
if cfg.same_codec and (a.vcodec != b.vcodec):
    return False
if cfg.same_container and (a.container != b.container):
    return False
```

The CLI currently builds `PipelineConfig` with these disabled:

```python
same_res=False
same_codec=False
same_container=False
```

Therefore, normal Q3 grouping is primarily duration-based.

### Q3 Scoring Is Still Metadata-Only

After clustering, Q3 calls `_score_metadata_cluster`. That function uses:

- duration proximity
- file size similarity
- resolution similarity
- codec/container hints
- bitrate similarity

These are useful candidate signals, but they are not proof of shared video content.

The default `metadata_score_floor` is `0.55`. This is a heuristic threshold, not a calibrated probability that two files are duplicates. Similar-duration unrelated videos can clear it, especially when size/bitrate/resolution are also similar.

### Q3 Accepted Groups Are Emitted as Duplicate Groups

When `_score_metadata_cluster` accepts a cluster, Q3 writes it into `groups`:

```python
groups[group_id] = filtered
```

Those groups later go through `choose_winners` and `write_report`, just like exact hash duplicates. This makes metadata candidates appear as actionable duplicate groups.

### Q3 Groups Can Block Later Verification

The pipeline excludes accepted Q3 groups from Q4:

```python
excluded_after_q3.add(_normalized_path(vm.path))
```

Then Q4 uses:

```python
pending_for_q4 = [v for v in video_for_q4 if _normalized_path(v.path) not in excluded_after_q3]
```

This means Q3 false positives can poison higher-quality runs too. If Q3 wrongly groups two unrelated videos, those videos may never reach visual verification in Q4.

## Why Q1-2 Is Reliable

Q1 is only size bucketing. The comments in `pipeline.py` correctly say Q1 is an optimization hint, not an elimination stage.

Q2 computes partial hashes first, but it does not emit duplicate groups from partial hash alone. Partial-hash collisions are escalated to full-file hashing. Groups are only formed when full hashes collide.

That means Q1-2 reports represent exact byte-level duplicates. This is why Q1-2 appears sane while Q1-3 produces nonsense.

## Why Q3 Produces Nonsense in Real Libraries

Many unrelated videos naturally share metadata:

- TV episodes from the same source often have nearly identical durations.
- Screen recordings may have similar lengths and bitrates.
- Camera clips from the same device can share resolution, codec, container, and bitrate.
- Downloaded videos from the same platform can share encoding presets.
- Exported clips from the same editor can share technical metadata.
- Different music videos, tutorials, or social clips can be near the same length.

None of these facts imply overlapping pixels or audio.

In the current CLI configuration, Q3 can group such files if duration is close enough and the metadata score passes. With no Q4 visual check, those groups go straight into the report.

## Higher Quality Levels May Still Be Affected

The user observed that anything above Q1-2 fails and that Q1-3 reports are full of nonsense. The immediate root cause is Q3. Higher quality levels can inherit the same problem because Q3 runs before Q4 and excludes accepted Q3 members from later stages.

Also, quality defaults widen `duration_tolerance` at higher levels:

- Base default: `2.0` seconds.
- Level 4: `3.0` seconds.
- Level 5: `4.0` seconds.
- Level 6: `5.0` seconds.
- Level 7: `6.0` seconds.

Wider tolerance means broader metadata clusters and higher false-positive risk if Q3 remains report-producing.

## Most Likely Failure Mechanism

The most likely false-positive path is:

1. User runs quality `3`.
2. Q1 scans size buckets.
3. Q2 finds exact byte duplicates correctly.
4. Q3 probes all videos not already excluded by Q2.
5. Two or more unrelated videos have close durations.
6. Optional strict metadata constraints are disabled.
7. `_score_metadata_cluster` accepts the cluster because metadata is similar enough.
8. The cluster is emitted as a duplicate group.
9. `choose_winners` selects one keep by longer/resolution/bitrate/newer/smaller/deeper.
10. `write_report` records the other files as losers.

No visual frame comparison or audio comparison is performed in this path.

## Recommended Fix Direction

### Short-Term Safety Fix

Do not allow Q3 to emit deletion-ready duplicate groups by default.

Preferred behavior:

- Q3 generates candidate pairs or candidate clusters.
- Q4+ verifies candidates with visual/audio evidence.
- Only verified groups are written as apply-ready report groups.

If Q3 report output is retained, it should be explicitly marked:

- low confidence
- metadata-only
- review required
- not apply-safe by default

### Pipeline Architecture Fix

Separate the pipeline into two concepts:

- Candidate generation: cheap, broad signals such as duration, metadata, size, coarse hashes.
- Verification: expensive, strong signals such as exact hash, dense pHash alignment, scene sequence matching, audio alignment.

Only verification stages should produce deletion-ready groups.

### Q3-Specific Hardening

If Q3 remains usable:

- Enable strict resolution/codec/container constraints by default for Q3-only runs.
- Raise `metadata_score_floor` substantially.
- Require size and bitrate similarity in addition to duration.
- Never exclude Q3 groups from Q4 unless Q3 is treated as verified, which it should not be.
- Add a report field like `confidence`, `detector`, and `review_required`.

These are mitigations, not a complete solution. Metadata-only duplicate detection remains unsafe.

### Tests to Add

Add hard negative tests proving Q3 does not emit final groups for unrelated videos:

- Same duration, different content.
- Same duration and same resolution, different content.
- Same duration, resolution, codec, and container, different content.
- Similar bitrate but different content.
- Same show/source format but different episode.
- Same intro/outro but different main content.

Add positive tests for real desired behavior:

- Exact duplicate detected by Q2.
- Short clip detected inside longer source.
- Re-encoded clip detected inside longer source.
- Same content at different resolution detected only after visual/audio verification.

## Bottom Line

Q1-2 is reliable because it depends on full-file hash equality. Q1-3 is unreliable because Q3 emits duplicate groups from metadata similarity alone. Metadata is useful for candidate generation, but it should not be final evidence for deletion or automatic loser selection.

