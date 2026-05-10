---
plan_index: 0006
origin: ai
status: implemented
source_file: user_request_20260509_plan_plus_2
---

# Plan +2: Bootstrap/aebndl Install Repair

## Goals

- Treat `modules/aebndl_module` as the canonical local `aebndl` package.
- Skip the older duplicate `pscripts/modules/aebn-vod-downloader-custom` install when the canonical module exists.
- Add installer diagnostics for `WinError 32` locked console scripts such as `.venv\Scripts\aebndl.exe`.
- Avoid repeated noisy reinstall attempts for the same package after a locked executable failure in one module setup run.
- Detect invalid `~*bndl*` pip distribution leftovers by default, and delete them only behind an explicit repair flag.
- Keep setup.py metadata fallback support for package name/version decisions.
- Add tests for duplicate package-name handling, locked console-script classification, invalid leftover detection, and setup.py metadata fallback.

## Implementation Notes

- Implemented in root `setup.py`, `modules/setup.py`, `pscripts/modules/setup.py`, and `modules/setup_utils/tests/installer_version_test.py`.
- The explicit repair flag is `-I/--repair-invalid-aebndl-dists`.
- Validation should include setup utility tests.

