# Stage 0 — Decision Record & Environmental Verification

**Plan:** `20261024-0920_video-compression`  
**Date:** 2026-10-24  
**Audited Baseline:** Git commit `6fa307f3` on `videocompress-20261024-0920`  

---

## Part 1: Environmental Audit & Verified Hardware Facts

| Capability | Probed Fact | Status | Notes |
|---|---|---|---|
| **OS** | Windows 11 Enterprise / PowerShell 7.5 | Verified | Native Windows environment. |
| **GPU** | NVIDIA GeForce RTX 5090 (Blackwell) | Verified | Driver 617.14, CUDA 13.4, 32,607 MiB VRAM. |
| **FFmpeg** | `ffmpeg 9.0.2-full_build-www.gyan.dev` | Verified | Full build with gcc 16.2.0; supports NVENC/NVDEC, libvmaf, libsvtav1, libx265, libx264. |
| **Hardware Encoders** | `av1_nvenc`, `hevc_nvenc`, `h264_nvenc` | Verified | All present in `ffmpeg -encoders`. |
| **Software Encoders** | `libsvtav1`, `libx265`, `libx264`, `librav1e`, `libaom-av1` | Verified | All present for software baseline comparisons. |
| **VMAF** | `libvmaf`, `vmafmotion` | Verified | Present in `ffmpeg -filters`. |
| **`ab-av1`** | Not found on host PATH | Verified | Native FFmpeg backend must be the primary/default encoder. An `ab-av1` adapter can remain an optional capability if installed later. |
| **Curses (Windows)** | `import curses` succeeds | Verified | Standard curses wrapper present in Python 3.12 environment on this machine. |

---

## Part 2: Answers to the 12 Local Agent Architectural Questions

### 1. Coupling and Dependency Direction between `compresser` and `videocompress`
- **Decision:** Build `videocompress` as a clean, independent module with its own standalone CLI entrypoint (`vcompress = "videocompress.cli:main"`).
- **Coupling Prevention:** `videocompress` will **never** import `compresser.cli`, Pillow image models, or image transactions.
- **Routing:** `compresser` will provide a thin, lazy router: when `compresser video <args>` is invoked, it delegates to `videocompress.cli.main(args)`. If `videocompress` is not installed, it yields a clear diagnostic without failing normal image commands.

### 2. FFprobe Fields and Fallback Policies
- **Video Bitrate:** Probed from `stream['bit_rate']`. If missing or 0, fallback to calculating `container_bit_rate - sum(known_audio_bitrates)` only with provenance tag `estimated_from_container`. If container bitrate is also missing, record `unknown_video_bitrate`.
- **Rotation:** Extracted from stream side data / display matrix (`rotation` or `displaymatrix`). Output resolution calculation must apply rotation before applying resolution filters.
- **VFR:** Inferred from `avg_frame_rate != r_frame_rate`.
- **HDR:** Identified via `color_transfer` in (`smpte2084`, `arib-std-b67`) and `color_primaries` (`bt2020`). Any asset with Dolby Vision or HDR dynamic metadata is tagged and marked **ineligible for automatic lossy apply by default**.
- **Multi-Video Tracks:** Counted and inventoried; if multiple non-cover-art video streams exist, the asset is tagged `multi_video_streams` and skipped for automatic apply until an explicit primary stream policy is given.

### 3. Promoting No-Encode Estimates to Decision-Grade
- **Rule:** A no-encode estimate (`--tier metadata`) provides **feasibility screening and candidate ranking only**, not decision-grade proof of quality.
- **Abstention:** If an asset belongs to an uncalibrated cohort (unseen source codec, extreme bitrate/resolution combination, or missing stream bitrates), the estimator returns `decision = "needs_measurement"` with an explicit `abstention_reason`. It will **never** fabricate a fixed 50% savings ratio.

### 4. Native FFmpeg vs `ab-av1`
- **Decision:** Since `ab-av1` is not currently present on the host PATH and native FFmpeg 9.0.2 is fully equipped with `av1_nvenc` and `libvmaf`, **native FFmpeg is the primary engine**.
- **Scope:** Native FFmpeg gives complete control over stream mapping (`-map 0`), audio copying, subtitle preservation, and bounded progress parsing (`-progress`). An `ab-av1` adapter remains optional if the binary is provided.

### 5. Benchmark Corpus and Budget
- **Corpus Proposal:** A synthetic and royalty-free test corpus (15–20 short clips) spanning 1080p/4K, H.264/HEVC/AV1, diverse content types (film, anime/flat art, high grain, fast action, screen recording).
- **Group-Disjoint Holdout:** Files grouped by source series/origin so that training and holdout evaluation never share frames or duplicate sequences.
- **Budget:** Strict per-run timeout (`-M 5m`) and max trials (`-T 10`). Synthetic fixtures for unit tests are capped at <= 5 seconds.

### 6. Temporal Sampling and GOP Bias
- **Risk:** Short 10s–20s clip encodes have a higher proportion of I-frames (GOP starts) than a continuous stream, which can bias the estimated bitrate upward.
- **Detection & Mitigation:** Compare clip-sum bitrate against complete-file ground truth during Stage 6 calibration. Clip extraction will discard warmup frames or use pre-roll where necessary, and empirical GOP bias correction will only be applied if verified against held-out complete encodes.

### 7. Acceptable Error and False-Positive Rates
- **Thresholds:**
  - Median Byte Error: <= 8% on calibrated cohorts.
  - P90 Absolute Percentage Error: <= 15%.
  - False-Positive Conversion Rate (predicting >= 20% savings when true savings are < 0% or negative): **0% allowed on holdout**. When in doubt, the decision must abstain to `needs_measurement`.

### 8. Media Preservation Contract
- **Audio:** Copy all audio streams (`-c:a copy`), preserving track order, channels, dispositions, and language tags. Skip transcode if container is incompatible.
- **Subtitles & Attachments:** Copy all subtitle streams (`-c:s copy`) and font attachments (`-c:t copy` for MKV).
- **Exclusions:** Multi-video streams, unverified HDR/Dolby Vision, corrupt seek tables, and unknown codecs cause a recorded skip reason.

### 9. `cli_tui` Windows Integration
- **Verification:** Windows Python 3.12 imports `curses` cleanly on this machine.
- **Subprocess Cancellation:** Must ensure cancellation sends signals to the entire process tree (Job Objects on Windows) so FFmpeg child processes are never orphaned when quitting the TUI.

### 10. Compatibility with Image Workflows
- **Workspaces:** Kept completely separate. Images use `.compresser/<target>/`, videos use `.videocompress/<target>/`.
- **Database/Cache:** Separate SQLite databases (`inventory.sqlite3`, `trials.sqlite3`) and versioned schemas. Image schemas are never loaded or modified by video routines.

### 11. Staging and Independent Approval Gates
- **Stage 1 (TUI Images)** can be delivered and validated independently.
- **Stage 2 (Inventory/Filters)** requires no transcoding and can be tested on mock/synthetic files safely.
- **Stage 3–6 (Estimation/Measurement)** requires synthetic clip encoding with bounded budgets.
- **Stage 7 (Apply)** requires explicit user validation before any write operations.

### 12. Justification for Complexity Models or Core Refactoring
- A complex ML model or global `compression_core` extraction is **not justified** at this time. We maintain a simple, transparent, typed backend in `videocompress` until empirical data demonstrates that a more complex model provides higher accuracy per compute second.
