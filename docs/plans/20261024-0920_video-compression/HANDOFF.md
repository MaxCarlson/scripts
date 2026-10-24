# Plan Handoff: Video Compression (`20261024-0920_video-compression`)

**Date:** 2026-10-24  
**Branch:** `videocompress-20261024-0920`  
**Worktree:** `C:\Users\mcarls\src\scripts\.worktrees\videocompress-20261024-0920`  
**Active Plan Location:** `docs/plans/20261024-0920_video-compression/`  
**Status:** Stage 0, Stage 1, Stage 2, Stage 3, Stage 4, and Stage 5 completed and verified across all test suites.

## Summary of Accomplishments

1. **Stage 0 Environment Verification & Architecture**:
   - Audited local environment: FFmpeg 9.0.2 full build (with `av1_nvenc`, `hevc_nvenc`, `libvmaf`), NVIDIA RTX 5090 Blackwell GPU (Driver 617.14, 32GB VRAM), Python 3.12 curses.
   - Initialized standalone `modules/videocompress` (`0.1.0`) with console script `vcompress`.
   - Addressed all 12 architectural questions in `00_stage0_decisions_and_verification.md`.
2. **Stage 2 Discovery, Probe, Eligibility & SQLite Caching**:
   - `videocompress.workspace`: path-hashed external workspaces (`.videocompress/<leaf>_<hash>/`).
   - `videocompress.discovery`: scoped recursive file finding, loop/workspace exclusion guards.
   - `videocompress.probe`: full FFprobe JSON extraction (video, audio, subtitles, attachments, chapters, HDR10/BT.2020, display rotation).
   - Video stream bitrate strictly isolated from container bitrate with provenance tracking.
   - `videocompress.eligibility`: configurable lower bounds (`-B`, `-R`, `-S`, `-D`) with display rotation adjustment and conservative unknown handling.
   - `videocompress.inventory`: SQLite cache (`inventory.sqlite3`) with WAL mode, schema version 1, incremental mtime:size change detection, and stale file pruning.
   - `videocompress.events`: monotonic progress event emission for CLI and future `cli_tui` integration.
   - `vcompress inventory` CLI: human-readable and structured JSON outputs (`-J`).
   - Addressed user review findings: decoupled `source_id` from mutable mtime/size, added `-f/--force-refresh`.
3. **Stage 1 TUI Integration for Images (`compresser tui`)**:
   - Added `windows-curses>=2.4.1; sys_platform == 'win32'` platform dependency in `modules/cli_tui/pyproject.toml`.
   - Resolved process-tree orphan risk: implemented non-forced `taskkill /PID <pid> /T` in `ProcessRunner.terminate()` and forced `taskkill /F /T /PID <pid>` in `kill()`.
   - Connected `compresser tui`, `compresser -T`, and `compresser --tui` CLI routing *before* image-only argument normalization.
   - Implemented `modules/compresser/compresser/tui.py`: introspected `compresser` parser into interactive forms, filtered `tui` to prevent recursion, and connected post-run preview viewer for `preview` operation.
4. **Stage 3 Cheap Predictor & Feasibility Screening (Corrected & Verified)**:
   - Quantile consistency corrected: strictly enforced and verified $\text{Output}(q) + \text{Savings}(q) = \text{Source}$ across all quantiles ($p_{10}, p_{50}, p_{90}$) with monotonic ordering.
   - Container size reconciliation: tracks probed stream bitrate vs container size, recording unaccounted container bytes and issuing discrepancy warnings.
   - Heuristic non-video decomposition: explicitly labeled as `estimated_stream_heuristics`, `estimated_fallback`, and `estimated_container_model`.
   - Quality floor re-classification: bitrate floors treated as heuristic screening signals (`quality_floor_violation`, `is_hard_infeasible = False`), reserving `infeasible` strictly for physical budget overflow ($V_{\max} \le 0$).
   - Honest calibration status: labeled as `uncalibrated_scenario_assumptions` with capped confidence.
   - Parameterized property-based consistency tests added and verified.
5. **Stage 4 Controlled Encoder & Measurement Backend**:
   - `videocompress.adapters.ffmpeg`: robust FFmpeg subprocess wrapper with `-nostdin`, `-hide_banner`, `-nostats`.
   - Strict Media Safety: verified source immutability guard (`mtime_ns:size`), isolated scratch execution (`<workspace>/scratch/trial_<id>/`), and automatic scratch cleanup.
   - Subprocess Management & Cancellation: Windows process tree termination (`taskkill /PID <pid> /T` followed by forced `/F` if needed) preventing orphan `ffmpeg.exe` processes on timeout or abort.
   - `videocompress.sampling`: deterministic temporal window selection (`s3`, `s5`, `s8`) across playable duration with short-asset boundaries.
   - Output Validation: all sample outputs probed via FFprobe, verifying non-empty container, video stream existence, target codec match, and elementary stream bitrate.
   - `videocompress.trials`: SQLite cache (`trials.sqlite3`) with WAL mode and `(source_id, stat_fingerprint, recipe_id, window_index)` key deduplication.
   - Quota Scheduling: `--max-trials` and `--max-time` limits enforced.
   - Empirical Sample Aggregator: combines measured sample bitrates with Stage 3 stream breakdown to produce empirical `estimate --tier sampled` predictions.
   - CLI integration: connected `vcompress estimate --tier sampled` with budget controls.
   - Zero full-file encoding: verified zero full-file encoding and zero source mutations in Stage 4.
6. **Stage 5 Quality, Compare & Preview**:
   - `videocompress.quality`: frame-aligned metric calculation (SSIM, PSNR, VMAF) via synchronized FFmpeg filtergraph with `settb=AVTB,setpts=PTS-STARTPTS,format=yuv420p`.
   - Perceptual vs Bitrate Confidence Separation: full-reference metrics explicitly documented as measuring fidelity to the existing lossy reference, with mandatory caveats alerting that measured bitrate confidence does not guarantee preserved visual quality.
   - Source Immutability Guard: verified before/after execution; raises `SourceMutationError` if mutated.
   - `videocompress.compare`: multi-recipe empirical comparison across candidate recipes (`vcompress compare` / `vcompress analyze`), computing Pareto efficiency (savings vs quality vs encoding FPS) and recipe rankings.
   - `videocompress.preview`: visual preview generator rendering side-by-side split-screen comparison clips (`hstack`) and standalone clips with structured inspection manifests (`preview_manifest.json`) in `<workspace>/previews/<preview_id>/`.
   - CLI integration: connected `vcompress compare`, `vcompress analyze`, and `vcompress preview` with formatted comparison tables and structured JSON (`-J`). All flags have short and long forms.
7. **Verification & Testing Evidence**:
   - `modules/videocompress/tests`: **85/85 passed** in 3.88s.
   - `modules/cli_tui/tests`: **107/107 passed** in 6.32s.
   - `modules/compresser/tests`: **523 passed, 1 skipped** in 40.0s.
   - `modules/scripts_help/tests`: **55/55 passed** in 0.76s.
   - Total test suite: **770 passed, 1 skipped** across the repository.

## Next Step

Present Stage 5 deliverables, quality metric contracts, Pareto rankings, preview manifests, tests, and commit SHA to user for review before proceeding to Stage 6 (Estimation Calibration & Selection).
