# Estimation Benchmark Protocol — Video Compression

**Companion to:** [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md), especially §§5–7, 9 and 13.  
**Status:** Proposed test specification; not a claim that any algorithm achieves the targets below.  
**Baseline repository:** `MaxCarlson/scripts`, `main` @ `a0ff1778` (2026-10-20); recheck checkout before execution.  
**Owner:** Implementing agent; update this protocol *before* looking at holdout results when a design changes.

## 1. Decision this protocol must support

Choose the **least computationally expensive estimator that gives dependable decisions** about whether a source video is worth transcoding to a *specific* codec/encoder/recipe at an acceptable quality and cost. Estimate (a) finished output **container bytes**, (b) encode time/energy when measurable, (c) evidence about visual quality, and (d) uncertainty or an explicit abstention. A small absolute byte error is valuable, but the main failure to avoid is recommending a conversion that fails the user's minimum savings, quality, compatibility or compute-cost requirements.

Three claims must remain distinct:

1. **Feasibility:** known input bytes, duration and required nonvideo payloads imply an upper video-bitrate budget. This is arithmetic, **not** a quality or achievable-compression prediction.
2. **Prediction:** estimates of target video bitrate/bytes conditioned on *source* and *recipe*, and an estimate for copied/re-encoded audio, subtitles and container overhead. This may be highly uncertain without trials.
3. **Decision:** select/skip/sample-more/abstain based on savings *and* quality/compatibility/cost rules. Only `apply` can produce actual library savings.

A cold-start metadata model with no validated calibration cohort must label its figures `exploratory` or abstain. Do not assert a universal H.264→HEVC/AV1 ratio.

## 2. Candidate algorithms (test on identical held-out sources)

| ID | Method | Target encodes? | Purpose / scope |
|---|---|---:|---|
| `M0` | Exact source facts + bitrate feasibility; abstain on final-size prediction | 0 | Cheap negative gate and control |
| `M1` | Codec/recipe-conditioned empirical cohort prior, including nonvideo bytes | 0 | Fast cold/warm prediction; cold start may abstain |
| `M2` | Simple regularized metadata regression using duration, video bitrate, bpppf, resolution, FPS, source codec, target recipe | 0 | Test added value against `M1`; train only on training data |
| `F1` | Optional spatial/temporal complexity descriptors or sparse decode | 0 target encodes | Does feature cost beat doing a few short clips? |
| `S3` | 3 deterministic, spread short clips (initial candidate: 12–30 s each) | 3/recipe | Minimum sampled baseline |
| `S5` | 5 clips, same recipe/window rules | 5/recipe | Test marginal improvement |
| `S8` | 8 clips, same recipe/window rules | 8/recipe | Test diminishing returns |
| `SA` | Adaptive added clips triggered by declared uncertainty/decision ambiguity | bounded | Test value of information, not just average error |
| `AB` | Optional `ab-av1` structured JSON sample/CRF estimation | bounded | External baseline, if current CLI and semantics verified |
| `CAL` | Model calibrated on independent completed source-file encodes | not free | Bias correction, residual distribution and intervals |

`S3/S5/S8` are **experimental candidates**, not promises or final defaults. Clip-length and count must be predeclared and measured. `ab-av1` may predict video bytes excluding source/container streams; reconcile accounting before comparing. `F1` may perform significant decoder I/O; record its cost. Record an encoder attempt only when the backend actually starts target encoding.

## 3. Corpus, units, splits and provenance

- **Unit of inference:** one independent source video (or content-family/series group), not a clip or frame. Clip measurements within a video are dependent repeated measures.
- Assemble a consented, **read-only** corpus with diversity in source codecs (H.264, HEVC, AV1 if available), bitrate, resolution (SD/HD/4K), duration, FPS, live action vs animation, grain/noise, dark gradients, motion and track complexity. Include already well-compressed files, short videos, high-audio-byte files, chapters and containers with copied tracks. Exclude unsupported HDR/multivideo from automatic apply studies but keep them in the inventory/eligibility benchmark.
- Start with a *bounded pilot* (e.g., 12–20 independent files across applicable cohorts); propose a later validation cohort (e.g., 30–60 independent files) only with user-approved full-encode budget. These counts are **planning sizes**, not a basis for claiming confidence intervals by themselves. The agent must calculate feasible sample sizes/cost.
- Use group-disjoint training/calibration/holdout splits by source series, episode, release family, camera capture or near-duplicate class. Never split clips from the same original across these sets.
- Freeze the manifest and holdout **before** estimator selection. Reserve at least ~20–30% of *independent groups* for a locked holdout where feasible; stratify groups carefully, disclose cohorts too small for reliable evaluation.
- Version the fixture manifest: source path or private opaque ID, source sha256 or hash policy, bytes, stream manifest digest, source/target codec pair, exact recipe, tool binary hashes/versions, GPU/driver, seed, clip windows, calibration split, platform and test date. Do not commit personal video paths or content hashes if privacy-sensitive; use anonymized IDs in shareable reports.
- The **ground truth** for each evaluated source×recipe is a completed transcode into a safe test output, verified for container/stream validity and actual file bytes. Failures/unsupported are first-class results, not silently removed from accuracy averages. Keep source untouched.

## 4. Experimental controls

- Compare methods only for the **same frozen source, exact target encoder, rate control, preset, pixel/color policy, stream policy, container and quality-measurement pipeline**. Codec names alone are not recipe identities.
- A recipe at fixed bitrate measures size predictability, *not* equivalent quality; a CRF/CQ recipe measures output size conditioned on quality setting, *not* equivalent quality across encoders. To compare encoders fairly, either quality-match to a declared model/tolerance or report rate–distortion curves rather than treating CRF/CQ numbers as comparable.
- Source bitrate for eligibility is *video stream bitrate*. Container bitrate includes audio/overhead and is not a substitute. Preserve missing/unknown bitrate as unknown, not zero.
- Sample windows must report **actual** frame ranges, presentation timestamps, realized decoded duration and bytes; seek/keyframe drift matters. Spread clips across the full duration; hold clip protocol fixed within each comparison.
- For file-size prediction, ordinary time-probability clips must be uniformly/systematically sampled or accompanied by inclusion probabilities/weights. Add deliberately hard scenes to a **separate quality-stress pool**; never blend nonrepresentative stress segments into the mean bitrate without proper weighting.
- Sample output may differ from full encode due to GOP reset, scene cuts, rate-control state, lookahead, header and segment overhead. Calibrate against full-file results; report residuals by duration/content class.
- Do not treat per-clip VMAF variation as independent evidence about library-level uncertainty. HDR without a validated metric is an excluded quality cohort, never a scored zero.
- Repeated runs of stochastic/time-sensitive methods must preserve seeds and report run-to-run variation. Disable concurrent unrelated encode jobs for controlled speed/energy comparisons or explicitly record contention.

## 5. Output-size and feasibility arithmetic

For source `i`, recipe `r`:

- `S_i` = current entire source container size (bytes); `T_i` = valid presentation duration (s).
- `Vhat_ir` = predicted output video-stream payload bytes; `Ahat_ir` = estimated **all** retained/reencoded nonvideo payload bytes (audio/subs/fonts/data); `Hhat_ir` = mux/metadata/index overhead and other non-payload bytes.
- `Ohat_ir = Vhat_ir + Ahat_ir + Hhat_ir`; `Ghat_ir = S_i - Ohat_ir` (allow **negative** savings).
- If exact constrained output video bitrate `b` is achieved, first-order `Vhat_ir ≈ b T_i / 8`; this does not say that resulting quality is adequate.
- Required savings fraction `f` yields `b_video_max = 8[(1-f)S_i - Ahat_ir - Hhat_ir]/T_i`, valid for `T_i>0`. Nonpositive available video byte budget means economic infeasibility under the stream-preservation policy; positive budget is **not** evidence the target encoder can meet quality.
- Each estimated component must carry a provenance tag (`measured_packet`, `probe_reported`, `learned`, `sampled`, `assumed`) and uncertainty when relevant. Full media packet accounting can be I/O-heavy and must be an explicit deeper tier.
- Report raw gross prediction and the policy-adjusted retained size separately (`min(S_i, Ohat_ir)` only when a keep-original-if-larger policy is in force).

## 6. Required evaluation metrics

Compute **per complete-file prediction**, and aggregate over independent source videos (prefer grouped bootstrap intervals for summary uncertainty if sample size permits):

| Metric | Definition / concern |
|---|---|
| `AE_i` | `abs(Ohat_i - O_i)` bytes; also report signed error (`Ohat_i - O_i`) |
| `APE_i` | `abs(Ohat_i - O_i)/O_i` for `O_i>0`; report median and P90 by cohort |
| `WAPE` | `sum_i abs(Ohat_i-O_i) / sum_i O_i` (denominator actual output bytes) |
| `signed_bias` | `sum_i (Ohat_i-O_i) / sum_i O_i`; detect optimism/pessimism |
| `interval_coverage` | Fraction of held-out actual `O_i` falling in each declared prediction interval (e.g., nominal 80%/90%) |
| `interval_width` | Width relative to predicted/actual bytes; prevents uninformative all-encompassing ranges |
| `decision_precision` | Fraction of recommended conversions that **actually** satisfy every enabled savings, quality and compatibility gate |
| `false_positive_recommendations` | Count/rate of recommendations failing actual requirements; **critical** operational error |
| `abstention_rate` | Fraction with insufficient evidence, broken down by reason and source bytes |
| `compute_cost` | Target-encoded seconds, wall time, CPU/GPU utilization if reliable, bytes read/written, trial attempts, cache hits |
| `energy` | Incremental measured energy where feasible; identify wall-meter vs NVML GPU-only estimates; don't compare unlike accounting scopes |

Report both unweighted per-video and source-size-weighted results. Include skip/unsupported rates as denominators, rather than cherry-picking only successes. Exclude failed ground truths from numerical AE but **include them in coverage/reliability reporting**. Use exact measured **final container** bytes for ground truth.

For quality, measure properly aligned source vs candidate using supported VMAF/SSIM/PSNR, with per-scene/tail diagnostics and metric model+processing identity. High VMAF against an already-lossy source is not proof of recovered original quality. Do not auto-approve HDR/Dolby Vision based on SDR VMAF.

## 7. Stopping and adaptive decision benchmark

- Separate a **provisional predictor** (`prediction_range`) from a **safety gate** (`recommended`, `skip`, `sample_more`, `abstain`). Apply policy and unknown-handling consistently for all candidate algorithms.
- Proposed decision rule for testing: stop with `skip` if even a calibrated optimistic scenario cannot meet minimum savings; stop with `recommend_for_full_validation` if a calibrated conservative scenario meets savings and quality/cost conditions; otherwise sample more while limits remain, then `abstain`.
- A *recommendation for full validation* is never authorization for source replacement. Actual `apply` must reverify the complete output.
- Formal intervals require a specified sampling/coverage model. Repeated optional stopping can invalidate ordinary fixed-design CIs; test anytime-valid bounds or separately-calibrated decision thresholds if adaptive claims are made. Otherwise label ranges `empirical heuristic` and avoid coverage guarantees.
- Analyze sensitivity at boundaries such as minimum 5%, 10%, 20%, and 30% savings; compare both absolute (GiB) and relative gates and explicit AND/OR composition.
- Pre-register maximum sampling budget (encoded seconds, trials, wall time) and minimal useful material savings. Enforce limits even when tool retries or quality searches perform nested FFmpeg calls.

## 8. Pre-registered gates for selecting an estimator

These are **proposed target values for agent/user review**, not validated current performance:

1. **Correctness:** 100% of qualifying ground-truth outputs pass required technical stream/content validation; failed/unsupported trials remain visible. No silent edits, no source loss.
2. **Decision reliability:** On the *held-out supported cohort*, target `decision_precision ≥ 95%` and report the denominator and confidence limitations; if the sample is too small, **do not claim 95%**. Conservative abstention is acceptable.
3. **Size prediction:** For the chosen primary estimate mode, initially seek `WAPE ≤ 15%`, `abs(signed_bias) ≤ 5%`, and `P90 APE ≤ 30%`; evaluate per codec pair, container, duration band, and source-size band. If missed, mark the cohort unsupported/uncalibrated and revise, **not** fake precision.
4. **Intervals:** Evaluate empirical coverage for 80%/90% prediction intervals. Intervals that are not calibrated must be marked exploratory. No fixed arbitrary ±10% intervals.
5. **Cost:** Compare improvement in WAPE and false-positive decisions **per additional encoded minute/GB read/kWh**, including per-source overhead and cache effects. If `F1`, `M2` or complex adaptive methods do not materially beat `S3` or `M1` per unit cost, defer them.
6. **Data adequacy:** No claimed estimator acceptance for a codec-pair/cohort without enough independent holdout groups and a disclosed uncertainty statement; small pilot evidence can justify continued research, not production certainty.

Use a results matrix with columns: cohort, method, N independent groups, recipes, sample count/duration, WAPE, median/P90 APE, bias, interval coverage+width, decision precision, abstention, wall time, energy evidence and failure count.

## 9. Execution schedule and reporting

1. **Stage A — zero-encode baseline:** Build read-only inventory; apply min source bitrate/resolution/duration/size eligibility; calculate exact budget feasibility; run `M0`, `M1` only when trained priors exist. Prove no FFmpeg encode process was launched.
2. **Stage B — small controlled pilot:** Freeze corpus, settings and splits; run `S3`, `S5`, `S8` using a small recipe grid; confirm actual stream/packet accounting, segment seeking and cache identities. Stop if validation, cancellation or resource budgets misbehave.
3. **Stage C — full-file truth:** Encode only approved calibration/holdout sources **into separate test outputs**, recording complete streams, bytes, duration, quality where valid and wall/energy costs.
4. **Stage D — compare/decide:** Score all methods on locked holdout; analyze residuals and outcomes near thresholds. Only then enable additional algorithm complexity (`M2`, `F1`, `SA`, optional `AB`) if likely to win on benefit/cost.
5. **Stage E — acceptance:** Publish immutable report JSON, summary Markdown, environment manifest, decision record and reproducible commands/configs; do not overwrite a previous run. Do not apply to a real media library as part of benchmarking.

**Artifacts:** `benchmarks/<run-id>/manifest.json`, `recipes.json`, `samples.jsonl`, `measurements.jsonl`, `ground_truth.jsonl`, `predictions.jsonl`, `summary.json`, `report.md`, `validation.json`. These are **proposed v1 artifacts**; finalize their schema before implementation. Secrets/cookies and sensitive source paths must not enter public reports.

## 10. Primary references to independently reverify

- [ab-av1](https://github.com/alexheretic/ab-av1) — short-sample estimation, CRF search and JSON output (verify current commands/schema).
- [Av1an](https://github.com/rust-av/Av1an) — scene-level and chunked encoding approaches (later option).
- [ffmpeg-quality-metrics](https://github.com/slhck/ffmpeg-quality-metrics) — per-frame reference metrics and summary API.
- [VCA](https://github.com/cd-athena/VCA) — spatial/temporal complexity feature extraction; review license/dependencies.
- [SVT-AV1 Bitrate Estimation Using Motion Search Information](https://arxiv.org/abs/2407.05900) — model feature choices; validate datasets and error metrics before adoption.
- [Parametric Rate-Distortion Model for Video Transcoding](https://arxiv.org/abs/2404.09029) — applicability of fitted rate–distortion curves; not a universal cross-codec constant.
- [FFmpeg documentation](https://ffmpeg.org/ffmpeg.html), [FFprobe documentation](https://ffmpeg.org/ffprobe.html).

**Handoff gate:** The agent must bring back the frozen corpus and recipe design, budget estimate, acceptance metrics and any concerns about statistical identifiability **before** expensive full-file calibration begins.
