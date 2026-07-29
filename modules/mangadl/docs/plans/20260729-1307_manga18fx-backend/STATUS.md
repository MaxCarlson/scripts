# Manga18FX Backend Status

## Current State

Implementation is present on `agent/add-manga18fx-backend`. Manga18FX URL files route and download correctly on Windows 11. Live testing established that four outer series workers are stable on the current B: destination, while a fifth outer worker immediately drives the disk to 100% utilization and prevents observable progress even with only one or two image threads per series.

## Completed

- Added native Manga18FX HTML parsing and image downloading.
- Added `manga18fx` backend routing for series-root URLs.
- Integrated the backend with mangadl workers, partial directories, retries, logs, progress sampling, and destination merging.
- Added destination-aware skipping so reruns do not redownload image files already present in the final library.
- Added stable chapter folder prefixes, including fractional chapter numbers such as `215.5`.
- Added bounded per-chapter Manga18FX image concurrency with `-I/--image-workers`, defaulting to four and accepting one through eight.
- Confirmed live operation with `-w 2 -I 2`, `-w 2 -I 4`, `-w 4 -I 1`, `-w 4 -I 2`, `-w 4 -I 4`, and `-w 4 -I 5`.
- Added a default outer-worker safety ceiling of four; experimental overrides are bounded at eight.
- Added configurable staggered worker startup, defaulting to two seconds.
- Added runtime worker and image-thread controls, logical-CPU-minus-one aggregate budgeting, and immediate `q` interruption.
- Added bounded preflight auto-tuning with explicit worker and image-thread ranges, repeated timed samples, temporary probe downloads, JSON reports, and automatic application of the selected combination.
- Reduced worker filesystem scans and cached identity lookup to avoid unnecessary disk saturation.
- Counted active `.part` bytes in throughput reporting.
- Parsed Manga18FX chapter and final completion records inside the worker wrapper.
- Classified `downloaded=0, skipped>0` as an already-complete/skipped job instead of a zero-byte success.
- Classified `downloaded=0, skipped=0` as a backend failure instead of silently succeeding.
- Reported exact final image totals from Manga18FX completion counts.
- Removed `/?` from active dashboard and displayed activity-log counts when a final total is not yet known.
- Pinned Manga18FX identities to `M18:<series-slug>`.
- Replaced the wide worker row with an explicit fixed-width field schema.
- Added fixed-width activity-log identity, count, size, and rate columns.
- Retained the second progress/activity line for each worker.
- Added regression tests for native-output parsing, resume classification, zero-output rejection, unknown-total rendering, activity-log alignment, and Manga18FX identity formatting.
- Bumped `mangadl` to 1.10.1.

## Validation Evidence

The original serial implementation averaged approximately 800 KiB/s with two outer workers. Inner image concurrency increased observed aggregate throughput to approximately 15-17 MiB/s during a four-worker live run.

One worker in that run displayed zero bytes and later `FINISH_SUCCESS`. Its backend behavior was consistent with a fully existing series: `manga18fx.py` skips images found in the final library and can legitimately finish with zero new files. The wrapper previously discarded the backend-reported skipped count. Version 1.10.1 uses that count to report the job as already complete.

The parser and classification helpers passed isolated source-level checks. The full Windows suite has not yet run against 1.10.1.

## Unverified

- Full `pytest --tb=short -q .\tests\` after the 1.10.1 changes.
- Live confirmation that a fully existing series is shown as skipped/already complete with an exact final image count.
- Live confirmation of the two-row dashboard, fixed column positions, and normalized activity-log display.
- Live auto-tune report quality and selected `-w`/`-I` combination.
- Whether an explicit `--max-workers 5` plus a longer launch stagger can avoid the observed fifth-worker disk saturation.
- Site age-verification, anti-bot, rate-limit, or cookie requirements remain environment-dependent.

## Next Action

Pull the latest feature branch, reinstall editable `mangadl`, and run the full Windows test suite. Then rerun one already-downloaded Manga18FX series and confirm it reports already complete rather than zero-byte success. Do not merge into `main` until those checks pass.
