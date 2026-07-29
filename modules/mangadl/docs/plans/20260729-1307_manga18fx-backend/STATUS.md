# Manga18FX Backend Status

## Current State

Implementation is present on `agent/add-manga18fx-backend`. The user confirmed that a Manga18FX URL file is routing and downloading correctly on Windows 11.

## Completed

- Added native Manga18FX HTML parsing and image downloading.
- Added `manga18fx` backend routing for series-root URLs.
- Integrated the backend with mangadl workers, partial directories, retries, logs, progress sampling, and destination merging.
- Added destination-aware skipping so reruns do not redownload image files already present in the final library.
- Added stable chapter folder prefixes, including fractional chapter numbers such as `215.5`.
- Added offline tests for parsing, natural chapter ordering, lazy image extraction, URL validation, Windows-safe names, stable chapter names, and worker command construction.
- Bumped `mangadl` from 1.6.0 to 1.7.0.
- Confirmed through current web indexing that Manga18FX still exposes series chapter lists and `/manga/<slug>/chapter-<n>` chapter pages.
- Confirmed through the user's live run that the URL-file workflow downloads Manga18FX series correctly.
- Fixed the Windows pytest base-temp setup so the parent directory is created before `tmp_path` fixtures initialize.
- Moved base-temp selection into a module-local pytest hook so tests remain under `modules/mangadl/.pytest_tmp_root` regardless of the shell working directory.
- Made gallery-dl backend tests independent of whether `gallery-dl` is installed by injecting a deterministic fake `gallery_dl.extractor` module.
- Preserved the bare nhentai-ID dry-run coverage by mocking `GalleryDlBackend.score` inside the CLI test.
- Executed an isolated regression replica for the final gallery-dl test doubles with no gallery-dl installation: 2 passed.

## Validation Evidence

The first Windows full-suite run exposed a missing pytest base-temp parent plus one environment-dependent gallery-dl assertion. After fixing the base-temp setup, the second Windows run reached 48 passing tests and only two failures. Both remaining failures were caused by gallery-dl not being installed: one test imported it directly, and the CLI dry-run test expected its extractor to route nhentai. Both tests now use isolated test doubles instead of requiring the optional runtime module.

## Unverified

- The complete mangadl pytest suite has not yet been rerun in the user's Windows checkout after the final two test fixes.
- A second live run has not yet confirmed that all existing Manga18FX image files are skipped.
- Site age-verification, anti-bot, or cookie requirements remain environment-dependent.

## Next Action

Pull the latest branch and run `pytest --tb=short -q .\tests\` from `modules/mangadl`. If it passes, review the branch diff and merge it into `main` as the next separate action.
