# Stage 3: MangaDL Integration (`mangadl compress`)

> Historical integration intent. S5/S7 in 05_reviewed-plan.md supersede defaults,
> lossy approval, selection, recovery and audit guarantees. Existing adapter uses
> substring filtering and no runtime audit baseline; these need correction.

## Goal
Integrate the reusable `compresser` module into MangaDL through a native `mangadl compress` subcommand, enabling users to analyze, benchmark, and compress downloaded manga libraries without disrupting MangaDL's audit contracts or reader compatibility.

## Scope of Work

1. **CLI Registration (`modules/mangadl/mangadl/cli_core.py`)**:
   - Add `compress` subcommand to the top-level argument parser.
   - Arguments (all with short and long forms):
     - `-d`, `--destination`: Destination library root or gallery folder (required).
     - `-u`, `--url`: Target specific series matching URL or folder name (repeatable).
     - `-f`, `--format`: Target image format (`auto`, `webp`, `jpeg`, `avif`, `keep`). Default: `auto`.
     - `-m`, `--mode`: Strategy mode (`lossless`, `perceptual`, `lossy`). Default: `lossless`.
     - `-q`, `--quality`: Quality setting `1..100` (default: 80).
     - `-p`, `--perceptual-target`: SSIM threshold `0.80..1.00` (default: 0.990).
     - `-c`, `--compare`: Benchmark comparison matrix without modifying files.
     - `-s`, `--sample`: Number of sample images per gallery to benchmark.
     - `-w`, `--write`: Explicit write mode (default: dry-run analysis).
     - `-L`, `--allow-lossy`: Explicit permission to apply lossy compression in write mode.
     - `-F`, `--allow-larger`: Replace files even if compressed output is larger.
     - `-t`, `--threads`: Concurrency worker threads (default: min(cpu_count, 4)).
     - `-N`, `--no-ui`: Disable live Termdash dashboard.
     - `-J`, `--json`: Machine-readable output.
     - `-v`, `--verbose`: Detailed diagnostic logging.

2. **Integration Adapter (`modules/mangadl/mangadl/compress.py`)**:
   - Discovers target galleries under destination root.
   - Leverages `library_index.py` and `destination_audit.py` to identify valid gallery folders.
   - Passes gallery paths to `compresser.compress_collection()`.
   - Bridges progress events into MangaDL's Termdash dashboard or renders via `compresser.ui`.

3. **MangaDL Safety & Invariant Guards**:
   - **Audit Invariant Non-Regression**:
     - `destination_audit.py` matches `_PAGE_FILE` (`001.ext`) and flags duplicate pages (`duplicate_pages`) if both `001.jpg` and `001.webp` exist.
     - Multi-file replacements write to temporary files, validate with complete pixel decode (`im.load()`), record transactions in `.compress_journal.json`, and recover automatically on restart.
     - Acceptance criterion is **defect non-regression**: compression preserves existing audit state (incomplete galleries with missing pages retain those exact missing pages; clean galleries remain clean with zero duplicates).
   - **Sidecar Protection**:
     - Preserves `.mangadl-source.json`, `info.json`, cover files, and any hidden `.mangadl` state directories untouched.
   - **Manhwa Height Guard**:
     - Detects image height or width exceeding 16,383px.
     - Refuses WebP conversion for those specific pages, preserving optimized JPEG/PNG format to prevent reader display failures.
   - **Pillow Safety**:
     - Never sets `Image.MAX_IMAGE_PIXELS = None` globally. Enforces header inspection and bounded configurable limits (`200_000_000` pixels) to protect against decompression bombs while allowing tall manhwa.
   - **Explicit Lossy Permission**:
     - In write mode, refuses lossy compression unless `-L` / `--allow-lossy` or an explicit lossy mode is requested.

4. **Testing (`modules/mangadl/tests/compress_test.py`)**:
   - Test CLI parser argument contract (`mangadl compress --help`).
   - Test dry-run analysis across mock gallery folders.
   - Test atomic write mode and verify no duplicate page files remain.
   - Test that destination audit verifies defect non-regression: clean galleries stay clean; incomplete galleries retain their exact missing pages without artificial fixes or regressions.
   - Test tall image WebP avoidance.
   - Test transaction crash recovery when an interrupted conversion state is encountered.
