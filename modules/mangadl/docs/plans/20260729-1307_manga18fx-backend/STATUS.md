# Manga18FX Backend Status

## Current State

Implementation is present on `agent/add-manga18fx-backend`. The user confirmed that Manga18FX URL files route and download correctly on Windows 11. Live testing established that four outer series workers are stable on the current B: destination, while a fifth outer worker immediately drives the disk to 100% utilization and prevents observable progress even with only one or two image threads per series.

## Completed

- Added native Manga18FX HTML parsing and image downloading.
- Added `manga18fx` backend routing for series-root URLs.
- Integrated the backend with mangadl workers, partial directories, retries, logs, progress sampling, and destination merging.
- Added destination-aware skipping so reruns do not redownload image files already present in the final library.
- Added stable chapter folder prefixes, including fractional chapter numbers such as `215.5`.
- Added bounded per-chapter Manga18FX image concurrency with `-I/--image-workers`, defaulting to four and accepting one through eight.
- Preserved serial chapter discovery, deterministic output names, per-thread HTTP openers, `.part` files, and atomic final renames.
- Confirmed live operation with `-w 2 -I 2`, `-w 2 -I 4`, `-w 4 -I 1`, `-w 4 -I 2`, `-w 4 -I 4`, and `-w 4 -I 5`.
- Confirmed that `-w 5` and above cause immediate disk saturation and apparent freeze on the current destination, independently of `-I`.
- Added a default outer-worker safety ceiling of four; experimental overrides are bounded at eight.
- Added a configurable worker launch stagger, defaulting to two seconds.
- Added runtime `+`/`-` worker-target controls and `[`/`]` Manga18FX image-thread controls.
- Made worker reductions drain-only and image-thread changes apply to newly launched Manga18FX jobs.
- Added logical-CPU-minus-one aggregate concurrency budgeting.
- Changed `q` to enter the same immediate interruption and worker-termination path as Ctrl+C.
- Added fixed-width ANSI-aware dashboard columns, an `M18` backend badge, runtime concurrency header data, and a second progress/activity row per worker.
- Added bounded preflight auto-tuning with explicit worker and image-thread ranges, repeated timed samples, temporary probe downloads, JSON reports, near-tie efficiency selection, and automatic application of the winning combination.
- Included worker startup/stagger time in auto-tune throughput scores.
- Fixed Windows pytest base-temp setup and removed gallery-dl installation dependence from routing tests.
- Added offline tests for parsers, downloader concurrency, CPU budgeting, worker ceilings, runtime controls, UI alignment, progress rows, auto-tune bounds, stagger timing, scoring, and CLI previews.
- Bumped `mangadl` to 1.10.0.

## Validation Evidence

The original serial implementation averaged approximately 800 KiB/s with two outer workers. Inner image concurrency substantially improved throughput. The stable live range on the current hardware is four or fewer outer workers; increasing image threads is substantially cheaper than adding a fifth outer worker.

The previous Windows suite reached 48 passing tests before the remaining optional gallery-dl assumptions were fixed. The latest UI, safety-ceiling, stagger, and auto-tune changes have not yet received a complete Windows test run.

## Unverified

- Full `pytest --tb=short -q .\tests\` after the 1.10.0 changes.
- Live confirmation that default `-w 5` is reduced to four and starts workers with the configured stagger.
- Live auto-tune report quality and selected `-w`/`-I` combination.
- Whether an explicit `--max-workers 5` plus a longer launch stagger can avoid the observed fifth-worker disk saturation.
- Site age-verification, anti-bot, rate-limit, or cookie requirements remain environment-dependent.

## Next Action

Pull the latest feature branch, reinstall editable `mangadl`, and run the full Windows test suite. Then run a short dry-run auto-tune preview followed by one bounded live tuning run using the safe default outer-worker ceiling of four. Do not merge into `main` until those checks pass.
