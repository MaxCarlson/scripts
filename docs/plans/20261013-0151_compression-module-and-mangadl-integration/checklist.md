# Compression Module and MangaDL Integration Checklist

## Reviewed acceptance gates (2026-10-13)

The original checked items below are predecessor claims, NOT accepted guarantees.
Use REVIEW.md and 05_reviewed-plan.md; these reopened gates are authoritative.

- [x] Review all plan/source/test changes and saved folder report.
- [x] Record truthful safety/fidelity/analysis/UI requirements and audit follow-up.
- [x] Publish docs-only revised plans before implementation (`f1baeab`).
- [x] S5 read-only analysis, owned durable transactions/recovery, collision/source
  drift/concurrency refusal, truthful codecs, quality rejection and failure tests.
- [x] S5 CLI input/exit/JSON contracts and enforced decode/resource bounds.
- [x] S6 real PNG/codec selection, measured auto, stratified savings, persistent
  inventory/benchmark cache and bounded perceptual memory.
- [ ] S7 termdash widths/Unicode, true renderer/gallery/overall/rolling ETA,
  stderr/plain/NO_COLOR, exact MangaDL selection and finally cleanup.
  - [x] Shared LiveBlock renderer, exact flat-gallery selection, summaries/timers.
  - [x] Nested galleries and MangaDL run/repair/compression operation ownership.
  - [ ] Standalone/external-writer boundary and real terminal/reader QA.
- [ ] S8 full affected suites, dispatcher, real terminal and isolated acceptance,
  truthful docs/API/version sync. No merge or production writes.

Branch: `compression-module-mangadl-20261013-0151`

## Stage 1: Termdash Enhancements (`modules/termdash`)
- [x] Add `Table` class and `render_table()` in `modules/termdash/table.py`
  - [x] Auto-calculate column widths based on longest cell content
  - [x] ANSI-aware text length measurement (ignoring escape codes)
  - [x] Support left, right, and center alignments per column
  - [x] Configurable borders / dividers matching Termdash separator styles
  - [x] Handle column width limits with clean truncation
- [x] Add `render_horizontal_bar()` in `modules/termdash/progress.py`
  - [x] Width-bounded bar rendering with fill character and background
  - [x] Ratio or percentage support
  - [x] ANSI color support for filled vs empty segments
- [x] Expose `Table`, `render_table`, and `render_horizontal_bar` in `termdash/__init__.py`
- [x] Add unit tests in `modules/termdash/tests/table_test.py`
- [x] Add unit tests in `modules/termdash/tests/horizontal_bar_test.py`
- [x] Bump `termdash` version in `pyproject.toml` (0.5.0 -> 0.6.0)
- [x] Run full termdash test suite and ensure all pass (68 passed)

## Stage 2: Reusable Standalone `compresser` Module (`modules/compresser`)
- [x] Create package layout (`pyproject.toml`, `README.md`, `compresser/`)
- [x] Implement `compresser/models.py` (data structures for scans, plans, results)
- [x] Implement `compresser/scanner.py` (recursive directory scanning, image metadata)
- [x] Implement `compresser/perceptual.py` (vectorized NumPy SSIM, quality binary search)
- [x] Implement `compresser/codecs/`
  - [x] Base codec interface (`codecs/base.py`)
  - [x] Pillow JPEG codec (`codecs/pillow_jpeg.py`)
  - [x] Pillow WebP codec (`codecs/pillow_webp.py`)
  - [x] Pillow AVIF codec (`codecs/pillow_avif.py`)
  - [x] External CLI detector (`codecs/external_cli.py`)
- [x] Implement `compresser/engine.py` (multi-threaded compression, atomic swap, size guard)
- [x] Implement `compresser/cache.py` (mtime/size-based benchmark caching)
- [x] Implement `compresser/ui.py`
  - [x] Live in-place Termdash dashboard (lines 1-N status, per-file bar, overall bar)
  - [x] Post-run colored summary table via `render_table`
  - [x] Post-run comparison table with horizontal comparison bars
- [x] Implement `compresser/cli.py` & `compresser/__main__.py`
  - [x] All arguments have short and long forms
  - [x] Analysis/dry-run by default, `-w/--write` to apply
  - [x] Subcommands/options for analyze, compare, compress
- [x] Initial test suite in `modules/compresser/tests/` (17 passed)
- [x] Refine core per external review:
  - [x] Strict lossless JPEG: Require `jpegtran` for true DCT-level optimization; never claim Pillow re-encode is lossless; report unavailable if `jpegtran` absent
  - [x] Bounded resource safety: Remove global `Image.MAX_IMAGE_PIXELS = None`; use header inspection and configurable memory-safe limit
  - [x] Full pixel decode verification: Upgrade `validate_image_file` to use `im.load()` / dimension checking rather than just `im.verify()`
  - [x] True cross-extension crash safety: Implement `.compress_journal.json` transaction records and startup crash recovery
  - [x] Robust quality search: Implement bounded candidate search across discrete qualities
  - [x] Cache key precision: Include encoder name/version, metric version, and full strategy parameters
  - [x] Termdash UI polish: Show active task / last completed file, current gallery progress, overall progress, and 15s rolling smoothed ETA

## Stage 3: MangaDL Integration (`mangadl compress`)
- [x] Create `modules/mangadl/mangadl/compress.py`
  - [x] Resolve destination libraries, gallery folders, or URL files
  - [x] Integrate with `compresser` API
  - [x] Gallery-level and collection-level progress reporting
- [x] Register `compress` subcommand in `modules/mangadl/mangadl/cli_core.py`
  - [x] All flags have short and long forms
  - [x] Proper help strings and default values
- [x] Enforce library safety and invariants:
  - [x] Atomic file replacement with crash recovery journal to prevent duplicate page files (`001.jpg` + `001.webp`)
  - [x] WebP 16,383px height limit guard (skip WebP for tall manhwa)
  - [x] Explicit lossy permission required (`--allow-lossy` or `-m lossy`) in write mode
  - [x] Memory-safe decompression limits without process-global bypass
  - [x] Preserve sidecar files (`info.json`, `.mangadl-source.json`, covers)
- [x] Expand unit tests in `modules/mangadl/tests/compress_test.py`:
  - [x] Dry-run analysis
  - [x] Write mode with atomic replacement
  - [x] Invariant defect non-regression test: incomplete galleries retain their exact missing pages without false repairs, and clean galleries remain 100% clean with 0 duplicate pages
  - [x] Size guard (refusing larger files unless requested)
  - [x] WebP tall image fallback
  - [x] Crash recovery test for interrupted cross-extension conversion

## Stage 4: Repository Registration & Verification
- [x] Register `compresser` in `validation-targets.json`
- [x] Add `compresser` to `mangadl` bootstrap in `validation-targets.json`
- [x] Register `compresser (module)` in `modules/scripts_help/scripts_help/registry/registry.py`
- [x] Update `docs/HANDOFF.md` and plans
- [x] Run `./Invoke-Tests.ps1` for `compresser` and `mangadl` (both 100% PASS)
- [x] Run Termdash pytest suite (68 passed, 1 skipped)
- [x] Run scripts_help pytest suite (55 passed)
- [x] Run Ruff linting and Python compilation checks
- [x] Verify `--help` contract for both `compresser` and `mangadl compress`
