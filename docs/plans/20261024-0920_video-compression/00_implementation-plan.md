# Implementation Plan — Estimation-First Video Compression for `scripts`

**Plan ID:** `20261024-0920_video-compression`  
**Date:** 2026-10-24  
**Branch:** `videocompress-20261024-0920`  
**Worktree:** `C:\Users\mcarls\src\scripts\.worktrees\videocompress-20261024-0920`  
**Package:** `modules/videocompress` (`vcompress`)  
**Integration Points:** `modules/compresser` (`compresser video`, `compresser tui`), `modules/cli_tui`, `modules/scripts_help`  
**Reference Handoff Package:** `modules/videocompress/docs/` (`IMPLEMENTATION_PLAN.md`, `ESTIMATION_BENCHMARK_PROTOCOL.md`, `MEDIA_SAFETY_CONTRACT.md`, `INTEGRATION_CONTRACTS.md`)

---

## 1. Executive Summary & Goals

Build a media-aware decision and compression system (`videocompress`), not an exhaustive video encoding matrix. Retain the existing image-compression workflow in `compresser`. Create a standalone `videocompress` backend integrated under `compresser video`, and separately enable `compresser tui` via the existing `cli_tui` package.

The core workflow:
```text
Fast complete inventory (no encodes)
  -> user-selected lower-bound eligibility filters (video bitrate, resolution, size, duration)
  -> cheap, explicitly uncertain prediction / feasibility checks (no encodes)
  -> a deterministic plan with a displayed work budget
  -> selective short-segment trial encodes only with explicit opt-in
  -> quality and size analysis, with evidence/calibration status
  -> optional previews and selected full-file calibration runs
  -> independently authorized, verified, journaled apply/recover
```

### Non-Negotiable Invariants
1. **Mode Discipline**: `inventory`, `plan`, and `estimate --tier metadata` **never** encode video.
2. **Stream Preservation**: Preserve all compatible audio, subtitle, chapter, font attachment, and metadata tracks by default; do not silently transcode audio to AAC or drop subtitles.
3. **Hardware Grounding**: Leverage local FFmpeg 9.0.2 and NVIDIA GeForce RTX 5090 Blackwell NVENC (`av1_nvenc`, `hevc_nvenc`, `h264_nvenc`) with verified hardware capabilities.
4. **Crash Safety & Atomic Journaling**: File publication occurs via staged atomic moves with durable state tracking. In-place replacement requires separate, explicit authorization.
5. **No Regressions**: Existing `compresser` image operations, MangaDL workflows, and `scripts_help` must continue passing 100% of tests.

---

## 2. Staged Roadmap

| Stage | Focus | Status | Deliverables & Verification Gates |
|---|---|---|---|
| **0** | Verification & Architecture | **IN PROGRESS** | Local tool audit (FFmpeg 9.0.2, RTX 5090, curses), decision record answering the 12 handoff questions, module scaffolding (`videocompress` 0.1.0, contracts, CLI parser, test suite). |
| **1** | Optional TUI for Images | Planned | Integrate `compresser tui` using `cli_tui`; verify native Windows curses launch and process-tree cancellation without touching image CLI semantics. |
| **2** | Video Package & Capabilities / Inventory / Filters | Planned | Implement `vcompress capabilities`, `inventory` (`files`, `probe`), stream layout parsing, and user eligibility filters (`-B`, `-R`, `-S`, `-D`). |
| **3** | Cheap Predictor & Feasibility Screening | Planned | `vcompress plan` and `vcompress estimate --tier metadata`: container math, bit budget feasibility arithmetic, honest abstention. Zero target encodes. |
| **4** | Controlled Encoder & Measurement Backend | Planned | Typed recipes (`av1_nvenc`, `hevc_nvenc`), FFmpeg subprocess manager, temporal sampling windows, trial cache, bounded work scheduler. |
| **5** | Quality, Comparison & Previews | Planned | VMAF/metric scoring, recipe comparison reports, clip preview generation with manifests. |
| **6** | Estimation Calibration & Selection | Planned | Stratified validation on representative test corpus; empirical error calibration; selection of optimal sampling strategy (S3/S5/S8/SA). |
| **7** | Safe Apply & Recovery | Planned | Staged publication to external tree (`apply -w`), journal state machine, verification levels (V1/V2), non-clobber guarantees, read-only recovery inspection. |
| **8** | Final Integration & Performance Audit | Planned | `compresser video` router, `compresser tui` video menu, full regression suite (`pytest`, `Invoke-Tests.ps1`), documentation. |

---

## 3. Approval and Verification Boundaries

- **Local Tests**: All tests run against module-local `.pytest_tmp_root` and isolated synthetic fixtures.
- **Production Media**: No production video library scanning or transcoding is authorized without explicit, scoped user confirmation.
- **Stage Progression**: Each stage must achieve a clean test run, updated status and checklist, and user review before advancing.
