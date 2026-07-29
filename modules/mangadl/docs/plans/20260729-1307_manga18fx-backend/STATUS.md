# Manga18FX Backend Status

## Current State

Implementation is present on `agent/add-manga18fx-backend`. Manga18FX URL files route and download correctly on Windows 11. Four outer series workers are stable on the current B: destination, while a fifth outer worker immediately drives the disk to 100% utilization and prevents observable progress even with only one or two image threads per series.

Current package version: `mangadl 1.11.0`.

## Completed

- Added native Manga18FX HTML parsing, image downloading, backend routing, retries, partial directories, destination merging, and destination-aware resume.
- Added deterministic chapter prefixes, including fractional chapters, and zero-padded image names.
- Added bounded per-chapter image concurrency through `-I/--image-workers`.
- Confirmed live operation with `-w 2 -I 2`, `-w 2 -I 4`, `-w 4 -I 1`, `-w 4 -I 2`, `-w 4 -I 4`, and `-w 4 -I 5`.
- Added a default outer-worker ceiling of four, a hard override ceiling of eight, staggered startup, runtime worker/image-thread controls, and logical-CPU-minus-one aggregate budgeting.
- Reduced recursive filesystem polling and included active `.part` bytes in transfer statistics.
- Added cumulative native progress records with downloaded, existing, processed, and discovered counts.
- Classified already-complete and genuine zero-output jobs correctly.
- Removed misleading unknown-total denominators and aligned worker/activity-log columns.
- Added the concise `run` interface plus `run config`, `run optimize`, `run benchmark`, and their config variants.
- Added adaptive online optimization with decaying exploration, state coverage, neighbor search, UCB exploitation, convergence reporting, and durable reports.
- Added systematic online benchmarking with alternating ascending/descending rounds.
- Added the interactive schema-tolerant archive browser.
- Added regression tests for progress, resume classification, CLI organization, optimization, and archive browsing.

## Validation Evidence

The original serial implementation averaged approximately 800 KiB/s with two outer workers. Inner image concurrency increased observed aggregate throughput to approximately 15-17 MiB/s during a four-worker live run.

Resume-only workers previously appeared frozen at zero because the wrapper only counted newly written partial files. Version 1.10.2 and later consume cumulative native progress, allowing processed-image counts to advance while network byte speed remains honest.

## Unverified

- Full Windows `pytest --tb=short -q .\tests\` against 1.11.0.
- Installed help output for the concise/nested command hierarchy.
- Live adaptive optimizer convergence and timed candidate termination.
- Live complete-series optimization.
- Interactive archive browsing against the user's current archive.
- The validation report the user said was pushed is not visible in the connected branch comparison.

## Next Action

Pull the latest feature branch, reinstall editable `mangadl`, run the complete Windows suite, inspect all mode-specific help, run one small report-only timed benchmark, and open the archive browser. Do not merge into `main` until those checks pass.
