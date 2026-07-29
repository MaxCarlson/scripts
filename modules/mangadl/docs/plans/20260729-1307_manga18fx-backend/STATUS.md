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
- Replaced the gallery-dl routing test's dependency on the installed extractor catalog with a deterministic mocked extractor registry.
- Executed an isolated regression replica covering the pytest hook and backend routing tests: 11 passed.

## Validation Evidence

The user's pre-fix full-suite run showed that production downloading worked, while test setup failed before affected tests executed because `.pytest_tmp_root` did not exist. The only assertion failure depended on whether the installed gallery-dl build currently registered nhentai. Both root causes have been corrected.

## Unverified

- The complete mangadl pytest suite has not yet been rerun in the user's Windows checkout after the fixes.
- A second live run has not yet confirmed that all existing Manga18FX image files are skipped.
- Site age-verification, anti-bot, or cookie requirements remain environment-dependent.

## Next Action

Pull the latest branch and run `pytest --tb=short -q .\tests\` from `modules/mangadl`. If it passes, review the branch diff and merge it into `main` as the next separate action.
