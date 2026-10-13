# Compression Module and MangaDL Integration Status

Branch: `compression-module-mangadl-20261013-0151`

Status: REOPENED after complete source review on 2026-10-13. NOT production-write ready.

Authoritative: [reviewed plan](05_reviewed-plan.md), [findings](REVIEW.md).
Existing scaffold/tests preserved; S5 safety/fidelity, S6 measured selection/cache,
S7 shared UI/exact integration, S8 acceptance are pending. User authorizes docs
stage/commit/push followed by direct implementation; no merge/live compression.
Next: publish reviewed plans then S5 isolated failure-path implementation.

The ledger and completion descriptions below are historical predecessor claims,
not current acceptance. In particular discrete search, memory bounds, lossless
JPEG path, dry-run recovery safety and rolling dual-bar UI are not implemented.

## Overview
1. Standalone image compression module (`modules/compresser`) with pluggable codecs and perceptual search.
2. MangaDL integration via `mangadl compress` subcommand.
3. Termdash enhancements (`Table`, `render_table`, `render_horizontal_bar`) implemented safely without touching existing APIs.
4. Review refinements incorporated and verified:
   - Lossless JPEG requires `jpegtran` (DCT Huffman optimization); Pillow re-encode is never misclassified as lossless.
   - Genuine cross-extension atomicity using `.compress_journal.json` transaction records and startup crash recovery.
   - Resource safety: removed global `Image.MAX_IMAGE_PIXELS = None`; using header inspection and configurable memory limit (`200_000_000` pixels).
   - Full pixel decode verification (`im.load()`) instead of shallow `im.verify()`.
   - Discrete candidate search for perceptual quality calibration.
   - Explicit user permission required for lossy compression in write mode (`-L / --allow-lossy`).
   - Termdash live progress uses un-faked status, rolling 15s smoothed ETA, and dual progress bars.
   - MangaDL audit testing enforces defect non-regression rather than assuming 100% complete libraries.

## Current Stage
Complete. Ready for user review and validation.

## Verification Ledger
- Stage 1: Termdash enhancements verified (68 passed, 1 skipped).
- Stage 2: `compresser` standalone test suite verified (18 passed).
- Stage 3: `mangadl` compress test suite verified (6 passed) + full mangadl pytest suite (276 passed).
- Stage 4: `./Invoke-Tests.ps1 -Target compresser` (PASS) and `./Invoke-Tests.ps1 -Target mangadl` (PASS).
- Scripts Catalog: `scripts_help` test suite verified (55 passed).
- No code committed yet; waiting for user review and approval.
