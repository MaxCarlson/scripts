# Stage 2: Reusable Standalone `compresser` Module

> Historical scaffold specification. S5/S6 in 05_reviewed-plan.md supersede
> safety, recovery, quality/cache and auto-selection claims. Do not treat the
> implemented suffix as acceptance; REVIEW.md identifies source contradictions.

## Goal
Implement a standalone, reusable image compression module (`modules/compresser`) with a rich Python API and an independent CLI that provides recursive analysis, comparison benchmarking, perceptual quality constraints, smart caching, and safe compression execution.

## Scope of Work

1. **Package Setup (`modules/compresser`)**:
   - `pyproject.toml` with `version = "0.1.0"`, entry point `compresser = "compresser.cli:main"`.
   - `compresser/__init__.py` exposing high-level functions: `analyze_collection`, `compare_strategies`, `compress_collection`.
   - `docs/README.md` and `docs/HANDOFF.md`.

2. **Data Models (`compresser/models.py`)**:
   - `ImageMetadata`: path, format, width, height, size_bytes, is_grayscale, aspect_ratio.
   - `ScanSummary`: total_images, total_bytes, format_counts, format_bytes, dimensions_summary.
   - `CompressionStrategy`: name, format, mode (`lossless`, `lossy`, `perceptual`), quality (`int`), perceptual_target (`float`), method (`int`), extra_args.
   - `TrialResult`: strategy, input_bytes, output_bytes, ssim, elapsed_seconds, success, error_message.
   - `BatchResult`: total_processed, total_saved_bytes, savings_percent, average_ssim, failed_count, skipped_count.

3. **Scanner (`compresser/scanner.py`)**:
   - Fast recursive scanning of target directories for image files (`.jpg`, `.jpeg`, `.webp`, `.png`, `.avif`).
   - Extracts image headers via Pillow without loading full bitmap buffers where possible.
   - Collects per-format statistics and aggregates.

4. **Perceptual Metrics (`compresser/perceptual.py`)**:
   - Vectorized SSIM implementation on luminance channel using NumPy (Gaussian filter windowing).
   - Bounded candidate search across discrete quality levels (e.g. [70, 80, 85, 90, 95]) rather than assuming pure monotonic binary search.
   - Safe header inspection and configurable memory-safe pixel limits without process-global `Image.MAX_IMAGE_PIXELS = None`.
   - Luminance entropy / variance calculation to distinguish line-art from continuous-tone images.

5. **Codecs & Tool Adapters (`compresser/codecs/`)**:
   - `BaseCodec`: Abstract interface defining `encode(image, options) -> bytes`.
   - `PillowJpegCodec`:
     - Lossy mode: configurable quality, subsampling control.
     - Lossless mode: reports unavailable if called on Pillow, directing lossless JPEG requests to `jpegtran`.
   - `PillowWebpCodec`:
     - Lossless mode: `lossless=True`, `method=6`.
     - Lossy mode: configurable quality, `method=6`.
   - `PillowAvifCodec`: AVIF support when available.
   - `ExternalCliCodec`: Discover and invoke `jpegtran` (required for strict DCT-level lossless JPEG), `cwebp`, `cjpeg` (mozjpeg), `jpegli`, `cjxl` if available on PATH or configured.

6. **Engine & Strategy Selector (`compresser/engine.py`)**:
   - `AutoStrategy`: Chooses best format/settings per image (protects >16,383px images from WebP; tests line-art vs photo).
   - Multi-threaded execution pool (memory-bounded, defaulting to min(cpu_count, 4)).
   - Full pixel decode validation (`im.load()`) and dimension check on all outputs.
   - Transactional journaling (`.compress_journal.json`) and startup crash recovery for genuine cross-extension safety.
   - Never replace with larger file unless `--allow-larger` is set.
   - Require explicit opt-in for lossy compression in write mode (`--allow-lossy` or `-m lossy`).

7. **Caching Layer (`compresser/cache.py`)**:
   - Caches image scan metadata and benchmark trial results keyed by `(path, size, mtime_ns, codec_name, codec_version, metric_version, strategy_params)`.
   - Avoids re-compressing sample images on subsequent runs against the same collection.

8. **Terminal UI & Reports (`compresser/ui.py`)**:
   - Live Termdash progress display matching the required layout:
     - Line 1: Header (mode, strategy, workers).
     - Line 2: Last completed file (path, old size -> new size, savings %, SSIM).
     - Line 3: Throughput (img/s, MB/s), elapsed time, rolling 15s smoothed ETA.
     - Line 4: Current savings (bytes, %).
     - Line 5: Current gallery progress bar.
     - Line 6: Overall batch progress bar.
   - Post-run colored summary table using `termdash.render_table()`.
   - Comparison matrix table with horizontal comparison bars using `termdash.render_horizontal_bar()`.

9. **CLI (`compresser/cli.py`)**:
   - Full CLI adhering to repository standards (every option has short and long form).
   - Flags for `-i/--input`, `-o/--output`, `-f/--format`, `-m/--mode`, `-q/--quality`, `-p/--perceptual-target`, `-c/--compare`, `-s/--sample`, `-w/--write`, `-L/--allow-lossy`, `-F/--allow-larger`, `-t/--threads`, `-N/--no-ui`, `-J/--json`, `-v/--verbose`.
   - Default is dry-run analysis.

10. **Testing (`modules/compresser/tests/`)**:
    - Comprehensive unit and integration tests covering scanner, codecs, perceptual metrics, caching, engine atomic safety, CLI parsing, and UI generation.
