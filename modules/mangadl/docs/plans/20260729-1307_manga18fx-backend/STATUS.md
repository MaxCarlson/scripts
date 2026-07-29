# Manga18FX Backend Status

## Current State

Implementation is present on `agent/add-manga18fx-backend`. The user confirmed that a Manga18FX URL file routes and downloads correctly on Windows 11. The first live run also exposed low throughput because each series downloaded chapter images serially.

## Completed

- Added native Manga18FX HTML parsing and image downloading.
- Added `manga18fx` backend routing for series-root URLs.
- Integrated the backend with mangadl workers, partial directories, retries, logs, progress sampling, and destination merging.
- Added destination-aware skipping so reruns do not redownload image files already present in the final library.
- Added stable chapter folder prefixes, including fractional chapter numbers such as `215.5`.
- Added offline tests for parsing, natural chapter ordering, lazy image extraction, URL validation, Windows-safe names, stable chapter names, and worker command construction.
- Confirmed through current web indexing that Manga18FX still exposes series chapter lists and `/manga/<slug>/chapter-<n>` chapter pages.
- Confirmed through the user's live run that the URL-file workflow downloads Manga18FX series correctly.
- Fixed the Windows pytest base-temp setup so the parent directory is created before `tmp_path` fixtures initialize.
- Moved base-temp selection into a module-local pytest hook so tests remain under `modules/mangadl/.pytest_tmp_root` regardless of the shell working directory.
- Made gallery-dl backend tests independent of whether `gallery-dl` is installed by injecting a deterministic fake `gallery_dl.extractor` module.
- Preserved the bare nhentai-ID dry-run coverage by mocking `GalleryDlBackend.score` inside the CLI test.
- Added `-I/--image-workers` to `mangadl run`, with a default of `4` and an accepted range of `1` through `8`.
- Added bounded per-chapter Manga18FX image concurrency while retaining serial chapter discovery, deterministic output names, per-thread HTTP openers, `.part` files, and atomic final renames.
- Added offline tests for public flag parsing, default selection, environment propagation to worker subprocesses, concurrency overlap, and the upper bound.
- Bumped `mangadl` from 1.7.0 to 1.8.0.

## Validation Evidence

The first Windows full-suite run exposed a missing pytest base-temp parent plus one environment-dependent gallery-dl assertion. After fixing the base-temp setup, the second Windows run reached 48 passing tests and only two failures. Both remaining failures were caused by gallery-dl not being installed and were replaced with isolated test doubles.

The first live Manga18FX batch downloaded correctly but averaged approximately 800 KiB/s with two outer workers because each series had only one active image request. The new implementation allows up to `workers × image-workers` image transfers, bounded by a maximum of eight image workers per series.

## Unverified

- The complete mangadl pytest suite has not yet been rerun in the user's Windows checkout after the image-concurrency changes.
- The new `-I/--image-workers` path has not yet been measured against the live Manga18FX batch.
- A second live run has not yet confirmed that all existing Manga18FX image files are skipped.
- Site age-verification, anti-bot, rate-limit, or cookie requirements remain environment-dependent.

## Next Action

Pull the latest branch and run `pytest --tb=short -q .\tests\` from `modules/mangadl`. If it passes, rerun the same URL file with the default `-w 2 -I 4`, compare throughput, and then review the branch diff before merging into `main`.
