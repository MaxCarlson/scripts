Break it up. I would **not** ask the other LLM to plan against the whole GPU document at once. It is too broad, and it will likely either over-plan, miss safety details, or start implementing Q6/deep embeddings before Q4G/Q5G are correct.

Use the full document as the **reference spec**, but give the other LLM one scoped planning task at a time.

## Recommended chunking

### Plan 0 — Safety semantics cleanup

This should happen first.

**Goal:** make `REVIEW` a report/viewer label only, while keeping candidate-only groups impossible to apply.

Ask it to plan changes for:

```text
report.py
report_models.py
report_viewer.py
video_dedupe.py
tests/*
```

Acceptance criteria:

```text
candidate_only=true is never applyable
actionable=false is never applyable
actionable=true + review_required=true is applyable
review_required groups display REVIEW in report view
-F is removed, deprecated, or no-op
```

---

### Plan 1 — GPU capability and routing foundation

**Goal:** add GPU detection without changing detection behavior yet.

Ask it to plan:

```text
gpu_capabilities.py
PipelineConfig GPU fields
--gpu auto|on|off
fallback behavior
tests
```

Acceptance criteria:

```text
CPU route remains default-safe fallback
--gpu off always uses CPU
--gpu on fails if CUDA/PyNvVideoCodec unavailable
--gpu auto falls back cleanly
no Q4+ algorithm changes yet
```

---

### Plan 2 — Q4G GPU frame sampling + fingerprint extraction

**Goal:** decode sampled frames and compute GPU hashes, but do not yet make complex deletion decisions.

Ask it to plan:

```text
gpu_sampling.py
gpu_decode.py
gpu_fingerprint.py
VideoSignature / FrameSignature models
cache design if feasible
tests
```

Acceptance criteria:

```text
deterministic frame sampling
GPU decode when available
CPU fallback when allowed
dHash64 or pHash64 computed in batches
low-entropy frames marked invalid
signatures can be serialized/deserialized
```

This is the first big implementation chunk.

---

### Plan 3 — Q4G coarse duplicate detection

**Goal:** use GPU fingerprints to emit only high-confidence full-video perceptual duplicates and candidate pairs.

Ask it to plan:

```text
gpu_index.py
gpu_pipeline.py
pipeline.py integration
report evidence contract
tests
```

Acceptance criteria:

```text
full re-encode can be detected
unrelated same-duration videos do not group
Q3 candidates can prioritize Q4G work
uncertain visual matches become candidates, not apply-safe groups
report groups include backend/match_type/evidence
```

---

### Plan 4 — Q5G temporal alignment

**Goal:** detect subset/overlap from frame-signature sequences.

Ask it to plan:

```text
gpu_alignment.py
TemporalAlignmentResult
classification rules
report conversion
tests with synthetic subset fixtures
```

Acceptance criteria:

```text
short clip inside longer video is detected
full duplicate vs subset vs partial_overlap are distinguished
same intro/different body is not full duplicate
partial_overlap is REVIEW/non-default-safe
timestamp ranges appear in evidence
```

---

### Plan 5 — Q6G deep embeddings, later

Do **not** ask for this until Q4G/Q5G work.

**Goal:** handle crop/watermark/color/compression hard cases.

Ask it to plan only after the first four plans are implemented and tested.

## Best instruction to give the other LLM

Use something like this:

```text
Use the attached GPU acceleration reference spec as background only. Do not implement the whole thing.

Generate a detailed implementation plan for Plan 0 only: safety semantics cleanup.

Focus on the current repo state and produce:
1. files to modify
2. exact behavior changes
3. data model/report JSON changes
4. CLI changes
5. tests to add/update
6. risks and compatibility notes

Do not plan GPU code yet.
Do not change Q4+ algorithms yet.
Preserve the current public CLI unless the spec explicitly requires a change.
```

Then repeat for Plan 1, Plan 2, etc.

## My recommended execution order

```text
0. Safety semantics cleanup
1. GPU capability/routing foundation
2. GPU sampling + decode + fingerprint extraction
3. Q4G coarse duplicate detection
4. Q5G temporal alignment
5. Q6G deep embeddings
```

The most important split is between **Plan 2** and **Plan 3**. First prove you can reliably extract and cache GPU signatures. Only then use them to emit duplicate groups.

