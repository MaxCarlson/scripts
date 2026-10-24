# Stage 5 Plan: Quality, Compare & Preview

**Stage:** 5  
**Plan ID:** `20261024-0920_video-compression`  
**Date:** 2026-10-24  
**Status:** In Progress  

---

## 1. Goal & Architectural Boundaries

Implement frame-aligned objective quality measurement, multi-recipe comparison reports, and visual preview generation without modifying source files or enabling full-file encoding:
1. **Frame-Aligned Quality Scoring**: Extract temporal source slice and compare against encoded sample clip using aligned frame timestamps. Support SSIM, PSNR, and VMAF metrics via FFmpeg filter graphs.
2. **Quality vs Bitrate Confidence Separation**: Keep confidence in measured sample bitrate separate from confidence in perceptual quality and full-file savings. Record explicit caveats regarding generational loss and lossy source reference.
3. **Multi-Recipe Comparison (`vcompress compare` / `analyze`)**: Evaluate candidate recipes (AV1 vs HEVC vs H.264, varying CQ/CRF) across shared sample windows. Generate Pareto-efficiency rankings (savings vs quality vs encoding throughput).
4. **Visual Preview Generation (`vcompress preview`)**: Render bounded visual preview clips (side-by-side split-screen comparison or synchronized clips) and structured inspection manifests (`preview_manifest.json`) in `<workspace>/previews/<preview_id>/`.
5. **Media Safety & Immutability**: All preview clips written to external workspace preview folders. Source media is verified read-only (`mtime_ns:size` immutability check). Zero full-file encoding.

---

## 2. Modules to Implement

| Module | Purpose |
|---|---|
| `videocompress.quality` | Frame-aligned metric calculation (SSIM, PSNR, VMAF) via FFmpeg filtergraph. |
| `videocompress.compare` | Multi-recipe comparison engine, Pareto frontier analysis, and reporting. |
| `videocompress.preview` | Side-by-side comparison clip rendering and visual preview manifest generation. |
| `videocompress.cli` | Integration into `vcompress compare`, `vcompress analyze`, and `vcompress preview`. |

---

## 3. Verification Criteria

1. **Frame Alignment**: Tests verify reference and distorted clips are synchronized with zero-start timestamps (`settb=AVTB,setpts=PTS-STARTPTS`).
2. **Metric Extraction**: Tests parse real and synthetic filter outputs for PSNR, SSIM, and VMAF cleanly.
3. **Multi-Recipe Comparison**: Running compare across 2+ recipes produces valid side-by-side metrics and rankings.
4. **Visual Preview Manifest**: Preview operation renders clips in `<workspace>/previews/` with valid `preview_manifest.json`.
5. **Immutability & Zero Full-File Encoding**: Verified source files remain untouched and only short bounded clips are encoded.
