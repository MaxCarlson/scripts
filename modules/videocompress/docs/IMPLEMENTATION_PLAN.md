# Final Implementation Handoff — Estimation-First Video Compression for `scripts`

**Status:** Proposed, independently researched engineering specification; **planning only**, not authorization to edit, commit, publish, or process a production library.  
**Prepared:** 2026-10-23 (America/Los_Angeles).  
**Repository:** [`MaxCarlson/scripts`](https://github.com/MaxCarlson/scripts).  
**Remote baseline inspected:** `main` at `a0ff1778ef1737f1c23d8f1cbd7ef57d4973af75`, committed 2026-10-20.  
**Primary environment for acceptance:** Windows 11, PowerShell 7, NVIDIA RTX 5090, substantial HDD-based media collections; portability to WSL2/Linux and other platforms should be considered, but **must not be claimed without tests**.

**Companion engineering contracts (this handoff package):**

- [`ESTIMATION_BENCHMARK_PROTOCOL.md`](ESTIMATION_BENCHMARK_PROTOCOL.md) — locked ground truth, estimator comparisons, uncertainty, compute budgets and decision gates.
- [`MEDIA_SAFETY_CONTRACT.md`](MEDIA_SAFETY_CONTRACT.md) — non-destructive invariants, stream/metadata preservation, journal states and recovery tests.
- [`INTEGRATION_CONTRACTS.md`](INTEGRATION_CONTRACTS.md) — module boundaries, typed schemas, CLI/TUI dispatch and compatibility gates.

Read these alongside the main plan. They are proposed contracts for independent agent review; where an implementation detail conflicts with current source code or independently validated findings, document and resolve the conflict before coding. Neither this document nor its companions authorizes commits, publication or media writes.

> **READ FIRST — instruction to the local agent.** Independently re-read the live repository, active instructions, tool capabilities, and the sources linked below before implementing. This document is a hypothesis-driven plan, **not gospel**. Challenge design choices and research assumptions; document better alternatives. Source and test evidence supersede this document. The user has requested a final plan for handoff, **not blanket authorization to modify code, commit/push/merge, or write to media collections**. Obtain the necessary approval gates under `AGENTS.md`. Never silently turn an analysis operation into an encoding or destructive operation.

---

## 0. Executive decision

**Build a media-aware decision and compression system, not an exhaustive video encoding matrix.** Retain the existing image-compression workflow. Create a standalone `videocompress` backend integrated under `compresser video`, and separately add `compresser tui` via the already implemented `cli_tui` package.

The default video workflow is:

```text
Fast complete inventory (no encodes)
  -> user-selected lower-bound eligibility filters
  -> cheap, explicitly uncertain prediction / feasibility checks (no encodes)
  -> a deterministic plan with a displayed work budget
  -> selective short-segment trial encodes only with explicit opt-in
  -> quality and size analysis, with evidence/calibration status
  -> optional previews and a few selected full-file calibration runs
  -> independently authorized, verified, journaled apply/recover
```

**Primary requirement:** Determine *whether* a video can be compressed enough, at adequate quality and acceptable cost, **before** spending hours transcoding it. An inability to give a defensible prediction should be reported as `insufficient_evidence`, not disguised with an arbitrary codec efficiency ratio.

### Non-negotiable goals

1. Reuse existing `scripts` foundations without breaking `compresser` images or MangaDL.
2. Support user-configurable minimum **source video bitrate** and **resolution**, plus size/duration/codec constraints; also support separately configured **minimum projected benefit**.
3. Inventory complete media metadata, separating video, audio, subtitles, attachments, container and missing values.
4. Make no-target-encode analysis available, but distinguish low-confidence screening from verified prediction.
5. Use bounded, resumable, stratified sample encodes where needed; compare alternatives on empirical *accuracy per compute cost*.
6. Predict final container bytes and quality *honestly*, accounting for nonvideo stream retention and audio/container overhead.
7. Preserve source files, stream structure, timing and metadata, or fail/skip transparently.
8. Provide a real `compresser tui` for **both image and video workflows** using `cli_tui`, without forcing TUI dependencies on ordinary CLI usage.
9. Prefer correctness, auditability and reversibility over throughput; make every costly action and media mutation explicit.

### Explicitly out of scope initially

Full scene-adaptive transcoding, distributed encoding, a bespoke video player, arbitrary mid-file transcode resumption, DRM bypass, automatic HDR/Dolby Vision source replacement without validation, bulk auto-conversion of unknown source formats, a required ML/PyTorch runtime, and refactoring the entirety of the image-compression core before a video prototype works.

---

## 1. Pre-implementation instructions and ownership

Before changes, the agent must:

1. Run `git status`, determine current branch/worktree, current revision, submodule limitations and unrelated local changes. Do not overwrite others' work. Use a separate worktree/branch **only if creating one is explicitly authorized**.
2. Read `AGENTS.md`, `REPO_LLM_INSTRUCTIONS.md`, `docs/agent/PYTHON_REPO_STANDARDS.md`, `docs/agent/SCRIPTS_REPO_STANDARDS.md`, and module-specific active instructions/handoffs/plans and tests. Also inspect `docs/agent/HYBRID_REMOTE_LOCAL_DEVELOPMENT_WORKFLOW.md` for execution split.
3. Reinspect source paths in §2 and record any drift since the audited commit. Files and tests override historical handoffs.
4. Create or propose a dated plan under `docs/plans/YYYYMMDD-HHMM_video-compression/` (cross-module scope); include `00_implementation-plan.md`, `STATUS.md`, `checklist.md`, and a decision record; once `videocompress` exists, its module-owned design docs may live under `modules/videocompress/docs/`.
5. In Stage 0, evaluate a native FFmpeg backend and an optional `ab-av1` subprocess adapter; do not assume the initially proposed split is optimal.
6. Establish baseline passing tests before modifying shared `compresser`, `cli_tui`, `cross_platform`, or other code. Follow local-module pytest temp-root rules and version/registry requirements.
7. Report the revised plan and requested approval boundary. Only then proceed with authorized stages, pausing at high-risk validation gates.

**Repository packaging conventions:** Each public CLI option has short/long spellings; package `[project]` version and exposed `__version__` must agree; adding/renaming console entry points requires reinstall/version handling under `SCRIPTS_REPO_STANDARDS.md`; register the new command in `modules/scripts_help/scripts_help/registry/registry.py`. Prefer `termdash` for reusable terminal widgets. Do not assume an unapproved branch can be committed or pushed.

---

## 2. Verified repository starting points and hazards

The following was inspected on the referenced remote `main`; the local agent must reconfirm current source.

| Component | Existing useful capability | Constraint/action |
|---|---|---|
| `modules/compresser` (`3.2.0` in `pyproject.toml`/`__init__.py`) | `inventory`, `plan`, `estimate`, `analyze`, `compare`, `preview`, `apply`, `recover`; deterministic bounded trials, SQLite caches, reports, snapshots, locks/recovery | The codec engine handles Pillow image objects and encoded **bytes**; recipes, sampling, measurement and workspace ownership are image-specific. Do not blindly reinterpret image models as video models. |
| `modules/compresser/compresser/cli.py` | Standalone argparse operation tree | `build_parser()` registers the image-only operations; `main()` normalizes as image options immediately after parse. Dispatch a `video` subtree and `tui` **before** image-only normalization. The file has an embedded CLI `__version__ = '2.0.0'` while package says `3.2.0`: verify/reconcile version display. |
| `modules/compresser/compresser/{estimation_models.py,sampling_plan.py,measurement.py,estimation_stats.py}` | Typed frozen plans, fixed-design pilot/confirmation estimator, measured observation provenance | `PopulationView` owner and recipe validation are image-oriented; `MeasurementJob` opens `PIL.Image`; don't reuse the executor for video. Existing `--accuracy-pp` sequential-precision stopping is explicitly unimplemented. |
| `modules/compresser/compresser/{workspace.py,transactions.py,cache.py}` | Versioned workspace, source checks, journals, locking and trial persistence | Workspace owner is restricted (`compresser`, `mangadl-pages`); publisher handles image bytes and image extension changes. Video requires distinct identity/schema and file-backed publication. |
| `pyscripts/video_processor.py` (909 lines) | FFprobe inspection, x264/x265, H.264/HEVC NVENC, CRF/CQ, presets, filters, concurrency, FFmpeg progress and termination helpers | Builds FFmpeg with `-y` (overwrite), flattens output to `output_dir / video.path.name` (collisions), lacks complete stream-preservation verification, and contains an unconditional-looking MP4 `+faststart`. Extract/test useful methods, **not** the entire script. |
| `modules/vdedup` | Video probe, fingerprinting, GPU/video metadata handling | Its `probe.py` focuses on selected video streams; insufficient for complete audio/subtitle/attachment inventory. Full package declares heavy `torch`, `torchvision`, `PyNvVideoCodec` dependencies—do not require them for normal FFmpeg NVENC. |
| `modules/video_dataset_tools` | FFmpeg-based controlled media transformations | Use for synthetic varied-media fixtures and repeatable regression tests. |
| `modules/cross_platform/locks.py` | OS-backed folder read/write coordination, process identity and lock inspection, external target-scoped lock paths | Reuse. Never delete a persistent lock just because it exists. Validate independent targets work concurrently and overlapping write scopes are serialized. |
| `modules/benchmark_core` | Typed trial results and comparisons | Reuse metric/report contracts, **not** scheduling or subprocess orchestration. Its own `AGENTS.md` requires backward compatibility with `agent_benchmark`. |
| `modules/termdash` | Progress, tables, in-place display | Reuse for batch and quality benchmarking. |
| `modules/cli_tui` (`0.1.0` metadata) | Argparse introspection, forms, multi-pane runs, ANSI capture, custom post-run actions, image preview viewer | Already present; `modules/mangadl/mangadl/tui.py` is a working design example. The viewer is **image-only**. See Windows/cancellation risks in §11. |
| `modules/scripts_help` | Central CLI registry | Register new `videocompress` console command; update versions as needed. |

**Avoid a monolithic core migration.** First implement the video backend with clear interfaces; factor out `compression_core` components only after demonstrating that shared models do not inherit image-specific assumptions. Maintain image command paths, schemas, cache contents, error semantics and tests.

---

## 3. Proposed package and command architecture

```text
modules/
  compresser/compresser/
    cli.py                   # Route video/tui before image-only normalization
    tui.py                   # Optional wrapper of cli_tui; reuse image parser
    ...                      # Existing image operations remain stable
  videocompress/
    pyproject.toml
    videocompress/
      cli.py                 # Standalone argparse operations
      contracts.py           # Typed inventory, recipe, trial, plan, journal models
      discovery.py           # Scoped file finding + exclusions + fingerprinting
      probe.py               # FFprobe JSON for full stream/format/chapters
      inventory.py           # Incremental/versioned SQLite and reporting
      eligibility.py         # Staged metadata, compatibility and benefit filters
      capabilities.py        # FFmpeg/encoder/filter/model/driver feature probes
      recipes.py             # Codec-specific recipes and validation
      sampling.py            # Population selection + temporal windows
      estimators.py          # Fast priors / sampled predictions / calibration
      adapters/
        ffmpeg.py            # Source of truth for controlled FFmpeg execution
        ab_av1.py            # Optional strict NDJSON adapter (if justified)
        quality.py           # VMAF/XPSNR/SSIM backends
      trials.py              # Bounded jobs, caching, idempotent measurements
      scheduler.py           # CPU/NVENC/disk/scratch quotas
      preview.py             # Clips + manifests, external player support
      publication.py         # File-backed staging/validation/journal
      recovery.py            # Explicit state inspection/repair
      reporting.py           # CLI JSON/Markdown/termdash outputs
    tests/
    docs/
```

Names are **proposed**, not locked. An agent may merge responsibilities that are tightly coupled. Imports must not make the image CLI depend on GPU, Torch, FFmpeg, VMAF, or `ab-av1` for its normal operation.

**Proposed command tree:**

```text
compresser inventory|plan|estimate|analyze|compare|preview|apply|recover  # Existing images
compresser video capabilities|inventory|plan|estimate|analyze|compare|preview|apply|recover
compresser tui
vcompress capabilities|inventory|plan|estimate|analyze|compare|preview|apply|recover
```

Treat `vcompress` as a standalone convenience entry point using the **same** backend. The `tui` may be added independently of the video implementation; the video menu appears only when usable/installed. Avoid adding video operations to MangaDL's gallery-specific `compress` logic: MangaDL is a downloader/collection workflow, not the owner of general video compression.

**Logical workspace:** outside the target tree, separated from image data, with canonical target ownership and schema version:

```text
<analysis-parent>/.videocompress/<target-identity>/
  workspace.json
  inventory.sqlite3
  trials.sqlite3
  plans/
  reports/
  previews/
  jobs/
  journals/
```

Use a normalized/path-hashed identity to prevent two paths with identical last components from colliding, and keep the owner/type and source identity in the manifest. Plan/trial cache invalidation must be explicit. Reject workspaces located inside the input tree and unowned pre-existing artifact directories; guard symlinks/hardlinks and inode/path aliasing.

---

## 4. Required inventory and eligibility model

### 4.1 Inventory depths

- **`files`** — recursive paths, extension candidates, bytes, timestamps, filesystem identity, suspected duplicates, error states; minimum disk work, no decoder or encoder.
- **`probe`** — FFprobe format/streams/chapters/disposition/tag JSON per file, no target encoding; default descriptive video inventory.
- **`deep` (optional)** — explicit bounded packet/frame accounting or sparse decode for missing stream bitrates, difficult timestamp/VFR validation and complexity proxies. **May perform substantial sequential I/O**; it is not equivalent to cheap FFprobe headers.

For each file, retain at least:

- `relative_path`, canonical scope, source file bytes, container/format names, extension, file timestamps, fingerprint method, probe result/diagnostics and schema/runtime identities.
- Container duration, total/container bitrate (if available), mux metadata, chapters, seekability and errors.
- **Every** video stream: index, codec/profile/level, pixel dimensions, sample/display aspect ratio, rotation/display matrix, duration/time_base, nominal and average FPS, variable-frame-rate indicators if known, bit depth, pixel format, interlacing, color range/primaries/transfer/matrix, HDR flags and side data; separate thumbnail/cover-art streams from real video tracks.
- **Every** audio stream: codec, bitrate (with provenance), channels/layout, language, sample rate, sample format, duration, default/forced dispositions and metadata.
- Subtitle, data and attachment streams; codec, language, disposition, font attachments, packet/track metadata, chapter and track ordering.
- Unknown versus measured versus estimated fields; `ffprobe` stream `bit_rate` may be missing, stale, or inaccurate. Report where values originate.
- Derived: `bits_per_pixel_per_frame = video_bps / (display_width * display_height * fps)` only when all components are valid; avoid interpreting this as an objective quality measurement.

The initial implementation should treat multivideo, HDR/Dolby Vision, unusual interlaced and unsupported stream combinations as **discoverable and countable**, but possibly *ineligible for automatic conversion*. An inventory is not allowed to make risky files disappear.

### 4.2 User-configurable lower-bound filters

Provide independently combinable settings, with documentation and short/long CLI spellings:

1. **Minimum video-stream bitrate** in bits/s with decimal `M`/`k` notation (e.g. 4M). **Do not substitute container bitrate**. Missing bitrate produces `unknown_video_bitrate` and follows an explicit policy (`exclude` by default for a hard bitrate floor, `probe-deeper` optional).
2. **Minimum resolution**: `WIDTHxHEIGHT` with a documented *both-dimensions* default rule after display rotation. Also allow a minimum pixel count (`megapixels` or raw pixels) if useful for portrait and ultrawide assets; do not infer visual quality from pixels alone.
3. Minimum file size and duration; optional maximums; source codec/container include/exclude selectors; optionally FPS.
4. **Distinct economic gate**: minimum predicted *relative* and/or *absolute* savings, e.g., `% AND bytes` with explicit AND/OR policy. Preserve uncertainty handling (`candidate`, `uncertain`, `unlikely`, `infeasible`) instead of discarding borderline cases based on a point estimate alone.
5. Post-measurement gating: measured sample quality, projected time/energy, compatibility policy and quality failure risk.

**Filtering stages:** raw file discovery → probed metadata → cheap benefit screening → measured quality/savings decision → apply eligibility. A filter must not trigger more expensive work unless permitted by that operation and budget. Excluded/unknown/error item **counts, bytes and reasons** are part of all reports. Unknown bitrate is distinct from bitrate 0. Video bitrate must refer to the selected *real video* stream, not attached artwork; ambiguous multiple video streams should be skipped or require an explicit primary-track policy.

### 4.3 Sample source records (illustrative machine schema)

```json
{
  "schema_version": 1,
  "source_id": "sha256-of-canonical-identity-and-fingerprint",
  "relative_path": "Shows/Season 1/Episode 01.mkv",
  "file_bytes": 3250048000,
  "duration_seconds": 3600.0,
  "format_names": ["matroska", "webm"],
  "streams": [
    {"index": 0, "type": "video", "codec": "h264", "width": 1920, "height": 1080,
     "fps_num": 24000, "fps_den": 1001, "bitrate_bps": 6900000,
     "bitrate_provenance": "ffprobe_stream", "pix_fmt": "yuv420p", "hdr": "none"},
    {"index": 1, "type": "audio", "codec": "aac", "bitrate_bps": 192000,
     "bitrate_provenance": "ffprobe_stream", "language": "eng"}
  ],
  "eligibility": {"status": "eligible", "reasons": []},
  "probe": {"status": "complete", "tool_identity": "record-exact-version-hash"}
}
```

This example is **a proposed API shape, not real user data**. Separate source identity, content hashing policy and fingerprint provenance. Do not hash every multi-GB video merely to list it: use size/mtime/identity for provisional freshness and stronger hashes before source mutation/critical publication.

---

## 5. Estimation model: accurate arithmetic, honest uncertainty

### 5.1 Define three different questions

**A. What is the current source made of?** FFprobe inventory; cheap and factual where probe values are reliable.

**B. How large might the new codec output be?** A **conditional prediction** on source content + target encoder + preset/rate control + encoding policy. This is not determined by source bitrate alone at constant quality.

**C. Is conversion desirable?** An economic and quality decision involving saved bytes, visual-quality risk, encode time/energy, device compatibility, retention policy and user thresholds. A statistically promising size estimate alone is not permission to convert.

**Key generational-loss caveat:** An encoded file being compared to the user's already-lossy source can achieve high full-reference metric similarity but cannot restore fidelity lost by the original encoder. Automatic perceptual metrics do not guarantee freedom from new visible artifacts.

### 5.2 Exact size decomposition

Use real bytes consistently. For a target video `i`, define:

- `S_i`: current **whole container file bytes**.
- `T_i`: presentation duration seconds (with origin/precision noted).
- `Vhat_i(r)`: estimated output **video elementary-stream** bytes for target recipe `r`.
- `Ahat_i(r)`: retained/re-encoded **nonvideo stream payload** bytes (audio, subtitle, attachment/data; never omit required streams silently).
- `Hhat_i(r)`: output container/metadata/index overhead bytes (and any extra bitrate/size overhead not already in payload accounting).
- `Ohat_i(r) = Vhat_i(r) + Ahat_i(r) + Hhat_i(r)`: estimated finished file bytes.
- `Ghat_i(r) = S_i - Ohat_i(r)`: predicted gross saved bytes, potentially **negative**; policy may then retain source instead.
- `net_savings_i(r) = max(0, Ghat_i(r))` **only** when representing an explicit keep-original-if-larger policy; do not erase negative estimates in underlying records.

For a known target video bitrate `b` in bits/s, the first-order relation is `Vhat ≈ b * T / 8`. This predicts approximate bytes **conditional on achieving that bitrate**, not acceptable quality. For CRF/CQ or target-perceptual-quality encoding, the bitrate itself needs estimation or actual trial evidence. Multi-pass constrained bitrate control may still deviate from the target, especially on very short/complex streams.

Given required fraction `f` saved from source and predicted nonvideo/overhead bytes, the maximum video-bit budget is:

`b_video_max = 8 * ((1 - f) * S - Ahat - Hhat) / T` for `T > 0`.

If `((1 - f) * S - Ahat - Hhat) <= 0`, the requested savings are **infeasible** with current mandatory stream-preservation policy; otherwise bitrate feasibility **does not imply visual feasibility**. Report estimated `Ahat/Hhat` provenance and uncertainty; stream packet accounting may require a costly full-file scan.

### 5.3 Estimation tiers and allowed operations

| Tier | Computational work | Meaningful result | Defaults/policy |
|---|---|---|---|
| **0 Inventory** | `stat`, FFprobe metadata | Current source facts and eligibility; no compressed-size claim | `inventory` only, no target encoding |
| **1 Cheap prediction** | Cohort priors, calibrated metadata model, feasibility arithmetic | Exploratory size range, candidate rank and reasons; **abstain** when no reliable model | `plan`/`estimate --tier metadata`; zero target encodes |
| **2 Complexity features** | Selective source decode: texture/noise/motion/scene statistics or VCA | Improved conditional predictions if experimentally validated | Optional, per-asset cost recorded |
| **3 Short clip encoding** | Bounded FFmpeg/`ab-av1` actual segments, versioned recipes and metrics | Recipe-specific output bitrate/quality/time measurements with sampling error | Explicit sampling budget + consent; first reliable estimate baseline |
| **4 Full-file calibration** | Small representative complete encodes | Empirical estimator bias, full-container accounting, latency and quality | Selected pilot/holdout files only, non-destructive |
| **5 Apply** | Full encode and exhaustive validation | Actual measured savings and quality policy outcome | Separate, explicitly authorized write operation |

**Important default:** Inventory and plan must **never** encode. The initial `estimate` UX should default to a fast no-encode mode or require explicit `--tier sampled` and a displayed max-budget before invoking sample encoding. Exact tier and default selection are agent decisions based on UX/tests; never hide encoding work.

### 5.4 No-target-encode estimators worth testing

1. **Source/target codec cohort priors:** Empirical distributions for (`source codec`, resolution, fps, source bpppf, target encoder/preset/rate-control, quality policy, content class). User-specific, versioned records are preferred. Cold-start must return very wide/unverified uncertainty or `no_supported_prior`, not claim a precise 50% reduction.
2. **Metadata regression:** Model target `log(output video bytes)` or normalized bits/second, using codec pair, bitrate, duration, resolution, fps, bit depth, grain proxies and recipe. Use regularized/simple baselines, robust validation and source-grouped holdouts before considering ML frameworks. Distinguish a useful model from a mere prior; stop if added complexity does not beat baseline.
3. **Complexity features:** DCT/spatial/temporal features, sparse decode, scene boundaries, grain/noise, packet/keyframe statistics. Compare *compute cost* with just encoding 3 clips. Video Complexity Analyzer (`cd-athena/VCA`) offers an external research reference, but GPLv3 and dependency/licensing implications require review before code integration.
4. **Rate–distortion parametric modeling:** Jamali et al. [R2] predicts distortion at bitrates under studied transcoding conditions. Evaluate feature/anchor requirements; not a universal target-codec file-size oracle.
5. **Motion-search SVT-AV1 predictors:** Eichermüller et al. [R3] show promising bitrate correlation with motion-search features, but encoder/dataset transfer must be established and analysis is not free. The published correlation is **not** an absolute file-size error bound.
6. **External sample-prediction baseline:** `ab-av1` [R4–R5], which has mature sample-encode and CRF-search implementations. Its *video-stream-size* prediction needs container/nonvideo reconciliation. Compare against native FFmpeg samples before choosing the default.

**Research decision:** Do not implement a bespoke learned/no-encode model before a calibrated dataset exists. The fastest responsible route is metadata feasibility + versioned empirical priors (or explicit abstention) + targeted sample trials.

---

## 6. Short-clip prediction and experimental design

### 6.1 Two-stage sampling

**Stage A — videos:** Select independent source files from the eligible library. Stratify by source codec, resolution, bitrate/bpppf, source size/duration and content class when known. Gallery/series/camera/source duplicates should be grouped so near-duplicate items do not leak between training and holdout.

**Stage B — time within video:** Select clips across the *entire playable duration*, with deterministic pseudo-random or systematic spread. Each clip has actual decoded duration, timestamp interval, scene metadata, frame count and bytes. Clip windows near EOF may be shorter. Do not assume seeking lands exactly on nominal boundaries.

Use additional *stress scenes* (grain, rapid movement, dark gradients, fast fades, animation edge detail, subtitles) for low-tail quality checks. **Do not mix deliberately hard clips into the average bitrate prediction without sampling weights**—that biases projected file size upward.

### 6.2 Separate video stream estimates from nonvideo streams

If clips are encoded with silent/missing/shorter audio streams, the ratio of sample container bytes to original full-file container bytes is unsuitable. Estimate video output stream bitrate from actual encoded video payload/duration and separately account for retained audio/subtitles, attachments and mux overhead. If a packet census is too expensive, use labeled bounds/estimates and require selective full-file confirmation before converting a borderline source.

**GOP/keyframe bias:** Each independently encoded 10/20-second clip generates a new GOP boundary and encoder warm-up. Clip bitrate can systematically exceed continuous whole-file bitrate. Compare sample extraction methods, target encoder context, pre-roll/warm-up trimming, and full-file controls. Do not add ad hoc correction factors without measured evidence.

### 6.3 Short-clip baseline candidates (starting *experiment*, not production defaults)

Compare identical deterministic temporal positions under:

- `3 x 10s`, `3 x 20s`.
- `5 x 10s`, `5 x 20s`.
- `8 x 20s`.
- An adaptive schedule that starts small and only escalates where it may change an approval decision.

Cover at least two recipe quality/preset points per supported target family for calibration where feasible. Confirm whether a given sample-selection method is robust to animation, low motion, grain, action, variable frame rate, very short clips, and low bitrate originals.

### 6.4 Statistical truth and reporting

Store individual **complete-file** ground-truth results on a separate set of files and compare predictions using:

- Predicted vs actual output **whole-container bytes** and **video payload** bytes separately.
- Signed byte error; absolute error; median and 90th-percentile absolute percentage error; bias by codec, resolution and content class.
- Prediction-interval calibration/coverage for individual files; abstention rate for unrepresented cohorts.
- Aggregate library estimated bytes and savings; uncertainty method and correct sample weighting.
- Decision accuracy against minimum-savings/quality/cost policies: *false-positive conversion candidates* are especially important.
- Sample/feature computation seconds, new transcode seconds, total end-to-end elapsed time, disk reads/writes and cache-hit rate.

**Never conflate** an individual-video *prediction interval* with a library-total *confidence interval*. Videos, not within-video clips, are primary sampling units for inferential claims about library totals. If an adaptive algorithm chooses new items/segments based on observed outcomes, ordinary fixed-design confidence intervals may become invalid: use pre-specified evaluation procedures, sample-splitting and/or appropriately validated sequential methods. Existing `compresser` sequential `--accuracy-pp` is not an implemented solution.

### 6.5 Cost-aware decision process

The desired decision states are:

`excluded`, `ineligible`, `unknown_metadata`, `no_supported_predictor`, `estimated_unfavorable`, `estimated_promising`, `needs_measurement`, `measured_promising`, `quality_risk`, `unsupported`, `applied`, `retained_original`, `failed`.

Suggested logic (not a statistical proof):

1. Reject below-bound files and explicitly incompatible formats.
2. If mandatory stream bytes make required minimum savings impossible, mark `infeasible`.
3. If reliable predicted ranges lie entirely on the unprofitable side, skip further expensive trials *with a recorded uncertainty caveat*.
4. If predicted savings strongly exceed required minimum and confidence/quality evidence is adequate for the **current operation**, allow a preview or full-file confirmation; **not source replacement**.
5. If the plausible interval straddles the decision boundary, assign additional time samples or a full-file confirmation if expected information value is worth the cost.
6. If uncertainty cannot be resolved within budget, retain `needs_measurement`/`insufficient_evidence`. Do not hallucinate precision or override user guards.

Estimate benefit can incorporate **saved GiB per machine-hour** and, when calibrated by a wall meter, **saved GiB per incremental kWh**. Keep quality and playback compatibility as **hard constraints** first; do not trade visible loss for a trivial byte saving by default. Energy and electricity-cost predictions require measured system power, not GPU TDP or assumed local electricity prices.

### 6.6 Mandatory benchmark gate before estimator commitment

Use a **diverse, user-authorized fixture corpus** selected with recorded source rights and without touching production libraries. Initial design suggestion: tens of distinct videos, spanning H.264/HEVC/AV1, 720p/1080p/4K, different bitrates, grain/animation/action/low motion, audio complexity and duration. If only a small corpus is available, report results as exploratory rather than claiming validated 90th-percentile accuracy.

Reserve an independent **holdout by source/series/near-duplicate group**. Do not fit priors or sampling correction factors to the holdout. The number of full-file encodes and recipes is **bounded by approval, time and storage budgets**; start with a small pilot and expand only as needed.

Compare at least:

- M0: metadata-only cohort/global prior and honest abstention.
- M1: regularized metadata regression if enough calibration data exists.
- S3: three 20-second spaced clips; correct video-stream accounting.
- S5: five 20-second spaced clips.
- S8: eight 20-second spaced clips.
- SA: adaptive clips with the **same maximum work budget**.
- SC: sampled estimate with regression/GOP/source-content calibration learned *only on training corpus*.
- C: optional VCA/motion complexity; measure value per second vs sampled baseline.
- A: optional `ab-av1` sample prediction using a strict NDJSON adapter.

Measure actual whole-file encodes for the shortlisted recipes on the reserved validation set. Publish a comparison table of error **and** cost. Prefer the simplest method that meets user-chosen tolerances; if no method reaches required reliability, do not ship automatic predictive approval—ship accurately labeled exploratory estimates and require more confirmation.

**Proposed gate:** Agent must recommend numeric tolerances for median/P90 error, confidence/coverage, false-positive conversion recommendations, and cost, **based on pilot data and desired risk**, before promoting an estimator. No unexplained universal tolerance is presumed in this document.

---

## 7. `ab-av1` and codec-quality backends: build-versus-wrap experiment

`ab-av1` now documents `--stdout-format json` for `sample-encode` and `crf-search`; output is NDJSON to stdout. `sample-encode-done` and `crf-search-done` contain `crf`, `predicted_encode_size`, `predicted_encode_seconds`, `predicted_encode_percent`, `from_cache`, optional `vmaf`/`xpsnr`. Failures may emit `crf-search-error` or nonzero exit **without a final JSON record**. JSON behavior differs across older releases (e.g., some keys missing before v0.11.5). See [R4].

**Adapter experiment (Stage 0/3):**

1. Verify installed release and runtime capabilities on Windows; feature-detect NDJSON support, encoding backend support, preset/CRF semantics and FFmpeg compatibility.
2. Run sample-encode/crf-search on a tiny synthetic fixture, capture stdout NDJSON and stderr independently, parse typed result messages, reject malformed/truncated outputs and nonzero exit.
3. Check how the predicted **video stream bytes** relate to a complete output with copied audio/subtitles/attachments. Avoid interpreting `predicted_encode_size` as full file bytes unless experimentally verified for that release/mode.
4. Compare its sampling selections, selected encoder/preset/quality values, cache origin and actual runtime against a native FFmpeg baseline.
5. Test cancellation and FFmpeg descendants, time/resource admission, external cache paths, binary identity, and absence of accidental output writes.
6. Choose `ab-av1` as optional production backend **only if** it satisfies the same bounded job/provenance/quality contracts. Do not depend on parsing human-friendly stdout, or silently equate its CRF interface with `*_nvenc` CQ. Prefer native FFmpeg for encoder combinations not supported/valid through `ab-av1`.

`Av1an`'s scene-based target-quality and chunked encoding can inform an advanced backend; defer until clear benefits justify its complexity.

---

## 8. Quality assurance and preservation policies

### 8.1 Measurement

For standard SDR material where a supported, correctly configured full-reference pipeline exists, consider VMAF v1, XPSNR, SSIM and/or PSNR. Never score unaligned timestamps, different pixel processing or mismatched frame counts as comparable. Persist metric model, color conversion, bit depth, scaling, frame-synchronization policy and software versions.

Netflix released VMAF v1 models in June 2026 with viewing-condition-specific models. The 4K/3H model has a **0–110** scale, unlike other 0–100 profiles; SDR measurement is recommended at suitable processing precision (including 10-bit). A threshold appropriate for one model cannot blindly be applied to another. **Do not assert VMAF is validated for HDR or Dolby Vision solely because an executable returns a score.** [R6]

Quality policy should consider low-percentile/per-scene artifacts (blocking, banding, fine text/line work, grain smearing, dark gradients), not only mean VMAF. For manga/anime captures, fine line preservation and text fidelity may matter more than average score alone. Quality scores compare against the current source, which may already be degraded.

### 8.2 Media preservation

FFmpeg automatic stream selection chooses one stream of accepted types and **does not automatically include data/attachment streams**; explicit `-map` is necessary and even `-map 0` may be invalid for an incompatible target container. [R1]

Define stream-preservation capabilities by container and target recipe before execution. Default for ordinary re-encode: preserve all compatible audio/subtitle/attachment/data streams, languages, dispositions, chapters, sidecar metadata and timing as configured; do not recode audio by default. Reject or require an explicit policy when a target container cannot retain a source stream. Track subtitles and font attachments necessary for correct playback. Preserve stream count/order or document remapping and verify. Avoid changing resolution, frame rate, color, audio bit depth or channel layout unless separately requested.

Default initial *automatic lossy apply exclusions* should include HDR10+/Dolby Vision/dynamic metadata, poorly understood HDR, 3D/multiview, unusual interlacing, ambiguous multi-video-stream content, incompatible subtitle attachments and malformed/incomplete sources. This excludes apply by default, **not inventory/inspection**. Users may inspect or perform explicitly separate authorized experiments with unsupported material but no silent production substitution.

### 8.3 Playback/compatibility profiles

Create an explicit optional `playback_profile` contract: `general_compatibility`, `local_modern_hardware`, `media_server/direct_play` etc., with supported codec, bit-depth, container, subtitles/audio policies. Do not hard-code that a specific TV or media server can direct-play AV1 or Dolby Vision across every player/client profile. A successful transcode file is not a promise that every target client plays it without server transcoding.

---

## 9. RTX 5090 / NVENC benchmark plan

GPU family capability does not guarantee FFmpeg encoder availability or individual flags. NVIDIA's Blackwell platform supports H.264/HEVC/AV1 variants and newer SDK paths [R7–R8], but exact FFmpeg binaries, drivers, build options, 4:2:2/10-bit/UHQ support must be probed on the host. The RTX 5090 has multiple NVENC engines; this is **not** permission to run that number of simultaneous encodes without throughput tests.

**Stage 0 host capability record:** FFmpeg/FFprobe versions and binary hashes, `ffmpeg -encoders`, `ffmpeg -filters`, actual `ffmpeg -h encoder=av1_nvenc`, `ffmpeg -h encoder=hevc_nvenc`, installed GPU/driver details; 10-second sacrificial output smoke encodes to an isolated temp location (only after explicit local trial approval). Verify encoding and decoding output pixel formats, rate control/presets, throughput and VMAF filters separately.

**Controlled quality-equivalent comparison:** `hevc_nvenc` and `av1_nvenc` with supported HQ/UHQ versus `libx265` and `libsvtav1`, across at least two effort/quality settings. Compare at *matched measured output quality*, not matched CRF/CQ numbers or identical target bitrates. Record:

- Whole-container bytes, video-stream payload bytes, net savings and low-tail quality.
- Encoding/wall-time including decode, audio/subtitle copy, mux, output validation and storage I/O; not just FFmpeg frames/sec.
- Source disk throughput, destination/scratch bandwidth, concurrent job scaling 1→2→N subject to safe resource limits.
- CPU/GPU utilization, NVENC/NVDEC/video engine metrics where available; VRAM and temperature as diagnostics.
- Whole-system incremental watt-hours **only** with trustworthy measurements; no made-up energy figures from GPU TDP. Report storage saved per hour and per verified incremental kWh where possible.
- Effect of changing one resource (CPU preset, NVENC tuning/preset, clip count, SSD scratch) with other conditions held constant.

Published NVENC UHQ studies report improvements in bitrate–distortion at the expense of latency and power [R9]; assess whether the benefit justifies resource cost for the user's offline archival objective, not real-time latency requirements.

Prioritize reduced unnecessary processing and fair matched-quality comparisons. Underclocked/mining GPU conditions are **not** automatically representative of normal video-encoding settings.

---

## 10. Applying compression safely: transaction and recovery contract

**Mode discipline:** `inventory`, `plan`, `estimate metadata`, and inspection never mutate media. `compare`, sampled `estimate` and `preview` may encode into a controlled external analysis workspace only when explicitly budgeted and authorized. `apply` without `--write` prints a dry-run. Source replacement is a separate, stronger opt-in guarded by lossy authorization and rollback policy.

### Required sequence per video

1. Validate source and selected plan/recipe identity, full stream manifest, file fingerprint, target compatibility and user filters.
2. Acquire scope-specific read/write ownership; avoid conflicts with other compresser/MangaDL sessions on overlapping files/trees.
3. Check destination/scratch capacity conservatively, including full temporary candidate and retained originals. Use unique output path derived from complete relative path/source identity, never flatten to basename.
4. Journal the plan/source/recipe/output state before external encoding; `PENDING→ENCODING→VALIDATING→READY_TO_PUBLISH→PUBLISHED` with explicit failure/interruption/recovery states.
5. Run bounded FFmpeg with `-nostdin`, explicit stream maps and safe no-clobber output (`-n` or equivalent exclusive staging policy); never use `-y` against user media.
6. Check exit code, candidate existence/size, container completeness and full-decode status; verify duration/timestamps, expected stream count/codecs/languages/dispositions/chapters/attachments/color metadata and frame behavior. Determine whether any additional policy-specific quality check is required. Validate candidate byte savings against threshold.
7. Recheck source identity immediately before publication; reject changed or linked/aliased sources according to the chosen policy.
8. Use destination-filesystem staging and crash-safe publication; retain originals/independent rollback until explicitly authorized cleanup. Never assume cross-drive rename is atomic. Prefer external outputs as the first write implementation; in-place replacement only after proven recovery tests.
9. Write durable record of actual output hashes, size, recipe/runtime, verification evidence and outcome. On interruption, fail closed and keep enough state to inspect and resume the *batch* without redownloading/retranscoding completed verified files.

**No automatic deletion.** Mirror copies (including mirrored pair volumes) are not independent backups. Be particularly careful with drive free-space and hardlinked files.

**Recovery:** inspect without side effects; identify temporary, candidate, retained original and target files; require a fresh confirmation for irreversible actions; never delete a live lock inode. Support stale OS metadata inspection, but do not declare a lock unheld solely by reading JSON metadata.

**Cancellation:** Terminate entire encoder subprocess trees; await cleanup, drain process pipes, flush journals and release OS-backed locks. TUI `Q`, `q` and pane deletion must not orphan FFmpeg or misreport cancelled encoding as success.

---

## 11. `compresser tui` integration and repair gates

The **existing** `modules/cli_tui` introspects argparse, manages forms, panes, live subprocesses and post-run actions. `modules/mangadl/mangadl/tui.py` already shows the correct pattern: `CliTuiApp`, `introspect_parser`, explicit executable and filtering `tui` itself out of the menu.

Desired UX:

```text
compresser tui
  Images
    Inventory | Plan | Estimate | Analyze | Compare | Preview | Apply | Recover
  Videos
    Capabilities | Inventory | Plan | Estimate | Analyze | Compare | Preview | Apply | Recover
  Saved Work
    Plans | Inventory Summaries | Trials | Previews | Reports | Recovery Inspection
```

`cli_tui` already has a side-by-side **image** viewer, not a video player. For video preview, initially open generated clips/manifest in an external player and show saved paths; synchronized dual video playback is optional future work.

**Two concrete blockers to resolve/verify:**

1. `modules/cli_tui/cli_tui/app.py` uses unconditional `import curses`, while `pyproject.toml` currently lists `termdash` and `pillow` only. Python does not ship the standard curses module on Windows. Validate `windows-curses` as a *platform-conditional* dependency or implement a graceful fallback. Do a real PowerShell Windows launch smoke test, not merely Linux headless tests. [R10]
2. `ProcessRunner.terminate()`/`.kill()` target the direct child process. When a CLI spawns FFmpeg descendants, the TUI must coordinate cancellation/process tree cleanup. Test graceful stop, force quit and pane closure; avoid asserting success while children remain or journal state is incomplete.

**TUI decisions:** Reuse parser introspection and preserve CLI argument semantics, especially threshold and budget options. Remove recursion into `tui`. Display selected target, estimated max compute/disk cost, codec choices, plan ID, explicit `--write`/`--allow-lossy` consent and previously recorded results. CLI/headless JSON must continue working without curses/UI. Validate terminal widths (80/120/160), Windows ANSI and input, and no regressions in `mangadl tui`.

`compresser tui` should be an **independently shippable stage** that works for existing image operations before video is complete.

---

## 12. Proposed CLI and contracts (illustrative, final flags subject to review)

User-facing examples (not current commands):

```powershell
compresser tui
compresser video capabilities
compresser video inventory -i 'D:\Videos' -I 'E:\Analysis' -B 4M -R 1920x1080
compresser video plan -i 'D:\Videos' -I 'E:\Analysis' -B 4M -R 1920x1080 -E metadata
compresser video estimate -i 'D:\Videos' -I 'E:\Analysis' -r PLAN_ID -E metadata
compresser video estimate -i 'D:\Videos' -I 'E:\Analysis' -r PLAN_ID -E sampled -M 20m
compresser video compare -i 'D:\Videos' -I 'E:\Analysis' -r PLAN_ID
compresser video preview -i 'D:\Videos' -I 'E:\Analysis' -r PLAN_ID -n 3
compresser video apply -i 'D:\Videos' -I 'E:\Analysis' -r PLAN_ID  # dry run
```

**Proposed flag concepts:**

| Purpose | Suggested short | Suggested long | Required semantics |
|---|---|---|---|
| Input | `-i` | `--input` | File or directory; target identity |
| Workspace parent | `-I` | `--workspace` | Outside media tree |
| Min video bitrate | `-B` | `--min-video-bitrate` | Video stream bps, not whole container |
| Min dimensions | `-R` | `--min-resolution` | Display-oriented `WIDTHxHEIGHT`, both dimensions |
| Min size | `-S` | `--min-size` | Bytes with explicit units; check overlap with existing `compresser` flags, scoped parser |
| Min duration | `-D` | `--min-duration` | Explicit seconds/time notation |
| Estimator tier | `-E` | `--estimate-tier` | `metadata`, `features`, `sampled`, `calibrated` |
| Max active time | `-M` | `--max-time` | Hard wall-time budget on new analysis work |
| Max new trials | `-T` | `--max-trials` | Count unique actual encoding attempts; scoped parser |
| Plan | `-r` | `--plan-id` | Frozen plan selection and saved provenance |
| Report JSON | `-J` | `--json` | Machine-readable stable schema |
| Disable UI | `-N` | `--no-ui` | No live display |
| Verbosity | `-v` | `--verbose` | Bounded diagnostic mode |
| Commit output | `-w` | `--write` | Required for apply publication |
| Lossy permission | `-L` | `--allow-lossy` | Additional explicit authorization for source-affecting lossy output |

Short flags may legitimately be reused in operation-scoped parsers, but avoid ambiguous or conflicting shared options. All command surfaces (standalone, nested CLI, TUI) must use **identical typed normalization, safety guards, report schemas and exit semantics**. `recover` has its own confirmation-token safety contract. All examples are proposals; agent must settle verified parser behavior and help text.

### Planned persisted objects

- `VideoAsset`: immutable probed facts + fingerprint source/provenance + selected video stream.
- `VideoRecipe`: exact codec/encoder/rate-control/preset/container/stream/color/quality/retention policies + runtime identity; codec-specific ranges, no CRF/CQ equivalence.
- `EligibilityDecision`: stage, status, reasons, thresholds, metadata quality.
- `VideoEstimationPlan`: frozen source population, source/clip deterministic selection, owner/schema version, strata weights, recipes, budgets, eligibility/preservation policy, runtime identifiers.
- `TrialObservation`: recipe/source/clip IDs, real clip interval/duration, actual encoded elementary video bytes, nonvideo accounting, quality distribution, processing time, cache provenance, error/state.
- `Prediction`: full-file video bytes, retained nonvideo bytes, mux overhead, predicted final bytes, intervals/coverage method, calibration population/version, prediction tier, status/abstention reason.
- `VideoApplyJob`: source+target identities, candidate/backup/staging paths, output format, protected transaction states, validation decisions and write permission evidence.
- `CompressionReport`: counts/bytes/time/quality/cost with totals and per-source rows, not misleading point-only summaries.

**JSON contracts must be validated and versioned**. Never parse terminal-oriented output as a machine source of truth. Cache keys must change when source fingerprint, clip windows, recipe, FFmpeg binary/encoder/runtime, VMAF model/preprocessing, stream selection or schema changes. Keep inventory cache and trial cache separate.

---

## 13. Proposed implementation stages and mandatory gates

**Do not automatically start later stages merely because preceding tests pass.** Record status and respect project/user approval boundaries. Stage order may be revised, but dependency and safety gates remain binding.

| Stage | Deliverable | Gate |
|---|---|---|
| **0 — independent verification/architecture** | Reinspect sources/tests and external backends, inspect tools, benchmark/fixture design, CLI/data model, risks and approval boundaries. | Written decisions on native vs `ab-av1`, no-encode estimator, package boundaries, contracts, test budget; review before coding. |
| **1 — optional TUI for existing images** | `compresser tui` using `cli_tui`, correct parser dispatch; Windows curses/process-tree fixes where necessary. | Native Windows launch; CLI and `mangadl tui` regressions; no orphan child tasks. Independently deliverable. |
| **2 — video package + capability/inventory/filters** | Package, `compresser video` and `vcompress` dispatch, `capabilities`, `files`/`probe` inventory, complete stream schema and filters. | Zero encodes during inventory/plan; correct exclusions/unknown metadata; durable snapshots and independent target workspaces. |
| **3 — cheap predictor and feasibility screening** | File size budget arithmetic; calibrated priors only when data exists; explicit abstention; staged reporting. | No new target encode; explain evidence and uncertainty; no arbitrary ratios as facts. |
| **4 — controlled encoder and measurement backend** | Typed recipes, FFmpeg runner, optional ab-av1 adapter, budget scheduler, progress, sample clips and cache. | Controlled encodes only; output stream check; cancellation, retries, cache invalidation and failure tests. |
| **5 — quality/compare/preview** | VMAF/XPSNR where valid, per-clip quality distributions, recipe comparison reports, paired sample video previews. | Aligned comparable outputs and validated metric model; no automatic unsafe HDR quality approval. |
| **6 — estimation calibration/selection** | Representative full-file ground truth, M0/M1/S3/S5/S8/SA/SC comparisons, errors/costs, model/decision rules. | Locked holdout results; calibrated intervals or explicit abstention; selected algorithm justified by measured accuracy per resource. |
| **7 — safe apply/recover** | Journaled non-clobber file-backed publication, source checks, optional guarded in-place replace, robust verification/recovery. | Chaos/failure-injection and source-preservation validation; backups/free space; no accidental deletes. |
| **8 — integration/performance/final audit** | Documentation, examples/help registry, version updates, full regressions, Windows RTX 5090 benchmark and portability checks. | Verified current validation reports, exact commands/run environments, source-compatible image workflow, documented residual risks. |

For local scripts validation, read `validation-targets.json` and execute the appropriate `Invoke-Tests.ps1` targets. Use isolated synthetic/test media by default. Manual GUI/TUI and hardware checks are needed in addition to unit suites. The remote GitHub revision is not a substitute for local checkout and executed tests.

---

## 14. Acceptance-test matrix (minimum)

**Inventory/filter contracts**

- 0, missing, partial and contradictory stream bitrates; container bitrate remains distinct; one main video plus attached artwork; multiple video streams; rotated portrait; square/ultrawide; 4K; bad width/FPS/duration; empty/corrupt/truncated media.
- Required tracks and chapters, multi-audio, image/text subtitles, fonts/attachments/data, variable frame rate, interlacing, 8/10-bit, HDR static/dynamic metadata, Dolby Vision presence, MPEG-TS and Matroska/MP4 compatibility.
- Filter threshold exact equality and just-above/below values, `AND/OR` savings gating, counted exclusions, unknown-field explicit handling and resource-use audit proving no encoder launched during inventory/metadata plan.

**Estimation**

- Metadata-only mode creates **zero** new encodes, including behind optional adapters.
- Deterministic random source/time selection; correct partial EOF clip weighting; GOP/keyframe bias captured by validation; source bytes/audio/mux additive accounting; negative savings preserved in raw results.
- For every sampled recipe, actual sample frames, duration, bytes and status; cache hit/miss provenance, stopped/failed/partial states, stale source/runtime invalidation, stratified library weighting.
- Prediction vs held-out actual bytes, bias, absolute error, intervals, decision false positives and runtime/cost. No claim of certified adaptive statistical accuracy without valid design.

**FFmpeg/quality/compatibility**

- Encoder unavailable, driver mismatch, unsupported option, unsupported pixel depth, missing VMAF/model, malformed NDJSON (including missing end message), binary replacement during test.
- Stream mapping/codec compatibility and no dropped tracks, metadata, chapters and attachments; frame count/timing, optional full decode; model-aware SDR VMAF; HDR automatic-apply stop.
- Candidate larger than source; low savings; quality fail; exact path collision; source changed between scan and output; symlink/hardlink alias; source ACL/permission errors.

**Safety/failure/cancellation**

- Interruption before start, during FFmpeg, after candidate verification, during journal flush, between backup and publish, after output commit; full disk, inaccessible scratch, killed parent, killed FFmpeg child, process-tree orphan prevention, lock acquisition/release/stale inspection, concurrent sibling folders.
- Output in a separate tree preserving relative paths, same-volume atomicity, cross-volume copy/rename not assumed atomic; original retained; explicit confirmation needed for irreversible cleanup; recover inspect safe with no flags.

**TUI and regressions**

- `compresser tui` on native Windows and on relevant terminal variants; 80/120/160 cols, navigation, typed forms, budget summary, flag parity, image operations, video optional installation, no recursion, optional UI without breaking JSON/no-UI CLI.
- `Q`/`q`/pane close stop FFmpeg descendants and result in cancellable journal state; existing `mangadl tui`, image preview viewer, `compresser` image CLI, libraries and benchmark_core public APIs remain compatible.

**No tests, hardware benchmarks or user library scans were performed during this planning document.** These are acceptance criteria to be executed later on approved fixtures.

---

## 15. Explicit research findings: evidence and limitations

Evidence tiers: **A** = authoritative product/project source for a documented feature; **B** = academic research with its own evaluated conditions; **C** = source-code inference from repository inspection; **D** = proposed engineering judgment not yet experimentally validated.

| Decision | Evidence | What remains uncertain |
|---|---|---|
| FFmpeg automatic mapping is unsuitable for preservation of every stream | **A:** FFmpeg stream-selection documentation [R1] | Exact compatibility of all specific source containers/streams requires trials. |
| `ab-av1` offers structured NDJSON for sample/crf search | **A:** documented schema, final messages and errors [R4]; changelog [R5] | Installed version, preset/encoder support, cache equivalence, audio/accounting semantics and cancellation on Windows. |
| VMAF v1 is model/viewing-profile-specific | **A:** Netflix model documentation [R6] | Whether the specific FFmpeg build includes the models and valid pipelines; HDR acceptance policy needs independent proof. |
| Rate–distortion parametric and motion-search predictors can sometimes estimate target effects without full encoding | **B:** Jamali [R11], Eichermüller [R12] | Transferability across user's codecs/content/presets and added feature-compute cost. Correlation does not establish low per-file byte error. |
| Blackwell has NVENC codec/UHQ features | **A:** NVIDIA SDK documents [R7, R8] | Host driver/FFmpeg options, quality-equivalent speed, energy and concurrency. |
| NVENC UHQ may trade energy/latency for bitrate-quality gains | **B:** 2026 study [R9] | Marginal benefit on the user's offline compression workloads. |
| `cli_tui` requires Windows import and subprocess-tree attention | **C:** `cli_tui/app.py`, `pyproject.toml`, `process_runner.py`; **A:** Python platform docs [R10] | Actual Windows startup and real process behavior not tested here. |
| A tiered, decision-aware estimator is the best initial architecture | **D:** synthesis of costs and evidence above | Calibrated accuracy and thresholds await the controlled benchmark. |

### Source references (verify current versions before implementation)

- **[R1]** FFmpeg reference, stream selection / `-map`: https://ffmpeg.org/ffmpeg.html
- **[R2]** FFprobe, JSON stream/packet details and timing: https://ffmpeg.org/ffprobe.html
- **[R3]** FFmpeg filtering/quality options: https://ffmpeg.org/ffmpeg-filters.html
- **[R4]** `ab-av1` structured NDJSON contract: https://github.com/alexheretic/ab-av1/blob/main/stdout-format-json.md
- **[R5]** `ab-av1` source, changelog and usage: https://github.com/alexheretic/ab-av1 ; https://github.com/alexheretic/ab-av1/blob/main/CHANGELOG.md
- **[R6]** Netflix VMAF v1 models, SDR precision, viewing distance and score ranges: https://github.com/Netflix/vmaf/blob/master/resource/doc/models_v1.md
- **[R7]** NVIDIA NVENC application note: https://docs.nvidia.com/video-technologies/video-codec-sdk/13.1/nvenc-application-note/index.html
- **[R8]** NVIDIA FFmpeg GPU guide and Blackwell overview: https://docs.nvidia.com/video-technologies/video-codec-sdk/13.1/ffmpeg-with-nvidia-gpu/index.html ; https://developer.nvidia.com/blog/nvidia-video-codec-sdk-13-0-powered-by-nvidia-blackwell/
- **[R9]** Arunruangsirilert & Katto, *Evolution of NVENC Efficiency* (2026): https://arxiv.org/abs/2605.01187
- **[R10]** Python `curses` availability/optional module: https://docs.python.org/3/library/curses.html
- **[R11]** Jamali et al., *A Parametric Rate-Distortion Model for Video Transcoding* (2024): https://arxiv.org/abs/2404.09029
- **[R12]** Eichermüller et al., *SVT-AV1 Encoding Bitrate Estimation Using Motion Search Information* (2024): https://arxiv.org/html/2407.05900v1
- **[R13]** Video Complexity Analyzer (GPLv3): https://github.com/cd-athena/VCA
- **[R14]** Av1an target quality (advanced reference): https://rust-av.github.io/Av1an/Features/TargetQuality
- **[R15]** `ab-av1` sampling rationale and example: https://alexheretic.github.io/posts/ab-av1/
- **[R16]** Codec support can depend on media client/container: https://jellyfin.org/docs/general/clients/codec-support/

For research papers, retain exact model/codec/test dataset and error definition. Do not present an academic correlation, BD-rate gain or log-bitrate error metric as a general prediction-accuracy guarantee for archival file sizes.

---

## 16. Local-agent questions that must be answered explicitly

Before moving from Stage 0 into implementation, return a compact decision record that answers:

1. Does adding the video backend directly under `compresser video` minimize coupling compared with `vcompress` first and a wrapper later? Which dependency direction avoids circular imports?
2. What are the exact FFprobe fields and fallback policies for audio/video bitrate, rotation, VFR, HDR and ambiguous multi-video tracks?
3. What evidence is required to promote a no-encode estimate from `exploratory` to `decision-grade`? What are the abstention rules?
4. Are `ab-av1`'s NDJSON and samples adequate for bounded, reproducible, cross-codec evaluation? What codec families need native FFmpeg trials?
5. What is the minimum representative benchmark corpus for estimating prediction error per codec family without leakage? What is the approved maximum compute/disk budget?
6. What is the expected temporal sampling/GOP bias and how will it be detected rather than assumed away?
7. What constitutes acceptable **full-file container byte error, visual quality, and false-positive recommendation rate**, and how will these be calibrated?
8. What is the exact source-media preservation contract for audio/subtitles/attachments/HDR/timestamps, and which files must be skipped?
9. Which `cli_tui` Windows dependency/process-tree changes are needed? How will regressions be tested?
10. How will completed jobs, plan identity, trial cache, transactions and recovery remain compatible with current image workflows?
11. Which stages can be approved independently, and which explicitly require real RTX 5090/Windows user validation?
12. What concrete evidence would justify a learned complexity model or a `compression_core` refactor rather than maintaining the simple backend?

### Definition of done

The user can run **`compresser tui`** for existing image commands and new video commands, or call `compresser video` / `vcompress` headlessly. A video library can be accurately inventoried, filtered by explicit bitrate/resolution thresholds, cheaply screened for potential value, further estimated with bounded and calibrated samples, compared for actual quality/storage/cost, previewed, and finally converted only through an opt-in recoverable process. Every skipped, unknown, failed, retained and processed item is counted. Existing media and image-compressor behavior are preserved.

**Stop boundary for this handoff:** Deliver a reviewed implementation plan and revised architectural decisions. Do not claim this document includes executed benchmarks, authorized implementation, or safe-to-delete media backups.
