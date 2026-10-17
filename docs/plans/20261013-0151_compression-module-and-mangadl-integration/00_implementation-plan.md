# Image Compression Module and MangaDL Integration Plan

> Superseded specification: the complete current-tree review on 2026-10-13
> found critical gaps in the guarantees below. Use [reviewed implementation plan](05_reviewed-plan.md)
> and [review findings](REVIEW.md) as authoritative. Retained text below is
> historical design intent, not implemented capability or acceptance evidence.

## Objective

Develop a standalone, reusable image compression module (`modules/compresser`) and integrate it into MangaDL via `mangadl compress`.

The system's goal is to **minimize storage consumption across large manga and manhwa image collections (primarily JPEG and WebP) while providing fine-grained control over image formats, compression algorithms, encoding speed, and perceptual quality loss**.

The implementation adheres to the mandatory `termdash` terminal dashboard and reporting interface, follows repository CLI standards (short and long options), ensures zero data loss, guarantees non-destructive dry-run analysis by default, and preserves MangaDL library audit integrity and Kavita reader compatibility.

---

## 1. Technical Analysis & Environmental Findings

### 1.1 Local Environment State
- **Python**: 3.12.10 (AMD64) on Windows 11.
- **Pillow**: Version 12.2.0 installed. Native support verified for:
  - `webp` (lossy, lossless, effort/method 0–6)
  - `libjpeg_turbo` (Huffman optimization, progressive scans, DCT subsampling)
  - `avif` (AV1 image file format encoding & decoding verified)
  - `zlib_ng` / `png`
- **NumPy**: Version 2.4.4 installed. Enables pure, highly vectorized perceptual metrics (SSIM on luminance). `scikit-image` is not installed; vectorized NumPy SSIM provides a zero-dependency baseline with optional scikit-image dispatch if present.
- **External Binaries**: None currently bundled on PATH (`cwebp`, `jpegtran`, `mozjpeg`, `jpegli`, `cjxl`).
  - *Critical Invariant on JPEG Lossless*: Pillow cannot perform true lossless optimization on existing JPEGs because decoding and re-saving re-encodes DCT coefficients and causes generational loss. True lossless JPEG optimization operates on DCT coefficients without re-encoding pixels (via `jpegtran -optimize -progressive -copy all`).
  - *Policy*: If `jpegtran` is unavailable on PATH, lossless JPEG optimization must report that the capability is unavailable (or requires `jpegtran`), rather than silently performing a lossy Pillow re-encode and labeling it lossless.

### 1.2 MangaDL Architecture & Library Invariants
- **CLI Subcommand Structure**:
  - `mangadl/cli_core.py` builds the top-level argument parser via `build_parser()`.
  - Subcommands are managed through `argparse` subparsers (`run`, `inspect`, `status`, `retry`, `kavita`, `archive`, `patch-hdporncomics`, `audit`, `audit-destinations`, `repair-loose`, `repair-pages`, `repair`, `partials`, `auth`, `favorites`, `covers`).
  - Adding `compress` involves registering `compress` in `cli_core.py` and delegating to `mangadl/compress.py`.
- **Existing `optimizer.py`**:
  - Confirmed to be a worker and network throughput auto-tuner (optimizing worker counts vs image threads for download speed), *not* image compression.
- **Library Layout & Audit Invariants**:
  - MangaDL organizes downloaded galleries into destination folders containing numbered page files: `001.jpg`, `002.webp`, etc.
  - In `destination_audit.py`:
    - `_PAGE_FILE = re.compile(r"^(?P<page>\d+)\.[^.]+$", re.IGNORECASE)`
    - `IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp"}`
    - Images are validated using `_validate_image(path)` which requires non-empty, fully decodable image files.
    - **Critical Invariant**: Pages are grouped by integer page index: `pages[int(match.group("page"))].append(path)`.
    - **Duplicate Page Danger & Cross-Extension Atomicity**: Converting `001.jpg` -> `001.webp` involves two distinct filenames and cannot be a single atomic filesystem rename. If an interruption occurs after `001.webp` is written but before `001.jpg` is removed, both files exist, triggering `duplicate_pages` in `destination_audit.py`!
    - **Transactional Journaling & Crash Recovery**:
      - Conversions must use temporary siblings (`001.webp.tmp_<id>`), full pixel decode validation, and a persistent transaction journal (`.compress_journal.json`).
      - On start or resume, the engine checks for `.compress_journal.json` and performs deterministic recovery (if replacement is valid, complete the removal of the original; if invalid/interrupted, remove replacement and preserve original).
  - In `library_index.py`:
    - Sidecars include `.mangadl-source.json` and `info.json`.
    - `expected_pages` stores page count and integer page numbers (`1, 2, 3...`), not extensions or hashes.
  - In `archive.sqlite3`:
    - Records gallery-dl download keys (e.g. `nhentai 633374 1`). Changing local page extension does not corrupt download keys.
  - **Audit Invariant Verification**:
    - The acceptance criteria for post-compression audit is **defect non-regression**: compression must introduce zero new defects. Incomplete galleries (e.g. missing pages 3 and 7) must remain incomplete with identical missing pages, while clean galleries remain 100% clean with zero duplicate pages.
- **Reader Compatibility & Manhwa Quirks**:
  - **WebP 16,383px Dimension Limit**: WebP has a hard limit of 16,383 pixels in width and height. Manhwa frequently exceeds 20,000–40,000 pixels.
    - *Requirement*: The compression engine must inspect dimensions before WebP conversion. If height or width exceeds 16,383px, it must refuse WebP conversion and retain optimized JPEG/PNG.
  - **Pillow Decompression Bomb Guard**: Never disable Pillow's decompression bomb protection globally (`Image.MAX_IMAGE_PIXELS = None` is unsafe and process-global). Instead, inspect image headers first with `Image.open()` without loading full pixel buffers, and use a safe, configurable pixel limit (e.g. `200_000_000` pixels) that accommodates tall manhwa strips while blocking memory exhaustion attacks.
  - **Kavita / Tachiyomi Compatibility**: WebP, JPEG, and PNG are universal. AVIF is supported where available. JXL is experimental. Color profiles (ICC) and EXIF metadata must be preserved by default.

### 1.3 Termdash Mandatory Integration & Gaps
- **Existing `termdash` APIs**:
  - `TermDash`: In-place cursor manager, thread-safe, multi-line renderer with column alignment (`align_columns=True`).
  - `SimpleBoard`: Row builder using `Line` and `Stat` cells.
  - `ProgressBar`: `ProgressBar.cell()` plugs into `Line` as a `Stat`. Supports `advance()`, `set()`, `set_total()`, and custom charsets.
  - `utils`: Color formatting (`color_text`), time formatting (`fmt_hms`), byte sizing (`fmt_bytes`).
- **Gaps Addressed with Minimal Additions**:
  - To present post-processing summary tables and horizontal comparison bars without breaking existing APIs, `modules/termdash` is extended only with:
    1. `render_table()` / `Table` in `modules/termdash/table.py`.
    2. `render_horizontal_bar()` in `modules/termdash/progress.py`.
  - All existing Termdash classes and methods are strictly preserved and untouched.
  - Termdash owns all terminal output; compression workers report structured events to the UI thread.

---

## 2. Architecture & Design

### 2.1 Standalone Module: `modules/compresser`
The package `compresser` is organized as follows:

```
modules/compresser/
├── pyproject.toml
├── README.md
├── docs/
│   ├── README.md
│   └── HANDOFF.md
├── compresser/
│   ├── __init__.py          # Public API: analyze(), compress(), compare()
│   ├── __main__.py          # CLI entry point: python -m compresser
│   ├── cli.py               # Argument parser and CLI runner (short + long flags)
│   ├── models.py            # Data structures: ImageInfo, CompressionPlan, Result, etc.
│   ├── scanner.py           # Recursive filesystem scanner with metadata extraction
│   ├── perceptual.py        # SSIM, luminance metrics, binary search quality
│   ├── cache.py             # Memory & persistent analysis cache
│   ├── engine.py            # Core compression engine & format router
│   ├── ui.py                # Termdash live progress & summary reports
│   └── codecs/
│       ├── __init__.py      # Backend registry & tool discovery
│       ├── base.py          # Abstract Codec interface
│       ├── pillow_jpeg.py   # Pillow JPEG (lossless optimize & lossy)
│       ├── pillow_webp.py   # Pillow WebP (lossless & lossy)
│       ├── pillow_avif.py   # Pillow AVIF (optional)
│       └── external_cli.py  # Pluggable cwebp, jpegtran, mozjpeg, jpegli
└── tests/
    ├── conftest.py
    ├── scanner_test.py
    ├── perceptual_test.py
    ├── engine_test.py
    ├── cache_test.py
    ├── cli_test.py
    └── ui_test.py
```

### 2.2 Reusable Python API

```python
from compresser import (
    analyze_collection,
    compare_strategies,
    compress_collection,
    CompressionConfig,
    CompressionStrategy,
)

# 1. Non-destructive scan and analysis
analysis = analyze_collection(
    target_path=Path("/manga/series1"),
    recursive=True,
    sample_size=None, # None = full, or int for representative sample
)

# 2. Benchmark competing strategies
comparison = compare_strategies(
    target_path=Path("/manga/series1"),
    strategies=[
        CompressionStrategy(format="webp", lossy=True, quality=80),
        CompressionStrategy(format="webp", lossy=True, perceptual_target=0.990),
        CompressionStrategy(format="webp", lossless=True),
        CompressionStrategy(format="jpeg", lossless=True), # Huffman + progressive
        CompressionStrategy(format="auto"), # Best per image
    ],
    sample_images=50,
)

# 3. Apply compression safely (dry_run=True by default)
result = compress_collection(
    target_path=Path("/manga/series1"),
    strategy=chosen_strategy,
    dry_run=True, # Explicit write required to mutate
    allow_larger=False, # Never replace if compressed file is bigger
)
```

### 2.3 Compression Strategies & Codec Support

1. **Lossless Compression**:
   - **JPEG Lossless Optimization**:
     - *DCT-level lossless*: Requires `jpegtran` (`-optimize -progressive -copy all`). Optimizes Huffman tables and progressive scans without touching DCT coefficients or decompressing/recompressing pixel data.
     - Preserves 100% of decoded pixel data, metadata, and color profiles (ICC). Typical savings: 2%–12%.
     - **Safety Guard**: Pillow *cannot* do lossless JPEG optimization. If `jpegtran` is unavailable, the engine reports that lossless JPEG optimization is unavailable, rather than silently running a lossy Pillow re-encode.
   - **WebP Lossless**:
     - Encodes with `lossless=True`, `method=6`.
     - Preserves 100% of decoded pixels. Best for PNG conversions or raw scans.
   - **PNG Optimization**:
     - Lossless recompression via Pillow / zlib-ng.

2. **Lossy Compression with Explicit Permission & Perceptual Guardrails**:
   - **Explicit Lossy Opt-In**: In write mode, lossy compression requires explicit user opt-in (`--allow-lossy` or an explicit lossy mode `-m lossy` / `-q <quality>`). Default behavior is dry-run analysis or lossless optimization.
   - **Quality Presets**: `high` (q=88), `medium` (q=80), `low` (q=72), or explicit `--quality 1..100`.
   - **Perceptual Target Guard**:
     - Uses Structural Similarity (SSIM) computed on luminance channels.
     - Rather than relying on unbounded binary search that assumes strict monotonic quality behavior, uses bounded candidate search across discrete quality levels (e.g. evaluating coarse steps [70, 80, 85, 90, 95] and refining).
     - Configurable defaults:
       - **Manga** (black-and-white / screentones): `threshold = 0.992` (protects fine dithering/screentone patterns from moiré artifacts).
       - **Manhwa** (continuous-tone color webtoons): `threshold = 0.988`.
     - Users can calibrate and override these thresholds per collection.
   - **Generational Loss Prevention**:
     - If re-encoding an existing lossy JPEG/WebP achieves less than a minimum savings threshold (e.g. < 8% space saved) or drops SSIM below the perceptual floor, the original file is preserved as-is.
   - **Metadata & Color Profile Preservation**:
     - ICC color profiles and EXIF orientation/metadata are extracted and preserved by default during re-encoding (`-copy all` in `jpegtran`, and embedding `icc_profile` and `exif` via Pillow).

3. **Auto Strategy**:
   - Automatically determines whether an image is grayscale line-art or full color.
   - For line-art: tests lossless WebP vs high-quality WebP.
   - For tall images (>16,383px): restricts format to JPEG (or PNG) to prevent WebP spec violations.
   - For each image, selects the strategy that minimizes bytes while meeting the quality constraint.

### 2.4 Caching for Efficient Repeated Analysis
- Analysis results and benchmark evaluations are cached in an LRU / session store.
- **Cache Key**: Includes all parameters affecting output: `hash(file_path, file_size, mtime_ns, codec_name, codec_version, metric_version, strategy_params)`.
- If the file has not been modified and compression settings match, cached benchmark sizes and SSIM scores are reused instantly.
- Invalidates automatically if source files change, codecs change, or settings differ.

### 2.5 Mandatory Termdash Terminal Layout & Reporting

#### Live In-Place Progress Display:
Driven by TermDash without fabricating unmeasurable per-file percentages:
- **Line 1**: `Compresser` | Mode: `ANALYSIS` (or `WRITE`) | Strategy: `webp-lossy (q=80)` | Workers: `4`
- **Line 2**: Last completed: `042.jpg` -> `042.webp` | Saved: `52.1%` (1.42 MB -> 680 KB) | SSIM: `0.993`
- **Line 3**: `142/350 files` | `18.4 img/s` (24.1 MB/s) | Elapsed: `00:00:08` | ETA: `00:00:11` (15s rolling smoothed)
- **Line 4**: Current Savings: `112.4 MB / 380.2 MB` (`-29.6%`)
- **Line 5**: Current Gallery Progress Bar: `[====================..........] 65%`
- **Line 6**: Overall Batch Progress Bar: `[==============................] 40.6%`

Termdash owns all console output; compression workers report structured progress events to the main UI thread.

#### Post-Processing Report:
- **Single Strategy Summary Table**:
  - Rendered via `termdash.render_table()`.
  - Includes: Input format breakdown, total images, original size, compressed size, absolute savings, percent savings, average SSIM, encoding throughput (img/s and MB/s), skipped/larger count, failures.
- **Multi-Strategy Comparison Matrix**:
  - Columns: Strategy / Codec, Target Format, Quality/SSIM, Total Size, Savings %, Speed (img/s), Relative Visual Bar.
  - Visual horizontal comparison bars rendered via `termdash.render_horizontal_bar()`:
    ```
    Strategy             Size       Savings    Speed     Relative Savings Bar
    -------------------------------------------------------------------------
    jpeg-lossless        342.1 MB   -10.0%     62 img/s  [██                  ] 10.0%
    webp-lossless        301.4 MB   -20.7%     14 img/s  [████                ] 20.7%
    webp-lossy (q=85)    190.2 MB   -49.9%     22 img/s  [██████████          ] 49.9%
    webp-perceptual      171.5 MB   -54.9%     16 img/s  [███████████         ] 54.9%
    auto (recommended)   165.8 MB   -56.4%     18 img/s  [████████████        ] 56.4%
    ```

### 2.6 MangaDL Integration: `mangadl compress`

CLI invocation:
```bash
mangadl compress -d <destination> [options]
```

#### CLI Flags Contract:
- `-d`, `--destination`: Destination library directory or specific gallery folder.
- `-u`, `--url`: Target specific galleries matching URL or folder name (repeatable).
- `-f`, `--format`: Output format (`auto`, `webp`, `jpeg`, `avif`, `keep`). Default: `auto`.
- `-m`, `--mode`: Compression mode (`lossless`, `perceptual`, `lossy`). Default: `lossless` (safe non-destructive).
- `-q`, `--quality`: Quality setting `1..100` (default: 80 for lossy).
- `-p`, `--perceptual-target`: Minimum SSIM threshold `0.80..1.00` (default: 0.990).
- `-c`, `--compare`: Run comparison matrix across strategies without compressing.
- `-s`, `--sample`: Benchmark only a representative sample of N images per gallery.
- `-w`, `--write`: Explicit write mode. (Default is dry-run analysis).
- `-F`, `--allow-larger`: Replace files even if the output is larger (default: False).
- `-L`, `--allow-lossy`: Explicit permission to apply lossy compression in write mode.
- `-t`, `--threads`: Concurrency worker threads (default: min(cpu_count, 4), memory-bounded).
- `-N`, `--no-ui`: Disable live TermDash dashboard (plain text output).
- `-J`, `--json`: Output machine-readable JSON results.
- `-v`, `--verbose`: Detailed diagnostic logging.

#### Safe Application Guarantees:
1. **Dry-Run by Default**: Unless `-w` / `--write` is specified, no files on disk are touched.
2. **Explicit Lossy Opt-In**: In write mode, lossy compression requires explicit permission (`--allow-lossy` or `-m lossy`).
3. **Full Output Verification**:
   - Written files are verified via complete pixel decode (`im.load()`), dimension checking against original, and non-empty size.
4. **Crash-Safe Journaled Replacement**:
   - Compressed file written to temporary sibling: `001.webp.tmp_<id>`.
   - Verified completely.
   - Transaction recorded in `.compress_journal.json`.
   - Swapped to target name; original deleted; journal updated/cleaned.
   - Automatic crash recovery on startup.
5. **Audit Defect Non-Regression**:
   - Destination audit verifies that no new defects are introduced, existing missing pages are preserved without false repairs, and duplicate page files are prevented.
6. **Sidecar Protection**:
   - Preserves `.mangadl-source.json`, `info.json`, cover files, and any hidden `.mangadl` state directories untouched.

---

## 3. Implementation Stages

### Stage 1: Termdash Enhancements (`modules/termdash`)
- Keep existing termdash functionality untouched to prevent breaking changes.
- Implement `termdash/table.py`:
  - `Table` class and `render_table(headers, rows, alignments, styles)`.
  - ANSI-aware width measurement, column truncation, left/right/center alignment, clean border formatting.
- Implement `render_horizontal_bar()` in `termdash/progress.py`:
  - Width-bounded horizontal bar with ratio/percentage fill, color gradients, and text overlays.
- Unit tests in `modules/termdash/tests/table_test.py` and `horizontal_bar_test.py`.
- Bump `termdash` version in `pyproject.toml` (0.5.0 -> 0.6.0) and verify existing tests remain green.

### Stage 2: Reusable Standalone `compresser` Module (`modules/compresser`)
- Set up module structure: `pyproject.toml`, `README.md`, `compresser/`.
- Implement `models.py`: Dataclasses for scan statistics, compression strategies, trial results, and run manifests.
- Implement `scanner.py`: Recursive directory walker collecting formats, dimensions, sizes, and aspect ratios.
- Implement `perceptual.py`: Vectorized NumPy SSIM on luminance, luminance variance, bounded candidate search across discrete qualities. No global unsetting of `Image.MAX_IMAGE_PIXELS`.
- Implement `codecs/`:
  - `PillowJpegCodec`: Lossy JPEG encoding; disallows labeling Pillow re-encode as lossless.
  - `PillowWebpCodec`: Lossless & lossy with method tuning.
  - `PillowAvifCodec`: AVIF support when available.
  - `ExternalCliCodec`: Discover and invoke `jpegtran` (required for strict lossless JPEG), `cwebp`, `cjpeg` (mozjpeg), `jpegli`, `cjxl`.
- Implement `engine.py`: Multi-threaded compression worker pool, full pixel decode validation, transactional journaling (`.compress_journal.json`), crash recovery, size guards, format decision tree.
- Implement `cache.py`: Mtime/size/codec/settings-based benchmark caching.
- Implement `ui.py`: Termdash live dashboard adapter (last completed file, current gallery progress, overall progress, 15s rolling smoothed ETA) and post-run summary/comparison table generator.
- Implement `cli.py` & `__main__.py`: Full standalone CLI with short/long flags.
- Comprehensive unit tests in `modules/compresser/tests/`.

### Stage 3: MangaDL Integration (`mangadl compress`)
- Implement `modules/mangadl/mangadl/compress.py`:
  - Connects MangaDL's destination and gallery directory discovery to `compresser`.
  - Adapts MangaDL library models and handles gallery-by-gallery workflows.
- Update `modules/mangadl/mangadl/cli_core.py`:
  - Register `compress` parser with all short/long arguments.
  - Route execution to `mangadl.compress.run_cli(args)`.
- Enforce library safety & invariants:
  - Verify audit compatibility with `destination_audit.py`.
  - Prevent duplicate page files (`001.jpg` + `001.webp`) via transactional journaling and cleanup.
  - Check manhwa dimensions (guard against >16,383px WebP limit).
  - Memory-safe decompression limits without process-global bypass.
  - Require explicit opt-in for lossy compression.
- Unit tests in `modules/mangadl/tests/compress_test.py`:
  - Dry-run analysis across mock gallery folders.
  - Write mode with atomic replacement.
  - Invariant defect non-regression: existing incomplete status preserved, clean galleries remain clean with 0 duplicate pages.
  - Size guard (refusing larger files unless requested).
  - WebP tall image fallback to JPEG/PNG.
  - Crash recovery / transaction rollback.

### Stage 4: Repository Registration & Comprehensive Validation
- Register `compresser` in `validation-targets.json` with build, lint, compile, and pytest steps.
- Add `modules/compresser` to `mangadl` bootstrap in `validation-targets.json`.
- Register `compresser (module)` in `modules/scripts_help/scripts_help/registry/registry.py` under "Media Processing".
- Run test suites via `./Invoke-Tests.ps1` for `termdash`, `compresser`, `mangadl`, and `scripts_help`.
- Validate CLI help outputs (`compresser --help`, `mangadl compress --help`).
- Compile and Ruff checks on all modified packages.

---

## 4. Acceptance Criteria

1. **Standalone Capability**: `compresser` is independently installable and executable (`python -m compresser --help`).
2. **MangaDL Integration**: `mangadl compress --help` works cleanly, matching all repo CLI conventions.
3. **Termdash Compliance**: Both CLIs use `termdash` for live progress (status lines, gallery bar, overall bar, rolling smoothed ETA) and render colored post-run summary and comparison tables with horizontal bars without breaking existing Termdash functionality.
4. **Safety & Zero Data Loss**: Default behavior is dry-run analysis. Writes require explicit `-w` / `--write`. Lossy writes require explicit opt-in (`--allow-lossy` or `-m lossy`). Never replaces with a larger file unless `-F` / `--allow-larger` is set. Full pixel decode (`im.load()`) verifies all outputs.
5. **Lossless JPEG Rigor**: Strict lossless JPEG requires DCT-level optimization (`jpegtran`). Pillow re-encode is never misclassified as lossless.
6. **Cross-Extension Crash Safety**: Multi-file replacement uses transactional journaling (`.compress_journal.json`) and startup crash recovery, preventing orphan duplicate pages.
7. **No Audit Regressions**: Post-compression audit introduces zero new defects; incomplete galleries maintain their specific missing page findings, and clean galleries remain 100% valid with zero duplicates.
8. **Manhwa Safe**: Images exceeding 16,383px in height or width are safely rejected from WebP conversion and handled via JPEG/PNG. Safe memory limits prevent decompression bombs without global bypass.
9. **Complete Test Pass**: All new and existing tests in `termdash`, `compresser`, and `mangadl` pass cleanly.
