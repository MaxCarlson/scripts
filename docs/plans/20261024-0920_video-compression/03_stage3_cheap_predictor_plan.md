# Stage 3 Implementation Plan — Cheap Predictor & Feasibility Screening

**Plan ID:** `20261024-0920_video-compression`  
**Stage:** 3  
**Focus:** Pure metadata-based feasibility screening, container math, honest uncertainty, zero encodes  
**Branch:** `videocompress-20261024-0920`  

---

## 1. Objectives & Non-Negotiable Invariants

1. **Zero-Encode Guarantee**:
   - Predictor and planner must **never** invoke FFmpeg, spawn encoder processes, or touch source media files.
   - Verified via static analysis and monkeypatched process test guards.

2. **Container Math & Stream Accounting**:
   - Separate accounting for video elementary stream, audio streams, subtitle streams, font attachments, and container mux overhead.
   - Never assume container bitrate equals video bitrate.
   - If container bitrate is used as an approximation when video stream bitrate is missing, explicitly label it: `bitrate_provenance = "container_derived_approximation"`.

3. **Hard Impossibility vs. Heuristic Feasibility**:
   - If mandatory preserved non-video streams and mux overhead exceed the target budget, classify as `infeasible` (`infeasible_nonvideo_budget_exceeded`).
   - If required video bitrate falls below minimum acceptable quality floor, classify as `infeasible` (`infeasible_bitrate_below_floor`).
   - Distinct from heuristic prior predictions (`eligible_promising`, `eligible_uncertain`, `eligible_unlikely`).

4. **Honest Uncertainty & Calibration Integrity**:
   - Output predicted ranges as intervals (`p10`, `p50`, `p90`).
   - Never claim precise CRF/CQ-to-size predictions without empirical calibration (`calibration_status = "uncalibrated_metadata_prior"`).
   - Never assume lower bitrate preserves perceptual quality.
   - Explicitly report rejection reasons, warnings, and confidence.

---

## 2. Planned Deliverables

1. `videocompress/recipes.py`:
   - Typed standard recipes (`av1_nvenc_cq30`, `hevc_nvenc_cq28`, `h264_nvenc_cq24`).
   - Parser and resolver for CLI `--recipe` strings.

2. `videocompress/predictor.py`:
   - Pure Python mathematical feasibility engine.
   - Stream breakdown: audio payload, subtitle payload, attachments, container mux overhead.
   - Codec priors (H.264 -> HEVC -> AV1) with adjustments for resolution, bpppf, HDR10/10-bit, and frame rate.
   - `evaluate_feasibility(asset, recipe, ...)` returning typed `Prediction` and `FeasibilityReport`.

3. `videocompress/plan.py`:
   - `build_estimation_plan()`: Freezes target scope, eligible inventory assets, target recipes, and deterministic sampling windows.
   - Saves frozen plan artifact to `<workspace>/plans/<plan_id>.json`.

4. `videocompress/cli.py` Integration:
   - Subcommand `vcompress plan`: creates frozen estimation plan.
   - Subcommand `vcompress estimate --tier metadata`: runs zero-encode feasibility screening across inventory.
   - Emits human-readable tables and structured JSON (`-J`/`--json`).

5. Comprehensive Unit & Regression Tests (`tests/test_predictor.py`, `tests/test_plan.py`):
   - Pure math tests (known bitrates, missing bitrates, zero duration, non-video budget overflows).
   - Unusual stream combinations (multitrack audio, PGS subtitles, fonts).
   - Already-efficient AV1 sources and ultra-low bitrate sources.
   - HDR10/PQ and VFR metadata handling.
   - Process execution prohibition verification (subprocess monkeypatch).
